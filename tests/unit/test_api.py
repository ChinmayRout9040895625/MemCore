"""End-to-end API tests over the ASGI app (no network, in-memory state)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from memcore.adapters.inmemory import (
    HashingEmbeddingProvider,
    ImmediateWorkflowEngine,
    InMemoryGraphStore,
    InMemoryMemoryStore,
    InMemoryObjectStore,
    InMemoryVectorStore,
    InMemoryWorkingMemory,
    ScriptedLLMProvider,
)
from memcore.api.app import create_app
from memcore.api.deps import AppState
from memcore.config import Settings
from memcore.services import (
    ConsolidationService,
    DecayService,
    MemoryService,
    RecallService,
    SessionService,
)

KEY_T1, KEY_T2 = "key-tenant-1", "key-tenant-2"


def _state() -> AppState:
    store = InMemoryMemoryStore()
    working = InMemoryWorkingMemory()
    objects = InMemoryObjectStore()
    vectors = InMemoryVectorStore()
    graph = InMemoryGraphStore()
    embedder = HashingEmbeddingProvider(dimension=64)
    collection = "mem_64"
    memories = MemoryService(store, vectors, embedder, collection=collection)
    llm = ScriptedLLMProvider(
        responses=['{"summary": "test session", "facts": [], "entities": [], '
                   '"relations": [], "invalidations": []}']
    )
    consolidation = ConsolidationService(
        store, working, memories, vectors, graph, llm
    )
    workflow = ImmediateWorkflowEngine()

    async def _consolidate(payload: dict[str, object]) -> None:
        await consolidation.consolidate_session(
            str(payload["tenant_id"]), str(payload["session_id"])
        )

    workflow.register("consolidate_session", _consolidate)

    decay = DecayService(store, memories)

    async def _decay(payload: dict[str, object]) -> None:
        await decay.sweep(str(payload["tenant_id"]))

    workflow.register("decay_tenant", _decay)
    return AppState(
        store=store,
        working=working,
        objects=objects,
        vectors=vectors,
        graph=graph,
        embedder=embedder,
        sessions=SessionService(store, working, objects),
        memories=memories,
        recall=RecallService(
            store, vectors, embedder, collection=collection, graph=graph
        ),
        consolidation=consolidation,
        workflow=workflow,
        api_keys={KEY_T1: "tenant-1", KEY_T2: "tenant-2"},
    )


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app(Settings(_env_file=None), state=_state())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        # Trigger lifespan manually is not needed: ASGITransport doesn't run
        # lifespan, so ensure collection exists via a first write instead.
        yield c


def _h(key: str = KEY_T1) -> dict[str, str]:
    return {"X-API-Key": key}


async def test_health_needs_no_auth(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_missing_or_bad_api_key_is_401(client: AsyncClient) -> None:
    response = await client.post("/v1/sessions", json={"agent_id": "a1"})
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    response = await client.post(
        "/v1/sessions", json={"agent_id": "a1"}, headers=_h("wrong")
    )
    assert response.status_code == 401


async def test_session_flow(client: AsyncClient) -> None:
    opened = await client.post(
        "/v1/sessions", json={"agent_id": "a1"}, headers=_h()
    )
    assert opened.status_code == 201
    session_id = opened.json()["session"]["id"]

    appended = await client.post(
        f"/v1/sessions/{session_id}/messages",
        json={"role": "user", "content": "hello memcore"},
        headers=_h(),
    )
    assert appended.status_code == 202
    assert appended.json()["session"]["turn_count"] == 1

    closed = await client.post(f"/v1/sessions/{session_id}/close", headers=_h())
    assert closed.status_code == 200
    assert closed.json()["session"]["closed"] is True

    # Appending after close → 422 problem.
    rejected = await client.post(
        f"/v1/sessions/{session_id}/messages",
        json={"role": "user", "content": "too late"},
        headers=_h(),
    )
    assert rejected.status_code == 422


async def test_memory_crud_and_versions(client: AsyncClient) -> None:
    created = await client.post(
        "/v1/memories",
        json={"agent_id": "a1", "content": "Chinmay prefers dark mode."},
        headers=_h(),
    )
    assert created.status_code == 201
    memory_id = created.json()["memory"]["id"]

    fetched = await client.get(f"/v1/memories/{memory_id}", headers=_h())
    assert fetched.status_code == 200

    patched = await client.patch(
        f"/v1/memories/{memory_id}",
        json={"content": "Chinmay prefers dark mode everywhere."},
        headers=_h(),
    )
    assert patched.status_code == 200
    new_id = patched.json()["memory"]["id"]
    assert patched.json()["memory"]["version"] == 2

    versions = await client.get(f"/v1/memories/{new_id}/versions", headers=_h())
    assert [v["id"] for v in versions.json()["versions"]] == [memory_id, new_id]

    deleted = await client.delete(f"/v1/memories/{new_id}?mode=soft", headers=_h())
    assert deleted.status_code == 204

    missing = await client.get("/v1/memories/nonexistent", headers=_h())
    assert missing.status_code == 404
    assert missing.json()["title"] == "NotFoundError"


async def test_recall_endpoint(client: AsyncClient) -> None:
    await client.post(
        "/v1/memories",
        json={"agent_id": "a1", "content": "Chinmay's favorite editor theme is dark."},
        headers=_h(),
    )
    await client.post(
        "/v1/memories",
        json={"agent_id": "a1", "content": "Bangalore weather is rainy in July."},
        headers=_h(),
    )
    response = await client.post(
        "/v1/recall",
        json={"agent_id": "a1", "query": "which theme does chinmay use?", "k": 1},
        headers=_h(),
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert "dark" in results[0]["memory"]["content"]
    assert {"relevance", "recency", "importance", "final"} <= results[0].keys()


async def test_cross_tenant_isolation_at_api(client: AsyncClient) -> None:
    created = await client.post(
        "/v1/memories",
        json={"agent_id": "a1", "content": "tenant-1 secret preference"},
        headers=_h(KEY_T1),
    )
    memory_id = created.json()["memory"]["id"]

    # Tenant 2 cannot read tenant 1's memory ...
    assert (
        await client.get(f"/v1/memories/{memory_id}", headers=_h(KEY_T2))
    ).status_code == 404
    # ... nor recall it.
    recall = await client.post(
        "/v1/recall",
        json={"agent_id": "a1", "query": "secret preference"},
        headers=_h(KEY_T2),
    )
    assert recall.json()["results"] == []


async def test_recall_with_weights_and_context(client: AsyncClient) -> None:
    await client.post(
        "/v1/memories",
        json={"agent_id": "a1", "content": "Chinmay deploys MemCore on Kubernetes."},
        headers=_h(),
    )
    response = await client.post(
        "/v1/recall",
        json={
            "agent_id": "a1",
            "query": "kubernetes deployment",
            "weights": {"relevance": 2.0, "recency": 0.0, "importance": 0.0},
            "rerank": True,
            "as_context": True,
        },
        headers=_h(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["results"]
    assert body["context"].startswith("Relevant memories")
    assert body["context_tokens"] > 0
    # recency/importance weights 0 -> those factors neutralize: final = rel^2
    top = body["results"][0]
    assert top["final"] == pytest.approx(top["relevance"] ** 2, rel=1e-6)


async def test_close_session_triggers_consolidation(client: AsyncClient) -> None:
    opened = await client.post("/v1/sessions", json={"agent_id": "a1"}, headers=_h())
    session_id = opened.json()["session"]["id"]
    await client.post(
        f"/v1/sessions/{session_id}/messages",
        json={"role": "user", "content": "I like tea."},
        headers=_h(),
    )
    await client.post(f"/v1/sessions/{session_id}/close", headers=_h())
    # Immediate engine ran consolidation inline: episodic summary exists.
    recall = await client.post(
        "/v1/recall",
        json={"agent_id": "a1", "query": "test session", "types": ["episodic"]},
        headers=_h(),
    )
    assert recall.json()["results"], "episodic summary should be recallable"


async def test_explicit_consolidate_and_job_status(client: AsyncClient) -> None:
    opened = await client.post("/v1/sessions", json={"agent_id": "a1"}, headers=_h())
    session_id = opened.json()["session"]["id"]
    await client.post(
        f"/v1/sessions/{session_id}/messages",
        json={"role": "user", "content": "consolidate me"},
        headers=_h(),
    )
    response = await client.post(
        "/v1/consolidate", json={"session_id": session_id}, headers=_h()
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert response.json()["state"] == "succeeded"  # immediate engine

    status = await client.get(f"/v1/jobs/{job_id}", headers=_h())
    assert status.json()["state"] == "succeeded"

    # Consolidating another tenant's session is rejected before enqueue.
    other = await client.post(
        "/v1/consolidate", json={"session_id": session_id}, headers=_h(KEY_T2)
    )
    assert other.status_code == 404


async def test_request_validation_extra_field_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/sessions", json={"agent_id": "a1", "bogus": 1}, headers=_h()
    )
    assert response.status_code == 422


async def test_create_app_builds_state_and_runs_lifespan() -> None:
    """`build_state` + lifespan: SQL init, collection ensure, dev-key injection."""
    s = Settings(_env_file=None)
    s.env = "local"
    s.vector.provider = "inmemory"
    s.redis.provider = "inmemory"
    s.graph.provider = "inmemory"
    s.embedding.provider = "inmemory"
    s.llm.provider = "inmemory"
    s.llm.fallback_provider = None
    s.scheduler.provider = "inmemory"
    s.database.provider = "sql"
    s.database.url = "sqlite+aiosqlite:///:memory:"
    app = create_app(s)
    async with app.router.lifespan_context(app):
        state: AppState = app.state.memcore
        assert state.api_keys == {"dev-key": "local"}  # env=local injection
        # Lifespan created tables + collection: a real write must succeed.
        record = await state.memories.remember("local", "a1", "boot check")
        assert (await state.store.get("local", record.id)) is not None


async def test_decay_endpoint_enqueues_sweep(client: AsyncClient) -> None:
    response = await client.post("/v1/decay", headers=_h())
    assert response.status_code == 202
    body = response.json()
    assert body["state"] == "succeeded"  # immediate engine runs inline
    job = await client.get(f"/v1/jobs/{body['job_id']}", headers=_h())
    assert job.status_code == 200


async def test_remember_and_correct_accept_confidence(client: AsyncClient) -> None:
    created = await client.post(
        "/v1/memories",
        json={"agent_id": "a1", "content": "Bruno is a beagle.",
              "confidence": 0.7},
        headers=_h(),
    )
    assert created.status_code == 201
    memory = created.json()["memory"]
    assert memory["confidence"] == 0.7

    corrected = await client.patch(
        f"/v1/memories/{memory['id']}",
        json={"confidence": 0.9},
        headers=_h(),
    )
    assert corrected.status_code == 200
    assert corrected.json()["memory"]["confidence"] == 0.9


async def test_restore_endpoint_round_trip(client: AsyncClient) -> None:
    created = await client.post(
        "/v1/memories", json={"agent_id": "a1", "content": "restore me"},
        headers=_h(),
    )
    memory_id = created.json()["memory"]["id"]
    # Soft delete, then restore.
    deleted = await client.delete(f"/v1/memories/{memory_id}", headers=_h())
    assert deleted.status_code == 204
    restored = await client.post(
        f"/v1/memories/{memory_id}/restore", headers=_h()
    )
    assert restored.status_code == 200
    assert restored.json()["memory"]["status"] == "active"
    # A restored record is fetchable again.
    got = await client.get(f"/v1/memories/{memory_id}", headers=_h())
    assert got.status_code == 200


async def test_restore_is_tenant_scoped(client: AsyncClient) -> None:
    created = await client.post(
        "/v1/memories", json={"agent_id": "a1", "content": "tenant one only"},
        headers=_h(),
    )
    memory_id = created.json()["memory"]["id"]
    await client.delete(f"/v1/memories/{memory_id}", headers=_h())
    # Tenant 2 cannot restore tenant 1's record.
    other = await client.post(
        f"/v1/memories/{memory_id}/restore", headers=_h(KEY_T2)
    )
    assert other.status_code == 404
