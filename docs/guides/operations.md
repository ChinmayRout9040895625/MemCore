# MemCore Operations Guide

Everything an operator needs to configure, observe, and troubleshoot a running
MemCore deployment. Every value below is read from source (`config.py`,
`observability/`, `api/routes.py`, `services/{importance,decay,memories}.py`,
`workers/celery_app.py`); where the code and this guide could drift, the code
wins.

## 1. Configuration reference

Settings load via `pydantic-settings`. Every field is an environment variable
prefixed `MEMCORE_`; nested blocks use the `__` delimiter. A `.env` file in the
process working directory is read automatically (`env_file=".env"`, UTF-8).
Unknown env vars are ignored (`extra="ignore"`).

Nesting example: the `url` field of the `vector` block is
`MEMCORE_VECTOR__URL`. A dict-typed field takes JSON:
`MEMCORE_API__KEYS={"k1":"tenant1"}`.

### Root

| Env var | Default | Notes |
|---------|---------|-------|
| `MEMCORE_ENV` | `local` | `local` \| `staging` \| `production`. `local` enables the dev-key fallback (see `api` below). |
| `MEMCORE_LOG_LEVEL` | `INFO` | Standard logging level name. |
| `MEMCORE_LOG_JSON` | `false` | `true` emits structured JSON log lines (includes `request_id`). |

### `redis` — working memory + session buffer

| Env var | Default | Notes |
|---------|---------|-------|
| `MEMCORE_REDIS__PROVIDER` | `redis` | `redis` \| `inmemory`. |
| `MEMCORE_REDIS__URL` | `redis://localhost:6379/0` | Working-memory connection. |
| `MEMCORE_REDIS__SESSION_TTL_SECONDS` | `3600` | ≥ 1. Session buffer TTL. |
| `MEMCORE_REDIS__BUFFER_MAX_TURNS` | `200` | ≥ 1. Max turns kept per session buffer. |

### `vector` — vector projection

| Env var | Default | Notes |
|---------|---------|-------|
| `MEMCORE_VECTOR__PROVIDER` | `qdrant` | `qdrant` \| `pgvector` \| `inmemory`. |
| `MEMCORE_VECTOR__URL` | `http://localhost:6333` | Qdrant endpoint. |
| `MEMCORE_VECTOR__API_KEY` | _(unset)_ | Optional; `None` when unset. |
| `MEMCORE_VECTOR__COLLECTION_PREFIX` | `memcore` | Collection name is `{prefix}_{embedding_dimension}`. |

### `graph` — entity/relation graph

| Env var | Default | Notes |
|---------|---------|-------|
| `MEMCORE_GRAPH__PROVIDER` | `neo4j` | `neo4j` \| `inmemory`. |
| `MEMCORE_GRAPH__URL` | `bolt://localhost:7687` | Neo4j bolt endpoint. |
| `MEMCORE_GRAPH__USER` | `neo4j` | |
| `MEMCORE_GRAPH__PASSWORD` | `neo4j` | Change for any non-local deployment. |

### `embedding` — text → vectors

| Env var | Default | Notes |
|---------|---------|-------|
| `MEMCORE_EMBEDDING__PROVIDER` | `bge` | `bge` \| `openai` \| `inmemory`. |
| `MEMCORE_EMBEDDING__MODEL` | `BAAI/bge-small-en-v1.5` | bge/openai adapters self-declare dimension (ADR-0010). |
| `MEMCORE_EMBEDDING__DIMENSION` | `384` | ≥ 1. Used by the `inmemory` provider only. |
| `MEMCORE_EMBEDDING__API_KEY` | _(unset)_ | `openai` provider only. |

### `llm` — consolidation model

