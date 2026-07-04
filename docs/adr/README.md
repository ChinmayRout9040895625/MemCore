# Architecture Decision Records

Each ADR captures one significant decision: its context, the decision, and its
consequences. ADRs are immutable once `Accepted`; a reversal is a new ADR that
supersedes the old one.

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-async-consolidation.md) | Asynchronous consolidation, not inline | Accepted |
| [0002](0002-vector-store-qdrant.md) | Vector store = Qdrant (pgvector as alt) | Accepted |
| [0003](0003-graph-store-neo4j.md) | Graph store = Neo4j | Accepted |
| [0004](0004-scheduler-celery-default.md) | Scheduler = Celery default, Temporal future | Accepted |
| [0005](0005-postgres-source-of-truth.md) | Postgres is metadata/audit source of truth | Accepted |
| [0006](0006-hexagonal-architecture.md) | Hexagonal ports-and-adapters core | Accepted |
| [0007](0007-immutable-versioned-records.md) | Memory records are immutable + versioned | Accepted |
| [0008](0008-multi-tenancy.md) | Row/payload-level multi-tenancy | Accepted |
| [0009](0009-consolidation-model.md) | Claude Sonnet primary, Ollama fallback | Accepted |
| [0010](0010-embeddings.md) | bge-small default, pluggable embeddings | Accepted |
| [0011](0011-storage-adapter-conventions.md) | Storage adapter conventions & contract testing | Accepted |
| [0012](0012-sql-metadata-store.md) | SQL metadata store (Postgres prod, SQLite tests) | Accepted |
| [0013](0013-retrieval-engine.md) | Hybrid retrieval engine design | Accepted |
| [0014](0014-consolidation-design.md) | Consolidation agent design | Accepted |
| [0015](0015-importance-scoring.md) | Importance scoring: LLM-assessed base + read-time reinforcement/decay, pinning | Accepted |
| [0016](0016-decay-and-pruning.md) | Decay & pruning: per-tenant sweep, snapshot via set_decay, rail-guarded soft-delete prune | Accepted |

> ADR numbering here is renumbered from the design package (§3) for a clean log.
