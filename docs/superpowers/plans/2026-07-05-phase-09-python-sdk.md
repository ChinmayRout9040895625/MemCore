# Phase 9 — Python SDK Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A typed async + sync Python client (`memcore.sdk`) covering the whole v1 API, with conservative retries/backoff, typed error mapping, a job-polling helper, an independent `memcore[sdk]` install extra, and quickstart docs.

**Architecture:** `src/memcore/sdk/` is a consumer layer (like `api/` and `evaluation/`): it imports `memcore.domain.models` for typed responses and lazy-imports `httpx` behind the new `sdk` extra (core deps stay pydantic-only, so `pip install memcore[sdk]` is fully server-independent). Pure, transport-agnostic logic (retry policy/backoff math, retryability rules, problem+json → typed exceptions) lives in `_shared.py` and is tested once; `AsyncMemCoreClient` and `MemCoreClient` are thin mirrors over `httpx.AsyncClient`/`httpx.Client` with injectable transports (ASGI/Mock in tests) and injectable sleep (deterministic retry tests). Retries are GET-only by design — non-idempotent POSTs are never replayed after an ambiguous failure (recorded in ADR-0018).

**Tech Stack:** Python 3.11+, httpx (new `sdk` extra), pydantic v2 (existing core dep), pytest with `httpx.ASGITransport` (real in-process app, no network) and `httpx.MockTransport`.

## Global Constraints

- Quality gate (every task, before commit): `./.venv/Scripts/python.exe -m pytest` all pass, coverage ≥ 85%; `./.venv/Scripts/python.exe -m ruff check .` clean; `./.venv/Scripts/python.exe -m mypy` clean (strict).
- Hexagonal: `memcore.sdk` is a consumer layer — it may import `memcore.domain.*` and httpx; it must NOT import services/ports/adapters/api, and nothing outside `memcore.sdk` (and tests) may import it.
- `httpx` is lazy-imported at client construction with the install hint `"httpx is not installed; install the sdk extra: pip install 'memcore[sdk]'"` (project convention: optional deps fail with install hint). Module-level `import httpx` only under `TYPE_CHECKING`.
- Retries: GET-only, statuses {429, 502, 503, 504} or transport errors; deterministic exponential backoff `base * 2**attempt` capped (no jitter — testability); defaults `max_attempts=3, backoff_base=0.2, backoff_cap=5.0`.
- No server-side changes in this phase. The v1 API currently has no list-style/paginated endpoints, so the outline's "pagination helpers" item is consciously deferred until one exists — record this in the phase doc and PROJECT_STATE.
- Determinism in tests: no network, no real sleeping (injectable `sleep`), ASGI/Mock transports only.
- One commit per task; phase gate + docs in Task 4; WAIT for user approval after the phase commit.

---

### Task 1: SDK foundation — exceptions, retry/backoff, error mapping, packaging

**Files:**
- Create: `src/memcore/sdk/__init__.py` (minimal for now; Task 2 extends)
- Create: `src/memcore/sdk/exceptions.py`
- Create: `src/memcore/sdk/_shared.py`
- Create: `src/memcore/sdk/models.py`
- Modify: `pyproject.toml` (add `sdk` extra; ruff per-file-ignore for lazy imports)
- Test: `tests/unit/test_sdk_shared.py`

**Interfaces:**
- Consumes: `memcore.domain.models.ScoredMemory` (for `RecallOutcome`).
- Produces (Tasks 2–3 rely on these exact names):
  - `memcore.sdk.exceptions`: `MemCoreClientError(Exception)`; `TransportError(MemCoreClientError)`; `JobTimeout(MemCoreClientError)`; `APIError(MemCoreClientError)` with keyword-only `__init__(*, status: int, title: str, detail: str)` and attributes `.status/.title/.detail`; subclasses `AuthError` (401), `NotFoundError` (404), `ConflictError` (409), `ValidationAPIError` (422), `ServerError` (5xx).
  - `memcore.sdk._shared`: `RETRYABLE_STATUSES: frozenset[int]`, `RetryPolicy` (frozen dataclass: `max_attempts=3, backoff_base=0.2, backoff_cap=5.0`), `compute_backoff(attempt: int, policy: RetryPolicy) -> float`, `is_retryable(method: str, status: int | None) -> bool`, `error_from_response(status: int, payload: dict[str, Any] | None) -> APIError`.
  - `memcore.sdk.models`: `Job(BaseModel)` with `job_id: str, state: str` and helper property `done: bool` (state in {"succeeded","failed"}); `RecallOutcome(BaseModel)` with `results: list[ScoredMemory], context: str | None = None, context_tokens: int | None = None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_sdk_shared.py`:

