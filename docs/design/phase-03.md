# Phase 3 — Memory APIs

## Objective
The unified memory API: FastAPI app + the metadata source of truth, wired
through a service layer so routes stay thin and invariants live in one place.

## Delivered

**`MemoryStore` port** (ADR-0005 made concrete) — versioned records, append-only
audit, session bookkeeping. Adapters:
- `InMemoryMemoryStore` (reference/test double)
- `SqlMemoryStore` — SQLAlchemy 2 async; Postgres in prod, SQLite in tests
  (ADR-0012). Atomic `supersede`, ISO-8601 datetimes, JSON list/dict columns.

**Services**
- `SessionService` — open/append/close. Append is the fast ingest path
  (ADR-0001): working-memory push + immutable raw archive to the object store
  (the DR rebuild source) + session stats. Appending to a closed session is
  rejected; close is idempotent (consolidation enqueue arrives in Phase 5).
- `MemoryService` — remember / correct / forget with the ADR-0007 invariants:
  correct = supersede (new version, old vector removed from the index), forget =
  soft/hard status change + immediate de-indexing, every mutation audited.
- `RecallService` — retrieval v1: filtered ANN candidates (tenant/agent/status/
  type) re-scored by `relevance × recency × importance` with per-type recency
  τ (working 6h, episodic 7d, semantic 30d); reinforcement on recall; the
  store is authoritative — index-lag hits are dropped. Graph expansion, caller
  weights and reranking land in Phase 4.

**API (FastAPI)**
- `POST /v1/sessions`, `GET/POST /v1/sessions/{id}[/messages|/close]`
- `POST /v1/memories`, `GET /v1/memories/{id}[/versions]`,
  `PATCH /v1/memories/{id}`, `DELETE /v1/memories/{id}?mode=soft|hard`
- `POST /v1/recall`, `GET /health`
- Auth v1: `X-API-Key` → tenant from `MEMCORE_API__KEYS` (JSON map). No default
  credentials; `env=local` with an empty map injects `dev-key` with a warning.
- Domain errors → RFC-7807 problem+json (401/404/409/422/500/503).
- `create_app(settings, state=...)` factory; adapters built via the factory
  module; startup runs store `init()` + vector-collection ensure.

## Tests
MemoryStore contract against **both** adapters (the SQL one runs on SQLite in
CI); service tests (session lifecycle + archive, versioning + re-indexing,
soft/hard forget, recall ranking/reinforcement/type-filter/isolation/index-lag);
API tests over ASGI (auth, session flow, CRUD + versions, recall, cross-tenant
isolation, strict request validation).

## Deliberately deferred
- Outbox relay: Phase 3 writes are single-owner (service coordinates store +
  vector). The transactional outbox becomes necessary when consolidation
  (Phase 5) introduces multi-record, multi-store writes — noted in ADR-0005.
- Real embedding providers (bge/OpenAI): Phase 4. `build_embedding_provider`
  fails loudly for them rather than degrading.
- S3 object-store adapter (deployment phase); API uses in-memory archive until.
- Rate limiting, RBAC roles, idempotency keys: security hardening phase.

## Self-review
Recorded in the delivery message; fixes applied before sign-off.
