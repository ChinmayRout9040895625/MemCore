# ADR-0017: Evaluation framework — deterministic offline harness, baseline + ablations

**Status:** Accepted (2026-07-05)

## Context
Phases 4–7 shipped ranking behaviors — hybrid scoring (ADR-0013), reinforcement
and decay (ADR-0015), sweep/prune (ADR-0016) — each covered by unit tests, but
nothing measured retrieval quality as a system or compared it against a
baseline. A regression that made ranking worse overall (e.g. a bad exponent
default, a sign error in decay) could pass every unit test and still ship.

## Decision

1. **`memcore.evaluation` is a consumer/composition layer**, like
   `memcore.api`: it is allowed to build in-memory adapters directly.
   Nothing in `services`/`domain`/`ports`/`adapters` may import it.

2. **Evaluation is deterministic and offline** — a hand-written token-overlap
   dataset (`synthetic-v1`, 12 records / 8 cases) with no LLM, no network, no
   randomness. Ages are simulated by backdating `created_at`, not by waiting.

3. **Binary-relevance metrics** — `recall@k`, `MRR`, `nDCG@k`
   (`evaluation/metrics.py`) — pure functions, each id's gain counted once
   (ADR-0017 review fix, commit `497df6e`: duplicate ids in `ranked` no
   longer double-count, keeping nDCG bounded in [0, 1] even for degenerate
   inputs).

4. **Each configuration runs on a freshly rebuilt and re-seeded stack**
   (`EvalHarness._reset`/`seed`): recall's write-back reinforcement is part
   of the system under test, so results reflect it *within* a configuration,
   but it must never leak *between* configurations. Within a configuration,
   cases run in fixed dataset order — reproducible by construction, no
   seeding of a PRNG required because there is none.

5. **Standard configs** (`STANDARD_CONFIGS`, `evaluation/harness.py`):
   `naive-vector` (recency/importance weights zeroed, `lexical_alpha=0` —
   pure vector relevance) as the baseline; `hybrid` (full defaults);
   `no-importance` and `no-recency` ablations (one weight zeroed each).

6. **Two scenario runners double as regression guards**
   (`evaluation/scenarios.py`):
   - *Reinforcement ablation* — identical content twins, one reinforced 10x;
     asserts the reinforced twin outranks its cold twin under `hybrid` and
     ties under `no-importance` (importance weight zeroed removes the
     reinforcement signal's effect on final score).
   - *Longitudinal curve* — recall@5 at target ages `[0, 7, 30, 90, 180]`
     days, with and without a decay sweep, demonstrating Phase 6/7 fading and
     eventual pruning end to end.

7. **`python -m memcore.evaluation`** (`evaluation/__main__.py`) prints the
   reproducible baseline report — standard-config table, ablation outcome,
   longitudinal curve — recorded verbatim in `docs/design/phase-08.md`.

## Consequences
- Ranking changes now have a measurable, versioned quality baseline instead
  of unit-test-only coverage; a future ranking regression that unit tests
  miss should show up as a baseline-number regression in the phase-08
  report.
- The synthetic dataset is embedder-honest (token overlap engineered so the
  deterministic hashing embedder and real embedding models both see
  distinctive shared tokens between query and target) but small — 12
  records, 8 cases. Real-corpus datasets and LLM-judged relevance are future
  work (Phase 12 examples / post-v1), not required to ship Phase 8.
- Per-config fresh-stack isolation costs one full stack rebuild per config
  per run (cheap: in-memory adapters, sub-second) in exchange for
  eliminating cross-config state leakage as a source of flaky or
  order-dependent results.
- Scenario runners make Phase 6 (reinforcement) and Phase 7 (decay/prune)
  behaviors regression-visible end to end, beyond their existing unit tests.
- No pgvector/Qdrant-backed evaluation run yet — the harness is in-memory
  only; a live-backend eval run is deferred (see phase-08.md).
