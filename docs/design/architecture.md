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
                       ├─ Postgres (records/audit/outbox — source of truth)
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
| `ObjectStore` | S3-compatible | raw archive / backups |

In-memory adapters implement these for offline dev and tests.

## Consistency

Postgres write + outbox row in one transaction; outbox relay projects to the
indexes idempotently (ADR-0005). Indexes are rebuildable from Postgres + archive
— the ultimate disaster-recovery path.

See the [ADR log](../adr/) for the reasoning behind each choice.
