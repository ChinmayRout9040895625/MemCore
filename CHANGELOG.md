# Changelog

All notable changes to MemCore are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/); versions follow SemVer.

## [Unreleased]

### Added (post-v1)
- SDK: `restore_memory(memory_id)` on both `AsyncMemCoreClient` and
  `MemCoreClient`, wrapping the `POST /v1/memories/{id}/restore` endpoint
  (REST endpoint shipped Phase 11, no typed SDK wrapper until now). Closes
  the first post-v1 backlog item.

### Fixed (post-v1)
- Celery worker: run every task on one persistent event loop
  (`memcore.workers.celery_app._get_loop`) instead of a fresh loop per
  `asyncio.run` call. The cached per-process service graph (incl. the asyncpg
  connection pool) was bound to the first task's loop, so the *second*
  consolidation/decay job in a worker's lifetime crashed with
  "got Future attached to a different loop" and silently produced no
  memories. Regression-guarded by `tests/unit/test_workers.py`.

### Added — Phase 12: Documentation & examples
- `docs/api-reference.md` generated from the OpenAPI schema by
  `scripts/generate_api_reference.py`; a CI drift test keeps it current —
  ADR-0021.
- `examples/`: four runnable SDK scripts (async/sync quickstarts, memory
  lifecycle, sessions + consolidation), each executed in CI against the
  in-process app.
- `docs/guides/operations.md` (config reference, backing services,
  observability runbook, memory ops, troubleshooting, known limits) and
  `docs/guides/deployment.md` (compose → Kubernetes walkthrough);
  `docs/design/architecture.md` refreshed through Phase 11.
- README overhauled: v0.1 feature-complete, quickstart, docs index, extras
  table. All 12 roadmap phases complete.

### Added — Phase 11: Deployment (Docker, K8s, CI/CD)
- Multi-stage `Dockerfile` (non-root) serving the API via uvicorn or the
  Celery worker by command override; `.dockerignore`, `.env.example` — ADR-0020.
- Full `docker-compose.yml` stack: API + worker + Postgres + Qdrant + Neo4j
  + Redis with healthchecks and `depends_on: service_healthy`.
- Kubernetes manifests (`deploy/k8s/`): API/worker Deployments, Service,
  ConfigMap, Secret template, Ingress; `livenessProbe→/health`,
  `readinessProbe→/ready`; edge rate limiting + internal-only ops endpoints.
- Worker Prometheus exposition via `start_metrics_server` on worker init
  (`MEMCORE_METRICS_PORT`).
- CI: integration job (Qdrant/Neo4j/Redis service containers) + image build.
- Operational backlog closed: `POST /v1/memories/{id}/restore` for
  soft-deleted records; per-tenant in-process decay-sweep dedupe lock.

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

### Added — Phase 9: Python SDK
- `memcore.sdk`: typed async (`AsyncMemCoreClient`) + sync (`MemCoreClient`)
  clients covering the full v1 API (sessions, memories, recall, consolidate,
  jobs, decay), validating responses into domain models — ADR-0018.
- Typed errors from problem+json (`AuthError`/`NotFoundError`/`ConflictError`
  /`ValidationAPIError`/`ServerError`), `TransportError`, `JobTimeout`.
- GET-only automatic retries ({429,502,503,504} + transport failures),
  deterministic exponential backoff, injectable sleep; `wait_for_job` polling.
- New install extra: `pip install 'memcore[sdk]'` (pydantic, pydantic-settings
  + httpx only); sync/async surface parity enforced by test;
  `docs/sdk-quickstart.md`.

### Added — Phase 8: Evaluation framework & baselines
- `memcore.evaluation`: deterministic offline harness — binary-relevance
  metrics (recall@k, MRR, nDCG@k), token-overlap dataset `synthetic-v1`,
  per-config stack isolation, standard configs (naive-vector baseline,
  hybrid, no-importance, no-recency) — ADR-0017.
- Scenario regression guards: reinforcement ablation (reinforced twin wins
  under hybrid, ties under no-importance) and longitudinal decay curve
  (sweep collapses recall past the prune horizon).
- `python -m memcore.evaluation` prints the reproducible baseline report
  (recorded in docs/design/phase-08.md).
- Phase 7 backlog closed: decay sweep scans oldest-first (convergence for
  tenants above `scan_limit`; ADR-0016 amended) and `set_decay` clamps
  scores to [0, 1]; `list_records` gained `oldest_first`.

### Added — Phase 7: Memory decay & pruning
- `MemoryStore.set_decay` (in-place decay snapshots) and tenant-wide
  `list_records(agent_id=None)`; contract kit covers both — ADR-0016.
- `services/decay.py`: `DecayService.sweep` scores ACTIVE records with the
  Phase 6 functions, snapshots `decay_score`, and soft-deletes records that
  fail every rail (score < threshold, not pinned, older than `min_age_days`);
  per-record DELETE audits + one PRUNE summary event per sweep.
- `RetentionSettings` (`prune_threshold=0.05`, `min_age_days=14`,
  `scan_limit=10000`) on `Settings.retention`; `AuditAction.PRUNE`;
  `MemoryService.forget` accepts `reason`.
