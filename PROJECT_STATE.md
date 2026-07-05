# MemCore — Live Project State

> Updated at every phase gate (mandatory, same tier as tests). If the
> session-start hook says this file is stale, update it before new work.

## Current position
- **Phase 9 (Python SDK): COMPLETE.**
- **Phase 10 (Observability & monitoring): NOT STARTED — awaiting user approval.**
- Phases 1–9 complete and committed (see `git log --oneline`).

## Last gate (Phase 9, 2026-07-05, incl. final-review fix commit)
- pytest: **189 passed, 3 integration-skipped** · coverage **93.96%**
- ruff: clean · mypy (strict, 99 files): clean
- `memcore.sdk`: `AsyncMemCoreClient` (full v1 surface) + `MemCoreClient`
  (sync mirror, signature-parity guarded); GET-only retries with
  deterministic backoff; typed errors from problem+json; `wait_for_job`.
  New `sdk` extra (`pip install 'memcore[sdk]'`, pydantic, pydantic-settings
  + httpx only).
  ADR-0018; quickstart in `docs/sdk-quickstart.md`. Full report in
  `docs/design/phase-09.md`.

## Workspace (2026-07-02)
- Setup complete: context layer + SessionStart hook + sonnet agents
  (`implementer`, `debugger`). Dispatch test passed (py.typed, gate green).

## Next tasks (Phase 10, once approved)
1. Structured request/job logging with correlation ids.
2. Prometheus metrics endpoint.
3. Health/readiness probes including backend checks (Qdrant, Neo4j, Redis,
   Postgres).
4. Latency histograms for recall/consolidation/decay.
5. Backlog carried over (deployment/security phase): per-tenant sweep
   dedupe + rate limiting; restore endpoint for soft-deleted records.

## Open decisions for the user
- Approve Phase 10 start.
