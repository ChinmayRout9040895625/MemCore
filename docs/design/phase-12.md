# Phase 12 — Documentation & examples

## Objective
Close the 12-phase roadmap: make the API, SDK, and deployment surfaces
self-documenting and hard to let rot — a generated API reference with a CI
drift guard, runnable examples executed in CI, hand-written guides for
operations and deployment, a refreshed architecture doc, and a README that
gives a new reader a working path in under a minute. Design in ADR-0021.

## Delivered

**Generated API reference** — `scripts/generate_api_reference.py` renders
`docs/api-reference.md` from the live FastAPI app's OpenAPI schema, with a
hand-maintained section for operational endpoints excluded from that schema
(`/health`, `/ready`, `/metrics`); a CI test regenerates the file and diffs
it byte-for-byte against the committed copy, failing on drift.

**Examples** (`examples/`) — four runnable SDK scripts, each exposing a
`main(client)` seam and executed in CI against the in-process ASGI app
(`tests/unit/test_examples.py`):
- `quickstart_async.py` — remember + hybrid recall, `AsyncMemCoreClient`.
- `quickstart_sync.py` — the same flow, blocking `MemCoreClient`.
- `memory_lifecycle.py` — versioned correction, version chain, hard delete.
- `sessions_and_consolidation.py` — sessions, async consolidation job, recall
  of extracted facts.

`examples/README.md` covers setup (`pip install 'memcore[sdk]'`, compose
stack) and a table of what each script demonstrates.

**Guides** — `docs/guides/operations.md` (config reference, backing
services, observability runbook, memory operations, troubleshooting, known
limits) and `docs/guides/deployment.md` (Docker Compose local stack →
Kubernetes walkthrough, using the Phase 11 artifacts as the worked example).
`docs/design/architecture.md` refreshed to reflect the system through
Phase 11 (services, API, SDK, observability, deployment topology).

**README overhaul** — status line updated to v0.1 feature-complete (all 12
roadmap phases done); added a **Quickstart** section (compose stack up,
`pip install 'memcore[sdk]'`, a 6-line snippet mirroring
`examples/quickstart_async.py`'s actual `remember`/`recall` calls); added a
**Documentation** index linking the API reference, SDK quickstart,
operations guide, deployment guide, examples, and the ADR log; added an
**Install extras** table covering all `pyproject.toml` optional-dependency
groups (`sdk`, `api`, `vector`, `graph`, `working`, `sql`, `postgres`,
`scheduler`, `embeddings`, `llm`, `observability`, `dev`). Kept to 120 lines.

**ADR-0021** — docs-as-code: the API reference is generated with a CI drift
test, examples are CI-executed scripts, guides are hand-written but
source-verified at write/review time, phase docs and ADRs stay the
unmodified historical record while guides are the living surface.

## Gate (2026-07-10)
- pytest: **228 passed, 3 integration-skipped** (Qdrant/Redis/Neo4j
  unreachable — no live backends in this environment, expected) ·
  coverage **93.93%**
- ruff: clean
- mypy (strict, 108 files): clean

## Self-review
- Verified the README's quickstart snippet against `examples/quickstart_async.py`
  line-by-line: `AsyncMemCoreClient(url, key)`, `client.remember(agent_id, content,
  importance=..., tags=...)` returning a record with `.id`/`.importance`, and
  `client.recall(agent_id, query)` returning `.results` of `ScoredMemory`-like
  objects with `.final`/`.memory.content` — all real, not paraphrased.
- Confirmed every link added to the README and to `docs/adr/README.md`
  resolves to a file that exists on disk (`docs/api-reference.md`,
  `docs/sdk-quickstart.md`, `docs/guides/operations.md`,
  `docs/guides/deployment.md`, `examples/README.md`,
  `docs/adr/0021-documentation-strategy.md`) before writing this doc.
- `scripts/generate_api_reference.py` and `tests/unit/test_examples.py`,
  named in ADR-0021, both confirmed present on disk rather than assumed from
  the task brief's description.
- Gate numbers above are this task's own run, not carried over from Phase 11
  (228 vs. 221 passed reflects the example/doc-drift tests added across
  Phase 12's four prior commits).

## Deferred (post-v1 backlog)
- SDK `restore_memory` method — the REST `POST /v1/memories/{id}/restore`
  endpoint shipped in Phase 11 has no typed SDK wrapper yet.
- Distributed (cross-process) decay-sweep dedupe (Redis lock) + in-app/
  distributed rate limiting — both flagged as deferred since ADR-0020;
  still open.
- Per-role slim Docker images (API without `embeddings`/`llm`, worker
  without `api`) — the single image today carries every extra.
- Helm chart for `deploy/k8s/` — currently plain manifests.
- Postgres-in-CI contract test — the `integration` CI job exercises
  Qdrant/Neo4j/Redis against real containers; the SQL store is still only
  unit-tested against SQLite.
- Prometheus multiprocess mode — needed to support worker concurrency > 1
  without racing the metrics port (ADR-0020 constrained workers to
  `--concurrency=1` for this reason).
- Grafana dashboards and alert rules on top of Phase 10's metrics.
- Real-corpus evaluation datasets — Phase 8's evaluation harness runs on a
  synthetic dataset (`synthetic-v1`); a real-corpus benchmark is future work.

## Roadmap status
All 12 phases are now complete. MemCore is v0.1, feature-complete. Future
work is tracked as the post-v1 backlog above, carried into
`PROJECT_STATE.md`.
