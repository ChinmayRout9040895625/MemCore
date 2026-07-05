# Phase 8 — Evaluation framework & baselines

## Objective
Give MemCore a measurable, versioned retrieval-quality baseline: a
deterministic offline harness that compares scoring configurations against a
naive-vector baseline, regression-guards the Phase 6/7 ranking behaviors
(reinforcement, decay/pruning) end to end, and closes the Phase 7 backlog
items that block decay from converging. Design in ADR-0017 (evaluation) and
ADR-0016 (amended, decay backlog).

## Delivered

**Phase 7 backlog hardening** (`ports/memory_store.py`, both adapters,
`services/decay.py`; ADR-0016 amended)
- `MemoryStore.list_records` gained `oldest_first` (plus the prior review fix:
  a deterministic `id` tiebreaker for equal-timestamp records) — the decay
  sweep now scans oldest-first, so the scanned page always contains the
  tenant's most-decayed records. Tenants above `scan_limit` converge across
  repeated sweeps instead of never seeing their oldest records; this resolves
  the non-convergence limitation called out in phase-07.md's Deferred section.
- `MemoryStore.set_decay` clamps scores to `[0, 1]` at the adapter layer,
  guarding against out-of-range input reaching storage.

**`evaluation/metrics.py`** — pure binary-relevance metric primitives:
`recall_at_k`, `mrr`, `ndcg_at_k`. `ndcg_at_k` counts each id's gain once
(review fix, commit `497df6e`), keeping the score bounded under duplicate ids
in the ranked list.

**`evaluation/datasets.py`** — `synthetic_dataset()` builds `synthetic-v1`: 12
hand-written records and 8 query cases, token-overlap engineered so each
query shares distinctive tokens with its target and only generic tokens with
distractors (4 pure distractors, no matching case).

**`evaluation/harness.py`** — `EvalHarness` owns one in-memory stack
(`InMemoryMemoryStore` + `InMemoryVectorStore` + `HashingEmbeddingProvider`),
fully rebuilt on every `seed()` call so reinforcement write-back from one
configuration's recall calls never leaks into another. `EvalConfig` carries
per-config `ScoreWeights` and an optional `lexical_alpha` override.
`STANDARD_CONFIGS`: `naive-vector` (recency/importance weights zero,
`lexical_alpha=0` — pure vector relevance, the baseline), `hybrid` (full
defaults), `no-importance`, `no-recency` (one weight zeroed each).
`run_config`/`run` seed, recall every case, and average recall@5/MRR/nDCG@5.

**`evaluation/scenarios.py`** — two scenario runners:
- `reinforcement_ablation`: identical content twins, one reinforced 10x per
  pair; compares final ranking under `hybrid` vs. `no-importance`.
- `longitudinal_curve`: recall@5 at target ages `[0, 7, 30, 90, 180]` days,
  optionally running a `DecayService.sweep` first, showing the recall curve
  with and without pruning taking effect.

**`evaluation/__main__.py`** — `python -m memcore.evaluation` prints the
combined baseline report (see below), reproducible by construction.

**Tests** (`tests/unit/test_eval_harness.py` and existing metric/scenario
tests)
- Metric primitives: recall@k, MRR, nDCG@k correctness including the
  duplicate-id bound.
- Harness: per-config stack isolation (no cross-config leakage), standard
  configs produce distinct results (`naive-vector` worse than `hybrid`).
- Scenario correctness: reinforcement ablation wins under `hybrid`, ties
  under `no-importance`; longitudinal curve shows fading with age and
  collapse to zero after a sweep past the prune horizon.
- Decay: `list_records(oldest_first=True)` ordering; `set_decay` clamp to
  `[0, 1]`.

## Baselines (2026-07-05, `python -m memcore.evaluation`)

```
MemCore evaluation — synthetic-v1 (deterministic, in-memory)

config           recall@5     mrr  ndcg@5
naive-vector        0.875   0.604   0.670
hybrid              1.000   0.771   0.829
no-importance       1.000   0.792   0.845
no-recency          1.000   0.771   0.829

reinforcement ablation (identical twins, one reinforced x10):
  hybrid          wins=6 ties=0 losses=0 of 6
  no-importance   wins=0 ties=6 losses=0 of 6

longitudinal recall@5 by target age (hybrid config):
 age_days  no sweep  after sweep
        0     1.000        1.000
        7     1.000        1.000
       30     1.000        1.000
       90     0.875        0.000
      180     0.875        0.000
```

Reading the numbers: `hybrid` beats the `naive-vector` baseline on all three
metrics on this dataset (recall@5 0.875 → 1.000; MRR 0.604 → 0.771; nDCG@5
0.670 → 0.829). The reinforcement ablation confirms recall's write-back
signal changes ranking only when importance weight is nonzero (6/6 wins under
`hybrid`, 6/6 ties under `no-importance`). The longitudinal curve shows
recall@5 unaffected by age alone through 30 days, a natural dip at 90/180
days from decayed-but-unswept records, and a hard collapse to 0.000 once a
sweep prunes records that fail every ADR-0016 rail past the ~90-day horizon —
this is the decay/pruning contract working as designed, not a defect.

## Gate (2026-07-05, incl. review-polish commit)
- pytest: **161 passed, 3 integration-skipped** · coverage **94.52%**
- ruff: clean
- mypy (strict, 90 files): clean

## Deferred
- Real-corpus and LLM-judged relevance datasets — `synthetic-v1` is small
  (12 records / 8 cases) and hand-engineered; broader coverage is future
  work (Phase 12 examples / post-v1).
- Per-tenant sweep dedupe + rate limiting, and a restore endpoint for
  soft-deleted records — carried over from the Phase 7 final review,
  deployment/security phase.
- pgvector/Qdrant-backed evaluation runs — the harness is in-memory only
  today; a live-backend run (real embeddings, real vector index) is not yet
  wired up.

## Self-review
Verified against the implementation commits (`707d289`, `2cfd7a3`, `02f74ff`,
`497df6e`, `3d549f9`, `b3a4993`): `list_records` gained a deterministic id
tiebreaker and then `oldest_first`, and the decay sweep now scans
oldest-first per ADR-0016's amendment; `set_decay` clamps to `[0, 1]` at the
adapter layer; `evaluation/metrics.py`'s `ndcg_at_k` counts each id once,
fixed post-review; the harness rebuilds its stack on every `seed()` call so
no configuration's reinforcement write-back leaks into another; standard
configs and both scenario runners match the numbers pasted above verbatim
from `python -m memcore.evaluation`. No issues found requiring a follow-up
commit.
