# Phase 10 — Observability & Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correlation-id structured logging, a Prometheus `/metrics` endpoint with HTTP and operation-latency histograms (recall / consolidation / decay), and a `/ready` probe with per-backend checks — all behind an optional `observability` extra.

**Architecture:** A dependency-light `memcore/observability/` package holds the request-id contextvar (`context.py`) and a lazy prometheus-client wrapper (`metrics.py`) that silently no-ops when the extra is absent and renders the exposition text when present. The API layer owns the HTTP touchpoints: a pure-ASGI middleware (`api/middleware.py`) binds/propagates `X-Request-ID`, emits one structured access-log line per request, and records HTTP metrics labeled by **route template** (not raw path — bounded cardinality); `/metrics` and `/ready` join the unauthenticated `health_router`. Readiness uses duck-typed optional `ping()` methods on adapters (same precedent as the existing `getattr(store, "init", ...)` in `create_app`) — no port ABC changes. Operation latencies are recorded at call boundaries (recall route, immediate-engine handlers, Celery task shells), keeping `services/*` untouched and hexagonal. No new `Settings` block: log level already gates verbosity, and `/metrics` degrades to a clear 501 problem+json without the extra (recorded in ADR-0019).

**Tech Stack:** stdlib `logging` + `contextvars`, prometheus-client (new `observability` extra), FastAPI/pure-ASGI middleware, pytest with in-process ASGI clients.

## Global Constraints

- Quality gate (every task, before commit): `./.venv/Scripts/python.exe -m pytest` all pass, coverage ≥ 85%; `./.venv/Scripts/python.exe -m ruff check .` clean; `./.venv/Scripts/python.exe -m mypy` clean (strict).
- Hexagonal: `services/*`, `domain/*`, `ports/*` are NOT touched in this phase. `memcore.observability` imports stdlib + lazily prometheus-client only (plus `memcore.exceptions` for the hint error); it must not import services/ports/adapters/api. `api/*` may import observability.
- `prometheus_client` is lazy-imported with the install hint `"prometheus-client is not installed; install the observability extra: pip install 'memcore[observability]'"`; when absent, all record functions are silent no-ops and only `render()` raises `ConfigurationError`.
- Adapter `ping()` is optional and duck-typed (NOT added to any port ABC); absence means "no probe, assumed ok". Live-backend pings (qdrant/neo4j/redis) live in files already excluded from unit coverage.
- HTTP metrics are labeled by route template (`/v1/memories/{memory_id}`), never raw paths with ids.
- Metric names exactly: `memcore_http_requests_total{method,route,status}`, `memcore_http_request_duration_seconds{method,route,status}`, `memcore_operation_duration_seconds{operation}` with operation values exactly `"recall"`, `"consolidation"`, `"decay_sweep"`.
- The module-level metrics registry is shared across app instances in one process: tests assert presence/labels, never exact counts.
- One commit per task; phase gate + docs in Task 5; WAIT for user approval after the phase commit.

---

### Task 1: Request-id context + log injection

**Files:**
- Create: `src/memcore/observability/__init__.py`
- Create: `src/memcore/observability/context.py`
- Modify: `src/memcore/logging.py` (context filter + plain-format field)
- Test: `tests/unit/test_observability_context.py`

**Interfaces:**
- Consumes: nothing project-specific.
- Produces (Tasks 3–4 rely on):
  - `memcore.observability.context`: `new_request_id() -> str` (32-char uuid4 hex); `get_request_id() -> str | None`; `bind_request_id(value: str) -> Token[str | None]`; `reset_request_id(token: Token[str | None]) -> None`.
  - Every log record formatted by `memcore.logging` carries a `request_id` attribute (`"-"` when unbound) in both plain and JSON output.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_observability_context.py`:

```python
"""Phase 10 — request-id context propagation + log injection."""

from __future__ import annotations

import asyncio
import json
import logging

from memcore.logging import configure_logging, get_logger
from memcore.observability.context import (
    bind_request_id,
    get_request_id,
    new_request_id,
    reset_request_id,
)


def test_new_request_id_is_32_hex() -> None:
    rid = new_request_id()
    assert len(rid) == 32
    assert int(rid, 16) >= 0  # valid hex
    assert new_request_id() != rid  # unique


def test_bind_get_reset_roundtrip() -> None:
    assert get_request_id() is None
    token = bind_request_id("abc123")
    assert get_request_id() == "abc123"
    reset_request_id(token)
    assert get_request_id() is None


