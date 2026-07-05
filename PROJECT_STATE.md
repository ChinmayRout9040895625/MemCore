# MemCore — Live Project State

> Updated at every phase gate (mandatory, same tier as tests). If the
> session-start hook says this file is stale, update it before new work.

## Current position
- **Phase 8 (Evaluation framework & baselines): COMPLETE.**
- **Phase 9 (Python SDK): NOT STARTED — awaiting user approval.**
- Phases 1–8 complete and committed (see `git log --oneline`).

## Last gate (Phase 8, 2026-07-05)
- pytest: **159 passed, 3 integration-skipped** · coverage **94.52%**
- ruff: clean · mypy (strict, 90 files): clean
- Baselines (`python -m memcore.evaluation`, synthetic-v1): hybrid beats
  naive-vector on recall@5 (1.000 vs 0.875), MRR (0.771 vs 0.604), nDCG@5
  (0.829 vs 0.670); reinforcement ablation 6/6 wins under hybrid, 6/6 ties
  under no-importance; longitudinal sweep collapses recall@5 to 0.000 at
  ages 90/180 days. Full report in `docs/design/phase-08.md`.

## Workspace (2026-07-02)
- Setup complete: context layer + SessionStart hook + sonnet agents
  (`implementer`, `debugger`). Dispatch test passed (py.typed, gate green).

## Next tasks (Phase 9, once approved)
1. Typed async + sync Python client over the v1 API (sessions, memories,
   recall, decay/jobs endpoints).
2. Retries/backoff for transient failures; pagination helpers for
   list-style endpoints.
3. Packaging extras for the SDK (installable independently of the server
   extras); quickstart docs.
4. Backlog carried over (deployment/security phase): per-tenant sweep
   dedupe + rate limiting; restore endpoint for soft-deleted records.

## Open decisions for the user
- Approve Phase 9 start.
