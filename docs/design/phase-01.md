# Phase 1 — Project Setup & Repository Structure

## Objective
Stand up a production-grade Python monorepo skeleton that every later phase
plugs into without refactors: the hexagonal core (domain + ports), in-memory
reference adapters, configuration, and the full quality gate (lint, types,
tests, CI).

## Delivered

**Structure**
```
src/memcore/
  domain/    enums.py, models.py        # the contract (pydantic v2)
  ports/     7 abstract interfaces        # VectorStore, GraphStore, ...
  adapters/inmemory/                      # reference/test doubles
  config.py  logging.py  exceptions.py
tests/unit/                               # models, config, adapters, package
docs/adr/   docs/design/
```

**Domain models** — `MemoryRecord` (versioned, bitemporal, provenanced),
`Entity`, `Relation`, `Session`, `Interaction`, `AuditEvent`, `ScoredMemory`,
`ConsolidationCandidate`. Immutability-by-version implemented via
`superseded_by()` (ADR-0007).

**Ports** — `VectorStore`, `GraphStore`, `WorkingMemory`, `EmbeddingProvider`,
`LLMProvider`, `WorkflowEngine`, `ObjectStore`. All tenant-scoped; no driver
types leak across boundaries (ADR-0006).

**In-memory adapters** — `InMemoryVectorStore` (exact cosine + payload filter),
`InMemoryWorkingMemory` (bounded buffer + scratch), `InMemoryObjectStore`,
`HashingEmbeddingProvider` (deterministic, offline). These make the whole system
runnable and testable with zero external services.

**Config** — `pydantic-settings` pinning the approved stack (Qdrant + Celery +
Redis + Neo4j; Claude Sonnet w/ Ollama fallback; bge-small embeddings) via
nested `MEMCORE_*` env vars.

**Quality gate** — ruff, mypy(strict), pytest with an 85% coverage floor,
pre-commit, and a 3.11–3.13 CI matrix.

## Decisions recorded
ADRs 0001–0010 seeded, including the approved-decision ADRs: 0004 (Celery
default / Temporal future), 0009 (Claude Sonnet + Ollama), 0010 (bge-small +
pluggable embeddings).

## Explicitly deferred
Backend adapters (Qdrant/Neo4j/Redis), FastAPI app, Postgres schema, and the
outbox relay land in Phase 2+. Phase 1 intentionally ships no network I/O.

## Self-review
See the Phase 1 review notes in the delivery message; issues found were fixed
before sign-off (fragile lazy import in `models.py`; dead monkeypatch loop in
`test_config.py`).