async def test_context_is_task_isolated() -> None:
    async def worker(rid: str) -> str | None:
        bind_request_id(rid)
        await asyncio.sleep(0)
        return get_request_id()

    first, second = await asyncio.gather(worker("rid-1"), worker("rid-2"))
    assert first == "rid-1"
    assert second == "rid-2"
    assert get_request_id() is None  # outer context untouched


def test_json_logs_carry_request_id(capsys: object) -> None:
    import pytest

    assert isinstance(capsys, pytest.CaptureFixture)
    configure_logging("INFO", json_output=True)
    token = bind_request_id("rid-json")
    try:
        get_logger("obs-test").info("hello")
    finally:
        reset_request_id(token)
        configure_logging("INFO", json_output=False)  # restore default
    line = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["request_id"] == "rid-json"
    assert payload["msg"] == "hello"


def test_plain_logs_show_dash_when_unbound(capsys: object) -> None:
    import pytest

    assert isinstance(capsys, pytest.CaptureFixture)
    configure_logging("INFO", json_output=False)
    get_logger("obs-test").info("plain hello")
    out = capsys.readouterr().out
    assert "[-]" in out
    assert "plain hello" in out


def test_filter_does_not_clobber_explicit_extra() -> None:
    # A caller passing extra={"request_id": ...} wins over the contextvar.
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    configure_logging("INFO", json_output=False)
    root = logging.getLogger()
    capture = Capture()
    for f in root.handlers[0].filters:
        capture.addFilter(f)
    root.addHandler(capture)
    try:
        get_logger("obs-test").info("x", extra={"request_id": "explicit"})
    finally:
        root.removeHandler(capture)
    assert records[-1].request_id == "explicit"
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_observability_context.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'memcore.observability'`.

- [ ] **Step 3: Implement context + package init**

Create `src/memcore/observability/__init__.py`:

```python
"""Observability plumbing (Phase 10, ADR-0019).

Dependency-light by design: ``context`` is stdlib contextvars, ``metrics``
lazy-imports prometheus-client behind the ``observability`` extra and no-ops
without it. This package must never import services/ports/adapters/api —
the API layer consumes it, not the other way around.
"""

from memcore.observability.context import (
    bind_request_id,
    get_request_id,
    new_request_id,
    reset_request_id,
)

__all__ = [
    "bind_request_id",
    "get_request_id",
    "new_request_id",
    "reset_request_id",
]
```

Create `src/memcore/observability/context.py`:

```python
"""Request/job correlation id — a contextvar visible to every log record.

The ASGI middleware binds one id per HTTP request (honoring an incoming
``X-Request-ID``); worker task shells bind one per job. ``memcore.logging``'s
context filter stamps the current value onto every record.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar, Token

_request_id: ContextVar[str | None] = ContextVar("memcore_request_id", default=None)


def new_request_id() -> str:
    """Fresh opaque correlation id (uuid4 hex, 32 chars)."""
    return uuid.uuid4().hex


def get_request_id() -> str | None:
    """The correlation id bound to the current context, if any."""
    return _request_id.get()


def bind_request_id(value: str) -> Token[str | None]:
    """Bind ``value`` for the current context; return the reset token."""
    return _request_id.set(value)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the binding that ``token``'s ``bind_request_id`` replaced."""
    _request_id.reset(token)
```

- [ ] **Step 4: Inject into logging**

In `src/memcore/logging.py`:

1. Add after the imports:

```python
from memcore.observability.context import get_request_id


