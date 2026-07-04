# ADR-0016: Decay & pruning — per-tenant sweep, snapshot, rail-guarded soft-delete

**Status:** Accepted (2026-07-04)

## Context
ADR-0015 defined the decay math (`decay_score = exp(−age/τ)`, `pinned` tag
exempt) but persisted nothing — `decay_score` was computed on the recall hot
path and discarded. Without a snapshot and a pruning policy, dead memories
accumulate forever and the stored `decay_score` field stays a constant 1.0
(it is never written), so nothing downstream of recall can see how stale a
record has become.

## Decision

1. **`DecayService.sweep(tenant_id)`** scores every ACTIVE record with
   `services/importance.py`'s `decay_score` function — imported, never
   re-derived (ADR-0015 point 4 honored) — and persists the results as
   snapshots via the new `MemoryStore.set_decay(tenant_id, scores)`. Like
   `reinforce`, this is an in-place signal update, explicitly exempt from
   ADR-0007's immutable-versioning rule: decay is a recomputable derived
   signal, not a fact about the memory's content.

2. **Prune policy requires ALL rails to agree:**
   - `decay_score < prune_threshold` (default `0.05`, ≈ 90 days untouched at
     the default `τ=30d`)
   - AND not `pinned`
   - AND `age ≥ min_age_days` (default `14`) — protects young records outright
     even if their score is momentarily low.

3. **Pruning is soft-delete only**, routed through `MemoryService.forget` —
   the single place that already handles audit + vector-index removal, now
   extended with a `reason` kwarg. Each pruned record gets a per-record
   DELETE audit (`reason="decay prune (score=…)"`), and the sweep as a whole
   emits one `AuditAction.PRUNE` summary event (`actor="decay"`). Hard
   deletion remains a manual/GDPR operation, out of scope here.

4. **The sweep is per-tenant**: `POST /v1/decay` (202 + job handle) enqueues
   the Celery task `memcore.decay_tenant`, mirroring the consolidation job
   shape from Phase 5. Recurring scheduling (e.g. Celery beat calling the
   task per tenant on an interval) is a deployment concern, deferred: MemCore
   has no tenant-enumeration facility yet, so "sweep every tenant on a
   schedule" cannot be wired up until that exists — revisit then.

5. **`list_records` gained `agent_id=None`** (tenant-wide, not scoped to one
   agent) so the sweep can see every ACTIVE record for a tenant. v1 scans a
   single `scan_limit` (default `10_000`) page, newest-first. This is an
   accepted v1 limitation: oldest records are only missed if a tenant exceeds
   `scan_limit` ACTIVE records in one sweep, and subsequent sweeps converge
   as pruned records free up the page.

## Consequences
- Decayed memories leave the retrievable set reversibly and auditably —
  soft-delete plus a DELETE+PRUNE audit trail, not silent data loss.
- `decay_score` in API responses is now a live-ish snapshot: its accuracy is
  bounded by "time since the last sweep," not continuously live like
  `effective_importance` on the recall path.
- Pinning gives users a hard opt-out from pruning, unchanged from ADR-0015.
- Storage cost of a sweep is one bulk signal update (`set_decay`) plus one
  soft-delete write per pruned record — no new record versions are created.
- Paged scanning past `scan_limit`, tenant enumeration for scheduled sweeps,
  and a hard-delete retention job are explicitly deferred (see phase-07.md).
