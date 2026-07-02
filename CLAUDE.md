# MemCore — Claude Code Project Guide

Long-term memory infrastructure for AI agents (working/episodic/semantic) —
FastAPI + Qdrant + Neo4j + Redis + Postgres, hexagonal core. Personal project
of Chinmay; built phase-by-phase (see roadmap in docs map below).

## Phase gate (NEVER skip any item)
1. `./.venv/Scripts/python.exe -m pytest` — all pass, coverage ≥ 85%
2. `./.venv/Scripts/python.exe -m ruff check .` — clean
3. `./.venv/Scripts/python.exe -m mypy` — clean (strict)
4. Docs: `docs/design/phase-XX.md` + CHANGELOG + ADR for any new decision
5. Update `PROJECT_STATE.md` (current phase, gate results, next tasks)
6. Per-phase git commit; then WAIT for user approval before next phase

## Conventions
- Hexagonal: core imports ports only; drivers stay inside `adapters/*`.
- Heavy/optional deps are lazy-imported behind extras; fail with install hint.
- Every port method is tenant-scoped; isolation is asserted by the contract
  kit (`memcore.testing.contracts`) — new adapters must pass it.
- Records are immutable+versioned (supersede, never edit) — ADR-0007.

## Response style (token economy)
- Compact, outcome-first reports: gate results table + what changed + issues
  found/fixed. Do not restate design docs or repeat unchanged plans.

## Delegation
- Master session: design, decisions, reviews, ADRs/docs, state updates.
- `implementer` agent (sonnet): scoped code+test tasks, runs the gate.
- `debugger` agent (sonnet): root-cause work. Opus only when user asks.

## Docs map (read on demand — never inject wholesale)
- ADRs: `docs/adr/` (index in README.md) · Phases: `docs/design/phase-*.md`
- Roadmap: `docs/design/roadmap.md` · Specs/plans: `docs/superpowers/`

@PROJECT_STATE.md
