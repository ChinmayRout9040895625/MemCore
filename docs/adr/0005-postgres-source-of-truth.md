# ADR-0005: Postgres is the metadata/audit source of truth

**Status:** Accepted (2026-07-01)

## Context
Vector and graph indexes are derived, rebuildable projections. Dual-writing to
them risks drift and makes disaster recovery hard.

## Decision
**Postgres** holds the authoritative `memory_records`, versions, audit log, and
tenant/RBAC control tables. Writes go to Postgres plus an `outbox` row in one
transaction; an outbox relay projects changes to Qdrant/Neo4j
(at-least-once, idempotent by `memory_record_id` + `version`).

## Consequences
- Qdrant/Neo4j can be rebuilt from Postgres + the object-store archive (DR path).
- Requires the outbox relay + reconciliation job (Risk R-4).
- Slightly higher write complexity, bought back in consistency + recoverability.
