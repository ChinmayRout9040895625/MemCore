# MemCore — Live Project State

> Updated at every phase gate (mandatory, same tier as tests). If the
> session-start hook says this file is stale, update it before new work.

## Current position
- **Phase 10 (Observability & monitoring): COMPLETE.**
- **Phase 11 (Deployment: Docker, K8s, CI/CD): NOT STARTED — awaiting user approval.**
- Phases 1–10 complete and committed (see `git log --oneline`).

## Last gate (Phase 10, 2026-07-06)
- pytest: **208 passed, 3 integration-skipped** · coverage **94.01%**
- ruff: clean · mypy (strict, 106 files): clean
- Correlation ids (`memcore.observability.context` contextvar; stamped on
  every log record by a logging filter; bound per HTTP request by
  `ObservabilityMiddleware` honoring/echoing `X-Request-ID`, per job by
  Celery task shells). Prometheus metrics behind the new `observability`
  extra (`pip install 'memcore[observability]'`): `memcore_http_requests_total`
  / `memcore_http_request_duration_seconds` (route-template labels),
  `memcore_operation_duration_seconds` (recall/consolidation/decay_sweep);
  `GET /metrics` (501 + install hint without the extra). `GET /ready`:
  per-component readiness via duck-typed adapter `ping()` (SQL, Qdrant,
  Neo4j, Redis); 503 + `"degraded"` on any probe failure.
  ADR-0019. Full report in `docs/design/phase-10.md`.

## Workspace (2026-07-02)
- Setup complete: context layer + SessionStart hook + sonnet agents
  (`implementer`, `debugger`). Dispatch test passed (py.typed, gate green).

## Next tasks (Phase 11, once approved)
1. Dockerfile + docker-compose stack covering the full backend set (API,
   worker, Postgres, Qdrant, Neo4j, Redis).
2. Kubernetes manifests wiring the new `/ready` and `/health` endpoints to
   readiness/liveness probes.
3. CI pipeline running the full phase gate (pytest+coverage, ruff, mypy)
   plus the integration suite against live backend containers.
4. Worker metric exposition (pushgateway or sidecar — no HTTP server in
   Celery workers today).
5. Backlog carried over: per-tenant sweep dedupe + rate limiting; restore
   endpoint for soft-deleted records.

## Open decisions for the user
- Approve Phase 11 start.
