"""Async MemCore client over the v1 HTTP API (httpx.AsyncClient).

Thin transport shell: retryability, backoff and error mapping live in
``memcore.sdk._shared``; responses are validated into domain models. The
transport and the sleep function are injectable so tests run against an
in-process ASGI app with zero real waiting.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import TYPE_CHECKING, Any

from memcore.domain.enums import MemoryType
from memcore.domain.models import MemoryRecord, Session
from memcore.sdk._shared import (
    RETRYABLE_STATUSES,
    RetryPolicy,
    compute_backoff,
    error_from_response,
    is_retryable,
)
from memcore.sdk.exceptions import JobTimeout, MemCoreClientError, TransportError
from memcore.sdk.models import Job, RecallOutcome

if TYPE_CHECKING:
    import httpx

_INSTALL_HINT = "httpx is not installed; install the sdk extra: pip install 'memcore[sdk]'"


class AsyncMemCoreClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 10.0,
        retry: RetryPolicy | None = None,
        transport: Any | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        try:
            import httpx as _httpx
        except ImportError as exc:
            raise MemCoreClientError(_INSTALL_HINT) from exc
        self._retry = retry or RetryPolicy()
        self._sleep = sleep if sleep is not None else asyncio.sleep
        self._client = _httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-API-Key": api_key},
            timeout=timeout,
            transport=transport,
        )
        self._httpx = _httpx

    # -- plumbing ---------------------------------------------------------
    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        attempt = 0
        while True:
            try:
                response: httpx.Response = await self._client.request(
                    method, path, json=json, params=params
                )
            except self._httpx.TransportError as exc:
                if is_retryable(method, None) and attempt + 1 < self._retry.max_attempts:
                    await self._sleep(compute_backoff(attempt, self._retry))
                    attempt += 1
                    continue
                raise TransportError(
                    f"{method} {path} failed after {attempt + 1} attempt(s): {exc}"
                ) from exc
            if (
                response.status_code in RETRYABLE_STATUSES
                and is_retryable(method, response.status_code)
                and attempt + 1 < self._retry.max_attempts
            ):
                await self._sleep(compute_backoff(attempt, self._retry))
                attempt += 1
                continue
            if response.status_code >= 400:
                try:
                    payload = response.json()
                except ValueError:
                    payload = None
                raise error_from_response(response.status_code, payload)
            if response.status_code == 204 or not response.content:
                return None
            return response.json()

    # -- health -----------------------------------------------------------
    async def health(self) -> dict[str, Any]:
        result: dict[str, Any] = await self._request("GET", "/health")
        return result

    # -- sessions ----------------------------------------------------------
    async def open_session(self, agent_id: str) -> Session:
        data = await self._request("POST", "/v1/sessions", json={"agent_id": agent_id})
        return Session.model_validate(data["session"])

    async def get_session(self, session_id: str) -> Session:
        data = await self._request("GET", f"/v1/sessions/{session_id}")
        return Session.model_validate(data["session"])

    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        data = await self._request(
            "POST",
            f"/v1/sessions/{session_id}/messages",
            json={"role": role, "content": content, "metadata": metadata or {}},
        )
        return Session.model_validate(data["session"])

    async def close_session(self, session_id: str) -> Session:
        data = await self._request("POST", f"/v1/sessions/{session_id}/close")
        return Session.model_validate(data["session"])

    # -- memories ----------------------------------------------------------
    async def remember(
        self,
        agent_id: str,
        content: str,
        *,
        type: MemoryType = MemoryType.SEMANTIC,
        importance: float = 0.5,
        confidence: float = 1.0,
        tags: list[str] | None = None,
    ) -> MemoryRecord:
        data = await self._request(
            "POST",
            "/v1/memories",
            json={
                "agent_id": agent_id,
                "content": content,
                "type": type.value,
                "importance": importance,
                "confidence": confidence,
                "tags": tags or [],
            },
        )
        return MemoryRecord.model_validate(data["memory"])

    async def get_memory(self, memory_id: str) -> MemoryRecord:
        data = await self._request("GET", f"/v1/memories/{memory_id}")
        return MemoryRecord.model_validate(data["memory"])

    async def memory_versions(self, memory_id: str) -> list[MemoryRecord]:
        data = await self._request("GET", f"/v1/memories/{memory_id}/versions")
        return [MemoryRecord.model_validate(v) for v in data["versions"]]

    async def correct_memory(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        importance: float | None = None,
        confidence: float | None = None,
        tags: list[str] | None = None,
    ) -> MemoryRecord:
        body: dict[str, Any] = {}
        if content is not None:
            body["content"] = content
        if importance is not None:
            body["importance"] = importance
        if confidence is not None:
            body["confidence"] = confidence
        if tags is not None:
            body["tags"] = tags
        data = await self._request("PATCH", f"/v1/memories/{memory_id}", json=body)
        return MemoryRecord.model_validate(data["memory"])

    async def forget_memory(self, memory_id: str, *, mode: str = "soft") -> None:
        await self._request(
            "DELETE", f"/v1/memories/{memory_id}", params={"mode": mode}
        )

    # -- recall ------------------------------------------------------------
    async def recall(
        self,
        agent_id: str,
        query: str,
        *,
        k: int = 8,
        types: list[MemoryType] | None = None,
        weights: dict[str, float] | None = None,
        graph_expand: bool | None = None,
        rerank: bool = False,
        as_context: bool = False,
    ) -> RecallOutcome:
        body: dict[str, Any] = {
            "agent_id": agent_id,
            "query": query,
            "k": k,
            "rerank": rerank,
            "as_context": as_context,
        }
        if types is not None:
            body["types"] = [t.value for t in types]
        if weights is not None:
            body["weights"] = weights
        if graph_expand is not None:
            body["graph_expand"] = graph_expand
        data = await self._request("POST", "/v1/recall", json=body)
        return RecallOutcome.model_validate(data)

    # -- jobs ---------------------------------------------------------------
    async def consolidate(self, session_id: str) -> Job:
        data = await self._request(
            "POST", "/v1/consolidate", json={"session_id": session_id}
        )
        return Job.model_validate(data)

    async def job(self, job_id: str) -> Job:
        data = await self._request("GET", f"/v1/jobs/{job_id}")
        return Job.model_validate(data)

    async def run_decay(self) -> Job:
        data = await self._request("POST", "/v1/decay")
        return Job.model_validate(data)

    async def wait_for_job(
        self, job_id: str, *, timeout: float = 30.0, interval: float = 0.2
    ) -> Job:
        """Poll until the job reaches a terminal state; JobTimeout otherwise."""
        waited = 0.0
        while True:
            current = await self.job(job_id)
            if current.done:
                return current
            if waited >= timeout:
                raise JobTimeout(
                    f"job {job_id} still {current.state!r} after {timeout}s"
                )
            await self._sleep(interval)
            waited += interval

    # -- lifecycle -----------------------------------------------------------
    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> AsyncMemCoreClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
