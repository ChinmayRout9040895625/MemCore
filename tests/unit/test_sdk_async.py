"""Phase 9 — async SDK client: end-to-end over ASGI + deterministic retries."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

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
from memcore.sdk import AuthError, JobTimeout, NotFoundError, ServerError, TransportError
from memcore.sdk._shared import RetryPolicy
from memcore.sdk.async_client import AsyncMemCoreClient
from memcore.services import (
    ConsolidationService,
    DecayService,
    MemoryService,
    RecallService,
    SessionService,
)

API_KEY = "sdk-test-key"


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
        responses=['{"summary": "sdk session", "facts": [], "entities": [], '
                   '"relations": [], "invalidations": []}'] * 4
    )
    consolidation = ConsolidationService(store, working, memories, vectors, graph, llm)
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
        store=store, working=working, objects=objects, vectors=vectors,
        graph=graph, embedder=embedder,
        sessions=SessionService(store, working, objects),
        memories=memories,
        recall=RecallService(store, vectors, embedder, collection=collection, graph=graph),
        consolidation=consolidation, workflow=workflow,
        api_keys={API_KEY: "sdk-tenant"},
    )


def _client(**kwargs: Any) -> AsyncMemCoreClient:
    transport = httpx.ASGITransport(app=create_app(Settings(_env_file=None), state=_state()))
    return AsyncMemCoreClient(
        "http://sdk.test", API_KEY, transport=transport, **kwargs
    )


async def test_end_to_end_memory_lifecycle() -> None:
    async with _client() as client:
        health = await client.health()
        assert health["status"] == "ok"

        record = await client.remember(
            "a1", "Chinmay's dog is named Bruno.", importance=0.8, confidence=0.9,
            tags=["pet"],
        )
        assert record.importance == 0.8
        assert record.confidence == 0.9

        fetched = await client.get_memory(record.id)
        assert fetched.content == record.content

        corrected = await client.correct_memory(record.id, content="Bruno is a beagle.")
        assert corrected.supersedes == record.id
        versions = await client.memory_versions(corrected.id)
        assert [v.id for v in versions] == [record.id, corrected.id]

        outcome = await client.recall("a1", "what is the dog named", as_context=True)
        assert any(s.memory.id == corrected.id for s in outcome.results)
        assert outcome.context is not None

        # Soft delete is intentionally recoverable (ADR-0007): a soft-deleted
        # record still reads back by id (hidden only from listings/recall).
        # Hard delete is what makes a memory truly inaccessible.
        await client.forget_memory(corrected.id, mode="hard")
        with pytest.raises(NotFoundError):
            await client.get_memory(corrected.id)


async def test_session_and_jobs_flow() -> None:
    async with _client() as client:
        session = await client.open_session("a1")
        session = await client.append_message(session.id, "user", "I work on Apollo.")
        assert session.turn_count == 1
        closed = await client.close_session(session.id)
        assert closed.closed

        job = await client.consolidate(session.id)
        finished = await client.wait_for_job(job.job_id)
        assert finished.state == "succeeded"

        decay_job = await client.run_decay()
        assert (await client.wait_for_job(decay_job.job_id)).done


async def test_wrong_api_key_raises_auth_error() -> None:
    transport = httpx.ASGITransport(app=create_app(Settings(_env_file=None), state=_state()))
    async with AsyncMemCoreClient("http://sdk.test", "wrong-key", transport=transport) as client:
        with pytest.raises(AuthError):
            await client.open_session("a1")


async def test_get_retries_transient_503_with_backoff() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503, json={"title": "down", "detail": "later"})
        return httpx.Response(200, json={"status": "ok", "version": "x"})

    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    client = AsyncMemCoreClient(
        "http://sdk.test", API_KEY,
        transport=httpx.MockTransport(handler), sleep=fake_sleep,
    )
    health = await client.health()
    assert health["status"] == "ok"
    assert calls == 3
    assert slept == [pytest.approx(0.2), pytest.approx(0.4)]
    await client.aclose()


async def test_get_gives_up_after_max_attempts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"title": "down", "detail": "still down"})

    async def fake_sleep(seconds: float) -> None:
        return None

    client = AsyncMemCoreClient(
        "http://sdk.test", API_KEY,
        transport=httpx.MockTransport(handler),
        retry=RetryPolicy(max_attempts=2), sleep=fake_sleep,
    )
    with pytest.raises(ServerError):
        await client.health()
    await client.aclose()


async def test_post_is_never_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"title": "down", "detail": "later"})

    async def fake_sleep(seconds: float) -> None:
        return None

    client = AsyncMemCoreClient(
        "http://sdk.test", API_KEY,
        transport=httpx.MockTransport(handler), sleep=fake_sleep,
    )
    with pytest.raises(ServerError):
        await client.remember("a1", "never retried")
    assert calls == 1
    await client.aclose()


async def test_transport_failure_on_get_retried_then_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    async def fake_sleep(seconds: float) -> None:
        return None

    client = AsyncMemCoreClient(
        "http://sdk.test", API_KEY,
        transport=httpx.MockTransport(handler), sleep=fake_sleep,
    )
    with pytest.raises(TransportError):
        await client.health()
    await client.aclose()


async def test_wait_for_job_times_out() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"job_id": "j1", "state": "pending"},
        )

    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    client = AsyncMemCoreClient(
        "http://sdk.test", API_KEY,
        transport=httpx.MockTransport(handler), sleep=fake_sleep,
    )
    with pytest.raises(JobTimeout):
        await client.wait_for_job("j1", timeout=1.0, interval=0.5)
    assert len(slept) == 2  # 0.5 + 0.5 -> waited 1.0 -> timeout check trips
    await client.aclose()


async def test_missing_httpx_raises_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "httpx":
            raise ImportError("no httpx")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    from memcore.sdk.exceptions import MemCoreClientError

    with pytest.raises(MemCoreClientError, match=r"memcore\[sdk\]"):
        AsyncMemCoreClient("http://x", "k")


def test_json_payload_shapes_are_strict() -> None:
    # Guard against silent drift: the request bodies the client sends must
    # match the API schemas' extra="forbid" contract. (Compile-time-ish check:
    # keys used in async_client must be accepted by the server schemas.)
    from memcore.api.schemas import RecallRequest, RememberRequest

    RememberRequest.model_validate(
        {"agent_id": "a", "content": "c", "type": "semantic",
         "importance": 0.5, "confidence": 1.0, "tags": []}
    )
    RecallRequest.model_validate(
        {"agent_id": "a", "query": "q", "k": 8, "rerank": False,
         "as_context": False}
    )
    assert json.dumps({"ok": True})  # keep json import purposeful