class _ContextFilter(logging.Filter):
    """Stamp the correlation id onto every record (``"-"`` when unbound).

    An explicit ``extra={"request_id": ...}`` from the caller wins.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id() or "-"
        return True
```

2. In `configure_logging`, attach the filter and include the field in the plain format:

```python
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_ContextFilter())
    if json_output:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s %(name)s [%(request_id)s]: %(message)s"
            )
        )
    root.addHandler(handler)
```

(The JSON formatter needs no change: `request_id` is a non-reserved record attribute, so the existing extras loop already emits it.)

- [ ] **Step 5: Run tests, then full gate**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_observability_context.py tests/unit/test_logging.py -v`
Expected: all PASS (including the pre-existing logging tests — if one asserts the old plain format string verbatim, update it to expect the ` [%(request_id)s]` field; that change is the point of this task).
Then the full gate. Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/memcore/observability/__init__.py src/memcore/observability/context.py src/memcore/logging.py tests/unit/test_observability_context.py tests/unit/test_logging.py
git commit -m "feat(obs): request-id context + log injection (Phase 10)"
```

---

### Task 2: Lazy Prometheus metrics module + packaging

**Files:**
- Create: `src/memcore/observability/metrics.py`
- Modify: `src/memcore/observability/__init__.py` (exports)
- Modify: `pyproject.toml` (`observability` extra; prometheus-client in `dev`; ruff per-file-ignore; mypy override)
- Test: `tests/unit/test_observability_metrics.py`

**Interfaces:**
- Consumes: `memcore.exceptions.ConfigurationError`.
- Produces (Tasks 3–4 rely on):
  - `metrics_available() -> bool`
  - `observe_http(method: str, route: str, status: int, seconds: float) -> None` (no-op without the extra)
  - `observe_operation(operation: str, seconds: float) -> None` (no-op without the extra)
  - `render() -> tuple[bytes, str]` — (exposition payload, content type); raises `ConfigurationError` with the install hint when the extra is absent
  - test-only escape hatch `_cache: dict[str, Any]` (cleared by tests to simulate a fresh process)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_observability_metrics.py`:

```python
"""Phase 10 — lazy Prometheus wrapper: real metrics with the extra, no-ops without."""

from __future__ import annotations

import builtins
from typing import Any

import pytest

from memcore.exceptions import ConfigurationError
from memcore.observability import metrics


def test_metrics_available_in_dev_env() -> None:
    # prometheus-client ships with the dev extra, so this env has it.
    assert metrics.metrics_available() is True


def test_observe_and_render_exposition() -> None:
    metrics.observe_http("GET", "/v1/memories/{memory_id}", 200, 0.012)
    metrics.observe_operation("recall", 0.034)
    payload, content_type = metrics.render()
    text = payload.decode()
    assert "memcore_http_requests_total" in text
    assert 'route="/v1/memories/{memory_id}"' in text
    assert 'status="200"' in text
    assert "memcore_http_request_duration_seconds" in text
    assert 'memcore_operation_duration_seconds' in text
    assert 'operation="recall"' in text
    assert content_type.startswith("text/plain")


def test_noop_without_prometheus(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("prometheus_client"):
            raise ImportError("no prometheus")
        return real_import(name, *args, **kwargs)

    saved = dict(metrics._cache)
    metrics._cache.clear()
    monkeypatch.setattr(builtins, "__import__", fake_import)
    try:
        assert metrics.metrics_available() is False
        # Record calls must be silent no-ops, not errors.
        metrics.observe_http("GET", "/health", 200, 0.001)
        metrics.observe_operation("recall", 0.001)
        with pytest.raises(ConfigurationError, match=r"memcore\[observability\]"):
            metrics.render()
    finally:
        monkeypatch.undo()
        metrics._cache.clear()
        metrics._cache.update(saved)


def test_unavailability_is_cached_per_process_state() -> None:
    # After the no-op test restored the cache, metrics work again.
    assert metrics.metrics_available() is True
    metrics.observe_operation("decay_sweep", 0.5)
    payload, _ = metrics.render()
    assert 'operation="decay_sweep"' in payload.decode()
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_observability_metrics.py -v`
Expected: FAIL — `ImportError: cannot import name 'metrics'` (module missing).

- [ ] **Step 3: Packaging**

In `pyproject.toml`:
1. `[project.optional-dependencies]` — after the `sdk` line add:

```toml
observability = ["prometheus-client>=0.20"]
```

2. Add `"prometheus-client>=0.20",` to the `dev` extra list (tests assert real exposition).
3. `[tool.ruff.lint.per-file-ignores]` — alongside the other lazy-import entries:

```toml
# Metrics lazy-import prometheus-client so core installs without the extra.
"src/memcore/observability/*" = ["PLC0415"]
```

4. Add `"prometheus_client.*"` to the existing `ignore_missing_imports` mypy override module list.

Then: `./.venv/Scripts/python.exe -m pip install "prometheus-client>=0.20"` (the venv needs it for the tests).

- [ ] **Step 4: Implement the metrics module**

Create `src/memcore/observability/metrics.py`:

```python
"""Lazy Prometheus wrapper — real metrics with the extra, no-ops without.