| Env var | Default | Notes |
|---------|---------|-------|
| `MEMCORE_LLM__PROVIDER` | `anthropic` | `anthropic` \| `ollama` \| `inmemory`. |
| `MEMCORE_LLM__MODEL` | `claude-sonnet-5` | |
| `MEMCORE_LLM__FALLBACK_PROVIDER` | `ollama` | Set empty/`None` to disable failover. |
| `MEMCORE_LLM__FALLBACK_MODEL` | `llama3.1` | |
| `MEMCORE_LLM__API_KEY` | _(unset)_ | Provider key; consolidation is a no-op path without a usable provider. |
| `MEMCORE_LLM__OLLAMA_URL` | `http://localhost:11434` | Used by the `ollama` provider/fallback. |

### `scheduler` — async workflow engine

| Env var | Default | Notes |
|---------|---------|-------|
| `MEMCORE_SCHEDULER__PROVIDER` | `celery` | `celery` \| `temporal` (future). |
| `MEMCORE_SCHEDULER__BROKER_URL` | `redis://localhost:6379/1` | Celery broker **and** result backend. Note DB `1`, distinct from working-memory Redis DB `0`. |

### `database` — metadata source of truth (ADR-0005)

| Env var | Default | Notes |
|---------|---------|-------|
| `MEMCORE_DATABASE__PROVIDER` | `sql` | `sql` \| `inmemory`. |
| `MEMCORE_DATABASE__URL` | `postgresql+asyncpg://memcore:memcore@localhost:5432/memcore` | Any SQLAlchemy-async URL. Postgres in prod; SQLite for tests/self-host. |

### `api` — API-key auth (v1)

| Env var | Default | Notes |
|---------|---------|-------|
| `MEMCORE_API__KEYS` | `{}` (empty) | JSON map of `api-key → tenant_id`, e.g. `{"k1":"tenant1"}`. No default credentials ship. |

Dev-key injection: when the map is empty **and** `MEMCORE_ENV=local`, startup
injects a `dev-key → local` binding (logged as a warning) so quickstarts work.
In any other env an empty map means every request is `401`.

### `retrieval` — hybrid recall engine

| Env var | Default | Notes |
|---------|---------|-------|
| `MEMCORE_RETRIEVAL__CANDIDATE_MULTIPLIER` | `4` | ≥ 1. Fan-out multiplier over `k`. |
| `MEMCORE_RETRIEVAL__MIN_CANDIDATES` | `32` | ≥ 1. Floor on candidate pool size. |
| `MEMCORE_RETRIEVAL__LEXICAL_ALPHA` | `0.3` | 0..1. `relevance = (1-α)·vector + α·lexical`. |
| `MEMCORE_RETRIEVAL__GRAPH_EXPAND` | `true` | Enable graph neighbour injection. |
| `MEMCORE_RETRIEVAL__GRAPH_MAX_HOPS` | `2` | 1..3. |
| `MEMCORE_RETRIEVAL__GRAPH_LIMIT` | `25` | ≥ 1. Max graph-injected candidates. |
| `MEMCORE_RETRIEVAL__GRAPH_MAX_ENTITIES` | `5` | ≥ 1. Entities used to seed expansion. |
| `MEMCORE_RETRIEVAL__GRAPH_RELEVANCE_FLOOR` | `0.45` | 0..1. Minimum relevance for structurally-related candidates. |
| `MEMCORE_RETRIEVAL__RERANK_WINDOW` | `20` | ≥ 1. Cross-encoder rerank window. |
| `MEMCORE_RETRIEVAL__CONTEXT_TOKEN_BUDGET` | `2000` | ≥ 50. `as_context` assembly budget. |
| `MEMCORE_RETRIEVAL__TAU_WORKING_HOURS` | `6.0` | > 0. Recency time constant, working memory. |
| `MEMCORE_RETRIEVAL__TAU_EPISODIC_DAYS` | `7.0` | > 0. Recency time constant, episodic. |
| `MEMCORE_RETRIEVAL__TAU_SEMANTIC_DAYS` | `30.0` | > 0. Recency time constant, semantic. |

### `consolidation` — consolidation agent