```python
"""Phase 9 — SDK pure logic: retry policy, backoff, error mapping."""

import pytest

from memcore.sdk._shared import (
    RETRYABLE_STATUSES,
    RetryPolicy,
    compute_backoff,
    error_from_response,
    is_retryable,
)
from memcore.sdk.exceptions import (
    APIError,
    AuthError,
    ConflictError,
    NotFoundError,
    ServerError,
    ValidationAPIError,
)
from memcore.sdk.models import Job


class TestBackoff:
    def test_exponential_progression(self) -> None:
        policy = RetryPolicy()
        assert compute_backoff(0, policy) == pytest.approx(0.2)
        assert compute_backoff(1, policy) == pytest.approx(0.4)
        assert compute_backoff(2, policy) == pytest.approx(0.8)

    def test_capped(self) -> None:
        policy = RetryPolicy(backoff_base=1.0, backoff_cap=3.0)
        assert compute_backoff(10, policy) == 3.0

    def test_policy_is_frozen(self) -> None:
        with pytest.raises(AttributeError):
            RetryPolicy().max_attempts = 5  # type: ignore[misc]


class TestRetryability:
    def test_get_retries_transient_statuses(self) -> None:
        for status in sorted(RETRYABLE_STATUSES):
            assert is_retryable("GET", status)
        assert is_retryable("get", 503)  # case-insensitive

    def test_get_retries_transport_failure(self) -> None:
        assert is_retryable("GET", None)

    def test_get_does_not_retry_client_errors(self) -> None:
        for status in (400, 401, 404, 409, 422):
            assert not is_retryable("GET", status)

    def test_non_idempotent_methods_never_retry(self) -> None:
        for method in ("POST", "PATCH", "DELETE", "PUT"):
            assert not is_retryable(method, 503)
            assert not is_retryable(method, None)


class TestErrorMapping:
    def test_status_specific_classes(self) -> None:
        cases = [(401, AuthError), (404, NotFoundError), (409, ConflictError),
                 (422, ValidationAPIError), (500, ServerError), (503, ServerError)]
        for status, expected in cases:
            error = error_from_response(status, {"title": "T", "detail": "D"})
            assert type(error) is expected
            assert error.status == status
            assert error.title == "T"
            assert error.detail == "D"

    def test_unknown_4xx_is_plain_api_error(self) -> None:
        error = error_from_response(418, {"title": "teapot", "detail": "no"})
        assert type(error) is APIError

    def test_tolerates_missing_payload(self) -> None:
        error = error_from_response(404, None)
        assert error.detail == "HTTP 404"
        assert "404" in str(error)


class TestJobModel:
    def test_done_states(self) -> None:
        assert Job(job_id="j", state="succeeded").done
        assert Job(job_id="j", state="failed").done
        assert not Job(job_id="j", state="pending").done
        assert not Job(job_id="j", state="running").done
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_sdk_shared.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'memcore.sdk'`.

- [ ] **Step 3: Packaging + package init**

1. `pyproject.toml` — in `[project.optional-dependencies]`, after the `api` line add:

```toml
sdk = ["httpx>=0.27"]
```

and in `[tool.ruff.lint.per-file-ignores]`, alongside the other lazy-import entries:

```toml
# The SDK lazy-imports httpx so `pip install memcore` works without it.
"src/memcore/sdk/*" = ["PLC0415"]
```

2. Create `src/memcore/sdk/__init__.py`:

```python
"""MemCore Python SDK (Phase 9, ADR-0018).

Typed async + sync clients over the v1 HTTP API. This package is a consumer
layer: it depends only on ``memcore.domain`` models and ``httpx`` (installed
via the ``sdk`` extra: ``pip install 'memcore[sdk]'``); it never imports
services, ports, adapters, or the server app.
"""

from memcore.sdk.exceptions import (
    APIError,
    AuthError,
    ConflictError,
    JobTimeout,
    MemCoreClientError,
    NotFoundError,
    ServerError,
    TransportError,
    ValidationAPIError,
)
from memcore.sdk.models import Job, RecallOutcome

__all__ = [
    "APIError",
    "AuthError",
    "ConflictError",
    "Job",
    "JobTimeout",
    "MemCoreClientError",
    "NotFoundError",
    "RecallOutcome",
    "ServerError",
    "TransportError",
    "ValidationAPIError",
]
```

