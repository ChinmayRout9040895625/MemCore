# ADR-0015: Importance scoring — write-time base, read-time reinforcement/decay

**Status:** Accepted (2026-07-04)

## Context
Ranking (ADR-0013) treated `importance` as a static write-time value with no
feedback loop, and Phase 5 consolidation stuffed extraction *confidence* into
that same field — conflating "how sure the extractor was" with "how much this
fact matters long-term." Neither usage (retrieval strengthens memory) nor time
(unused memories should fade) was modeled.

## Decision

1. **Base importance is write-time, LLM-assessed per fact.** The consolidation
   extraction prompt scores each candidate fact's `importance` (0.0–1.0,
   independent of extraction confidence). When the LLM omits it: an ADD or
   needs_review write defaults to 0.5; a contradiction UPDATE instead preserves
   the superseded record's prior base importance (`correct(importance=None)`
   means "don't change this field" — a lower-fidelity extraction must not
   flatten an already-assessed base). Confidence is stored separately on
   `MemoryRecord.confidence` instead of overloading `importance`.

2. **Usage reinforcement and time decay are pure read-time functions** over
   raw stored signals (`access_count`, `last_accessed_at`, `created_at`,
   `tags`), implemented once in `services/importance.py`:
   - `reinforcement = n/(n+s)` — Michaelis-Menten saturating curve in `access_count`
     (`n`), never rewriting the stored base.
   - `effective_importance = base + max_boost · reinforcement · (1 − base)` —
     bounded boost toward 1.0, capped at 1.0; base importance always keeps
     mattering.
   - `decay_score = exp(−age/τ)` — exponential decay in time since last touch
     (`last_accessed_at`, falling back to `created_at`).

3. **`pinned` tag exempts a record from decay** (`decay_score` short-circuits
   to 1.0), giving callers an escape hatch for memories that must never fade.

4. **Nothing derived is persisted in Phase 6.** `effective_importance` is
   computed on the recall hot path; `decay_score` is exposed but unused until
   Phase 7's prune job snapshots it into storage using these same functions —
   the math lives in exactly one place across both phases.

## Consequences
- Ranking closes the retrieval-strengthens-memory loop with bounded,
  monotonic boosts: a recalled memory's `effective_importance` — and thus its
  rank — rises for the next recall, but never past 1.0 and never in a way
  that outruns base importance's influence.
- Stored records stay raw and replayable: `access_count`/`last_accessed_at`
  are facts, not pre-baked scores, so tuning the curve constants
  (`ImportanceSettings`) is a config change, not a migration or backfill.
- Recomputation cost is O(candidates) arithmetic on the hot path — negligible
  next to the vector/graph lookups it rides alongside.
- Phase 7 must reuse `services/importance.py` verbatim for its snapshot job;
  duplicating the formulas there would fork the single source of truth this
  ADR establishes.