Metric objects live in a module-level cache keyed off one process-wide
registry: multiple app instances in one process share it (tests assert
presence, never exact counts). Without prometheus-client, ``observe_*`` are
silent no-ops and only ``render`` raises, so instrumented code paths never
need to branch on availability.
"""

from __future__ import annotations

from typing import Any

from memcore.exceptions import ConfigurationError

_INSTALL_HINT = (
    "prometheus-client is not installed; install the observability extra: "
    "pip install 'memcore[observability]'"
)

# Test-visible cache: {"available": bool, "registry": ..., metric objects...}
_cache: dict[str, Any] = {}

_HTTP_LABELS = ("method", "route", "status")
_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


def _load() -> dict[str, Any] | None:
    """Build (once) the registry + metric objects; None when unavailable."""
    if "available" in _cache:
        return _cache if _cache["available"] else None
    try:
        from prometheus_client import (
            CollectorRegistry,
            Counter,
            Histogram,
        )
    except ImportError:
        _cache["available"] = False
        return None
    registry = CollectorRegistry()
    _cache.update(
        available=True,
        registry=registry,
        http_total=Counter(
            "memcore_http_requests_total",
            "HTTP requests processed",
            _HTTP_LABELS,
            registry=registry,
        ),
        http_seconds=Histogram(
            "memcore_http_request_duration_seconds",
            "HTTP request latency",
            _HTTP_LABELS,
            buckets=_BUCKETS,
            registry=registry,
        ),
        operation_seconds=Histogram(
            "memcore_operation_duration_seconds",
            "Core operation latency (recall / consolidation / decay_sweep)",
            ("operation",),
            buckets=_BUCKETS,
            registry=registry,
        ),
    )
    return _cache


def metrics_available() -> bool:
    """Whether prometheus-client is importable (cached per process)."""
    return _load() is not None


def observe_http(method: str, route: str, status: int, seconds: float) -> None:
    """Record one HTTP request; silent no-op without the extra."""
    cache = _load()
    if cache is None:
        return
    labels = {"method": method, "route": route, "status": str(status)}
    cache["http_total"].labels(**labels).inc()
    cache["http_seconds"].labels(**labels).observe(seconds)


def observe_operation(operation: str, seconds: float) -> None:
    """Record one core-operation latency; silent no-op without the extra."""
    cache = _load()
    if cache is None:
        return
    cache["operation_seconds"].labels(operation=operation).observe(seconds)


def render() -> tuple[bytes, str]:
    """Prometheus exposition text and its content type.

    Raises :class:`ConfigurationError` with the install hint when the
    ``observability`` extra is absent — the /metrics route maps it to 501.
    """
    cache = _load()
    if cache is None:
        raise ConfigurationError(_INSTALL_HINT)
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return generate_latest(cache["registry"]), CONTENT_TYPE_LATEST
```

Update `src/memcore/observability/__init__.py`: add

```python
from memcore.observability import metrics
```

and `"metrics"` to `__all__` (alphabetized).

- [ ] **Step 5: Run tests, then full gate**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_observability_metrics.py -v`
Expected: all PASS.
Then the full gate. Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/memcore/observability/metrics.py src/memcore/observability/__init__.py pyproject.toml tests/unit/test_observability_metrics.py
git commit -m "feat(obs): lazy Prometheus metrics module + observability extra (Phase 10)"
```

---

### Task 3: Middleware, /metrics, /ready, adapter pings

**Files:**
- Create: `src/memcore/api/middleware.py`
- Modify: `src/memcore/api/routes.py` (add `/metrics` + `/ready` to `health_router`)
- Modify: `src/memcore/api/app.py` (install middleware; expose probe components on `app.state`)
- Modify: `src/memcore/adapters/sql/memory_store.py` (add `ping`)
- Modify: `src/memcore/adapters/qdrant/vector_store.py`, `src/memcore/adapters/neo4j/graph_store.py`, `src/memcore/adapters/redis/working_memory.py` (add `ping` — one cheapest-driver-call each; these files are excluded from unit coverage, validated by the integration suite)
- Modify: `tests/integration/test_backends.py` (assert `ping()` for each live backend inside the existing per-backend tests)
- Test: `tests/unit/test_api_observability.py`

**Interfaces:**
- Consumes (Tasks 1–2): `bind_request_id`/`reset_request_id`/`new_request_id`/`get_request_id`; `metrics.observe_http`, `metrics.render`, `metrics.metrics_available`.
- Produces (Task 4 relies on): requests run with a bound request id (handlers inherit it); `GET /metrics` (200 exposition | 501 problem+json without extra); `GET /ready` (200 `{"status": "ready", "components": {...}}` | 503 same shape with `"status": "degraded"`); adapters may expose `async def ping() -> None` (raise = unhealthy).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_api_observability.py`:

```python
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
    record = next(r for r in caplog.records if r.name == "memcore.api.access")
    assert record.request_id == "rid-log"
    assert record.method == "GET"
    assert record.path == "/health"
    assert record.status == 200
    assert record.duration_ms >= 0


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
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_api_observability.py -v`
Expected: FAIL — missing `x-request-id` header, 404 for `/metrics` and `/ready`, `AttributeError: ping`.

- [ ] **Step 3: Implement the middleware**

Create `src/memcore/api/middleware.py`:

```python
"""Pure-ASGI observability middleware (Phase 10, ADR-0019).

