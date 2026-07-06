# Phase 10 — Observability & monitoring

## Objective
Give MemCore correlation ids that tie together every log line of one request
or job, Prometheus metrics for HTTP and core-operation latency, and an honest
per-backend readiness probe — without adding a mandatory dependency or a
telemetry port. Design in ADR-0019.

## Delivered

**Correlation ids** (`memcore/observability/context.py`) — a single
`ContextVar[str | None]` with `bind_request_id`/`get_request_id`/
`reset_request_id`/`new_request_id` (uuid4 hex). `memcore/logging.py`'s
`_ContextFilter` stamps `request_id` onto every log record (`"-"` when
unbound; an explicit `extra={"request_id": ...}` wins); the plain formatter
gained `[%(request_id)s]`, the JSON formatter picks it up as a structured
field automatically. Bound per HTTP request by `ObservabilityMiddleware`
(honors an incoming `X-Request-ID`, echoes it on the response) and per job by
both Celery task shells (`consolidate_session`, `decay_tenant`).

**Metrics** (`memcore/observability/metrics.py`, new `observability` extra —
`observability = ["prometheus-client>=0.20"]` in `pyproject.toml`) — lazy
import into a module-level cache on a private `CollectorRegistry`;
`observe_http`/`observe_operation` are silent no-ops without the extra;
`render()` raises `ConfigurationError` with the install hint when absent.
Metrics: `memcore_http_requests_total` /
`memcore_http_request_duration_seconds` (labels `method`, `route`, `status` —
route is the matched path template, raw-path fallback for unmatched 404s) and
`memcore_operation_duration_seconds{operation}` for
`recall`/`consolidation`/`decay_sweep`.

**Middleware + routes** (`memcore/api/middleware.py`, `memcore/api/app.py`,
`memcore/api/routes.py`) — pure-ASGI `ObservabilityMiddleware`: binds/echoes
the request id, emits one structured access-log line per request
(`memcore.api.access`: `method`, `path`, `route`, `status`, `duration_ms`),
and records HTTP metrics. `GET /metrics`: 200 exposition text when the extra
is installed, 501 problem+json with the install hint otherwise. `GET /ready`:
probes `app.state.memcore_probes` (`store`, `vectors`, `graph`, `working`) via
a duck-typed optional `async ping()`; per-component `"ok"`/`"error: ..."`,
503 + `{"status": "degraded"}` if any probe fails.

**Adapter pings** — SQL store `SELECT 1` (unit-tested); Qdrant
`get_collections()`, Neo4j `verify_connectivity()`, Redis `PING`
(integration-tested, excluded from the coverage gate since they require live
backends).

**Operation latency at call boundaries** — `/v1/recall` route,
`build_state`'s `ImmediateWorkflowEngine` handlers (`_consolidate`/`_decay`,
try/finally so exceptions still record latency; covered by a direct
`build_state` test), and both Celery task shells (`consolidate_session`,
`decay_tenant`; also bind/reset a per-job request id). `services/*` itself
stays untouched — no telemetry port introduced (YAGNI).

## Gate (2026-07-06, incl. final-review polish commit)
- pytest: **210 passed, 3 integration-skipped** · coverage **94.03%**
- ruff: clean
- mypy (strict, 106 files): clean

## Deferred
- Worker metric exposition — Celery workers have no HTTP server to serve
  `/metrics` from; needs a pushgateway or sidecar (deployment phase).
- Integration tests for Celery-shell instrumentation (request-id binding +
  operation-latency recording) against a real broker — deferred pending a
  Celery/Redis integration harness (deployment phase).
- Grafana dashboards and alert rules built on the new metrics (deployment
  phase).
- OpenTelemetry traces (post-v1) — the current contextvar + Prometheus setup
  covers correlation and RED metrics without pulling in a tracing SDK.
- Backlog carried over (deployment/security phase): per-tenant sweep dedupe +
  rate limiting; a restore endpoint for soft-deleted records.

## Self-review
Verified against the implementation commits (`6128f68`, `c8e8546`,
`3e0e95a`, `668c098`, `0f5e8af`):
- `memcore/observability/context.py` matches the contextvar/bind/get/reset
  API described above verbatim; `memcore/logging.py`'s `_ContextFilter` and
  the `[%(request_id)s]` plain-format token confirmed by reading the file.
- `memcore/observability/metrics.py`: cache structure, private
  `CollectorRegistry`, exact metric names/labels, no-op behavior, and
  `ConfigurationError` + install-hint text on `render()` all match source.
- `memcore/api/middleware.py`: `ObservabilityMiddleware` binds from
  `x-request-id` (lowercased header lookup) or mints a new id, echoes it on
  `http.response.start`, records the access log and HTTP metric in a
  `finally` block, and resets the token — confirmed by reading the file.
- `memcore/api/app.py`: `app.state.memcore_probes` wired to
  `store`/`vectors`/`graph`/`working`; `ImmediateWorkflowEngine` handlers wrap
  `observe_operation` calls in try/finally — confirmed.
- `memcore/api/routes.py`: `/metrics` and `/ready` handlers match the
  described response shapes and status codes — confirmed.
- Adapter `ping()` methods found at `adapters/sql/memory_store.py:141`,
  `adapters/redis/working_memory.py:91`, `adapters/qdrant/vector_store.py:123`,
  `adapters/neo4j/graph_store.py:184`.
- `memcore/workers/celery_app.py`: both task shells bind/reset a request id
  and call `observe_operation` in a `finally` block — confirmed; worker
  coverage is intentionally low (50%, lines 49-68/93-112/117-126 excluded —
  those paths require a live broker).
- `observability = ["prometheus-client>=0.20"]` confirmed in
  `pyproject.toml`.
- Gate numbers above are the real output of this task's own run, not carried
  over from a prior session. No issues found requiring a follow-up commit.
