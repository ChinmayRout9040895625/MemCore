# Phase 9 — Python SDK

## Objective
Give MemCore a typed, ergonomic Python client so consumers stop hand-rolling
HTTP calls: async-first coverage of the full v1 API with a mechanically
mirrored sync surface, GET-only retry discipline, typed errors from the
server's problem+json bodies, and job-polling helpers — installable
server-free via a new `sdk` extra. Design in ADR-0018.

## Delivered

**Foundation** (`memcore/sdk/exceptions.py`, `memcore/sdk/_shared.py`,
`memcore/sdk/models.py`; `sdk = ["httpx>=0.27"]` extra in `pyproject.toml`)
- Exception hierarchy rooted at `MemCoreClientError`: `APIError` (carries
  `.status`/`.title`/`.detail`) with `AuthError`/`NotFoundError`/
  `ConflictError`/`ValidationAPIError`/`ServerError` subclasses by status
  code, plus `TransportError` and `JobTimeout`.
- `_shared.py` holds the transport-agnostic logic once, shared by both
  clients: `RetryPolicy` (max_attempts=3, backoff_base=0.2, backoff_cap=5.0
  defaults), `compute_backoff` (deterministic exponential, no jitter),
  `is_retryable` (GET-only, `{429,502,503,504}` or transport failure), and
  `error_from_response` (RFC-7807 payload → typed exception).
- `models.py`: `Job` (with a `done` property over
  `{"succeeded","failed"}`) and `RecallOutcome` — thin SDK-side wrappers;
  everything else validates directly into existing domain models
  (`Session`, `MemoryRecord`, `ScoredMemory`).
- Core dependencies stay pydantic-only; `httpx` is lazy-imported inside each
  client's `__init__`, raising `MemCoreClientError` with the standard
  install hint if missing.

**`AsyncMemCoreClient`** (`memcore/sdk/async_client.py`) — full v1 surface:
sessions (`open_session`, `get_session`, `append_message`, `close_session`),
memories (`remember`, `get_memory`, `memory_versions`, `correct_memory`,
`forget_memory`), `recall` (k, types, weights, graph_expand, rerank,
as_context all passed through), jobs (`consolidate`, `job`, `run_decay`,
`wait_for_job` with bounded timeout raising `JobTimeout`), and `health`.
Transport (`httpx.AsyncClient`) and `sleep` are both injectable constructor
args, so tests run against an in-process ASGI app with zero real waiting and
zero real network. `_request` centralizes retry/backoff/error-mapping using
`_shared`. Covered end to end by ASGI in-process tests exercising the full
surface plus deterministic retry-path tests (transport failure and each
retryable status).

**`MemCoreClient` sync mirror** (`memcore/sdk/client.py`) — identical public
surface with blocking `httpx.Client` calls, built directly against
`_shared` (no code generation). A signature-parity test asserts every public
method on `AsyncMemCoreClient` has a same-named, same-signature counterpart
on `MemCoreClient` (module boilerplate aside), so the two surfaces cannot
silently drift. A full-surface round-trip test exercises the sync client
against the same in-process ASGI app.

**Docs** — `docs/adr/0018-python-sdk.md` (+ README index line),
`docs/sdk-quickstart.md` (install, async example, sync example, errors and
retries).

## Gate (2026-07-05, incl. final-review fix commit)
- pytest: **189 passed, 3 integration-skipped** · coverage **93.96%**
- ruff: clean
- mypy (strict, 99 files): clean

## Deferred
- Pagination helpers — the v1 API has no list-style endpoints yet (sessions
  and memories are fetched by id); revisit once one lands.
- Higher-level conveniences (e.g. an auto-consolidating session context
  manager that opens, yields, and closes a session) — post-v1 ergonomics,
  not required for a typed 1:1 client over the existing API.
- Carried over from the Phase 7 final review (deployment/security phase):
  per-tenant sweep dedupe + rate limiting; a restore endpoint for
  soft-deleted records (see ADR-0018's Consequences for why this matters to
  the SDK specifically — soft-deleted records stay GET-visible today).

## Self-review
Verified against the implementation commits (`d56cada`, `0863bf7`,
`b7a14ba`, `90e128c`): the exception hierarchy, `_shared.py` primitives, and
`models.py` match `exceptions.py`/`_shared.py`/`models.py` as implemented;
`AsyncMemCoreClient`'s method list above matches `async_client.py`'s public
methods (`health`, `open_session`, `get_session`, `append_message`,
`close_session`, `remember`, `get_memory`, `memory_versions`,
`correct_memory`, `forget_memory`, `recall`, `consolidate`, `job`,
`run_decay`, `wait_for_job`) verbatim; the sync mirror and parity-guard test
exist per `b7a14ba`; the quickstart's async/sync examples call only methods
that exist with the signatures shown. `sdk = ["httpx>=0.27"]` confirmed in
`pyproject.toml`; core dependencies remain pydantic-only. No issues found
requiring a follow-up commit.
