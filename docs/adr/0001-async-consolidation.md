# ADR-0001: Asynchronous consolidation, not inline

**Status:** Accepted (2026-07-01)

## Context
Consolidation is LLM-heavy and slow. Running it inline on the write path would
blow the ingest latency budget and couple write availability to an external LLM
provider.

## Decision
Ingest appends to the working-memory buffer and returns immediately (p95 < 20ms).
A trigger (session close, buffer threshold, timer, or explicit call) enqueues a
consolidation job processed by a background worker.

## Consequences
- Eventual consistency between "said" and "remembered" (seconds); documented in
  the SDK contract.
- Write availability is decoupled from the LLM provider.
- Requires idempotent, replayable consolidation (see ADR-0005, ADR-0007).
