# MemCore Architecture

MemCore is a hexagonal (ports-and-adapters) system. The domain core has zero
I/O; every backend is an adapter behind a port (ADR-0006).

## Two paths

**Write / cold path** — `ingest` appends a turn to the working-memory buffer
(Redis) and returns immediately. A trigger enqueues an async **consolidation
job** that extracts facts/entities/relations, resolves conflicts, and writes
versioned records to Postgres + projects them to Qdrant/Neo4j. The caller never
blocks on an LLM (ADR-0001).

**Read / hot path** — `recall` embeds the query, fans out to vector ANN +
working memory, expands the graph (bounded hops), and re-scores by
`relevance × recency × importance`. Optional cross-encoder rerank is
budget-gated. Target: p95 < 100ms with no LLM on the path.

## Layers

```
SDK → API (FastAPI) → Memory Service (core)
                       ├─ Working Memory (Redis)
                       ├─ Storage ports → Qdrant (vector) + Neo4j (graph)
                       ├─ Postgres (records/audit — source of truth)
                       └─ Workflow engine (Celery) → consolidation/decay workers
```

## Ports (Phase 1)

| Port | Default adapter | Purpose |
|------|-----------------|---------|
| `VectorStore` | Qdrant | filtered ANN search |
| `GraphStore` | Neo4j | entities + temporal relations |
| `WorkingMemory` | Redis | session buffer + scratch |
| `EmbeddingProvider` | bge-small | text → vectors |
| `LLMProvider` | Claude Sonnet (Ollama fallback) | consolidation |
| `WorkflowEngine` | Celery (Temporal future) | async jobs |
| `ObjectStore` | in-memory (S3-compatible adapter is future work) | raw archive / backups |

In-memory adapters implement these for offline dev and tests.

## Consistency

Postgres is the authoritative record/audit store; Qdrant and Neo4j are derived,
rebuildable projections (ADR-0005). Today writes flow through a single owner —
`MemoryService` (and, for consolidation, `ConsolidationService` on top of it) —
which keeps the record and its vector projection in step per write. The
transactional **outbox relay** described in ADR-0005 is specified but **not yet
implemented** (deferred with the Postgres-first hardening; see `phase-05.md`).
The indexes remain rebuildable from Postgres + archive — the ultimate
disaster-recovery path — independent of the relay.

## Importance & decay (Phases 6–7)

`MemoryRecord.importance` is a write-time base. At recall time, ranking blends
it with a saturating function of `access_count`
(`effective_importance = base + max_boost · reinforcement · (1 − base)`);
`decay_score = exp(−age/τ)` fades untouched memories, and the `pinned` tag
exempts a record entirely. These are pure read-time functions in
`services/importance.py` — nothing derived is persisted on the hot path
(ADR-0015). A per-tenant **decay sweep** (`POST /v1/decay` → `decay_tenant`)
snapshots `decay_score` via `set_decay` and prunes records only when all rails
agree — `score < prune_threshold` **and** not `pinned` **and**
`age ≥ min_age_days` — as a reversible, audited soft-delete (ADR-0016).

## Evaluation (Phase 8)

`python -m memcore.evaluation` runs a deterministic, offline, in-memory harness
over a hand-written token-overlap dataset (no LLM, no network). It reports a
`naive-vector` baseline against the `hybrid` config plus `no-importance` /
`no-recency` ablations, and two scenario runners (reinforcement ablation,
longitudinal decay curve) double as end-to-end regression guards for the
Phase 6–7 ranking behaviors. `memcore.evaluation` is a consumer layer — nothing
in `services`/`domain`/`ports`/`adapters` imports it (ADR-0017).

## SDK (Phase 9)

`memcore.sdk` ships inside the package as a server-free consumer layer
(`pip install 'memcore[sdk]'` — pydantic + httpx only). It provides an
async-first `AsyncMemCoreClient` and a mechanically mirrored sync
`MemCoreClient` (drift caught by a signature-parity test), covering the full v1
surface. Retries are **GET-only** on `{429, 502, 503, 504}` / transport failure
with deterministic backoff — non-idempotent writes are never replayed. Responses
validate into the domain models; `wait_for_job` polls to a terminal state
(ADR-0018). See `docs/sdk-quickstart.md`.

## Observability (Phase 10)

One correlation id per HTTP request (honoring/echoing `X-Request-ID`) or per
job, stamped onto every log line as `request_id`. Prometheus metrics live behind
the optional `observability` extra: `memcore_http_requests_total` and
`memcore_http_request_duration_seconds` (labeled by route **template**, unmatched
→ `unmatched`) plus `memcore_operation_duration_seconds{operation}` for
`recall`/`consolidation`/`decay_sweep`. `/health` is liveness; `/ready` is an
honest per-backend probe (503 when any component's `ping()` fails). Metrics
call sites no-op without the extra (ADR-0019). Operator detail:
`docs/guides/operations.md`.

## Deployment shape (Phase 11)

One multi-stage image serves **two roles**: the API by default
(`uvicorn --factory memcore.api:create_app`) and the Celery worker via a
`command` override. `docker-compose.yml` is the full local stack (API + worker +
Postgres + Qdrant + Neo4j + Redis, healthchecked). `deploy/k8s/` wires
`livenessProbe → /health` and `readinessProbe → /ready`; backends are
bring-your-own prerequisites, rate limiting is an nginx-ingress edge concern,
and `/ready` + `/metrics` are cluster-internal only. Worker metrics are exposed
on `MEMCORE_METRICS_PORT` with a `--concurrency=1` constraint (ADR-0020).
Operator detail: `docs/guides/operations.md`, `deploy/k8s/README.md`.

See the [ADR log](../adr/) for the reasoning behind each choice.