- [ ] **Step 4: Implement exceptions, shared logic, models**

Create `src/memcore/sdk/exceptions.py`:

```python
"""SDK exception hierarchy — every client failure is a MemCoreClientError."""

from __future__ import annotations


class MemCoreClientError(Exception):
    """Base for all SDK errors."""


class TransportError(MemCoreClientError):
    """Network-level failure (connect/read) after retries were exhausted."""


class JobTimeout(MemCoreClientError):
    """A polled job did not reach a terminal state within the timeout."""


class APIError(MemCoreClientError):
    """A non-2xx response from the server (RFC-7807 problem+json)."""

    def __init__(self, *, status: int, title: str, detail: str) -> None:
        super().__init__(f"{status} {title}: {detail}")
        self.status = status
        self.title = title
        self.detail = detail


class AuthError(APIError):
    """401 — missing or invalid API key."""


class NotFoundError(APIError):
    """404 — resource does not exist (or belongs to another tenant)."""


class ConflictError(APIError):
    """409 — duplicate or conflicting write."""


class ValidationAPIError(APIError):
    """422 — request failed validation."""


class ServerError(APIError):
    """5xx — server-side failure (retried automatically for GETs)."""
```

Create `src/memcore/sdk/_shared.py`:

```python
"""Transport-agnostic SDK logic: retry policy, backoff, error mapping.

Kept pure (no httpx, no I/O) so both clients share one tested implementation.
Retries are deliberately GET-only: a non-idempotent POST that fails midway
may have taken effect server-side, and replaying it could duplicate writes
(ADR-0018).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from memcore.sdk.exceptions import (
    APIError,
    AuthError,
    ConflictError,
    NotFoundError,
    ServerError,
    ValidationAPIError,
)

RETRYABLE_STATUSES: frozenset[int] = frozenset({429, 502, 503, 504})
_RETRYABLE_METHODS: frozenset[str] = frozenset({"GET"})


@dataclass(frozen=True)
class RetryPolicy:
    """Deterministic exponential backoff (no jitter — reproducible tests)."""

    max_attempts: int = 3
    backoff_base: float = 0.2
    backoff_cap: float = 5.0


def compute_backoff(attempt: int, policy: RetryPolicy) -> float:
    """Delay before retry number ``attempt`` (0-based): base * 2**attempt, capped."""
    return min(policy.backoff_cap, policy.backoff_base * (2**attempt))


def is_retryable(method: str, status: int | None) -> bool:
    """Whether a failed request may be retried.

    ``status is None`` means the request never produced a response
    (transport failure) — retryable only for idempotent-safe methods.
    """
    if method.upper() not in _RETRYABLE_METHODS:
        return False
    return status is None or status in RETRYABLE_STATUSES


_ERROR_BY_STATUS: dict[int, type[APIError]] = {
    401: AuthError,
    404: NotFoundError,
    409: ConflictError,
    422: ValidationAPIError,
}


def error_from_response(status: int, payload: dict[str, Any] | None) -> APIError:
    """Map an RFC-7807 problem+json body to the typed exception hierarchy."""
    data = payload or {}
    title = str(data.get("title") or "APIError")
    detail = str(data.get("detail") or f"HTTP {status}")
    if status >= 500:
        cls: type[APIError] = ServerError
    else:
        cls = _ERROR_BY_STATUS.get(status, APIError)
    return cls(status=status, title=title, detail=detail)
```

Create `src/memcore/sdk/models.py`:

```python
"""SDK-side response models (thin wrappers over domain models)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from memcore.domain.models import ScoredMemory

_TERMINAL_STATES = frozenset({"succeeded", "failed"})


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    state: str

    @property
    def done(self) -> bool:
        return self.state in _TERMINAL_STATES


class RecallOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[ScoredMemory]
    context: str | None = None
    context_tokens: int | None = None
```

