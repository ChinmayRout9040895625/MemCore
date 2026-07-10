# MemCore — Live Project State

> Updated at every phase gate (mandatory, same tier as tests). If the
> session-start hook says this file is stale, update it before new work.

## Current position
- **Phase 11 (Deployment: Docker, K8s, CI/CD): COMPLETE.**
- **Phase 12 (Documentation & examples): NOT STARTED — awaiting user approval.**
- Phases 1–11 complete and committed (see `git log --oneline`).

## Last gate (Phase 11, 2026-07-10, incl. final-review fix commit)
- pytest: **221 passed, 3 integration-skipped** (Qdrant/Redis/Neo4j
  unreachable — no live backends in this environment, expected) ·
  coverage **93.81%**
- ruff: clean · mypy (strict, 106 files): clean
- Restore endpoint (`POST /v1/memories/{id}/restore`: SOFT_DELETED→ACTIVE,
  re-index, `AuditAction.RESTORE`, tenant-scoped 404). Per-tenant
  in-process decay-sweep dedupe (`asyncio.Lock` registry). Worker Prometheus
  exposition (`start_metrics_server` on `worker_process_init`, gated on
  `MEMCORE_METRICS_PORT`). Multi-stage `Dockerfile` (non-root uid 10001,
  one image serves API via uvicorn or worker via command override) +
  `.dockerignore` + `.env.example`; full `docker-compose.yml` stack
  (API+worker+Postgres+Qdrant+Neo4j+Redis, healthchecks,
  `depends_on: service_healthy`). Kubernetes manifests under `deploy/k8s/`
  (`livenessProbe→/health`, `readinessProbe→/ready`, ConfigMap, Secret
  template, Ingress with edge rate limiting + internal-only `/ready`+
  `/metrics`). CI gained `integration` (Qdrant/Neo4j/Redis service
  containers, `pytest -m integration`) and `docker` (build + compose
  validate, `timeout-minutes: 30`) jobs.
  ADR-0020. Full report in `docs/design/phase-11.md`.

## Workspace (2026-07-02)
- Setup complete: context layer + SessionStart hook + sonnet agents
  (`implementer`, `debugger`). Dispatch test passed (py.typed, gate green).

## Next tasks (Phase 12, once approved)
1. API reference generated from the OpenAPI schema.
2. Architecture and operations guides (deployment topology, backend
   provisioning, observability/runbook material building on ADR-0019/0020).
3. Runnable end-to-end examples using the Python SDK (`memcore.sdk`).
4. Deployment walkthrough (Docker Compose local, then Kubernetes) using the
   Phase 11 artifacts as the worked example.
5. Backlog carried over from Phase 11: distributed (cross-process) decay-sweep
   dedupe (Redis lock) + in-app/distributed rate limiting (edge-only today);
   per-role slim images; Helm chart.

## Open decisions for the user
- Approve Phase 12 start.
