"""Phase 9 — sync SDK client: mirror surface, deterministic retries."""

from __future__ import annotations

import inspect

import httpx
import pytest

from memcore.sdk import NotFoundError, ServerError
from memcore.sdk._shared import RetryPolicy
from memcore.sdk.async_client import AsyncMemCoreClient
from memcore.sdk.client import MemCoreClient

API_KEY = "sdk-test-key"


def test_sync_async_public_surface_parity() -> None:
    sync_public = {n for n in dir(MemCoreClient) if not n.startswith("_")}
    async_public = {n for n in dir(AsyncMemCoreClient) if not n.startswith("_")}
    assert sync_public - {"close"} == async_public - {"aclose"}
    # Same parameters for every shared method (self excluded).
    for name in sorted(sync_public - {"close"}):
        sync_params = list(inspect.signature(getattr(MemCoreClient, name)).parameters)
        async_params = list(
            inspect.signature(getattr(AsyncMemCoreClient, name)).parameters
        )
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