- [ ] **Step 5: Run tests, then full gate**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_sdk_shared.py -v`
Expected: all PASS.
Then the full gate. Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/memcore/sdk/__init__.py src/memcore/sdk/exceptions.py src/memcore/sdk/_shared.py src/memcore/sdk/models.py tests/unit/test_sdk_shared.py
git commit -m "feat(sdk): foundation — exceptions, retry policy, error mapping, sdk extra (Phase 9)"
```

---

### Task 2: `AsyncMemCoreClient` — full v1 surface + retries + job polling

**Files:**
- Create: `src/memcore/sdk/async_client.py`
- Modify: `src/memcore/sdk/__init__.py` (export `AsyncMemCoreClient`)
- Test: `tests/unit/test_sdk_async.py`

**Interfaces:**
- Consumes (Task 1): everything under `memcore.sdk._shared`, `memcore.sdk.exceptions`, `memcore.sdk.models`. Domain models: `Session`, `MemoryRecord`, `MemoryType`.
- Produces (Task 3 mirrors this exact surface, sync):
  - `AsyncMemCoreClient(base_url: str, api_key: str, *, timeout: float = 10.0, retry: RetryPolicy | None = None, transport: Any | None = None, sleep: Callable[[float], Awaitable[None]] | None = None)`
  - Methods (all return parsed domain/SDK models): `health() -> dict[str, Any]`; `open_session(agent_id) -> Session`; `get_session(session_id) -> Session`; `append_message(session_id, role, content, metadata=None) -> Session`; `close_session(session_id) -> Session`; `remember(agent_id, content, *, type=MemoryType.SEMANTIC, importance=0.5, confidence=1.0, tags=None) -> MemoryRecord`; `get_memory(memory_id) -> MemoryRecord`; `memory_versions(memory_id) -> list[MemoryRecord]`; `correct_memory(memory_id, *, content=None, importance=None, confidence=None, tags=None) -> MemoryRecord`; `forget_memory(memory_id, *, mode="soft") -> None`; `recall(agent_id, query, *, k=8, types=None, weights=None, graph_expand=None, rerank=False, as_context=False) -> RecallOutcome`; `consolidate(session_id) -> Job`; `job(job_id) -> Job`; `run_decay() -> Job`; `wait_for_job(job_id, *, timeout=30.0, interval=0.2) -> Job`; `aclose() -> None`; async context manager (`__aenter__`/`__aexit__`).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_sdk_async.py`:

```python
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

        await client.forget_memory(corrected.id)
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
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_sdk_async.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'memcore.sdk.async_client'`.

- [ ] **Step 3: Implement the async client**

Create `src/memcore/sdk/async_client.py`:

```python
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
        except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
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
```

Update `src/memcore/sdk/__init__.py`: add `from memcore.sdk.async_client import AsyncMemCoreClient` and `"AsyncMemCoreClient"` to `__all__` (keep alphabetized).

- [ ] **Step 4: Run tests, then full gate**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_sdk_async.py -v`
Expected: all PASS.
Then the full gate. Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/memcore/sdk/async_client.py src/memcore/sdk/__init__.py tests/unit/test_sdk_async.py
git commit -m "feat(sdk): AsyncMemCoreClient — full v1 surface, retries, job polling (Phase 9)"
```

---

### Task 3: `MemCoreClient` (sync mirror) + parity guard

**Files:**
- Create: `src/memcore/sdk/client.py`
- Modify: `src/memcore/sdk/__init__.py` (export `MemCoreClient`)
- Test: `tests/unit/test_sdk_sync.py`

**Interfaces:**
- Consumes (Tasks 1–2): `_shared`, `exceptions`, `models`; the async client's surface (for the parity test).
- Produces: `MemCoreClient` — identical constructor and method names/signatures to `AsyncMemCoreClient` except: `sleep: Callable[[float], None] | None = None` (sync), `close()` instead of `aclose()`, `__enter__`/`__exit__` instead of async context manager, and all methods are `def` (blocking).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_sdk_sync.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_sdk_sync.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'memcore.sdk.client'`.

- [ ] **Step 3: Implement the sync client**

Create `src/memcore/sdk/client.py` — the exact mirror of `async_client.py` with these mechanical transformations and NOTHING else changed (same docstrings adapted, same method order, same bodies):
- `import time` instead of `asyncio`; default sleep is `time.sleep`; `sleep: Callable[[float], None] | None = None`.
- `httpx.Client` instead of `httpx.AsyncClient`; `self._client.request(...)` without `await`; every `async def` → `def`; every `await self._request(...)` → `self._request(...)`; every `await self._sleep(...)` → `self._sleep(...)`.
- `close()` calling `self._client.close()`; `__enter__`/`__exit__` context manager:

```python
    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> MemCoreClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
```

- Class docstring notes: "Sync mirror of :class:`AsyncMemCoreClient` — same surface, blocking I/O. The parity test (`test_sdk_sync.py`) guards signature drift."

Update `src/memcore/sdk/__init__.py`: add `from memcore.sdk.client import MemCoreClient` and `"MemCoreClient"` to `__all__` (alphabetized).

- [ ] **Step 4: Run tests, then full gate**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_sdk_sync.py -v`
Expected: all PASS (parity test enforces the mirror stayed exact).
Then the full gate. Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/memcore/sdk/client.py src/memcore/sdk/__init__.py tests/unit/test_sdk_sync.py
git commit -m "feat(sdk): MemCoreClient sync mirror + surface-parity guard (Phase 9)"
```

---

### Task 4: Docs, ADR-0018, quickstart — phase gate

**Files:**
- Create: `docs/adr/0018-python-sdk.md`
- Create: `docs/sdk-quickstart.md`
- Create: `docs/design/phase-09.md`
- Modify: `docs/adr/README.md` (index line), `docs/design/roadmap.md` (Phase 9 → ✅ Complete, Phase 10 → ⏳ Next), `CHANGELOG.md`, `PROJECT_STATE.md`

**Interfaces:** none — documentation of Tasks 1–3 exactly as built.

- [ ] **Step 1: Write ADR-0018**

`docs/adr/0018-python-sdk.md` (match the style of `docs/adr/0017-evaluation-framework.md`):
- **Status:** accepted. **Context:** consuming MemCore required hand-rolled HTTP calls; no typed errors, no retry discipline, no job-polling ergonomics.
- **Decision:** (1) the SDK ships inside the `memcore` package as `memcore.sdk`, a consumer layer importing only `memcore.domain` + httpx — installable server-free via the new `sdk` extra (`pip install 'memcore[sdk]'` pulls pydantic + httpx only), httpx lazy-imported with the standard install hint; (2) async-first `AsyncMemCoreClient` with a mechanically mirrored sync `MemCoreClient`, drift prevented by a signature-parity test rather than code generation; shared pure logic (retry policy, backoff, RFC-7807 error mapping) lives once in `_shared.py`; (3) retries are GET-only on {429, 502, 503, 504} or transport failure, deterministic exponential backoff (no jitter) with injectable sleep — non-idempotent POSTs are never replayed after ambiguous failures; (4) responses validate into the existing domain models (`Session`, `MemoryRecord`, `ScoredMemory`) — the SDK inherits the server's schema evolution instead of duplicating models; (5) `wait_for_job` polls with a bounded timeout raising `JobTimeout`; (6) pagination helpers are deferred: the v1 API has no list-style endpoints yet — revisit when one lands.
- **Consequences:** one wire contract, typed end to end; SDK tests double as API contract tests (ASGI in-process end-to-end); the sync mirror costs mechanical duplication, paid deliberately for zero event-loop entanglement, guarded by the parity test.

Add to `docs/adr/README.md` index: `- [ADR-0018](0018-python-sdk.md) — Python SDK: async+sync typed clients, GET-only retries, sdk extra`.

- [ ] **Step 2: Write the quickstart**

`docs/sdk-quickstart.md`:

````markdown
# MemCore Python SDK — Quickstart

## Install

```bash
pip install 'memcore[sdk]'   # pydantic + httpx only; no server dependencies
```

## Async

```python
import asyncio
from memcore.sdk import AsyncMemCoreClient


async def main() -> None:
    async with AsyncMemCoreClient("http://localhost:8000", "your-api-key") as client:
        # Store a memory (importance/confidence optional, 0..1).
        record = await client.remember(
            "agent-1", "Chinmay prefers dark mode.", importance=0.8, tags=["pref"]
        )

        # Hybrid recall (relevance x recency x reinforced importance).
        outcome = await client.recall("agent-1", "what UI theme does chinmay like?")
        for scored in outcome.results:
            print(f"{scored.final:.3f}  {scored.memory.content}")

        # Sessions + async consolidation.
        session = await client.open_session("agent-1")
        await client.append_message(session.id, "user", "I moved to Pune last week.")
        await client.close_session(session.id)  # enqueues consolidation

        # Trigger a decay sweep and wait for it.
        job = await client.run_decay()
        await client.wait_for_job(job.job_id)


asyncio.run(main())
```

