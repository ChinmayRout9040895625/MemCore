"""Phase 12 — the shipped examples must actually run (ADR-0021).

Each example is loaded from examples/ by file path and its ``main(client)``
executed against the real in-process ASGI app — a broken example fails CI.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

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
from memcore.sdk import AsyncMemCoreClient, MemCoreClient
from memcore.services import (
    ConsolidationService,
    DecayService,
    MemoryService,
    RecallService,
    SessionService,
)

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
API_KEY = "dev-key"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, EXAMPLES / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _state() -> AppState:
    store = InMemoryMemoryStore()
    working = InMemoryWorkingMemory()
    vectors = InMemoryVectorStore()
    graph = InMemoryGraphStore()
    embedder = HashingEmbeddingProvider(dimension=64)
    collection = "mem_64"
    memories = MemoryService(store, vectors, embedder, collection=collection)
    llm = ScriptedLLMProvider(
        responses=['{"summary": "example session", "facts": [], "entities": [], '
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
        store=store, working=working, objects=InMemoryObjectStore(),
        vectors=vectors, graph=graph, embedder=embedder,
        sessions=SessionService(store, working, InMemoryObjectStore()),
        memories=memories,
        recall=RecallService(store, vectors, embedder, collection=collection, graph=graph),
        consolidation=consolidation, workflow=workflow,
        api_keys={API_KEY: "examples-tenant"},
    )


@pytest.mark.parametrize(
    "name",
    ["quickstart_async", "memory_lifecycle", "sessions_and_consolidation"],
)
async def test_async_examples_run_end_to_end(
    name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load(name)
    transport = httpx.ASGITransport(app=create_app(Settings(_env_file=None), state=_state()))
    async with AsyncMemCoreClient("http://examples", API_KEY, transport=transport) as client:
        await module.main(client)
    out = capsys.readouterr().out
    assert out.strip(), f"example {name} printed nothing"


def test_sync_example_runs(capsys: pytest.CaptureFixture[str]) -> None:
    module = _load("quickstart_sync")
    memory = {
        "id": "m1", "tenant_id": "t", "agent_id": "quickstart-agent",
        "type": "semantic", "content": "Bruno is a beagle.",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/memories" and request.method == "POST":
            return httpx.Response(201, json={"memory": memory})
        if request.url.path == "/v1/recall":
            return httpx.Response(200, json={
                "results": [{"memory": memory, "relevance": 0.9, "recency": 1.0,
                             "importance": 0.5, "final": 0.45}],
                "context": None, "context_tokens": None,
            })
        raise AssertionError(f"unrouted: {request.method} {request.url.path}")

    with MemCoreClient(
        "http://examples", API_KEY, transport=httpx.MockTransport(handler)
    ) as client:
        module.main(client)
    assert capsys.readouterr().out.strip()


def test_examples_have_env_entrypoints() -> None:
    # Every example must be runnable standalone against a real server.
    for name in ("quickstart_async", "quickstart_sync", "memory_lifecycle",
                 "sessions_and_consolidation"):
        text = (EXAMPLES / f"{name}.py").read_text(encoding="utf-8")
        assert '__main__' in text, f"{name} lacks a __main__ entrypoint"
        assert "MEMCORE_URL" in text and "MEMCORE_API_KEY" in text, (
            f"{name} must read MEMCORE_URL/MEMCORE_API_KEY"
        )
