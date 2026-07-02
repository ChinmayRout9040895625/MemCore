# Workspace Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Token-optimized Claude Code workspace for MemCore: auto-injected live context, a SessionStart git/staleness hook, and Sonnet subagents for implementation/debugging.

**Architecture:** Two root context files (static `CLAUDE.md` importing live `PROJECT_STATE.md`), one PowerShell SessionStart hook in project `.claude/settings.json`, two agent definitions in `.claude/agents/`. No MemCore source changes.

**Tech Stack:** Claude Code project config (CLAUDE.md, hooks, agents), PowerShell 5.1, git.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-02-workspace-setup-design.md` (approved).
- Injected context (CLAUDE.md + PROJECT_STATE.md combined) must stay ≤ ~2k tokens (~8 KB).
- Hook must never block a session: `$ErrorActionPreference='SilentlyContinue'`, always exit 0.
- Agents: model `sonnet` for both; implementer never edits ADRs/roadmap/PROJECT_STATE.md.
- Working directory: `c:\Users\chinm\Downloads\MemCore`. Windows paths; PowerShell 5.1 syntax (no `&&`).
- All gate commands use the project venv: `./.venv/Scripts/python.exe`.

---

### Task 1: Context layer — PROJECT_STATE.md + CLAUDE.md

**Files:**
- Create: `PROJECT_STATE.md`
- Create: `CLAUDE.md`

**Interfaces:**
- Produces: `PROJECT_STATE.md` at repo root (Task 2's hook stats this exact path; CLAUDE.md imports it via `@PROJECT_STATE.md`).

- [ ] **Step 1: Create `PROJECT_STATE.md`** with exactly this content:

```markdown
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
```

- [ ] **Step 2: Create `CLAUDE.md`** with exactly this content:

```markdown
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
```

- [ ] **Step 3: Verify size budget**

Run: `powershell -NoProfile -Command "(Get-Item CLAUDE.md).Length + (Get-Item PROJECT_STATE.md).Length"`
Expected: a number **< 8192** (bytes ≈ well under 2k tokens).

- [ ] **Step 4: Commit**

```
git add CLAUDE.md PROJECT_STATE.md
git commit -m "chore: workspace context layer (CLAUDE.md + live PROJECT_STATE.md)"
```

---

### Task 2: SessionStart hook

**Files:**
- Create: `.claude/hooks/session-start.ps1`
- Create: `.claude/settings.json`

**Interfaces:**
- Consumes: `PROJECT_STATE.md` at repo root (Task 1).
- Produces: hook stdout injected as session context by Claude Code.

- [ ] **Step 1: Create `.claude/hooks/session-start.ps1`** with exactly this content:

```powershell
# SessionStart hook: inject git snapshot + PROJECT_STATE.md staleness check.
# Must never block a session: swallow all errors, always exit 0.
$ErrorActionPreference = 'SilentlyContinue'

Write-Output '=== MemCore session snapshot ==='
git log --oneline -3
$dirty = (git status --porcelain | Measure-Object -Line).Lines
Write-Output "dirty files: $dirty"

$state = Get-Item 'PROJECT_STATE.md'
$lastCommitIso = git log -1 --format=%cI
if ($state -and $lastCommitIso) {
    $lastCommit = [datetime]::Parse($lastCommitIso)
    if ($state.LastWriteTime -lt $lastCommit) {
        Write-Output 'WARNING: PROJECT_STATE.md is STALE (older than last commit). Update it before new work.'
    } else {
        Write-Output 'PROJECT_STATE.md: fresh'
    }
}
exit 0
```

- [ ] **Step 2: Create `.claude/settings.json`** with exactly this content:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "powershell -NoProfile -ExecutionPolicy Bypass -File .claude/hooks/session-start.ps1"
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 3: Test the script — fresh case**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File .claude/hooks/session-start.ps1`
Expected output: 3 commit lines, `dirty files: N`, and `PROJECT_STATE.md: fresh`
(PROJECT_STATE.md was written after the last commit... if Task 1 was committed
last, the file mtime equals commit time — if it prints STALE here, `touch` it:
`powershell -NoProfile -Command "(Get-Item PROJECT_STATE.md).LastWriteTime = Get-Date"` and re-run).

- [ ] **Step 4: Test the script — stale case**

Run:
```
powershell -NoProfile -Command "(Get-Item PROJECT_STATE.md).LastWriteTime = (Get-Date).AddDays(-2)"
powershell -NoProfile -ExecutionPolicy Bypass -File .claude/hooks/session-start.ps1
```
Expected output: contains `WARNING: PROJECT_STATE.md is STALE`.
Then restore: `powershell -NoProfile -Command "(Get-Item PROJECT_STATE.md).LastWriteTime = Get-Date"`

- [ ] **Step 5: Test the never-block guarantee**

Run from a directory without the file (simulates odd cwd):
`powershell -NoProfile -Command "cd $env:TEMP; powershell -NoProfile -ExecutionPolicy Bypass -File c:\Users\chinm\Downloads\MemCore\.claude\hooks\session-start.ps1; Write-Output ('exit=' + $LASTEXITCODE)"`
Expected: `exit=0` (no thrown errors).

- [ ] **Step 6: Commit**

```
git add .claude/hooks/session-start.ps1 .claude/settings.json
git commit -m "chore: SessionStart hook (git snapshot + state staleness check)"
```

---

### Task 3: Subagent definitions

