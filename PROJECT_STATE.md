# MemCore — Live Project State

> Updated at every phase gate (mandatory, same tier as tests). If the
> session-start hook says this file is stale, update it before new work.

## Current position
- **Phase 6 (Importance scoring): NOT STARTED — awaiting user approval.**
- Phases 1–5 complete and committed (see `git log --oneline`).

## Last gate (Phase 5, 2026-07-02)
- pytest: **105 passed, 3 integration-skipped** · coverage **94.6%**
- ruff: clean · mypy (strict, 77 files): clean

## Next 3 tasks (Phase 6, once approved)
1. LLM-assessed importance at consolidation (extend extraction prompt + fact scoring).
2. Usage-based reinforcement curve feeding `importance`/`decay_score`.
3. Pinning (`pinned` tag exempt from decay) + ranking calibration tests.

## Open decisions for the user
- Approve Phase 6 start.
