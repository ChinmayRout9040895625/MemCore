# Phase 7 — Memory decay & pruning

## Objective
Turn Phase 6's decay math into a persisted signal and a real retention
policy: snapshot `decay_score` into storage on demand, and soft-delete
memories that have faded past every safety rail, all audited. Design in
ADR-0016.

## Delivered

**Port extensions** (`ports/memory_store.py`, both adapters)
- `MemoryStore.set_decay(tenant_id, scores)` — in-place decay-score snapshot
  update, same shape as `reinforce` (no new record versions, ADR-0007
  exempt).
- `MemoryStore.list_records(..., agent_id=None)` — tenant-wide listing (not
  scoped to a single agent), needed so the sweep can see every ACTIVE record
  for a tenant.
- Both implemented in `InMemoryMemoryStore` and `SqlMemoryStore`; the shared
  contract kit (`memcore.testing.contracts`) covers both, including tenant
  isolation.

**`RetentionSettings`** (`config.py`, on `Settings.retention`)
- `prune_threshold=0.05`, `min_age_days=14.0`, `scan_limit=10_000` — all
  config, no code change to retune the policy.

**`services/decay.py`** — `DecayService`
- `sweep(tenant_id)`: scores every ACTIVE record with
  `services/importance.py`'s `decay_score` (imported, never re-derived),
  snapshots all scores via `set_decay`, then prunes records that fail every
  rail — `score < prune_threshold` AND not `pinned` AND
  `age ≥ min_age_days`.
- Pruning goes through `MemoryService.forget(mode="soft", reason=...)`: one
  DELETE audit per pruned record plus one `AuditAction.PRUNE` summary event
  per sweep (`actor="decay"`), reporting scanned/snapshotted/pruned/pinned
  counts.
- Returns a `DecayReport` (scanned, snapshotted, pruned, skipped_pinned).
- Idempotent: soft-deleted records are no longer ACTIVE, so an immediate
  re-sweep prunes nothing further.

**`AuditAction.PRUNE`** (`domain/enums.py`) — new audit action for the
per-sweep summary event.

**`MemoryService.forget`** (`services/memories.py`) — gained a `reason`
kwarg, threaded into the DELETE audit event.

**Async job + API**
- Celery task `memcore.decay_tenant` (`workers/celery_app.py`), registered
  the same way as consolidation's job.
- `POST /v1/decay` (202 + job handle) — enqueues the sweep via the workflow
  engine (immediate engine in tests, Celery in production).

**API: `confidence` exposure** — `remember`/`correct` request schemas now
accept `confidence`, closing the Phase 6 backlog item (previously settable
only by consolidation, not the public API).

**Tests** (`tests/services/test_decay.py` and contract-kit additions)
- Snapshot correctness (`set_decay` persists scores per record).
- Prune + audit: DELETE + PRUNE events emitted, reasons include the score.
- Pinned exemption: pinned records are never pruned regardless of score.
- `min_age_days` rail: young low-score records survive.
- Idempotency: a second immediate sweep prunes nothing new.
- Tenant isolation: sweep on tenant A never touches tenant B's records.
- `forget(reason=...)` is recorded on the audit event.

## Gate (2026-07-04)
- pytest: **134 passed, 3 integration-skipped** · coverage **94.27%**
- ruff: clean
- mypy (strict, 81 files): clean

## Deferred
- Paged scanning beyond a single `scan_limit` page — v1 accepts that a
  tenant with more ACTIVE records than `scan_limit` may miss its oldest
  records in one sweep; subsequent sweeps converge as pruned records free
  the page (ADR-0016 point 5).
- Tenant enumeration + a Celery-beat recurring schedule — deployment phase;
  MemCore has no tenant-enumeration facility today, so "sweep every tenant
  periodically" cannot be wired up yet.
- Hard-delete retention job (GDPR erasure) — security phase; soft-delete via
  `forget` is the only deletion path in Phase 7.

## Self-review
Verified against the three implementation commits (`75ebb03`, `64a8cef`,
`be01845`): port extensions land with contract-kit coverage in both
adapters; `DecayService.sweep` imports `decay_score`/`PINNED_TAG` from
`services/importance.py` rather than re-deriving the math, matching ADR-0015
point 4 and ADR-0016 point 1; the prune loop requires all three rails
(`score < prune_threshold`, not pinned, `age_days >= min_age_days`) before
calling `forget`; the audit trail is per-record DELETE plus one PRUNE summary
per sweep, actor `"decay"`. No issues found requiring a follow-up commit.
