# Workspace Setup: Token-Optimized Dynamic Context for MemCore

**Date:** 2026-07-02 · **Status:** Approved · **Scope:** Claude Code workspace
configuration only — no changes to MemCore source code.

## Problem

Every session rebuilds project context from scratch by re-reading docs and git
history: slow starts, wasted tokens, and drift risk. All work currently runs in
one master session regardless of task size, and the installed plugins
(superpowers, context7, skill-creator, claude-code-setup) are unused.

## Goals

1. Fresh, curated context auto-injected into every session at ~1–2k tokens.
2. A mechanical refresh loop tied to project progress (no manual memory).
3. Master session reserved for reasoning/decisions; implementation and
   debugging delegated to cheaper Sonnet subagents.
4. Plugins integrated where they serve the existing phase rhythm (hybrid).

## Design

### 1. Context layer

Two files in the repo root:

**`CLAUDE.md`** (~40 lines, static). Contents: two-line project summary; the
phase-gate checklist (tests · ruff · mypy · docs · ADR · PROJECT_STATE.md —
never skip any); exact gate commands with venv paths; response-style rules
(compact, outcome-first reports; no restating design docs); the delegation
policy (below); a docs map pointing at `docs/adr/`, `docs/design/phase-*.md`,
`docs/design/roadmap.md` marked *read on demand — never inject*. Final line:
`@PROJECT_STATE.md` (auto-import).

**`PROJECT_STATE.md`** (~20 lines, live). Contents: current phase + status;
last gate result (test count, coverage, lint/type status); next 3 tasks; open
decisions awaiting the user. **Updating this file is a mandatory phase-gate
step**, same tier as tests. That rule *is* the refresh loop.

### 2. Hooks (project `.claude/settings.json`)

One **SessionStart** hook running a PowerShell one-liner that emits:
- last 3 commits (`git log --oneline -3`),
- dirty-file count (`git status --porcelain | measure`),
- a staleness warning when `PROJECT_STATE.md` is older than the last commit.

Failure mode: hook errors degrade to no injection; never block a session.
Staleness is flagged, never auto-fixed. No Stop/PostToolUse hooks (noise).
Configured via the `update-config` skill.

### 3. Agents (`.claude/agents/`)

| Agent | Model | Role | Constraints |
|---|---|---|---|
| `implementer` | sonnet | One scoped task: code + tests, run full gate, return compact report (files touched, gate output, decisions made) | Follows CLAUDE.md; never edits ADRs/roadmap/PROJECT_STATE.md |
| `debugger` | sonnet | Reproduce → isolate → root-cause → minimal fix → verify; returns root cause + fix | No band-aid fixes; escalates if root cause unclear |
| master (main session) | — | Design, task specs, review of subagent output, ADRs/docs, state updates, user approval gates | Opus escalation only when the user asks |

### 4. Workflow per phase (6–12)

Master designs → `writing-plans` produces task breakdown → `implementer`
executes tasks → master reviews + `verification-before-completion` at the gate
→ `systematic-debugging` via `debugger` when something resists → master writes
docs/ADR/CHANGELOG → **updates PROJECT_STATE.md** → user approval.
`context7` available to subagents for library-docs lookups. `claude-code-setup`
recommender reserved for a later tune-up.

## Deliverables (implementation plan input)

1. `CLAUDE.md` (root) — as specified above.
2. `PROJECT_STATE.md` (root) — seeded with Phase 5 complete / Phase 6 next.
3. `.claude/settings.json` — SessionStart hook (via `update-config` skill).
4. `.claude/agents/implementer.md`, `.claude/agents/debugger.md`.
5. Verification: fresh-session hook check; one small real task dispatched to
   `implementer` before trusting the pattern.

## Acceptance criteria

- New session starts with current phase/state visible without any file reads.
- Stale `PROJECT_STATE.md` produces a visible warning at session start.
- A scoped task dispatched to `implementer` returns passing gate output.
- Injected context stays ≤ ~2k tokens.

## Out of scope

MemCore source changes, Phase 6 feature work, CI changes, additional hooks,
Opus-by-default subagents, automated state-file regeneration.