**Files:**
- Create: `.claude/agents/implementer.md`
- Create: `.claude/agents/debugger.md`

**Interfaces:**
- Produces: agents `implementer` and `debugger`, invokable from the master
  session via the Agent tool (`subagent_type: "implementer"` / `"debugger"`).

- [ ] **Step 1: Create `.claude/agents/implementer.md`** with exactly this content:

```markdown
---
name: implementer
description: Implements one scoped MemCore task (code + tests), runs the full quality gate, and returns a compact report. Use for phase implementation tasks delegated from the master session.
model: sonnet
---

You implement exactly one scoped task for MemCore. Read CLAUDE.md first and
follow every convention in it (hexagonal boundaries, tenant scoping,
immutable+versioned records, lazy optional imports).

Process:
1. Read the task spec you were given plus only the files it names.
2. Write tests first when adding behavior; then the minimal implementation.
3. Run the full gate:
   - ./.venv/Scripts/python.exe -m pytest
   - ./.venv/Scripts/python.exe -m ruff check .
   - ./.venv/Scripts/python.exe -m mypy
4. Fix what the gate finds. Do not weaken configs to pass (no coverage
   omissions, no ignore-comments) unless the task spec says so.

Hard limits:
- Never edit: docs/adr/*, docs/design/roadmap.md, PROJECT_STATE.md,
  CHANGELOG.md (the master session owns those).
- Never commit. Leave changes in the working tree for master review.
- Stay inside the task scope; if the spec is ambiguous or requires touching
  out-of-scope files, STOP and report the question instead of guessing.

Report back (compact, outcome-first): what changed (files + one line each),
gate results (pass counts, coverage), decisions you had to make, open
questions. Do not paste whole diffs.
```

- [ ] **Step 2: Create `.claude/agents/debugger.md`** with exactly this content:

```markdown
---
name: debugger
description: Systematic root-cause debugging for MemCore failures (test failures, unexpected behavior, flaky gates). Returns root cause and a minimal verified fix.
model: sonnet
---

You debug exactly one reported failure in MemCore. Read CLAUDE.md first.

Protocol (in order, no shortcuts):
1. Reproduce: run the failing command yourself; capture exact output.
2. Isolate: minimize to the smallest failing case (single test, single input).
3. Root-cause: read the implicated code; state the mechanism of failure in
   one paragraph. No fix until the mechanism is understood.
4. Fix minimally: the smallest change that removes the root cause. No
   band-aids (no sleeps, no broad try/except, no test deletion/skipping).
5. Verify: re-run the failing command AND the full gate:
   ./.venv/Scripts/python.exe -m pytest && ruff check . && mypy (venv paths).

Hard limits:
- Never edit docs/adr/*, roadmap, PROJECT_STATE.md, CHANGELOG.md.
- Never commit.
- If the root cause is architectural (port contract wrong, design flaw),
  STOP after step 3 and report; the master session decides.

Report back: root cause (the mechanism), the fix (files + why it is
minimal), verification output summary, and any adjacent risks you noticed.
```

- [ ] **Step 3: Verify frontmatter parses**

Run: `powershell -NoProfile -Command "Get-Content .claude/agents/implementer.md -TotalCount 6; Get-Content .claude/agents/debugger.md -TotalCount 6"`
Expected: both start with `---`, contain `name:`, `description:`, `model: sonnet`.

- [ ] **Step 4: Commit**

```
git add .claude/agents/implementer.md .claude/agents/debugger.md
git commit -m "chore: sonnet subagents (implementer, debugger)"
```

---

### Task 4: End-to-end verification

**Files:**
- Create: `src/memcore/py.typed` (the dispatch test task — a real, useful chore)
- Modify: `pyproject.toml` (hatch include for py.typed if needed)

**Interfaces:**
- Consumes: `implementer` agent from Task 3.

- [ ] **Step 1: Dispatch a small real task to the `implementer` agent**

Agent prompt (verbatim):
```
Task: mark the memcore package as typed (PEP 561).
1. Create empty file src/memcore/py.typed.
2. Verify pyproject.toml wheel build includes it (hatchling packages
   src/memcore — package-data inclusion; add
   [tool.hatch.build.targets.wheel] force-include or confirm default
   includes non-Python files; adjust only if needed).
3. Run the full gate (pytest / ruff / mypy with ./.venv/Scripts/python.exe).
Report gate output. Do not commit.
```
Expected report: file created, gate all green (≥105 passed), no scope creep.

- [ ] **Step 2: Master review of the agent's diff**

Run: `git status --short` and `git diff`
Expected: only `src/memcore/py.typed` (+ optional minimal pyproject change).

- [ ] **Step 3: Commit the verified work**

```
git add -A
git commit -m "chore: PEP 561 py.typed marker (implementer-agent dispatch test)"
```

- [ ] **Step 4: Fresh-session hook check (user-assisted)**

Ask the user to open a new Claude Code session in this project and confirm the
session starts with `=== MemCore session snapshot ===`, 3 commits, dirty count,
and a freshness line. If the hook did not fire, check `.claude/settings.json`
placement (project root) and re-test the script from Task 2 Step 3.

- [ ] **Step 5: Update PROJECT_STATE.md and commit**

Append gate result under "Last gate" section noting workspace setup complete;
commit:
```
git add PROJECT_STATE.md
git commit -m "chore: state — workspace setup verified"
```