| Env var | Default | Notes |
|---------|---------|-------|
| `MEMCORE_CONSOLIDATION__MAX_TURNS` | `200` | ≥ 1. Turns pulled per consolidation. |
| `MEMCORE_CONSOLIDATION__DUP_SIMILARITY` | `0.9` | 0..1. Same subject+predicate and vector-similar object ⇒ NOOP. |
| `MEMCORE_CONSOLIDATION__CONFLICT_CONFIDENCE` | `0.7` | 0..1. Below this a conflicting fact is stored `needs_review` instead of superseding. |
| `MEMCORE_CONSOLIDATION__CANDIDATE_MATCHES` | `5` | ≥ 1. Related-memory lookups per fact. |
| `MEMCORE_CONSOLIDATION__EXTRACTION_MAX_TOKENS` | `2048` | ≥ 256. |

### `importance` — reinforcement + decay curves (ADR-0015)

| Env var | Default | Notes |
|---------|---------|-------|
| `MEMCORE_IMPORTANCE__REINFORCEMENT_SATURATION` | `5.0` | > 0. `access_count` at which reinforcement reaches half its ceiling. |
| `MEMCORE_IMPORTANCE__REINFORCEMENT_MAX_BOOST` | `0.3` | 0..1. Ceiling of the boost: `effective ≤ base + boost·(1-base)`. |
| `MEMCORE_IMPORTANCE__DECAY_TAU_DAYS` | `30.0` | > 0. Time constant for decay of untouched memories. |

### `retention` — decay sweep + prune policy (ADR-0016)

| Env var | Default | Notes |
|---------|---------|-------|
| `MEMCORE_RETENTION__PRUNE_THRESHOLD` | `0.05` | 0..1. Decay snapshot below this makes a record a prune candidate. |
| `MEMCORE_RETENTION__MIN_AGE_DAYS` | `14.0` | > 0. Never prune records younger than this, regardless of score. |
| `MEMCORE_RETENTION__SCAN_LIMIT` | `10000` | ≥ 1. Max records fetched per sweep (single page, oldest-first). |

### Non-Settings environment variables

| Env var | Default | Notes |
|---------|---------|-------|
| `MEMCORE_METRICS_PORT` | _(unset)_ | Read directly by the Celery worker (not part of `Settings`). When set, each worker process starts a Prometheus exposition server on this port. Unset = disabled. See §3. |

## 2. Backing services

| Store | Holds | Rebuildable? |
|-------|-------|--------------|
| **Postgres** | Authoritative `memory_records`, version chains, and the audit log — the source of truth (ADR-0005). | No — this is the primary. |
| **Qdrant** | Vector projection of active records for ANN recall. | Yes — re-indexable from the record store. |
| **Neo4j** | Entity + temporal-relation graph built during consolidation. | Yes — reprojectable from the record store. |
| **Redis** | Working-memory session buffer (DB `0`) **and** the Celery broker/result backend (DB `1`). | Ephemeral by nature. |

The vector and graph stores are **derived projections**: only Postgres is
authoritative, so both indexes can be rebuilt from the record store after loss
or a schema change. (Note: a transactional outbox relay is specified in
ADR-0005 but is **not yet implemented** — consolidation currently writes
record-by-record through `MemoryService`, which keeps the record/vector pair in
step per write; see `docs/design/phase-05.md`.)

**Provisioning.** Local: `docker-compose.yml` brings up all four backends plus
the API and worker with healthchecks and `depends_on: service_healthy`.
Cluster: `deploy/k8s/` deploys only the API and worker — the four backends are
bring-your-own prerequisites reachable at the DNS names in `configmap.yaml`
(`postgres:5432`, `qdrant:6333`, `neo4j:7687`, `redis:6379`). See
`deploy/k8s/README.md`.

## 3. Observability runbook

### Correlation ids

- The ASGI `ObservabilityMiddleware` binds one correlation id per HTTP request.
  An incoming `X-Request-ID` header is honored (rejected only if longer than
  128 chars, in which case a fresh id is minted); otherwise a uuid4 hex (32
  chars) is generated. The id is echoed back on the response as `X-Request-ID`.
- Celery task shells (`consolidate_session`, `decay_tenant`) bind one fresh id
  per job.