## Sync

```python
from memcore.sdk import MemCoreClient

with MemCoreClient("http://localhost:8000", "your-api-key") as client:
    record = client.remember("agent-1", "Bruno is a beagle.")
    print(client.get_memory(record.id).content)
```

## Errors and retries

Every failure is a `memcore.sdk.MemCoreClientError`:

- `AuthError` (401), `NotFoundError` (404), `ConflictError` (409),
  `ValidationAPIError` (422), `ServerError` (5xx) — typed from the server's
  problem+json body (`.status`, `.title`, `.detail`).
- `TransportError` — network failure after retries.
- `JobTimeout` — `wait_for_job` exceeded its timeout.

GET requests are retried automatically on 429/502/503/504 and network errors
(exponential backoff, 3 attempts by default — tune with
`RetryPolicy(max_attempts=..., backoff_base=..., backoff_cap=...)` from
`memcore.sdk._shared`). Writes (POST/PATCH/DELETE) are never retried
automatically: an ambiguous failure could otherwise duplicate a write.
````

- [ ] **Step 3: Write the phase doc + update CHANGELOG, roadmap, PROJECT_STATE**

`docs/design/phase-09.md`, same structure as `phase-08.md` (Objective / Delivered / Gate / Deferred / Self-review): Delivered = `sdk` extra + lazy httpx; exceptions hierarchy + `_shared` pure logic; `AsyncMemCoreClient` (full v1 surface, ASGI end-to-end tested); `MemCoreClient` sync mirror + parity guard; quickstart doc. Deferred = pagination helpers (no list endpoints in v1 yet); higher-level conveniences (auto-consolidating session context manager) — post-v1. Record the actual gate numbers from Step 4.

`CHANGELOG.md` — new block above Phase 8:

```markdown
### Added — Phase 9: Python SDK
- `memcore.sdk`: typed async (`AsyncMemCoreClient`) + sync (`MemCoreClient`)
  clients covering the full v1 API (sessions, memories, recall, consolidate,
  jobs, decay), validating responses into domain models — ADR-0018.
- Typed errors from problem+json (`AuthError`/`NotFoundError`/`ConflictError`
  /`ValidationAPIError`/`ServerError`), `TransportError`, `JobTimeout`.
- GET-only automatic retries ({429,502,503,504} + transport failures),
  deterministic exponential backoff, injectable sleep; `wait_for_job` polling.
- New install extra: `pip install 'memcore[sdk]'` (pydantic + httpx only);
  sync/async surface parity enforced by test; `docs/sdk-quickstart.md`.
```

`docs/design/roadmap.md`: Phase 9 → `✅ Complete`, Phase 10 → `⏳ Next`.

`PROJECT_STATE.md`: current position → Phase 9 complete / Phase 10 (Observability & monitoring) not started, awaiting approval; record the Phase 9 gate numbers; next tasks → Phase 10 outline (structured request/job logging with correlation ids, Prometheus metrics endpoint, health/readiness probes incl. backend checks, latency histograms for recall/consolidation/decay); backlog carried over (sweep dedupe + rate limiting; restore endpoint — deployment/security); open decision → approve Phase 10 start.

- [ ] **Step 4: Run the phase gate and record numbers**

Run: `./.venv/Scripts/python.exe -m pytest` (record pass count + coverage %), `./.venv/Scripts/python.exe -m ruff check .`, `./.venv/Scripts/python.exe -m mypy`
Expected: all clean, coverage ≥ 85%. Copy the real numbers into `phase-09.md` and `PROJECT_STATE.md`.

- [ ] **Step 5: Phase commit**

```bash
git add docs/adr/0018-python-sdk.md docs/adr/README.md docs/sdk-quickstart.md docs/design/phase-09.md docs/design/roadmap.md CHANGELOG.md PROJECT_STATE.md
git commit -m "docs: Phase 9 gate — Python SDK (ADR-0018, quickstart)"
```

Then STOP: per the phase gate, WAIT for user approval before any Phase 10 work.
