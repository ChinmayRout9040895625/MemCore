# ADR-0011: Storage adapter conventions & port contract testing

**Status:** Accepted (2026-07-02)

## Context
Phase 2 implements the first production adapters (Qdrant, Neo4j, Redis). We need
consistent conventions for id/collection/key schemas and a way to guarantee that
every adapter — in-memory or live — behaves identically to its port.

## Decision

**Contract test-kit.** Port behaviour is specified once in
`memcore.testing.contracts` as backend-agnostic `check_*_contract` coroutines.
In-memory adapters run them in CI; live adapters run the same checks in the
integration suite. The kit ships with the package so third-party adapters can
self-verify.

**Qdrant (VectorStore).** Cosine distance; one collection per embedding
dimension; point ids are UUID strings (MemCore's native id format, and required
by Qdrant). Payload equality → `MatchValue`, list → `MatchAny`. Tenant/agent
scoping is passed as filters on every query.

**Neo4j (GraphStore).** Entities are `(:Entity {id, tenant_id, ...})` nodes;
relations are a single `[:REL {predicate, ...}]` edge type (semantic predicate is
a property, keeping neighbour queries uniform). Enums → values, `metadata` →
JSON string, datetimes → ISO-8601, scalar lists → native arrays. Variable-length
expansion bounds hops with an integer-validated, interpolated upper bound; every
read filters on `tenant_id`.

**Redis (WorkingMemory).** Keys `{prefix}:{session}:buffer|scratch`. Buffer is a
list capped via `LTRIM`; both keys share a TTL refreshed on every write.

**Coverage policy.** Live-adapter network paths need running services, so they
are excluded from the unit-coverage gate and covered by the integration suite;
their pure helpers (filter builder, serde) keep dedicated unit tests.

## Consequences
- Adding a backend = implement the port + pass the contract kit.
- Isolation is asserted by the contract, not left to reviewers.
- CI stays green without Docker; integration tests skip when backends are absent.
