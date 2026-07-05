# ADR-0018: Python SDK — async+sync typed clients, GET-only retries, sdk extra

**Status:** Accepted (2026-07-05)

## Context
Consuming MemCore required hand-rolled HTTP calls: callers had to know the
wire shapes, build their own retry/backoff logic, poll job endpoints by hand,
and pattern-match RFC-7807 error bodies themselves. There was no typed error
hierarchy, no retry discipline, and no job-polling ergonomics — every
consumer (including our own future examples/tests) would otherwise
reimplement the same fragile plumbing.

## Decision

1. **The SDK ships inside the `memcore` package as `memcore.sdk`**, a
   consumer layer importing only `memcore.domain` + `httpx` — installable
   server-free via the new `sdk` extra (`pip install 'memcore[sdk]'` pulls
   pydantic, pydantic-settings + httpx only, no server/storage dependencies).
   `httpx` is lazy-imported with the standard install hint, consistent with
   every other optional-dependency adapter in the codebase.

2. **Async-first `AsyncMemCoreClient`** covers the full v1 surface (sessions,
   memories, recall, consolidate/jobs, decay) with a mechanically mirrored
   sync `MemCoreClient` — drift between the two is prevented by a
   signature-parity test rather than code generation. Shared pure logic
   (retry policy, backoff computation, RFC-7807 error mapping) lives once in
   `_shared.py`, imported by both clients so there is exactly one tested
   implementation of the transport-agnostic behavior.

3. **Retries are GET-only** on `{429, 502, 503, 504}` or transport failure,
   with deterministic exponential backoff (no jitter, for reproducible
   tests) and an injectable sleep function. Non-idempotent POSTs/PATCHes/
   DELETEs are never replayed after an ambiguous failure — a retried write
   could otherwise duplicate a side effect the server already applied.

4. **Responses validate into the existing domain models** (`Session`,
   `MemoryRecord`, `ScoredMemory`) plus two thin SDK-side models (`Job`,
   `RecallOutcome`) — the SDK inherits the server's schema evolution instead
   of duplicating model definitions that could drift from the API.

5. **`wait_for_job` polls with a bounded timeout**, raising `JobTimeout` if
   the job hasn't reached a terminal state (`succeeded`/`failed`) in time.

6. **Pagination helpers are deferred**: the v1 API has no list-style
   endpoints yet (sessions/memories are fetched by id, not listed) — revisit
   when one lands.

## Consequences
- One wire contract, typed end to end: SDK tests double as API contract
  tests, since they run against the real ASGI app in-process (no real
  network, no separate mock server to drift from the actual routes).
- The sync mirror costs mechanical duplication (`client.py` largely restates
  `async_client.py` with blocking calls) — paid deliberately for zero
  event-loop entanglement in sync callers, guarded by the parity test so the
  two surfaces cannot silently diverge.
- Typed errors (`AuthError`, `NotFoundError`, `ConflictError`,
  `ValidationAPIError`, `ServerError`, all `APIError` subclasses, plus
  `TransportError` and `JobTimeout`) let callers branch on failure kind
  without parsing problem+json themselves.
- **Soft-delete visibility note:** per the Task-2 review finding, a
  soft-deleted record remains GET-visible by design (only a hard delete
  404s) — `get_memory`/`memory_versions` on the SDK will happily return a
  soft-deleted record's data. This is server behavior the SDK faithfully
  surfaces, not an SDK bug; it contextualizes the restore-endpoint backlog
  item (Phase 7 final review, carried forward again here) — until a restore
  endpoint exists, "soft-deleted but still readable" is the only way to
  recover a mistaken delete.
- No pagination helpers yet, since v1 has nothing to paginate; adding them
  once a list-style endpoint ships is additive and does not require
  revisiting this ADR's decisions.
- SDK response models validate with `extra="forbid"`, so an additive server
  field breaks older SDK versions until they upgrade — acceptable while the
  SDK ships in lockstep with the server; revisit (switch to `extra="ignore"`)
  once they version and release separately.
