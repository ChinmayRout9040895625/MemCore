# ADR-0004: Scheduler = Celery (default), Temporal (future)

**Status:** Accepted (2026-07-01)

## Context
Consolidation and decay run as asynchronous, retriable background jobs off the
hot read path. Temporal offers durable execution and rich visibility that suit
multi-step consolidation workflows, but adds significant operational weight
(server, workers, DB). The approved default stack prioritizes an operable,
low-dependency footprint (Qdrant + Celery + Redis).

## Decision
Use **Celery** (broker: Redis) as the default `WorkflowEngine` adapter.
**Temporal** remains an approved *future* backend and MUST slot in behind the
`memcore.ports.workflow_engine.WorkflowEngine` interface without any change to
pipeline logic. Pipeline steps are therefore written against the port, never
against Celery primitives directly.

## Consequences
- Lower operational burden for self-host and early deployments.
- We forego Temporal's built-in durability/visibility for now; consolidation
  must implement its own idempotency (watermark + at-least-once) — already
  required by ADR-0005's outbox pattern, so no new cost.
- The port's surface is deliberately minimal (`enqueue` + `status`) to keep the
  future Temporal swap cheap.
