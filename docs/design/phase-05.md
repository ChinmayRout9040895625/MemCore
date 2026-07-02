# Phase 5 — Consolidation Agent

## Objective
The pipeline that makes MemCore cognitive: raw conversation → extracted,
deduplicated, conflict-resolved, graph-linked memory. Design in ADR-0014.

## Delivered

**LLM adapters** (`adapters/llm/`)
- `AnthropicLLMProvider` — Claude Sonnet; system-message mapping, JSON via
  assistant prefill, usage accounting; injectable client.
- `OllamaLLMProvider` — local fallback over plain httpx (`format: "json"`).
- `FailoverLLMProvider` — primary→fallback on `ProviderError` (ADR-0009).
- `ScriptedLLMProvider` (in-memory) for deterministic tests.
- Factory: `build_llm_provider` composes failover from settings (skipping the
  wrapper when fallback is disabled or identical to primary).

**ConsolidationService** (`services/consolidation.py`)
- Gather (post-watermark turns) → extract (one strict-JSON call, transcript as
  untrusted data) → deterministic classify (NOOP / UPDATE-supersede /
  needs_review-flag / ADD; invalidations → soft DELETE with vector+lexical
  agreement) → graph upserts (entity linking incl. aliases; relation provenance
  = fact record ids) → CONSOLIDATE audit + watermark advance.
- `ConsolidationReport` returns op counts + token usage per run.

**Workflow engines**
- `ImmediateWorkflowEngine` (in-memory; inline execution, job table).
- `CeleryWorkflowEngine` (`send_task`/`AsyncResult` in a thread; broker doubles
  as result backend); `memcore.workers.celery_app` worker entrypoint
  (`celery -A memcore.workers.celery_app worker`).
- Factory: `build_workflow_engine` (`celery` default, `inmemory`, `temporal`
  reserved-future per ADR-0004).

**API**
- `POST /v1/sessions/{id}/close` now enqueues consolidation (ADR-0001).
- `POST /v1/consolidate` (tenant-checked) → 202 + job handle;
  `GET /v1/jobs/{id}` → state.

**Supporting changes** — `MemoryService` gains `metadata` on
remember/correct and an `embed` helper; `ConsolidationSettings` +
`llm.ollama_url` config; `llm` extra gains httpx; CI installs `scheduler`.

## Tests (104 passing)
End-to-end ADD (fact + entities + relation provenance → **recallable via graph
expansion**); duplicate fact → NOOP (no second record); confident contradiction
→ supersede with old version preserved; low-confidence contradiction →
`needs_review` flag with `conflicts_with` pointer and original intact;
invalidation → soft delete; watermark idempotency (re-run: zero turns, zero LLM
calls); bad-JSON → `ProviderError`; injection-hardening prompt shape; LLM
adapters via fake clients (payload mapping, JSON modes, usage, error wrapping);
failover both directions; workflow engines (success/failure/unknown, Celery
state mapping, worker task shim); API close-triggers-consolidation and
consolidate/jobs endpoints with cross-tenant rejection.

## Deferred
- Transactional outbox: consolidation currently writes record-by-record through
  MemoryService with watermark-based resume; the outbox lands with the
  Postgres-first deployment hardening (tracked in ADR-0014 consequences).
- Importance scoring beyond confidence-seeding — Phase 6.
- Episodic→semantic abstraction (many events → one generalization) — backlog.

## Self-review
Issues found and fixed before sign-off are listed in the delivery message.
