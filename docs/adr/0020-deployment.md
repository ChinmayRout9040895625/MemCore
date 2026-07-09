# ADR-0020: Deployment — one image/two roles, compose stack, K8s probes, CI integration + image build

**Status:** Accepted (2026-07-10)

## Context
MemCore ran only from a dev checkout — `pip install -e .` plus manually
started backend processes. There was no container image, no orchestration
manifests, and CI exercised nothing beyond unit tests against in-memory/SQLite
fakes: no adapter ever ran against a real Qdrant, Neo4j, or Redis in CI, and
there was no path from a checkout to a deployable artifact.

## Decision

1. **One multi-stage image, two roles.** A single `Dockerfile`
   (`python:3.12-slim`, non-root `uid 10001`, dependencies installed into a
   venv in a builder stage and copied into a slim runtime stage) serves the
   API by default (`uvicorn --factory memcore.api:create_app`) and, with a
   `command` override, the Celery worker. One artifact, two roles — no
   separate worker image to build, tag, and keep in sync.

2. **`docker-compose.yml` is the full local stack** — API + worker +
   Postgres + Qdrant + Neo4j + Redis — with a `healthcheck` on every backend
   and `depends_on: {condition: service_healthy}` on the API and worker, so
   `docker compose up` brings up a working stack in dependency order instead
   of a race.

3. **Kubernetes manifests under `deploy/k8s/`** wire `livenessProbe` to
   `/health` and `readinessProbe` to `/ready` — the endpoints Phase 10 built
   for exactly this purpose. Configuration is a ConfigMap; credentials are a
   `secret.example.yaml` template only — the real `secret.yaml` is never
   committed. Backing services (Postgres/Qdrant/Neo4j/Redis) are documented
   as bring-your-own prerequisites, not manifests this repo owns: MemCore
   doesn't pick a Postgres operator or a Neo4j Helm chart for the cluster
   operator, only the DNS names it expects to reach.

4. **Rate limiting is an edge concern**, not an in-app limiter — nginx-ingress
   `limit-rps` annotations on `deploy/k8s/ingress.yaml`. A correct
   *distributed* in-app limiter needs a shared store (Redis) and coordinated
   key design; that's out of proportion to the need right now and is
   revisitable if a future deployment target has no rate-limiting edge.
   The same Ingress denies public access to `/ready` and `/metrics` —
   operational endpoints, not user-facing API surface — which are scraped
   cluster-internally instead.

5. **Worker metric exposition** via `start_metrics_server(port)` called from
   a `worker_process_init` handler, gated on `MEMCORE_METRICS_PORT` being
   set. Celery workers have no ASGI app to hang `/metrics` off of the way the
   API does (ADR-0019 deferred this explicitly); this closes that gap without
   forcing every worker deployment to run a metrics server it doesn't want.
   Unset the env var and the worker behaves exactly as before — never crashes
   the worker if metrics setup fails.

6. **CI gains two jobs** alongside the existing `test` matrix: an
   `integration` job with Qdrant/Neo4j/Redis service containers running
   `pytest -m integration` against real backends (the existing `test` job's
   plain `pytest` invocation already exercises integration-marked tests too,
   but they self-skip on connection failure — see
   `tests/integration/test_backends.py` — so `test` alone never actually
   proves the adapters work against live backends); and a `docker` job that
   builds the image and validates the compose file. Local build time was
   ~19 minutes including the `torch` dependency pulled in by the `embeddings`
   extra, so the `docker` job gets `timeout-minutes: 30`.

7. **Operational backlog closed:** `POST /v1/memories/{id}/restore`
   (SOFT_DELETED → ACTIVE, re-index, `AuditAction.RESTORE`, tenant-scoped
   404) and per-tenant in-process decay-sweep dedupe (an `asyncio.Lock`
   registry keyed by tenant, guarding concurrent sweeps within one process).
   Cross-process dedupe — needed once more than one worker process runs
   sweeps concurrently — is deferred; it needs a distributed lock (Redis).

## Consequences
- MemCore is deployable to any Docker or Kubernetes target from this repo
  alone, without hand-assembling a Dockerfile or manifests first.
- `/health` and `/ready` (Phase 10) now do real work for an orchestrator:
  liveness restarts a wedged pod, readiness pulls a pod with a down backend
  out of the Service rotation instead of routing traffic to it.
- CI now catches adapter regressions against real backend versions, not just
  the in-memory/SQLite fakes — a class of bug the unit suite structurally
  cannot see.
- The image carries the full default-stack extras (`api, sql, postgres,
  vector, graph, working, scheduler, llm, embeddings, observability`), which
  makes the image large (`embeddings` pulls in `torch`, ~8.7GB total) but
  keeps deployment simple: one image works regardless of which role or which
  optional backend a given deployment uses. A slimmer per-role image (API
  without `embeddings`/`llm`, worker without `api`) is a future optimization,
  not a blocker.
- Rate limiting and cross-process sweep dedupe are both documented,
  intentional deferrals, not oversights — each has a concrete follow-up
  (Redis-backed) if a real deployment needs it before that's built.
