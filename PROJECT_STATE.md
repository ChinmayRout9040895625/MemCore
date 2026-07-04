# MemCore — Live Project State

> Updated at every phase gate (mandatory, same tier as tests). If the
> session-start hook says this file is stale, update it before new work.

## Current position
- **Phase 7 (Memory decay & pruning): COMPLETE.**
- **Phase 8 (Evaluation framework & baselines): NOT STARTED — awaiting user approval.**
- Phases 1–7 complete and committed (see `git log --oneline`).

## Last gate (Phase 7, 2026-07-04, incl. final-review fix commit)
- pytest: **136 passed, 3 integration-skipped** · coverage **94.28%**
- ruff: clean · mypy (strict, 81 files): clean

## Workspace (2026-07-02)
- Setup complete: context layer + SessionStart hook + sonnet agents
  (`implementer`, `debugger`). Dispatch test passed (py.typed, gate green).

## Next tasks (Phase 8, once approved)
1. Evaluation harness: retrieval-quality baselines vs. naive vector search.
2. Decay/importance ablations (compare ranking with/without reinforcement
   and decay snapshots from Phases 6–7).
3. Longitudinal memory-quality metrics (tracking recall quality over
   simulated time/usage).
4. Backlog (from Phase 7 final review): per-tenant sweep dedupe + rate
   limiting; restore endpoint for soft-deleted records.

## Open decisions for the user
- Approve Phase 8 start.
