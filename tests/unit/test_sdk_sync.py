"""Phase 9 — sync SDK client: mirror surface, deterministic retries."""

from __future__ import annotations

import inspect
from typing import Any

import httpx
import pytest

from memcore.sdk import NotFoundError, ServerError, TransportError
from memcore.sdk._shared import RetryPolicy
from memcore.sdk.async_client import AsyncMemCoreClient
from memcore.sdk.client import MemCoreClient

API_KEY = "sdk-test-key"


def test_sync_async_public_surface_parity() -> None:
    sync_public = {n for n in dir(MemCoreClient) if not n.startswith("_")}
    async_public = {n for n in dir(AsyncMemCoreClient) if not n.startswith("_")}
    assert sync_public - {"close"} == async_public - {"aclose"}
    # Same parameters (name, kind, default) for every shared method (self
    # excluded); annotations are excluded since sync/async return types and
    # Callable[[float], None] vs Callable[[float], Awaitable[None]] legitimately
    # differ for `sleep`.
    for name in sorted(sync_public - {"close"}):
        sync_sig = inspect.signature(getattr(MemCoreClient, name))
        async_sig = inspect.signature(getattr(AsyncMemCoreClient, name))
        sync_params = [(p.name, p.kind, p.default) for p in sync_sig.parameters.values()]
        async_params = [(p.name, p.kind, p.default) for p in async_sig.parameters.values()]
        assert sync_params == async_params, f"signature drift on {name!r}"


def test_happy_path_remember_and_get() -> None:
    memory = {
        "id": "m1", "tenant_id": "t", "agent_id": "a1", "type": "semantic",
        "content": "Bruno is a beagle.",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={"memory": memory})
        return httpx.Response(200, json={"memory": memory})

    with MemCoreClient(
        "http://sdk.test", API_KEY, transport=httpx.MockTransport(handler)
    ) as client:
        record = client.remember("a1", "Bruno is a beagle.")
        assert record.id == "m1"
        assert client.get_memory("m1").content == "Bruno is a beagle."


def test_get_retries_then_succeeds_with_recorded_backoff() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"title": "slow down", "detail": "429"})
        return httpx.Response(200, json={"status": "ok", "version": "x"})

    slept: list[float] = []
    client = MemCoreClient(
        "http://sdk.test", API_KEY,
        transport=httpx.MockTransport(handler), sleep=slept.append,
    )
    assert client.health()["status"] == "ok"
    assert calls == 2
    assert slept == [pytest.approx(0.2)]
    client.close()


def test_transport_failure_on_get_retried_then_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = MemCoreClient(
        "http://sdk.test", API_KEY,
        transport=httpx.MockTransport(handler), sleep=lambda s: None,
    )
    with pytest.raises(TransportError):
        client.health()
    client.close()


def test_post_never_retried_and_maps_errors() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.method == "POST":
            return httpx.Response(503, json={"title": "down", "detail": "d"})
        return httpx.Response(404, json={"title": "NotFoundError", "detail": "gone"})

    client = MemCoreClient(
        "http://sdk.test", API_KEY,
        transport=httpx.MockTransport(handler), sleep=lambda s: None,
        retry=RetryPolicy(max_attempts=3),
    )
    with pytest.raises(ServerError):
        client.remember("a1", "x")
    assert calls == 1
    with pytest.raises(NotFoundError):
        client.get_memory("missing")
    client.close()


def test_full_surface_round_trip() -> None:  # noqa: PLR0915
    """Every remaining public method routes, parses, and returns typed models."""
    session = {"id": "s1", "tenant_id": "t", "agent_id": "a1"}
    memory = {
        "id": "m1", "tenant_id": "t", "agent_id": "a1", "type": "semantic",
        "content": "Bruno is a beagle.",
    }
    job = {"job_id": "j1", "state": "succeeded"}

    def handler(request: httpx.Request) -> httpx.Response:  # noqa: PLR0912
        path = request.url.path
        method = request.method
        status: int = 200
        data: dict[str, Any] | None = None
        if path == "/health":
            data = {"status": "ok", "version": "x"}
        elif path == "/v1/sessions" and method == "POST":
            status, data = 201, {"session": session}
        elif path.startswith("/v1/sessions/") and path.endswith("/messages"):
            status, data = 202, {"session": {**session, "turn_count": 1}}
        elif path.startswith("/v1/sessions/") and path.endswith("/close"):
            data = {"session": {**session, "closed": True}}
        elif path.startswith("/v1/sessions/"):
            data = {"session": session}
        elif path.endswith("/versions"):
            data = {"versions": [memory]}
        elif path.startswith("/v1/memories/") and method == "PATCH":
            data = {"memory": {**memory, "version": 2}}
        elif path.startswith("/v1/memories/") and method == "DELETE":
            status = 204
        elif path.startswith("/v1/memories/"):
            data = {"memory": memory}
        elif path == "/v1/recall":
            data = {
                "results": [{"memory": memory, "relevance": 0.9, "recency": 1.0,
                             "importance": 0.5, "final": 0.45}],
                "context": "ctx", "context_tokens": 3,
            }
        elif path in ("/v1/consolidate", "/v1/decay"):
            status, data = 202, job
        elif path.startswith("/v1/jobs/"):
            data = job
        else:
            raise AssertionError(f"unrouted: {method} {path}")
        return httpx.Response(status, json=data) if data is not None else httpx.Response(status)

    with MemCoreClient(
        "http://sdk.test", API_KEY, transport=httpx.MockTransport(handler)
    ) as client:
        assert client.open_session("a1").id == "s1"
        assert client.get_session("s1").id == "s1"
        assert client.append_message("s1", "user", "hi").turn_count == 1
        assert client.close_session("s1").closed
        assert client.memory_versions("m1")[0].id == "m1"
        assert client.correct_memory("m1", content="Bruno is a beagle.").version == 2
        assert client.restore_memory("m1").id == "m1"
        client.forget_memory("m1")
        outcome = client.recall("a1", "dog", weights={"importance": 2.0},
                                graph_expand=False)
        assert outcome.results[0].memory.id == "m1"
        assert outcome.context == "ctx"
        assert client.consolidate("s1").job_id == "j1"
        assert client.job("j1").state == "succeeded"
        assert client.run_decay().done
        assert client.wait_for_job("j1").state == "succeeded"


def test_missing_httpx_raises_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "httpx":
            raise ImportError("no httpx")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    from memcore.sdk.exceptions import MemCoreClientError

    with pytest.raises(MemCoreClientError, match=r"memcore\[sdk\]"):
        MemCoreClient("http://x", "k")
