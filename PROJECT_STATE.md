# MemCore — Live Project State

> Updated at every phase gate (mandatory, same tier as tests). If the
> session-start hook says this file is stale, update it before new work.

## Current position
- **Phase 6 (Importance scoring): COMPLETE.**
- **Phase 7 (Memory decay & pruning): NOT STARTED — awaiting user approval.**
- Phases 1–6 complete and committed (see `git log --oneline`).

## Last gate (Phase 6, 2026-07-04, incl. final-review fix commit)
- pytest: **125 passed, 3 integration-skipped** · coverage **94.72%**
- ruff: clean · mypy (strict, 79 files): clean

## Workspace (2026-07-02)
- Setup complete: context layer + SessionStart hook + sonnet agents
  (`implementer`, `debugger`). Dispatch test passed (py.typed, gate green).

## Next tasks (Phase 7, once approved)
1. Decay job that snapshots `decay_score` (from `services/importance.py`,
   unchanged) into storage on a schedule.
2. Prune policy: threshold/age-based deletion (or archival) of decayed,
   non-pinned records, with audit trail.
3. Retention configuration + tests (decay job idempotency, prune safety
   rails, pinned-record exemption end-to-end).
4. Backlog: expose `confidence` on the API remember/correct schemas
   (currently settable only by consolidation).

## Open decisions for the user
- Approve Phase 7 start.