- `POST /v1/decay` (202 + job handle) and Celery task `memcore.decay_tenant`.
- API: `confidence` exposed on remember/correct requests (Phase 6 backlog).

### Added — Phase 6: Importance scoring
- `services/importance.py`: pure reinforcement (`n/(n+s)` saturating curve),
  `effective_importance` (bounded boost toward 1.0), `decay_score`
  (exp(−age/τ) from last access; `pinned` tag exempt) — ADR-0015.
- Consolidation: extraction prompt scores per-fact `importance` (0–1,
  long-term value, independent of confidence); fact `confidence` now stored
  on `MemoryRecord.confidence` instead of overloading `importance`. When the
  LLM omits `importance`: ADD/needs_review default to 0.5; a contradiction
  UPDATE instead preserves the prior version's base importance.
- `MemoryService.remember`/`correct` accept `confidence`.
- Recall ranks with usage-reinforced effective importance
  (`ImportanceSettings` wired via `Settings.importance`).

### Added — Phase 5: Consolidation agent
- LLM adapters: `AnthropicLLMProvider` (Claude Sonnet, JSON prefill),
  `OllamaLLMProvider` (httpx), `FailoverLLMProvider`, `ScriptedLLMProvider`.
- `ConsolidationService`: strict-JSON extraction (transcript as untrusted
  data), deterministic ADD/UPDATE/DELETE/NOOP with SPO conflict detection,
  `needs_review` false-overwrite guard, entity linking + relation provenance,
  watermark idempotency, CONSOLIDATE audit — ADR-0014.
- Workflow engines: `ImmediateWorkflowEngine` (inline) and
  `CeleryWorkflowEngine` + `memcore.workers.celery_app` worker entrypoint.
- API: session close enqueues consolidation; `POST /v1/consolidate`,
  `GET /v1/jobs/{id}`.
- `MemoryService.remember/correct` accept `metadata`; `ConsolidationSettings`.

### Added — Phase 4: Retrieval engine
- Embedding adapters: `BgeEmbeddingProvider` (sentence-transformers, lazy) and
  `OpenAIEmbeddingProvider` (`text-embedding-3-large`, injectable client).
- Hybrid scoring: lexical-blended relevance + exponent `ScoreWeights`
  (`final = rel^wr · rec^wt · imp^wi`), per-type recency τ — ADR-0013.
- Graph expansion in recall: entity match → bounded neighbourhood → provenance
  memory injection with relevance floor; per-request `graph_expand` toggle.
- Optional budget-gated lexical rerank (cross-encoder/LLM slot).
- Context assembler (`as_context`): dedupe + provenance annotation + token
  budget; `/v1/recall` gains `weights`, `graph_expand`, `rerank`, `as_context`.
- Query-embedding LRU cache; `RetrievalSettings` config block.

### Added — Phase 3: Memory APIs
- `MemoryStore` port (records/audit/sessions) + `InMemoryMemoryStore` and
  `SqlMemoryStore` (SQLAlchemy async: Postgres prod, SQLite tests) — ADR-0012.
- Service layer: `SessionService` (fast ingest + raw archive), `MemoryService`
  (versioned remember/correct/forget + audit), `RecallService` (hybrid score v1
  `relevance × recency × importance`, reinforcement on recall).
- FastAPI v1 API: sessions, memories CRUD + versions, recall, health;
  `X-API-Key` tenant auth; RFC-7807 problem+json errors.
- `check_memory_store_contract` added to the shipped test-kit.
- Factory: `build_memory_store`, `build_embedding_provider`.
- Extras: `api`, `sql`, `postgres`; CI installs api+sql.

### Added — Phase 2: Storage layer (Qdrant · Neo4j · Redis)
- Live adapters: `QdrantVectorStore`, `Neo4jGraphStore`, `RedisWorkingMemory`.
- `InMemoryGraphStore` completing the offline substrate.
- `adapters/factory.py` selecting adapters from `Settings` (lazy driver imports).
- Shippable port contract test-kit `memcore.testing.contracts`.
- `docker-compose.yml` for local Qdrant/Neo4j/Redis with healthchecks.
- Integration suite (`-m integration`) that skips when backends are unreachable.
- ADR-0011 (storage adapter conventions & contract testing).

### Added — Phase 1: Project setup & repository structure
- `src/` hexagonal layout: `domain`, `ports`, `adapters`.
- Domain models: `MemoryRecord`, `Entity`, `Relation`, `Session`, `Interaction`,
  `AuditEvent`, `ScoredMemory`, with versioning/provenance fields.
- Seven storage/provider **ports** (abstract interfaces).
- In-memory reference adapters for `VectorStore`, `WorkingMemory`, `ObjectStore`.
- `pydantic-settings` configuration with per-backend nested prefixes.
- Structured logging, typed exception hierarchy.
- Tooling: ruff, mypy(strict), pytest(+cov gate 85%), pre-commit, GitHub Actions CI.
- ADR log seeded (ADR-001..012) reflecting approved stack decisions.
