# MemCore

**Long-term memory infrastructure for AI agents.**

LLMs forget everything outside their context window. MemCore is a production-grade
memory substrate that gives agents persistent **working**, **episodic**, and
**semantic** memory through one unified API — behaving like a cognitive memory
system, not a bare vector database.

> Status: **early development.** Built phase-by-phase; see [`docs/design/roadmap.md`](docs/design/roadmap.md).

## Why

Naive RAG retrieves on cosine similarity alone, never forgets, and silently
contradicts itself. MemCore adds:

- **Hybrid retrieval** — `relevance × recency × importance`, not similarity alone.
- **Consolidation** — raw conversations become structured memories (facts, entities,
  relations) with conflict resolution and provenance (`ADD / UPDATE / DELETE / NOOP`).
- **Decay & forgetting** — configurable retention, soft deletion, audit trail.
- **Pluggable storage** — vector + graph behind clean ports.

## Default stack

| Concern | Default | Alternative (pluggable) |
|---|---|---|
| Vector store | **Qdrant** | pgvector |
| Graph store | **Neo4j** | — |
| Working memory | **Redis** | — |
| Metadata / audit | **Postgres** | — |
| Scheduler | **Celery** | Temporal (future, behind `WorkflowEngine`) |
| Consolidation LLM | **Claude Sonnet** | Ollama (local fallback) |
| Embeddings | **BAAI/bge-small-en-v1.5** | OpenAI `text-embedding-3-large` |

## Architecture

Hexagonal / ports-and-adapters. The domain core (`src/memcore/domain`,
`src/memcore/ports`) has **zero I/O**; every backend is an adapter. See
[`docs/design/architecture.md`](docs/design/architecture.md) and the
[ADR log](docs/adr/).

```
src/memcore/
  domain/     # models + enums (the contract)
  ports/      # abstract interfaces (VectorStore, GraphStore, ...)
  adapters/   # concrete backends (inmemory now; Qdrant/Neo4j/Redis next)
  config.py   # pydantic-settings
```

## Development

```bash
python -m venv .venv
. .venv/Scripts/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest                        # unit tests + coverage gate
ruff check . && mypy          # lint + types
```

## License

Apache-2.0.
