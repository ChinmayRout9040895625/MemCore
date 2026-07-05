"""Phase 10 — middleware (request ids, access log, HTTP metrics), /metrics, /ready."""

from __future__ import annotations

import logging
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
from memcore.adapters.sql import SqlMemoryStore
from memcore.api.app import create_app
from memcore.api.deps import AppState
from memcore.config import Settings
from memcore.services import (
    ConsolidationService,
    MemoryService,
    RecallService,
    SessionService,
)

KEY = "obs-key"


def _state(store: InMemoryMemoryStore | None = None) -> AppState:
    store = store or InMemoryMemoryStore()
    working = InMemoryWorkingMemory()
    vectors = InMemoryVectorStore()
    graph = InMemoryGraphStore()
    embedder = HashingEmbeddingProvider(dimension=64)
    collection = "mem_64"
    memories = MemoryService(store, vectors, embedder, collection=collection)
    llm = ScriptedLLMProvider(responses=["{}"])
    consolidation = ConsolidationService(store, working, memories, vectors, graph, llm)
    return AppState(
        store=store, working=working, objects=InMemoryObjectStore(),
        vectors=vectors, graph=graph, embedder=embedder,
        sessions=SessionService(store, working, InMemoryObjectStore()),
        memories=memories,
        recall=RecallService(store, vectors, embedder, collection=collection),
        consolidation=consolidation, workflow=ImmediateWorkflowEngine(),
        api_keys={KEY: "obs-tenant"},
    )


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app(Settings(_env_file=None), state=_state())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://obs"
    ) as c:
        yield c


async def test_response_carries_generated_request_id(client: AsyncClient) -> None:
    response = await client.get("/health")
    rid = response.headers["x-request-id"]
    assert len(rid) == 32


async def test_incoming_request_id_is_propagated(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "caller-rid-7"})
    assert response.headers["x-request-id"] == "caller-rid-7"


async def test_access_log_line_has_fields(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="memcore.api.access"):
        await client.get("/health", headers={"X-Request-ID": "rid-log"})
    # Dynamic LogRecord extras (mypy doesn't know about them; noqa B009 per line).
    record = next(r for r in caplog.records if r.name == "memcore.api.access")
    assert getattr(record, "request_id") == "rid-log"  # noqa: B009
    assert getattr(record, "method") == "GET"  # noqa: B009
    assert getattr(record, "path") == "/health"  # noqa: B009
    assert getattr(record, "status") == 200  # noqa: B009
    assert getattr(record, "duration_ms") >= 0  # noqa: B009


async def test_metrics_endpoint_uses_route_template(client: AsyncClient) -> None:
    created = await client.post(
        "/v1/memories",
        json={"agent_id": "a1", "content": "observable fact"},
        headers={"X-API-Key": KEY},
    )
    memory_id = created.json()["memory"]["id"]
    got = await client.get(f"/v1/memories/{memory_id}", headers={"X-API-Key": KEY})
    assert got.status_code == 200

    exposition = await client.get("/metrics")
    assert exposition.status_code == 200
    text = exposition.text
    assert 'route="/v1/memories/{memory_id}"' in text
    assert memory_id not in text  # raw ids never become label values


async def test_ready_all_components_ok(client: AsyncClient) -> None:
    response = await client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    # In-memory adapters expose no ping; they are reported ok by convention.
    assert set(body["components"]) == {"store", "vectors", "graph", "working"}
    assert all(v == "ok" for v in body["components"].values())


async def test_ready_degrades_to_503_when_a_ping_fails() -> None:
    class BrokenStore(InMemoryMemoryStore):
        async def ping(self) -> None:
            raise RuntimeError("db is down")

    app = create_app(Settings(_env_file=None), state=_state(store=BrokenStore()))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://obs") as c:
        response = await c.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["components"]["store"].startswith("error:")
    assert body["components"]["vectors"] == "ok"


async def test_sql_store_ping() -> None:
    store = SqlMemoryStore("sqlite+aiosqlite:///:memory:")
    await store.init()
    await store.ping()  # must not raise
    await store.close()