- `memcore.logging`'s context filter stamps the current id onto **every** log
  record as `request_id` (`"-"` when unbound). The plain-text formatter renders
  it as `[request_id]`; the JSON formatter emits it as a structured field.

### Access log

Each request emits one access-log line (`api.access` logger) carrying:
`request_id`, `method`, `path` (raw), `route` (matched template, or the raw
path when unmatched), `status`, and `duration_ms`.

### Metrics

Prometheus support lives behind the optional `observability` extra
(`pip install 'memcore[observability]'`). Without it, `observe_*` calls are
silent no-ops and only `/metrics` reacts (501, below).

| Metric | Type | Labels | Notes |
|--------|------|--------|-------|
| `memcore_http_requests_total` | Counter | `method`, `route`, `status` | `route` is the matched Starlette path **template**; unmatched requests use the constant `unmatched` (never the raw path — bounded cardinality). |
| `memcore_http_request_duration_seconds` | Histogram | `method`, `route`, `status` | Same label semantics. Buckets: 0.005–10s. |
| `memcore_operation_duration_seconds` | Histogram | `operation` | `operation ∈ {recall, consolidation, decay_sweep}`. |

### `/metrics`, `/ready`, `/health`

- `GET /health` — liveness only: `{"status":"ok","version":...}`, always 200.
- `GET /metrics` — Prometheus exposition when the extra is installed; **501**
  `application/problem+json` (`ConfigurationError`, with the install hint in
  `detail`) when it is not. Served on the same HTTP port as the API (8000).
  Excluded from the OpenAPI schema.
- `GET /ready` — per-component readiness. Iterates
  `app.state.memcore_probes` (`store`, `vectors`, `graph`, `working`), calling
  each adapter's optional `async ping()`. Adapters without a `ping` (the
  in-memory ones) count as `ok`. Any failure makes the whole response **503**
  with `{"status":"degraded","components":{...}}`; each failed component reports
  only the **error class name** (`error: {ExceptionClassName}`) — the full error
  text goes to the server log, not the response body.

### Worker metric exposition

The Celery worker has no ASGI app, so it exposes its own metric registry over
HTTP when `MEMCORE_METRICS_PORT` is set — `start_metrics_server(port)` is called
from a `worker_process_init` handler. If the extra is missing or the server
fails to start, the failure is logged and the worker continues (metrics never
kill a worker).

**`--concurrency=1` constraint.** The exposition assumes a single worker
process. The shipped compose/K8s manifests pass `--concurrency=1` precisely so
exactly one process binds the port (e.g. 9100) and owns the registry. A default
prefork worker with multiple children would race the port and expose only one
child's counters. Higher concurrency needs prometheus multiprocess mode — not
built (ADR-0020).

## 4. Memory operations

### Importance & reinforcement (ADR-0015)

`MemoryRecord.importance` is the write-time **base** (LLM-assessed at
consolidation, or caller-provided), never silently rewritten by usage. At
**read** time, ranking uses `effective_importance = base + max_boost ·
reinforcement(access_count) · (1 − base)`, where `reinforcement = n/(n+s)` is a
saturating Michaelis-Menten curve (`s = reinforcement_saturation`). The boost is
bounded (`≤ max_boost` of the gap to 1.0), monotonic, and never exceeds 1.0, so
recall strengthens a memory's rank without ever drowning out base importance.
Nothing here is persisted — it is recomputed on the hot path.

### Decay + prune rails (ADR-0016)

`decay_score = exp(−age/τ)` where age counts from `last_accessed_at` (falling
back to `created_at`) and `τ = decay_tau_days`. A record tagged **`pinned`**
short-circuits to `1.0` — exempt from decay and pruning entirely.

`POST /v1/decay` (202 + job handle) enqueues `decay_tenant` for the calling
tenant. A sweep scores every ACTIVE record, persists snapshots via `set_decay`
(an in-place signal update — no new versions), then prunes. **All three rails
must agree** for a record to be pruned:

- `decay_score < prune_threshold` (default `0.05`), **AND**
- not tagged `pinned`, **AND**
- `age ≥ min_age_days` (default `14` days, measured from `created_at`).

