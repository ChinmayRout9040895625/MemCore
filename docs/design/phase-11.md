# Phase 11 — Deployment (Docker, K8s, CI/CD)

## Objective
Take MemCore from "runs out of a dev checkout" to "deployable to Docker or
Kubernetes," wire the Phase 10 `/health`/`/ready` endpoints into real
orchestrator probes, and get CI to actually exercise the storage adapters
against live backends instead of only in-memory/SQLite fakes. Design in
ADR-0020.

## Delivered

**Restore endpoint** (`POST /v1/memories/{id}/restore`) —
`MemoryService.restore` transitions a record `SOFT_DELETED → ACTIVE`,
re-indexes it, and records `AuditAction.RESTORE`; 404 is tenant-scoped (a
record belonging to another tenant is indistinguishable from a nonexistent
one).

**Per-tenant decay-sweep dedupe** — an `asyncio.Lock` registry keyed by
tenant id; `sweep` delegates to an internal `_sweep` guarded by the
per-tenant lock, so two concurrent sweep triggers for the same tenant within
one process collapse into one. Cross-process dedupe (multiple worker
processes/replicas sweeping the same tenant concurrently) is out of scope
here — deferred, needs a distributed lock.

**Worker Prometheus exposition** — `memcore.observability.metrics
.start_metrics_server(port)` starts a Prometheus HTTP server against the
module's private `CollectorRegistry` (raises `ConfigurationError` with an
install hint if the `observability` extra is absent); a `worker_process_init`
handler in `memcore.workers.celery_app` calls it when `MEMCORE_METRICS_PORT`
is set, and is a no-op otherwise. Failure to start the metrics server never
crashes the worker — this closes the gap ADR-0019 explicitly deferred
(Celery workers have no ASGI app to hang `/metrics` off).

**`Dockerfile`** — multi-stage: a `python:3.12-slim` builder installs the
full default-stack extras (`api, sql, postgres, vector, graph, working,
scheduler, llm, embeddings, observability`) into a venv; the runtime stage
copies just the venv and `src/`, runs as non-root `uid 10001`, and defaults
to `uvicorn --factory memcore.api:create_app`. The worker overrides `command`
to run `celery -A memcore.workers.celery_app worker` on the same image — one
artifact, two roles. `.dockerignore` keeps the build context to source +
metadata. `.env.example` is the compose-DNS template (`postgres`, `qdrant`,
`neo4j`, `redis` service hostnames) to copy to `.env` for local runs. The
image was built and run locally; the build took **~19 minutes**, driven
almost entirely by `torch` (pulled in transitively by the `embeddings`
extra) — this sizes the CI `docker` job's timeout below.

**`docker-compose.yml`** — full local stack: `qdrant`, `neo4j`, `redis`,
`postgres`, `api`, `worker`. Every backend has a `healthcheck`; `api` and
`worker` `depends_on` their backends with `condition: service_healthy`, so
`docker compose up` brings the stack up in working order instead of racing
the API against a still-starting Postgres.

**`deploy/k8s/`** — `namespace.yaml`, `configmap.yaml`,
`secret.example.yaml` (template only — a real `secret.yaml` is never
committed), `api-deployment.yaml` (`livenessProbe→/health`,
`readinessProbe→/ready`, non-root), `api-service.yaml`,
`worker-deployment.yaml` (exposes the metrics port for Prometheus scraping),
`ingress.yaml` (rate-limit annotations at the edge; denies public access to
`/ready` and `/metrics`). The README is explicit that Postgres/Qdrant/
Neo4j/Redis are bring-your-own prerequisites this repo does not provision —
only the DNS names the ConfigMap expects to reach.

**CI** (`.github/workflows/ci.yml`) — the existing `test` matrix job is
unchanged. Two new jobs:
- `integration`: Qdrant/Neo4j/Redis service containers, waits for all three
  to accept connections, then runs `pytest -m integration` with
  `MEMCORE_GRAPH__PASSWORD=memcore-dev-password` so the adapter contract
  tests run against real backends instead of skipping. (The `test` job's
  plain `pytest` already *collects* the same integration-marked tests — see
  `tests/integration/test_backends.py` — but each one self-skips on
  connection failure, so `test` alone never proves the adapters work; `-ra`
  in `addopts` reports the skip reason. `integration` is what actually
  proves it.)
