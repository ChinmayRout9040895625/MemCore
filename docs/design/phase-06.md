# Phase 6 — Importance scoring

## Objective
Close the retrieval-strengthens-memory loop: make importance a living signal
instead of a static write-time number, without giving up replayability of the
stored records. Design in ADR-0015.

## Delivered

**`ImportanceSettings`** (`config.py`, on `Settings.importance`)
- `reinforcement_saturation=5.0`, `reinforcement_max_boost=0.3`,
  `decay_tau_days=30.0` — all config, no code change to retune the curves.

**`services/importance.py`** — three pure functions + `PINNED_TAG`
- `reinforcement(access_count, *, saturation)` — `n/(n+s)` saturating curve.
- `effective_importance(record, *, settings)` — `base + max_boost · reinforcement · (1 − base)`,
  capped at 1.0.
- `decay_score(record, now, *, settings)` — `exp(−age/τ)` from
  `last_accessed_at` (falling back to `created_at`); `pinned` tag exempt
  (returns 1.0).

**Consolidation** (`services/consolidation.py`)
- Extraction prompt scores per-fact `importance` (0.0–1.0, independent of
  extraction confidence; defaults to 0.5 when the LLM omits it).
- Fact `confidence` now stored on `MemoryRecord.confidence` instead of
  overloading `importance`.
- `MemoryService.remember`/`correct` gained `confidence` kwargs
  (`services/memories.py`).

**Recall** (`services/recall.py`, `api/app.py`)
- Ranking's importance factor is now `effective_importance` (usage-reinforced),
  not the raw stored base.
- `RecallService` gained a constructor kwarg `importance_settings`, wired from
  `Settings.importance` in `build_state` (`api/app.py`).

**Tests**
- `services/importance.py`: reinforcement curve, effective-importance
  bounding/capping, decay exponential falloff, pinned exemption.
- Consolidation: extracted fact importance flows to the stored record;
  confidence stored separately from importance.
- Recall: three calibration tests — reinforced importance raises rank vs.
  unreinforced base; boost stays bounded by `reinforcement_max_boost`; base
  importance still discriminates between records at equal access count.

## Gate (2026-07-04)
- pytest: **124 passed, 3 integration-skipped** · coverage **94.80%**
- ruff: clean
- mypy (strict, 79 files): clean

## Deferred
- Persisting `decay_score` and running a prune policy — Phase 7. That job
  reuses `services/importance.py`'s functions unchanged (ADR-0015 point 4);
  no new math, only a snapshot + retention policy on top.
- Episodic→semantic abstraction (many events → one generalization) — backlog,
  carried over from Phase 5.

## Self-review
Issues found and fixed before sign-off are listed in the delivery message.
