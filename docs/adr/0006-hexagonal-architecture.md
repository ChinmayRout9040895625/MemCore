# ADR-0006: Hexagonal ports-and-adapters core

**Status:** Accepted (2026-07-01)

## Context
The system integrates many swappable backends (vector, graph, working memory,
LLM, embeddings, scheduler, object store). Coupling core logic to drivers would
make FR-10 (pluggable storage) and testing painful.

## Decision
The domain core depends only on **ports** (abstract interfaces in
`memcore.ports`). Concrete **adapters** (`memcore.adapters.*`) implement them.
Driver-specific types never cross a port boundary. In-memory adapters provide
test doubles and a zero-dependency local mode.

## Consequences
- More interfaces up front.
- Backends are swappable and independently testable; the whole system runs
  offline against in-memory adapters.
- Enables the Temporal (ADR-0004) and pgvector (ADR-0002) swaps at low cost.
