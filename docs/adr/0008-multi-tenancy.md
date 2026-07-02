# ADR-0008: Row/payload-level multi-tenancy

**Status:** Accepted (2026-07-01)

## Context
MemCore is multi-tenant. We must guarantee no cross-tenant read is possible
(NFR-7) without the cost of per-tenant clusters for every customer.

## Decision
Every record, vector payload, and graph node carries `tenant_id`. All queries
filter by tenant at the gateway **and** in the data layer (defense in depth).
Automated cross-tenant leak tests run in CI. The enterprise tier can graduate to
dedicated namespaces/databases per tenant.

## Consequences
- Isolation is a code + test invariant, verified continuously.
- A single shared cluster serves many tenants cost-efficiently in the base tier.
- Every port method that reads/writes tenant data takes `tenant_id` explicitly —
  there is no ambient tenant context that could be forgotten.
