# Phase 2 — Storage Layer (Qdrant · Neo4j · Redis)

## Objective
Implement production adapters for the three default backends behind the Phase 1
ports, with a reusable contract test-kit that proves in-memory and live adapters
behave identically.

## Delivered

**Live adapters**
- `adapters/qdrant/QdrantVectorStore` — filtered cosine ANN; equality/membership
  filters; UUID point ids; per-dimension collections.
- `adapters/neo4j/Neo4jGraphStore` — `(:Entity)` nodes + uniform `[:REL]` edges;
  enum/JSON/ISO serialization; hop-bounded, tenant-filtered neighbour expansion.
- `adapters/redis/RedisWorkingMemory` — capped list buffer + scratch hash, shared
  TTL refreshed per write (`RPUSH`/`LTRIM`/`EXPIRE`).

**Completing the offline substrate**
- `adapters/inmemory/InMemoryGraphStore` — BFS neighbour expansion, so graph
  contract tests run in CI without Neo4j.

**Wiring**
- `adapters/factory.py` — `build_vector_store` / `build_working_memory` /
  `build_graph_store` select adapters from `Settings` with lazy driver imports
  (a local run needs no backend extras). `provider` fields added to Redis/Graph
  settings (`qdrant|pgvector|inmemory`, `redis|inmemory`, `neo4j|inmemory`).

**Test-kit** (`memcore.testing.contracts`)
- `check_{vector,working_memory,object,graph}_store_contract` — one behavioural
  spec per port, asserting isolation, ordering, bounding and round-trip.

**Infra**
- `docker-compose.yml` — Qdrant + Neo4j + Redis with healthchecks for local
  integration runs.

## Tests
- Unit: contracts against all in-memory adapters; factory selection + error
  branches; pure-helper tests for the Qdrant filter builder and Neo4j serde.
- Integration (`-m integration`): same contracts against live backends, skipping
  cleanly when unreachable.

## Coverage / CI notes
Live-adapter modules are excluded from the unit-coverage gate (they need
servers) and validated by the integration suite; CI installs the storage extras
so mypy type-checks against the real driver types.

## Decisions recorded
ADR-0011 (storage adapter conventions & contract testing).

## Self-review — issues found & fixed
- Two adapters used a grotesque `class X(Port := __import__(...))` base
  expression; replaced with normal top-level imports.
- `Neo4j._read` originally used `record.data()` (ambiguous Relationship
  conversion); switched to returning raw `Record`s and reading node/edge
  properties explicitly.
- Contract kit used short string vector ids; Qdrant requires UUID/int ids —
  switched to real UUIDs so the same contract validates the live adapter.
- Tooling: mypy tripped on numpy 2.5's 3.12-only stub syntax → type target set to
  3.12 (tests still run on 3.11 as the runtime guard); Redis `hget` return
  narrowed with `cast`; test filter introspection rewritten with `isinstance`
  narrowing (no `type: ignore`); Qdrant client set `check_compatibility=False`.

## Deferred to later phases
Postgres metadata store + outbox relay (Phase 3/5), pgvector adapter, and the
services that orchestrate these adapters (ingest/recall) — Phase 3+.
