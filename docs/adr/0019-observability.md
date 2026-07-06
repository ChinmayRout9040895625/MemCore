# ADR-0019: Observability — correlation ids, Prometheus metrics, /ready probes

**Status:** Accepted (2026-07-06)

## Context
No correlation existed between log lines belonging to one HTTP request or one
background job — debugging a multi-step flow meant grepping timestamps and
guessing. There were no metrics: no request counts, no latency histograms for
the API or for core operations (recall, consolidation, decay sweep). `/health`
was liveness-only (`{"status": "ok"}`) and said nothing about whether the
storage backends (Qdrant, Neo4j, Redis, Postgres) were actually reachable.

## Decision

1. **Correlation ids via a contextvar** (`memcore.observability.context`):
   `bind_request_id`/`get_request_id`/`reset_request_id` wrap a single
   `ContextVar[str | None]`. `memcore.logging`'s `_ContextFilter` stamps the
   current value onto every log record as `request_id` (`"-"` when unbound;
   an explicit `extra={"request_id": ...}` from the caller still wins). The
   plain-text formatter gained `[%(request_id)s]`; the JSON formatter picks it
   up automatically as a structured extra. One id is bound per HTTP request by
   the pure-ASGI `ObservabilityMiddleware` — honoring an incoming
   `X-Request-ID` header if present, otherwise minting a fresh uuid4 hex, and
   echoing it back on the response — and one per job by each Celery task
   shell (`consolidate_session`, `decay_tenant`).

2. **Prometheus behind a new optional `observability` extra**
   (`observability = ["prometheus-client>=0.20"]` in `pyproject.toml`).
   `memcore.observability.metrics` lazy-imports `prometheus_client` once into
   a module-level cache built on a private `CollectorRegistry` (not the
   global default, so multiple app instances in one process don't collide);
   `observe_http`/`observe_operation` are silent no-ops when the import fails,
   so instrumented call sites never branch on availability. `render()` is the
   one function that raises — a `ConfigurationError` carrying the install
   hint — which the `/metrics` route maps to a 501 problem+json response.
   Metric names: `memcore_http_requests_total` and
   `memcore_http_request_duration_seconds` (labels `method`, `route`,
   `status` — route is the matched Starlette path *template*, not the raw
   path, to bound label cardinality; unmatched requests have no matched route
   and are labeled with the constant `unmatched` — the raw path appears only
   in the access log), and
   `memcore_operation_duration_seconds{operation}` for
   `recall`/`consolidation`/`decay_sweep`.

3. **Operation latency is recorded at call boundaries, not inside
   `services/*`**: the `/v1/recall` route, `build_state`'s
   `ImmediateWorkflowEngine` handlers (`_consolidate`/`_decay`, wrapped in
   try/finally so a raised exception still records the latency), and the two
   Celery task shells. No telemetry port was introduced — YAGNI; there is
   exactly one metrics backend and no service-layer code needs to know
   metrics exist. Revisit only if a second telemetry backend appears.

4. **Readiness via a duck-typed optional `async ping()`** on adapters —
   the same pattern `create_app` already uses for optional `init()`. `/ready`
   iterates `app.state.memcore_probes` (`store`, `vectors`, `graph`,
   `working`), calls `ping()` where present, and reports per-component
   `"ok"` / `"error: {exc}"`; any failure makes the whole response 503 with
   `{"status": "degraded", ...}`. Adapters without a `ping` (the in-memory
   ones) are treated as always-ok. Implemented: SQL store (`SELECT 1`),
   Qdrant (`get_collections`), Neo4j (`verify_connectivity`), Redis (`PING`).

5. **No new `Settings` block.** Verbosity is already gated by `log_level`;
   metrics availability is gated by whether the `observability` extra is
   installed. Nothing here needed its own configuration surface.

6. **Deferred to the deployment phase:** Celery workers have no HTTP server
   to expose `/metrics` on, so worker-process metric exposition (e.g. a
   pushgateway or a sidecar) is out of scope here.

## Consequences
- Every log line belonging to one request or one job carries the same
  `request_id`, so a multi-service or multi-log-line flow is greppable end to
  end without extra plumbing at each call site.
- Dashboards can be built from RED-style metrics per route
  (`memcore_http_*`) plus latency histograms for the three core operations,
  once the `observability` extra is installed in the target environment.
- `/ready` is now an honest per-backend signal instead of a static "ok",
  making it safe to wire into a Kubernetes readiness probe (Phase 11).
- The no-op fallback means `observe_http`/`observe_operation` call sites are
  unconditionally present in the source — they cost nothing and never fail
  when the extra is absent, at the price of a metrics call that silently does
  nothing if someone forgets to install the extra in production.
- Celery-shell instrumentation (request-id binding + operation-latency
  recording) is implemented but untested against a real broker in this phase
  — deferred pending an integration harness with Celery/Redis wired up.
