# MemCore

**Long-term memory infrastructure for AI agents.**

LLMs forget everything outside their context window. MemCore is a production-grade
memory substrate that gives agents persistent **working**, **episodic**, and
**semantic** memory through one unified API — behaving like a cognitive memory
system, not a bare vector database.

> Status: **v0.1, feature-complete.** All 12 roadmap phases shipped; see
> [`docs/design/roadmap.md`](docs/design/roadmap.md).

## Why

Naive RAG retrieves on cosine similarity alone, never forgets, and silently
contradicts itself. MemCore adds:

- **Hybrid retrieval** — `relevance × recency × importance`, not similarity alone.
- **Consolidation** — raw conversations become structured memories (facts, entities,
  relations) with conflict resolution and provenance (`ADD / UPDATE / DELETE / NOOP`).
- **Decay & forgetting** — configurable retention, soft deletion + restore, audit trail.
- **Pluggable storage** — vector + graph behind clean ports.
- **Deployable today** — Docker image, Kubernetes manifests, CI-verified.

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
  domain/ ports/ adapters/   # the hexagon: models, interfaces, backends
  services/ api/ sdk/        # sessions/memories/recall/consolidation/decay, FastAPI, client
```

## Quickstart

No server yet? Bring up the full local stack (API + worker + Postgres +
Qdrant + Neo4j + Redis):

```bash
cp .env.example .env && docker compose up -d --build
```

Then install the SDK and talk to it:

```bash
pip install 'memcore[sdk]'
```

```python
async with AsyncMemCoreClient(url, key) as client:
    record = await client.remember(
        agent_id, "Chinmay prefers dark mode in every editor.",
        importance=0.8, tags=["preference"],
    )
    outcome = await client.recall(agent_id, "what UI theme does the user like?")
    for scored in outcome.results:
        print(f"{scored.final:.3f}  {scored.memory.content}")
```

Full runnable version: [`examples/quickstart_async.py`](examples/quickstart_async.py)
(`quickstart_sync.py` for the blocking client). Full path from Compose to
Kubernetes: [`docs/guides/deployment.md`](docs/guides/deployment.md).

## Documentation

| Doc | Covers |
|---|---|
| [`docs/api-reference.md`](docs/api-reference.md) | Generated REST API reference (OpenAPI-driven, CI drift-tested) |
| [`docs/sdk-quickstart.md`](docs/sdk-quickstart.md) | Python SDK: install, auth, errors, retries |
| [`docs/guides/operations.md`](docs/guides/operations.md) | Config reference, backing services, observability, memory ops, troubleshooting |
| [`docs/guides/deployment.md`](docs/guides/deployment.md) | Docker Compose → Kubernetes walkthrough |
| [`examples/`](examples/) | Four runnable SDK scripts, CI-executed against the in-process app |
| [`docs/adr/`](docs/adr/) | Architecture Decision Records (21, one per significant decision) |
| [`docs/design/roadmap.md`](docs/design/roadmap.md) | Phase-by-phase build history |

## Install extras

The core package is dependency-light; backends and interfaces are opt-in extras:

| Extra | Adds | Use for |
|---|---|---|
| `sdk` | pydantic-settings, httpx | Talking to a MemCore server |
| `api` | fastapi, uvicorn | Running the API |
| `vector` / `graph` / `working` | qdrant-client / neo4j / redis | Storage adapters |
| `sql` / `postgres` | SQLAlchemy(+asyncio) / asyncpg | Metadata store (SQLite tests / Postgres prod) |
| `scheduler` | celery | Async consolidation & decay jobs |
| `embeddings` | sentence-transformers | Local `bge-small` embeddings |
| `llm` | anthropic, openai, httpx | Consolidation LLM providers |
| `observability` | prometheus-client | `/metrics`, worker metric exposition |
| `dev` | pytest, ruff, mypy, pre-commit | Contributing |

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