- `docker`: builds the image (`docker build -t memcore:ci .`) and validates
  the compose file. `timeout-minutes: 30`, sized against the measured ~19
  minute local build with headroom for a colder CI cache.

## Gate (2026-07-10)
- pytest: **219 passed, 3 integration-skipped (Qdrant/Redis/Neo4j
  unreachable in this environment — expected, no live backends here)** ·
  coverage **93.81%**
- ruff: clean
- mypy (strict, 106 files): clean

## Self-review
- Verified against the five implementation commits on `master`
  (`1a2f1dd`, `b096ec4`, `fb39648`, `47b6163`, `4ba1bba`/`9a8fe75`) by reading
  the actual diffs/files, not from memory of the commit messages:
  `MemoryService.restore` (`src/memcore/services/memories.py`), the
  `asyncio.Lock` registry in the decay service, `start_metrics_server` +
  `worker_process_init` in `memcore/workers/celery_app.py`, the multi-stage
  `Dockerfile`, `docker-compose.yml`'s healthcheck/`depends_on` wiring, and
  every file under `deploy/k8s/`.
- `tests/integration/test_backends.py` env var defaults confirmed by reading
  the file: `MEMCORE_VECTOR__URL` (default `http://localhost:6333`),
  `MEMCORE_REDIS__URL` (default `redis://localhost:6379/0`),
  `MEMCORE_GRAPH__URL`/`MEMCORE_GRAPH__USER`/`MEMCORE_GRAPH__PASSWORD`
  (defaults `bolt://localhost:7687` / `neo4j` / `memcore-dev-password`) —
  the CI `integration` job's service container ports (`6333`, `7687`,
  `6379` all mapped to the matching localhost port) and the one explicit env
  override (`MEMCORE_GRAPH__PASSWORD`, matching the `neo4j:5.24-community`
  service's `NEO4J_AUTH`) line up with what the test file actually reads.
- **One correction to the brief's CI job spec**, found by running it: the
  brief's `docker compose --env-file .env.example config` fails, because
  `--env-file` only supplies `${VAR}` interpolation values for the compose
  file itself — it does not satisfy `api`/`worker`'s `env_file: .env`
  directive, which is a literal filename, not a variable. Confirmed locally
  (`docker compose --env-file .env.example config` →
  `env file .env not found`; `docker compose config` after
  `cp .env.example .env` → succeeds and renders the expected service
  config). The `docker` job's "Validate compose" step here is `cp
  .env.example .env` followed by plain `docker compose config`, not the
  brief's literal command — `docker-compose.yml` itself is untouched.
- Local `docker --version` / `docker compose version` confirmed Docker is
  available in this environment (29.1.3 / v2.40.3), so the compose-config
  fix above was verified by actually running it, not just reasoned about.
  The full image build (~19 min) was not re-run in this task — Task 4's
  brief already recorded it as locally built and verified; re-verifying
  compose config end to end here didn't require a fresh multi-stage build.
- Gate numbers above are this task's own run, not carried over from a prior
  session.

## Deferred
- **Distributed (cross-process) sweep dedupe** — the current lock is
  per-process; multiple worker replicas can still race a sweep for the same
  tenant. Needs a Redis-backed distributed lock.
- **In-app/distributed rate limiting** — today's limiting is edge-only
  (nginx-ingress annotations); no in-process or Redis-backed limiter exists
  for deployment targets without an ingress controller in front.
- **Per-role slim images** — the one image serves both roles by carrying
  every extra (`embeddings`'s `torch` alone makes the unified image
  ~8.7GB). A slimmer API-only / worker-only image is a future split.
- **Helm chart** — `deploy/k8s/` is plain manifests; templating/values for
  multi-environment installs is not built.
- Grafana dashboards and alert rules on top of Phase 10's metrics — still
  open, unchanged from the Phase 10 deferral.