Pruning is a **soft delete** through `MemoryService.forget` (audit +
vector-index removal in one place). Each prune emits a per-record `DELETE` audit
(`reason="decay prune (score=…)"`) and the sweep emits one `PRUNE` summary
event. Re-running immediately is idempotent (pruned records are no longer
ACTIVE). Within one process, concurrent sweeps for the same tenant are
serialised by a per-tenant `asyncio.Lock` — but a prefork Celery worker gives
**no cross-process dedupe** (each child has its own lock registry); see §6.

### Restore & delete (ADR-0020, ADR-0007)

- `POST /v1/memories/{id}/restore` — brings a **SOFT_DELETED** record back to
  ACTIVE and re-indexes it (`AuditAction.RESTORE`). Re-indexing happens before
  the status flip, so an embedder failure leaves the record safely
  soft-deleted. A record that is not soft-deleted → `422`; a hard-deleted or
  missing record → `404`.
- `DELETE /v1/memories/{id}?mode=soft` (default) — soft delete: status →
  SOFT_DELETED, dropped from the retrievable index, `DELETE` audit. A
  **SUPERSEDED** version cannot be soft-deleted (soft delete targets the active
  version → `422`). A soft-deleted record remains GET-visible by design
  (ADR-0018).
- `DELETE /v1/memories/{id}?mode=hard` — GDPR-style permanent erase: status →
  HARD_DELETED, `ERASE` audit. Hard-deleted records `404` on GET and cannot be
  restored.

## 5. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `GET /metrics` returns 501 | `observability` extra not installed → `pip install 'memcore[observability]'`. The `detail` field carries this hint. |
| `/ready` returns 503 `degraded` | Check the named component in `components` (only the error **class** is in the response) and read the server log for the full error text. Confirm the backend is reachable at its configured URL. |
| Consolidation jobs failing | Check the LLM key (`MEMCORE_LLM__API_KEY`) and failover config (`MEMCORE_LLM__FALLBACK_PROVIDER`/`__FALLBACK_MODEL`, or the Ollama URL). Job state is queryable at `GET /v1/jobs/{id}` — a failed job returns `failed`, it does not raise. |
| `recall` returns nothing | Verify the API key maps to the expected tenant (recall is tenant-scoped), and that consolidation has actually run for the session — recall only sees committed records, not un-consolidated buffer turns. |
| First API/worker start is slow | The bge embedding model downloads on first use. In Kubernetes, budget for this with a `startupProbe` so the slow first start doesn't trip liveness. |
| Worker `/metrics` port not scrapeable | `MEMCORE_METRICS_PORT` unset, or the worker runs with `--concurrency>1` (only one child binds the port). Set the port and pin `--concurrency=1`. |

## 6. Known limits (honest)

- **No cross-process sweep dedupe.** The per-tenant `asyncio.Lock` protects
  only within a single process. A prefork Celery worker (multiple children) has
  no dedupe — concurrent sweeps of one tenant can duplicate DELETE audits and
  add DB load. Real dedupe needs a distributed (Redis) lock — deferred
  (ADR-0016/0020 backlog). Mitigation today: `--concurrency=1`.
- **Rate limiting is edge-only.** There is no in-app limiter; `POST /v1/decay`
  is authed by tenant key alone. Limiting is an nginx-ingress concern
  (`limit-rps` on `ingress.yaml`). A distributed in-app limiter (Redis) is
  deferred (ADR-0020).
- **Postgres not covered by CI integration.** The `integration` CI job runs
  against real Qdrant/Neo4j/Redis only; the SQL path is exercised against
  SQLite in the unit suite, not against a live Postgres in CI (ADR-0020).
- **Single-process worker metrics.** Worker metric exposition assumes one
  process per port; multi-process (prometheus multiprocess mode) is not built.
- **One fat image.** The single image carries all default-stack extras
  (including `torch` via `embeddings`, ~8.7 GB). Slimmer per-role images are a
  future optimization (ADR-0020).
