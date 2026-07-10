# MemCore — Live Project State

> Updated at every phase gate (mandatory, same tier as tests). If the
> session-start hook says this file is stale, update it before new work.

## Current position
- **ALL 12 PHASES COMPLETE — v0.1 feature-complete.**
- Phase 12 (Documentation & examples): COMPLETE. Phases 1–12 complete and
  committed (see `git log --oneline`).

## Last gate (Phase 12, 2026-07-10)
- pytest: **228 passed, 3 integration-skipped** (Qdrant/Redis/Neo4j
  unreachable — no live backends in this environment, expected) ·
  coverage **93.93%**
- ruff: clean · mypy (strict, 108 files): clean
- Generated `docs/api-reference.md` (from the live OpenAPI schema, CI
  drift-tested) — ADR-0021. Four CI-executed examples under `examples/`
  (async/sync quickstarts, memory lifecycle, sessions + consolidation).
  `docs/guides/operations.md` + `docs/guides/deployment.md`; refreshed
  `docs/design/architecture.md`. README overhauled: quickstart, docs index,
  install-extras table, v0.1 status. Full report in `docs/design/phase-12.md`.

## Workspace (2026-07-02)
- Setup complete: context layer + SessionStart hook + sonnet agents
  (`implementer`, `debugger`). Dispatch test passed (py.typed, gate green).

## Post-v1 backlog
1. SDK `restore_memory` method (REST endpoint shipped Phase 11, no typed
   SDK wrapper yet).
2. Distributed (cross-process) decay-sweep dedupe (Redis lock) + in-app/
   distributed rate limiting (edge-only today).
3. Per-role slim Docker images (API without `embeddings`/`llm`, worker
   without `api`).
4. Helm chart for `deploy/k8s/` (currently plain manifests).
5. Postgres-in-CI contract test (SQL store currently only unit-tested
   against SQLite; `integration` CI job covers Qdrant/Neo4j/Redis only).
6. Prometheus multiprocess mode (to support worker `--concurrency > 1`
   without racing the metrics port).
7. Grafana dashboards and alert rules on top of Phase 10's metrics.
8. Real-corpus evaluation datasets (Phase 8's harness runs on synthetic
   data only).

## Open decisions for the user
- Define the post-v1 roadmap (none pending).
