# ADR-0007: Memory records are immutable + versioned

**Status:** Accepted (2026-07-01)

## Context
Consolidation may refine or contradict existing memories. Editing in place would
destroy provenance and make bad consolidations irreversible — directly feeding
the false-overwrite risk (R-2).

## Decision
Records are immutable. An UPDATE creates a **new version** (`version + 1`,
`supersedes` = prior id) and marks the prior version `SUPERSEDED`; a DELETE marks
`SOFT_DELETED`. Nothing is destroyed until a retention/GDPR job performs a
`HARD_DELETE`. The domain model enforces this via `MemoryRecord.superseded_by()`,
which is purely functional (no mutation).

## Consequences
- Full audit trail, time-travel, and safe rollback of erroneous consolidations.
- Storage growth from versions — mitigated by decay + compaction of superseded
  versions past retention.
- Ambiguous conflicts are flagged `needs_review` rather than silently
  overwriting (controls the false-overwrite metric).
