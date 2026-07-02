# ADR-0014: Consolidation agent design

**Status:** Accepted (2026-07-02)

## Context
Consolidation turns raw conversation into structured memory — the
quality-critical, LLM-dependent heart of MemCore. It must resolve
contradictions without destroying correct facts (Risk R-2), resist prompt
injection from conversation content (R-5), stay idempotent under retries, and
keep LLM cost bounded (R-3).

## Decision

**One LLM call per consolidation, extraction only.** The model (Claude Sonnet
primary, Ollama fallback via `FailoverLLMProvider` — ADR-0009) returns a strict
JSON object: episodic summary, facts as SPO triples with confidence, entities
with aliases, relations, and explicit invalidations. JSON is enforced by
prefilling (`{`) on Anthropic and `format: "json"` on Ollama; output is parsed
tolerantly (outermost object) then schema-validated.

**Operation classification is deterministic, not delegated to the LLM.**
Each fact is vector-matched against existing active semantic memories; SPO
triples stored in record metadata make conflict detection exact:
- same subject+predicate, same object → **NOOP**
- same subject+predicate, different object → contradiction:
  - confidence ≥ `conflict_confidence` (0.7) → **UPDATE** = supersede
    (ADR-0007 — the old version survives as `SUPERSEDED`)
  - below the bar → stored **flagged `needs_review`** with a
    `conflicts_with` pointer; the original is untouched. This is the
    false-overwrite guard: uncertain evidence never destroys knowledge.
- no SPO match, high content similarity (≥ 0.9) → **NOOP** (dedup)
- otherwise → **ADD** (importance seeded from confidence)
- invalidations soft-delete their best match only when vector *and* lexical
  signals agree (**DELETE**).

**Prompt-injection hardening.** The transcript is wrapped in
`<conversation>` tags and the system prompt declares it DATA; the extractor has
no tools and its output is schema-validated — a hostile transcript can at worst
pollute its own agent's memories, never execute anything.

**Idempotency by watermark.** Only turns newer than the session's
`consolidation_watermark` are processed; the watermark advances transactionally
with the run. Re-enqueue/retry of the same session is a cheap no-op (no LLM
call).

**All writes flow through `MemoryService`** (versioning/indexing/audit in one
place) plus graph upserts whose relation `provenance` carries the fact-record
ids that Phase 4's graph expansion consumes. Each run emits a CONSOLIDATE audit
event with op counts.

**Execution:** enqueued via the `WorkflowEngine` port on session close or
`POST /v1/consolidate` — `ImmediateWorkflowEngine` inline for local/dev/tests,
`CeleryWorkflowEngine` (`send_task`/`AsyncResult`, broker doubles as result
backend) for production, workers via `memcore.workers.celery_app`.

## Consequences
- Extraction quality is the main LLM-quality surface; the eval suite (Phase 8)
  measures fact-level P/R/F1 and false-overwrite rate per provider.
- Deterministic classification is auditable and cheap, but only as good as the
  extracted SPO normalization — entity canonicalization improvements will
  raise match rates.
- The full transactional outbox (ADR-0005) is still deferred: consolidation
  writes go record-by-record through MemoryService (each write is index-
  consistent); a crash mid-run resumes safely because the watermark only
  advances at the end and re-processing yields NOOPs.
