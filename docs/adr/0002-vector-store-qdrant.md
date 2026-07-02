# ADR-0002: Vector store = Qdrant (pgvector as alternative)

**Status:** Accepted (2026-07-01)

## Context
We need filtered ANN search with strong multi-tenant payload filtering,
quantization, and horizontal scaling.

## Decision
Default to **Qdrant** behind the `VectorStore` port. **pgvector** remains a
supported adapter for small/self-host deployments (keeps FR-10 honest). The core
never imports a vector driver directly.

## Consequences
- One more system to operate in the default stack.
- Tenant isolation is enforced via payload filters on every query (adapter
  responsibility), backed by isolation tests.
- Collections are created per embedding-model dimension (see ADR-0010).