Per HTTP request: bind a correlation id (honoring an incoming
``X-Request-ID``), stamp it on the response, emit one structured access-log
line, and record HTTP metrics labeled by *route template* (bounded
cardinality; unmatched 404s fall back to the raw path, an accepted
low-volume exception).
"""

from __future__ import annotations

import time
from typing import Any

from memcore.logging import get_logger
from memcore.observability import metrics
from memcore.observability.context import bind_request_id, new_request_id, reset_request_id

_access_log = get_logger("api.access")

Scope = dict[str, Any]


class ObservabilityMiddleware:
    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v for k, v in scope.get("headers", [])}
        incoming = headers.get("x-request-id")
        request_id = incoming.decode("latin-1") if incoming else new_request_id()
        token = bind_request_id(request_id)
        status_holder = {"status": 500}
        started = time.perf_counter()

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                raw = list(message.get("headers", []))
                raw.append((b"x-request-id", request_id.encode("latin-1")))
                message = {**message, "headers": raw}
            await send(message)

        try:
            await self._app(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - started
            # Starlette stamps the matched route onto the scope during
            # routing; template beats raw path for label cardinality.
            route = scope.get("route")
            template = getattr(route, "path_format", None) or scope.get("path", "?")
            status = status_holder["status"]
            metrics.observe_http(scope.get("method", "?"), template, status, duration)
            _access_log.info(
                "request",
                extra={
                    "request_id": request_id,
                    "method": scope.get("method", "?"),
                    "path": scope.get("path", "?"),
                    "route": template,
                    "status": status,
                    "duration_ms": round(duration * 1000, 2),
                },
            )
            reset_request_id(token)
```

(`request_id` is passed explicitly in `extra` even though the logging context filter would stamp it on stream-handler output: test/log capture handlers — e.g. pytest's `caplog` — attach their own handlers without the filter, and an explicit extra is visible to all of them. The filter still covers every other logger's records.)

- [ ] **Step 4: Endpoints + wiring + pings**

1. `src/memcore/api/routes.py` — add to the imports `from fastapi.responses import JSONResponse, Response` and `from memcore.observability import metrics as obs_metrics`, then add to `health_router` after `health`:

```python
@health_router.get("/metrics", include_in_schema=False)
async def metrics_endpoint() -> Response:
    payload, content_type = obs_metrics.render()  # ConfigurationError -> 500-range problem
    return Response(content=payload, media_type=content_type)


@health_router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    components: dict[str, str] = {}
    degraded = False
    for name, component in request.app.state.memcore_probes.items():
        ping = getattr(component, "ping", None)
        if not callable(ping):
            components[name] = "ok"
            continue
        try:
            await ping()
            components[name] = "ok"
        except Exception as exc:  # noqa: BLE001 - any failure means not ready
            components[name] = f"error: {exc}"
            degraded = True
    status = 503 if degraded else 200
    return JSONResponse(
        status_code=status,
        content={"status": "degraded" if degraded else "ready",
                 "components": components},
    )
```

(`Request` is already imported in the api layer via `fastapi`; add it to the `fastapi` import line in routes.py: `from fastapi import APIRouter, Query, Request`.)
Note: `metrics_endpoint` deliberately lets `ConfigurationError` bubble into the app's existing problem+json mapping — `ConfigurationError` already maps to 500 in `_STATUS_BY_ERROR`; change that mapping tuple for this route ONLY by catching it locally instead if the test expects 501. Concretely, to return 501:

```python
@health_router.get("/metrics", include_in_schema=False)
async def metrics_endpoint() -> Response:
    try:
        payload, content_type = obs_metrics.render()
    except ConfigurationError as exc:
        return JSONResponse(
            status_code=501,
            media_type="application/problem+json",
            content={"type": "https://memcore.dev/errors/ConfigurationError",
                     "title": "ConfigurationError", "status": 501,
                     "detail": str(exc), "instance": "/metrics"},
        )
    return Response(content=payload, media_type=content_type)
```

(import `ConfigurationError` from `memcore.exceptions`; use this 501 variant — it keeps the endpoint self-describing without touching the global error mapping.)

2. `src/memcore/api/app.py` — in `create_app`, after `app.state.memcore = app_state` add:

```python
    app.state.memcore_probes = {
        "store": app_state.store,
        "vectors": app_state.vectors,
        "graph": app_state.graph,
        "working": app_state.working,
    }
    app.add_middleware(ObservabilityMiddleware)
```

Wait — `ObservabilityMiddleware` is pure ASGI, and `app.add_middleware` expects a class taking `app` as first arg — which it does. Add the import `from memcore.api.middleware import ObservabilityMiddleware`.

3. `src/memcore/adapters/sql/memory_store.py` — add next to `close()`:

```python
    async def ping(self) -> None:
        """Cheap liveness probe: one round-trip (`SELECT 1`)."""
        async with self._sessions() as db:
            await db.execute(text("SELECT 1"))
```

(add `text` to the existing `sqlalchemy` import.)

4. Live-backend adapters — add an `async def ping(self) -> None` to each, using the cheapest call the adapter's existing client exposes (read each file first; follow its established sync-to-thread or async pattern):
   - `adapters/qdrant/vector_store.py`: list collections (e.g. the client's `get_collections()` via the adapter's existing call pattern).
   - `adapters/neo4j/graph_store.py`: `RETURN 1` (driver's `verify_connectivity()` if the adapter holds a driver object).
   - `adapters/redis/working_memory.py`: the client's `ping()`.
   These files are excluded from unit coverage (`pyproject.toml` omit list) — correctness is validated by the integration suite.

5. `tests/integration/test_backends.py` — inside each existing live-backend test (they already skip when the backend is unreachable), add one `await adapter.ping()` assertion line near the start.

- [ ] **Step 5: Run tests, then full gate**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_api_observability.py tests/unit/test_api.py -v`
Expected: all PASS (pre-existing API tests unaffected — the middleware only adds a header).
Then the full gate. Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/memcore/api/middleware.py src/memcore/api/routes.py src/memcore/api/app.py src/memcore/adapters/sql/memory_store.py src/memcore/adapters/qdrant/vector_store.py src/memcore/adapters/neo4j/graph_store.py src/memcore/adapters/redis/working_memory.py tests/integration/test_backends.py tests/unit/test_api_observability.py
git commit -m "feat(obs): request middleware, /metrics + /ready, adapter pings (Phase 10)"
```

---

### Task 4: Operation latency instrumentation + job log correlation

**Files:**
- Modify: `src/memcore/api/routes.py` (time the recall call)
- Modify: `src/memcore/api/app.py` (time + correlate the immediate-engine handlers)
- Modify: `src/memcore/workers/celery_app.py` (bind job ids; time both tasks)
- Test: `tests/unit/test_api_observability.py` (extend)

**Interfaces:**
- Consumes: `metrics.observe_operation(operation, seconds)` with values `"recall"`, `"consolidation"`, `"decay_sweep"`; `bind_request_id`/`new_request_id`/`reset_request_id`.
- Produces: nothing new — instrumentation only; `services/*` remain untouched.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_api_observability.py`:

```python
async def test_operation_latency_histograms_recorded(client: AsyncClient) -> None:
    await client.post(
        "/v1/memories",
        json={"agent_id": "a1", "content": "the sky is blue"},
        headers={"X-API-Key": KEY},
    )
    recall = await client.post(
        "/v1/recall",
        json={"agent_id": "a1", "query": "sky"},
        headers={"X-API-Key": KEY},
    )
    assert recall.status_code == 200

    # decay runs through the immediate engine handler registered in create_app.
    decay = await client.post("/v1/decay", headers={"X-API-Key": KEY})
    assert decay.status_code == 202

    text = (await client.get("/metrics")).text
    assert 'memcore_operation_duration_seconds_count{operation="recall"}' in text
    assert 'memcore_operation_duration_seconds_count{operation="decay_sweep"}' in text


async def test_consolidation_latency_recorded_via_session_close(
    client: AsyncClient,
) -> None:
    opened = await client.post(
        "/v1/sessions", json={"agent_id": "a1"}, headers={"X-API-Key": KEY}
    )
    session_id = opened.json()["session"]["id"]
    await client.post(
        f"/v1/sessions/{session_id}/messages",
        json={"role": "user", "content": "hello"},
        headers={"X-API-Key": KEY},
    )
    closed = await client.post(
        f"/v1/sessions/{session_id}/close", headers={"X-API-Key": KEY}
    )
    assert closed.status_code == 200

    text = (await client.get("/metrics")).text
    assert 'memcore_operation_duration_seconds_count{operation="consolidation"}' in text
```

(Note: `_state()`'s `ScriptedLLMProvider` currently scripts one `"{}"` response — bump it to `responses=["{}"] * 4` so consolidation has responses available.)

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_api_observability.py -v -k operation_latency`
Expected: FAIL — no `memcore_operation_duration_seconds` samples for those operations.

- [ ] **Step 3: Instrument the call boundaries**

1. `src/memcore/api/routes.py`, `recall` route — wrap the service call (add `import time` at the top of the file and `from memcore.observability import metrics as obs_metrics` is already imported from Task 3):

```python
    started = time.perf_counter()
    results = await state.recall.recall(
        tenant,
        body.agent_id,
        body.query,
        k=body.k,
        types=body.types,
        weights=weights,
        graph_expand=body.graph_expand,
        rerank=body.rerank,
    )
    obs_metrics.observe_operation("recall", time.perf_counter() - started)
```

2. `src/memcore/api/app.py`, the immediate-engine handlers (add `import time`, `from memcore.observability import metrics as obs_metrics`):

```python
        async def _consolidate(payload: dict[str, object]) -> None:
            started = time.perf_counter()
            try:
                await consolidation.consolidate_session(
                    str(payload["tenant_id"]), str(payload["session_id"])
                )
            finally:
                obs_metrics.observe_operation(
                    "consolidation", time.perf_counter() - started
                )

        workflow.register("consolidate_session", _consolidate)

        async def _decay(payload: dict[str, object]) -> None:
            started = time.perf_counter()
            try:
                await decay.sweep(str(payload["tenant_id"]))
            finally:
                obs_metrics.observe_operation(
                    "decay_sweep", time.perf_counter() - started
                )

        workflow.register("decay_tenant", _decay)
```

3. `src/memcore/workers/celery_app.py` — both tasks gain job-scoped correlation ids and timing (add `import time`, `from memcore.observability import metrics as obs_metrics`, `from memcore.observability.context import bind_request_id, new_request_id, reset_request_id`):

```python
@app.task(name="memcore.consolidate_session")
def consolidate_session(tenant_id: str, session_id: str) -> dict[str, Any]:
    token = bind_request_id(new_request_id())
    started = time.perf_counter()
    try:
        service = _get_consolidation(_settings)
        report = asyncio.run(service.consolidate_session(tenant_id, session_id))
        logger.info("consolidated", extra={"session_id": session_id})
        return report.model_dump()
    finally:
        obs_metrics.observe_operation(
            "consolidation", time.perf_counter() - started
        )
        reset_request_id(token)


@app.task(name="memcore.decay_tenant")
def decay_tenant(tenant_id: str) -> dict[str, Any]:
    token = bind_request_id(new_request_id())
    started = time.perf_counter()
    try:
        service = _get_decay(_settings)
        report = asyncio.run(service.sweep(tenant_id))
        logger.info("decay swept", extra={"tenant_id": tenant_id})
        return report.model_dump()
    finally:
        obs_metrics.observe_operation("decay_sweep", time.perf_counter() - started)
        reset_request_id(token)
```

(Worker-process metric exposition — a worker has no HTTP server — is deferred to the deployment phase; the recording is still correct for the immediate engine and future exposition. Note this in the phase doc.)

- [ ] **Step 4: Run tests, then full gate**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_api_observability.py -v`
Expected: all PASS.
Then the full gate. Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/memcore/api/routes.py src/memcore/api/app.py src/memcore/workers/celery_app.py tests/unit/test_api_observability.py
git commit -m "feat(obs): operation latency histograms + job log correlation (Phase 10)"
```

---

### Task 5: Docs, ADR-0019 — phase gate

**Files:**
- Create: `docs/adr/0019-observability.md`
- Create: `docs/design/phase-10.md`
- Modify: `docs/adr/README.md` (index line), `docs/design/roadmap.md` (Phase 10 → ✅ Complete, Phase 11 → ⏳ Next), `CHANGELOG.md`, `PROJECT_STATE.md`

**Interfaces:** none — documentation of Tasks 1–4 exactly as built.

- [ ] **Step 1: Write ADR-0019**

`docs/adr/0019-observability.md` (match ADR-0018's style):
- **Status:** accepted. **Context:** no correlation between log lines of one request/job; no metrics; `/health` was liveness-only.
- **Decision:** (1) correlation ids via contextvar (`memcore.observability.context`), stamped on every log record by a logging filter (`"-"` when unbound), bound per HTTP request by pure-ASGI middleware (honoring incoming `X-Request-ID`, echoed on responses) and per job by the Celery task shells; (2) Prometheus behind the optional `observability` extra — `memcore.observability.metrics` lazy-imports prometheus-client, `observe_*` silently no-op without it, `/metrics` returns 501 problem+json with the install hint; metric names `memcore_http_requests_total`/`memcore_http_request_duration_seconds` (labels method/route/status, route = template not raw path — cardinality bound; unmatched 404s fall back to raw path, accepted) and `memcore_operation_duration_seconds{operation∈recall,consolidation,decay_sweep}`; (3) operation latency is recorded at call boundaries (recall route, immediate-engine handlers, Celery shells) — `services/*` untouched, no telemetry port (YAGNI; revisit if a second telemetry backend appears); (4) readiness via duck-typed optional `async ping()` on adapters (precedent: `init` in `create_app`); `/ready` reports per-component status and 503s when any probe fails; in-memory adapters expose no ping (assumed ok); (5) no new Settings block — log level gates verbosity, the extra gates metrics; (6) worker-process metric exposition (no HTTP server in workers) deferred to the deployment phase.
- **Consequences:** every log line of a request/job shares one id, greppable end to end; dashboards get RED metrics per route + core-operation histograms; readiness is honest per backend; the no-op fallback means instrumented code never branches on availability.

Add to `docs/adr/README.md` index: `- [ADR-0019](0019-observability.md) — Observability: correlation ids, Prometheus metrics + /ready probes behind an extra`.

- [ ] **Step 2: Write the phase doc + update CHANGELOG, roadmap, PROJECT_STATE**

`docs/design/phase-10.md`, same structure as `phase-09.md` (Objective / Delivered / Gate / Deferred / Self-review). Deferred = worker metric exposition (deployment phase); Grafana dashboards/alert rules (deployment phase); OpenTelemetry traces (post-v1); backlog carried (sweep dedupe + rate limiting, restore endpoint). Record the actual gate numbers from Step 3.

`CHANGELOG.md` — new block above Phase 9:

```markdown
### Added — Phase 10: Observability & monitoring
- Correlation ids: `memcore.observability.context` contextvar, stamped on
  every log record (plain + JSON) by a logging filter; ASGI middleware binds
  one per request (honors/echoes `X-Request-ID`); Celery task shells bind one
  per job — ADR-0019.
- Structured access log (`memcore.api.access`): method, path, route, status,
  duration_ms per request.
- Prometheus metrics behind the new `observability` extra
  (`pip install 'memcore[observability]'`): `memcore_http_requests_total`,
  `memcore_http_request_duration_seconds` (route-template labels),
  `memcore_operation_duration_seconds` (recall / consolidation /
  decay_sweep); `GET /metrics` (501 + install hint without the extra).
- `GET /ready`: per-component readiness via duck-typed adapter `ping()`
  (SQL `SELECT 1`; Qdrant/Neo4j/Redis driver pings, integration-tested);
  503 + `"degraded"` when any probe fails.
```

`docs/design/roadmap.md`: Phase 10 → `✅ Complete`, Phase 11 → `⏳ Next`.

`PROJECT_STATE.md`: current position → Phase 10 complete / Phase 11 (Deployment: Docker, K8s, CI/CD) not started, awaiting approval; record the Phase 10 gate numbers; next tasks → Phase 11 outline (Dockerfile + compose stack for the full backend set, K8s manifests with the new probes wired to liveness/readiness, CI pipeline running the gate + integration suite, worker metric exposition, per-tenant sweep dedupe + rate limiting, restore endpoint); open decision → approve Phase 11 start.

- [ ] **Step 3: Run the phase gate and record numbers**

Run: `./.venv/Scripts/python.exe -m pytest` (record pass count + coverage %), `./.venv/Scripts/python.exe -m ruff check .`, `./.venv/Scripts/python.exe -m mypy`
Expected: all clean, coverage ≥ 85%. Copy the real numbers into `phase-10.md` and `PROJECT_STATE.md`.

- [ ] **Step 4: Phase commit**

```bash
git add docs/adr/0019-observability.md docs/adr/README.md docs/design/phase-10.md docs/design/roadmap.md CHANGELOG.md PROJECT_STATE.md
git commit -m "docs: Phase 10 gate — observability & monitoring (ADR-0019)"
```

Then STOP: per the phase gate, WAIT for user approval before any Phase 11 work.
