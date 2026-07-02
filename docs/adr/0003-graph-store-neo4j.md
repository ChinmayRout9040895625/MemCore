# ADR-0003: Graph store = Neo4j

**Status:** Accepted (2026-07-01)

## Context
Semantic memory needs entities, temporal/versioned relationships, provenance
queries, and bounded multi-hop expansion during retrieval.

## Decision
Use **Neo4j** behind the `GraphStore` port. Model entities as nodes and
relations as versioned, temporal edges carrying provenance.

## Consequences
- License/cost considerations at scale; the adapter boundary allows swapping to
  another property-graph engine later.
- Graph expansion during retrieval is bounded (hops + limit) to protect the
  latency budget (Risk R-1).
