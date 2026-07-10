# Phase 12 — Documentation & Examples Implementation Plan (Final Phase)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship MemCore's user-facing documentation: a generated (drift-guarded) API reference, CI-tested runnable SDK examples, operations + deployment guides grounded in the Phase 10/11 artifacts, and a final README/state overhaul that closes the 12-phase roadmap.

**Architecture:** Docs-as-code (recorded as ADR-0021): the API reference is *generated* from the live FastAPI OpenAPI schema by `scripts/generate_api_reference.py` and a unit test regenerates it on every run — the committed file can never drift from the real API. Examples in `examples/` are plain runnable scripts (`python examples/x.py` against any running MemCore) structured as `main(client)` functions so a unit test can execute them end-to-end against the in-process ASGI app — examples that stop working fail CI. Guides (`docs/guides/`) are hand-written prose whose every factual claim (env var names, metric names, thresholds, commands) must be verified against source at writing time and is re-verified in review.

**Tech Stack:** Python 3.11+ (existing), FastAPI `app.openapi()`, `memcore.sdk`, pytest with `httpx.ASGITransport`/`MockTransport`, markdown.

## Global Constraints

- Quality gate (every task, before commit): `./.venv/Scripts/python.exe -m pytest` all pass, coverage ≥ 85%; `./.venv/Scripts/python.exe -m ruff check .` clean; `./.venv/Scripts/python.exe -m mypy` clean (strict).
- No source changes under `src/memcore/` in this phase EXCEPT none are planned — if a doc claim turns out false, fix the DOC (or escalate), never quietly change behavior in a docs phase.
- `examples/` and `scripts/` are outside the mypy `files` list (`["src", "tests"]` in pyproject) and outside coverage `source` — do NOT add them; ruff still lints them (keep clean).
- All generated/committed text files use LF newlines (`open(..., newline="\n")` in the generator; `.gitattributes` not touched).
- Every factual claim in guides must correspond to real code/artifacts: env var names match `src/memcore/config.py` (prefix `MEMCORE_`, nested `__`), metric names match `src/memcore/observability/metrics.py`, endpoints match `src/memcore/api/routes.py`, deploy commands match `docker-compose.yml`/`deploy/k8s/`.
- Examples default to the compose-stack dev credentials (`http://localhost:8000`, API key `dev-key`) overridable via `MEMCORE_URL` / `MEMCORE_API_KEY` env vars.
- One commit per task; phase gate + docs in Task 5; the roadmap ends here — after the phase commit, STOP and report project completion.

---

### Task 1: Generated API reference + drift test

**Files:**
- Create: `scripts/generate_api_reference.py`
- Create: `docs/api-reference.md` (generated — run the script, commit its output verbatim)
- Test: `tests/unit/test_api_reference.py`

**Interfaces:**
- Consumes: `memcore.api.create_app`, `memcore.config.Settings` (+ the per-block settings classes for all-inmemory construction).
- Produces: `scripts/generate_api_reference.py [OUTPUT_PATH]` (default `docs/api-reference.md`) — deterministic markdown; the drift test regenerates into a temp file and asserts byte-equality with the committed file.

- [ ] **Step 1: Write the failing drift test**

Create `tests/unit/test_api_reference.py`:

```python
"""Phase 12 — the committed API reference must match the live OpenAPI schema.

The reference is generated, not hand-written (ADR-0021): this test regenerates
it and compares byte-for-byte, so any route/schema change that forgets to
re-run the generator fails CI with a clear message.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts" / "generate_api_reference.py"
COMMITTED = REPO_ROOT / "docs" / "api-reference.md"


def test_api_reference_is_current(tmp_path: Path) -> None:
    output = tmp_path / "api-reference.md"
    subprocess.run(
        [sys.executable, str(GENERATOR), str(output)],
        check=True,
        cwd=REPO_ROOT,
        timeout=120,
    )
    generated = output.read_text(encoding="utf-8")
    committed = COMMITTED.read_text(encoding="utf-8")
    assert generated == committed, (
        "docs/api-reference.md is stale — regenerate it:\n"
        "  ./.venv/Scripts/python.exe scripts/generate_api_reference.py"
    )


def test_reference_covers_every_route(tmp_path: Path) -> None:
    text = COMMITTED.read_text(encoding="utf-8")
    # Spot-check the full v1 surface is present.
    for fragment in (
        "POST /v1/sessions",
        "POST /v1/sessions/{session_id}/messages",
        "POST /v1/sessions/{session_id}/close",
        "POST /v1/memories",
        "GET /v1/memories/{memory_id}",
        "GET /v1/memories/{memory_id}/versions",
        "PATCH /v1/memories/{memory_id}",
        "DELETE /v1/memories/{memory_id}",
        "POST /v1/memories/{memory_id}/restore",
        "POST /v1/recall",
        "POST /v1/consolidate",
        "GET /v1/jobs/{job_id}",
        "POST /v1/decay",
        "GET /health",
        "GET /ready",
    ):
        assert fragment in text, f"missing from api-reference.md: {fragment}"
```

(Note: `/ready` is `include_in_schema=False`, so it will NOT be in `app.openapi()` — the generator must append a short hand-maintained "Operational endpoints" section covering `/ready` and `/metrics` so the reference is complete; see Step 3.)

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_api_reference.py -v`
Expected: FAIL — the generator script and committed file don't exist yet.

- [ ] **Step 3: Write the generator**

Create `scripts/generate_api_reference.py`:

```python
"""Generate docs/api-reference.md from the live FastAPI OpenAPI schema.

Usage:
    python scripts/generate_api_reference.py [OUTPUT_PATH]

Deterministic: paths and fields are emitted in sorted/declared order, output
uses LF newlines, and no timestamps are embedded — so regeneration is
byte-stable and the drift test can compare exactly.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Ensure src/ is importable when run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memcore.api import create_app  # noqa: E402
from memcore.config import (  # noqa: E402
    DatabaseSettings,
    EmbeddingSettings,
    GraphSettings,
    LLMSettings,
    RedisSettings,
    SchedulerSettings,
    Settings,
    VectorSettings,
)

METHOD_ORDER = {"get": 0, "post": 1, "patch": 2, "put": 3, "delete": 4}

OPERATIONAL_SECTION = """\
## Operational endpoints (not in the OpenAPI schema)

These are deliberately excluded from the schema (`include_in_schema=False`)
because they are for probes and scrapers, not API clients:

| Method & path | Purpose |
|---|---|
| `GET /ready` | Readiness probe: pings each backing store (duck-typed adapter `ping()`); returns 200 `{"status": "ready"}` or 503 `{"status": "degraded"}` with per-component detail. No auth. |
| `GET /metrics` | Prometheus exposition for the API process; 501 problem+json with an install hint when the `observability` extra is absent. No auth — keep it cluster-internal (the shipped ingress blocks it). |
"""


def _build_schema() -> dict[str, Any]:
    settings = Settings(
        _env_file=None,
        redis=RedisSettings(provider="inmemory"),
        vector=VectorSettings(provider="inmemory"),
        graph=GraphSettings(provider="inmemory"),
        embedding=EmbeddingSettings(provider="inmemory"),
        llm=LLMSettings(provider="inmemory", fallback_provider=None),
        scheduler=SchedulerSettings(provider="inmemory"),
        database=DatabaseSettings(provider="inmemory"),
    )
    app = create_app(settings)
    schema: dict[str, Any] = app.openapi()
    return schema


def _resolve_ref(schema: dict[str, Any], ref: str) -> dict[str, Any]:
    node: Any = schema
    for part in ref.removeprefix("#/").split("/"):
        node = node[part]
    return dict(node)


def _type_of(prop: dict[str, Any], schema: dict[str, Any]) -> str:
    if "$ref" in prop:
        return prop["$ref"].rsplit("/", 1)[-1]
    if "anyOf" in prop:
        return " | ".join(_type_of(p, schema) for p in prop["anyOf"])
    kind = prop.get("type", "any")
    if kind == "array":
        return f"array[{_type_of(prop.get('items', {}), schema)}]"
    if "enum" in prop:
        values = " \\| ".join(str(v) for v in prop["enum"])
        return f"{kind} ({values})"
    return str(kind)


def _model_table(name: str, schema: dict[str, Any], emitted: set[str]) -> list[str]:
    if name in emitted or name not in schema.get("components", {}).get("schemas", {}):
        return []
    emitted.add(name)
    model = schema["components"]["schemas"][name]
    lines = [f"### `{name}`", ""]
    if model.get("description"):
        lines += [model["description"].strip(), ""]
    properties: dict[str, Any] = model.get("properties", {})
    if not properties:
        lines += ["(no fields)", ""]
        return lines
    required = set(model.get("required", []))
    lines += ["| Field | Type | Required | Default |", "|---|---|---|---|"]
    for field, prop in properties.items():
        default = prop.get("default", "—")
        lines.append(
            f"| `{field}` | {_type_of(prop, schema)} | "
            f"{'yes' if field in required else 'no'} | `{default}` |"
        )
    lines.append("")
    return lines


def _collect_refs(node: Any, found: list[str]) -> None:
    if isinstance(node, dict):
        if "$ref" in node:
            found.append(node["$ref"].rsplit("/", 1)[-1])
        for value in node.values():
            _collect_refs(value, found)
    elif isinstance(node, list):
        for item in node:
            _collect_refs(item, found)


def render(schema: dict[str, Any]) -> str:
    lines: list[str] = [
        f"# {schema['info']['title']} API Reference",
        "",
        f"Version {schema['info']['version']} — generated from the OpenAPI "
        "schema by `scripts/generate_api_reference.py`; do not edit by hand "
        "(a drift test regenerates and compares this file).",
        "",
        "**Authentication:** every `/v1/*` endpoint requires the `X-API-Key` "
        "header; the key maps to a tenant (`MEMCORE_API__KEYS`). Errors are "
        "RFC-7807 `application/problem+json`.",
        "",
        "## Endpoints",
        "",
    ]
    referenced_models: list[str] = []
    for path in sorted(schema["paths"]):
        operations = schema["paths"][path]
        for method in sorted(operations, key=lambda m: METHOD_ORDER.get(m, 9)):
            op = operations[method]
            lines.append(f"### `{method.upper()} {path}`")
            lines.append("")
            summary = op.get("summary") or op.get("operationId", "")
            if summary:
                lines += [summary, ""]
            if op.get("description"):
                lines += [op["description"].strip(), ""]
            params = op.get("parameters", [])
            if params:
                lines += ["| Parameter | In | Type | Required |", "|---|---|---|---|"]
                for param in params:
                    lines.append(
                        f"| `{param['name']}` | {param['in']} | "
                        f"{_type_of(param.get('schema', {}), schema)} | "
                        f"{'yes' if param.get('required') else 'no'} |"
                    )
                lines.append("")
            body = op.get("requestBody", {})
            body_schema = (
                body.get("content", {}).get("application/json", {}).get("schema", {})
            )
            if body_schema:
                lines += [f"Request body: `{_type_of(body_schema, schema)}`", ""]
                _collect_refs(body_schema, referenced_models)
            responses = op.get("responses", {})
            resp_lines = []
            for status in sorted(responses):
                resp = responses[status]
                resp_schema = (
                    resp.get("content", {})
                    .get("application/json", {})
                    .get("schema", {})
                )
                kind = f" — `{_type_of(resp_schema, schema)}`" if resp_schema else ""
                resp_lines.append(f"| {status} | {resp.get('description', '')}{kind} |")
                _collect_refs(resp_schema, referenced_models)
            if resp_lines:
                lines += ["| Status | Response |", "|---|---|", *resp_lines, ""]
    lines += [OPERATIONAL_SECTION, "## Models", ""]
    emitted: set[str] = set()
    # Emit referenced models first (stable order of first reference), then
    # transitively referenced ones discovered while emitting.
    queue = list(dict.fromkeys(referenced_models))
    while queue:
        name = queue.pop(0)
        model = schema.get("components", {}).get("schemas", {}).get(name, {})
        nested: list[str] = []
        _collect_refs(model, nested)
        lines += _model_table(name, schema, emitted)
        queue += [n for n in nested if n not in emitted]
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/api-reference.md")
    schema = _build_schema()
    with open(output, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render(schema))
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Generate the committed reference and run the tests**

Run:
```bash
./.venv/Scripts/python.exe scripts/generate_api_reference.py
./.venv/Scripts/python.exe -m pytest tests/unit/test_api_reference.py -v
```
Expected: `wrote docs/api-reference.md`, then both tests PASS. Read the generated file once end-to-end: every `/v1` route present, model tables render sensibly. If a fragment assertion fails because FastAPI names differ, fix the GENERATOR (or the test's fragment) to match reality — never hand-edit the generated file.

- [ ] **Step 5: Full gate, then commit**

Run the full gate. Expected: clean (the new test adds ~2 tests).

```bash
git add scripts/generate_api_reference.py docs/api-reference.md tests/unit/test_api_reference.py
git commit -m "feat(docs): generated API reference + drift test (Phase 12)"
```

---

### Task 2: Runnable SDK examples, CI-tested in-process

**Files:**
- Create: `examples/README.md`
- Create: `examples/quickstart_async.py`
- Create: `examples/quickstart_sync.py`
- Create: `examples/memory_lifecycle.py`
- Create: `examples/sessions_and_consolidation.py`
- Test: `tests/unit/test_examples.py`

**Interfaces:**
- Consumes: `memcore.sdk.AsyncMemCoreClient` / `MemCoreClient` (full v1 surface incl. `restore_memory`? — NO: the SDK does NOT have a restore method (it predates Phase 11); the lifecycle example calls restore via `client._request`? NO — keep examples to the public SDK surface only. The lifecycle example ends at forget; the restore endpoint is documented in the API reference and ops guide as HTTP-only for now, and "SDK restore_memory method" goes on the post-v1 backlog. Do not add SDK methods in a docs phase.)
- Produces: each example module exposes `async def main(client: AsyncMemCoreClient) -> None` (or `def main(client: MemCoreClient) -> None` for the sync one) plus an `if __name__ == "__main__"` block reading `MEMCORE_URL` (default `http://localhost:8000`) and `MEMCORE_API_KEY` (default `dev-key`).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_examples.py`:

```python
"""Phase 12 — the shipped examples must actually run (ADR-0021).

Each example is loaded from examples/ by file path and its ``main(client)``
executed against the real in-process ASGI app — a broken example fails CI.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

from memcore.adapters.inmemory import (
    HashingEmbeddingProvider,
    ImmediateWorkflowEngine,
    InMemoryGraphStore,
    InMemoryMemoryStore,
    InMemoryObjectStore,
    InMemoryVectorStore,
    InMemoryWorkingMemory,
    ScriptedLLMProvider,
)
from memcore.api.app import create_app
from memcore.api.deps import AppState
from memcore.config import Settings
from memcore.sdk import AsyncMemCoreClient, MemCoreClient
from memcore.services import (
    ConsolidationService,
    DecayService,
    MemoryService,
    RecallService,
    SessionService,
)

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
API_KEY = "dev-key"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, EXAMPLES / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _state() -> AppState:
    store = InMemoryMemoryStore()
    working = InMemoryWorkingMemory()
    vectors = InMemoryVectorStore()
    graph = InMemoryGraphStore()
    embedder = HashingEmbeddingProvider(dimension=64)
    collection = "mem_64"
    memories = MemoryService(store, vectors, embedder, collection=collection)
    llm = ScriptedLLMProvider(
        responses=['{"summary": "example session", "facts": [], "entities": [], '
                   '"relations": [], "invalidations": []}'] * 4
    )
    consolidation = ConsolidationService(store, working, memories, vectors, graph, llm)
    workflow = ImmediateWorkflowEngine()

    async def _consolidate(payload: dict[str, object]) -> None:
        await consolidation.consolidate_session(
            str(payload["tenant_id"]), str(payload["session_id"])
        )

    workflow.register("consolidate_session", _consolidate)
    decay = DecayService(store, memories)

    async def _decay(payload: dict[str, object]) -> None:
        await decay.sweep(str(payload["tenant_id"]))

    workflow.register("decay_tenant", _decay)
    return AppState(
        store=store, working=working, objects=InMemoryObjectStore(),
        vectors=vectors, graph=graph, embedder=embedder,
        sessions=SessionService(store, working, InMemoryObjectStore()),
        memories=memories,
        recall=RecallService(store, vectors, embedder, collection=collection, graph=graph),
        consolidation=consolidation, workflow=workflow,
        api_keys={API_KEY: "examples-tenant"},
    )


@pytest.mark.parametrize(
    "name",
    ["quickstart_async", "memory_lifecycle", "sessions_and_consolidation"],
)
async def test_async_examples_run_end_to_end(
    name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load(name)
    transport = httpx.ASGITransport(app=create_app(Settings(_env_file=None), state=_state()))
    async with AsyncMemCoreClient("http://examples", API_KEY, transport=transport) as client:
        await module.main(client)
    out = capsys.readouterr().out
    assert out.strip(), f"example {name} printed nothing"


def test_sync_example_runs(capsys: pytest.CaptureFixture[str]) -> None:
    module = _load("quickstart_sync")
    memory = {
        "id": "m1", "tenant_id": "t", "agent_id": "quickstart-agent",
        "type": "semantic", "content": "Bruno is a beagle.",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/memories" and request.method == "POST":
            return httpx.Response(201, json={"memory": memory})
        if request.url.path == "/v1/recall":
            return httpx.Response(200, json={
                "results": [{"memory": memory, "relevance": 0.9, "recency": 1.0,
                             "importance": 0.5, "final": 0.45}],
                "context": None, "context_tokens": None,
            })
        raise AssertionError(f"unrouted: {request.method} {request.url.path}")

    with MemCoreClient(
        "http://examples", API_KEY, transport=httpx.MockTransport(handler)
    ) as client:
        module.main(client)
    assert capsys.readouterr().out.strip()


def test_examples_have_env_entrypoints() -> None:
    # Every example must be runnable standalone against a real server.
    for name in ("quickstart_async", "quickstart_sync", "memory_lifecycle",
                 "sessions_and_consolidation"):
        text = (EXAMPLES / f"{name}.py").read_text(encoding="utf-8")
        assert '__main__' in text, f"{name} lacks a __main__ entrypoint"
        assert "MEMCORE_URL" in text and "MEMCORE_API_KEY" in text, (
            f"{name} must read MEMCORE_URL/MEMCORE_API_KEY"
        )


def _unused(*_args: Any) -> None:  # keeps the Any import purposeful for mypy
    return None
```

(If `Any` ends up unused after transcription, drop the import and `_unused` helper — keep ruff clean.)

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_examples.py -v`
Expected: FAIL — `FileNotFoundError` loading the example modules.

- [ ] **Step 3: Write the examples**

Create `examples/quickstart_async.py`:

```python
"""MemCore quickstart (async): store a memory, recall it by meaning.

Run against a live MemCore (e.g. the docker-compose stack):
    MEMCORE_URL=http://localhost:8000 MEMCORE_API_KEY=dev-key \
        python examples/quickstart_async.py
"""

from __future__ import annotations

import asyncio
import os

from memcore.sdk import AsyncMemCoreClient

AGENT = "quickstart-agent"


async def main(client: AsyncMemCoreClient) -> None:
    record = await client.remember(
        AGENT, "Chinmay prefers dark mode in every editor.",
        importance=0.8, tags=["preference"],
    )
    print(f"stored memory {record.id} (importance={record.importance})")

    outcome = await client.recall(AGENT, "what UI theme does the user like?")
    for scored in outcome.results:
        print(f"  {scored.final:.3f}  {scored.memory.content}")


if __name__ == "__main__":
    async def _run() -> None:
        url = os.getenv("MEMCORE_URL", "http://localhost:8000")
        key = os.getenv("MEMCORE_API_KEY", "dev-key")
        async with AsyncMemCoreClient(url, key) as client:
            await main(client)

    asyncio.run(_run())
```

Create `examples/quickstart_sync.py`:

```python
"""MemCore quickstart (sync): same flow as quickstart_async, blocking client.

Run:  MEMCORE_URL=http://localhost:8000 python examples/quickstart_sync.py
"""

from __future__ import annotations

import os

from memcore.sdk import MemCoreClient

AGENT = "quickstart-agent"


def main(client: MemCoreClient) -> None:
    record = client.remember(AGENT, "Bruno is a beagle.", tags=["pet"])
    print(f"stored memory {record.id}")
    outcome = client.recall(AGENT, "what kind of dog is bruno?")
    for scored in outcome.results:
        print(f"  {scored.final:.3f}  {scored.memory.content}")


if __name__ == "__main__":
    url = os.getenv("MEMCORE_URL", "http://localhost:8000")
    key = os.getenv("MEMCORE_API_KEY", "dev-key")
    with MemCoreClient(url, key) as client:
        main(client)
```

Create `examples/memory_lifecycle.py`:

```python
"""Memory lifecycle: remember -> recall -> correct -> versions -> forget.

Records are immutable and versioned: a correction supersedes rather than
edits, and soft deletion is reversible server-side (POST
/v1/memories/{id}/restore — not yet wrapped by the SDK).

Run:  MEMCORE_URL=http://localhost:8000 python examples/memory_lifecycle.py
"""

from __future__ import annotations

import asyncio
import os

from memcore.sdk import AsyncMemCoreClient, NotFoundError

AGENT = "lifecycle-agent"


async def main(client: AsyncMemCoreClient) -> None:
    original = await client.remember(
        AGENT, "Chinmay lives in Mumbai.", importance=0.7, confidence=0.6,
    )
    print(f"v1: {original.content!r} (id={original.id})")

    corrected = await client.correct_memory(
        original.id, content="Chinmay lives in Pune.", confidence=0.9,
    )
    print(f"v2: {corrected.content!r} supersedes {corrected.supersedes}")

    versions = await client.memory_versions(corrected.id)
    print(f"version chain: {[v.version for v in versions]}")

    outcome = await client.recall(AGENT, "where does chinmay live?")
    top = outcome.results[0].memory if outcome.results else None
    print(f"recall surfaces: {top.content!r}" if top else "recall found nothing")

    await client.forget_memory(corrected.id, mode="hard")
    try:
        await client.get_memory(corrected.id)
    except NotFoundError:
        print("hard-deleted memory is gone (404), as designed")


if __name__ == "__main__":
    async def _run() -> None:
        url = os.getenv("MEMCORE_URL", "http://localhost:8000")
        key = os.getenv("MEMCORE_API_KEY", "dev-key")
        async with AsyncMemCoreClient(url, key) as client:
            await main(client)

    asyncio.run(_run())
```

Create `examples/sessions_and_consolidation.py`:

```python
"""Sessions + async consolidation: converse, close, consolidate, poll the job.

Closing a session enqueues consolidation (an LLM extracts durable facts in
the background). With the compose stack, set MEMCORE_LLM__API_KEY server-side
for real extraction; without it, consolidation falls back per configuration.

Run:  MEMCORE_URL=http://localhost:8000 python examples/sessions_and_consolidation.py
"""

from __future__ import annotations

import asyncio
import os

from memcore.sdk import AsyncMemCoreClient

AGENT = "session-agent"


async def main(client: AsyncMemCoreClient) -> None:
    session = await client.open_session(AGENT)
    print(f"session {session.id} opened")

    for turn in (
        "I just moved to Pune for a new job at a robotics startup.",
        "My dog Bruno is settling in well.",
    ):
        session = await client.append_message(session.id, "user", turn)
    print(f"{session.turn_count} turns buffered")

    closed = await client.close_session(session.id)
    print(f"session closed: {closed.closed} (consolidation enqueued)")

    job = await client.consolidate(session.id)
    finished = await client.wait_for_job(job.job_id, timeout=60.0)
    print(f"consolidation job {finished.job_id}: {finished.state}")

    outcome = await client.recall(AGENT, "where does the user work now?")
    for scored in outcome.results[:3]:
        print(f"  {scored.final:.3f}  {scored.memory.content}")


if __name__ == "__main__":
    async def _run() -> None:
        url = os.getenv("MEMCORE_URL", "http://localhost:8000")
        key = os.getenv("MEMCORE_API_KEY", "dev-key")
        async with AsyncMemCoreClient(url, key) as client:
            await main(client)

    asyncio.run(_run())
```

Create `examples/README.md`:

```markdown
# MemCore examples

Runnable end-to-end scripts against any MemCore server. Each is also executed
in CI against an in-process app (`tests/unit/test_examples.py`), so they are
guaranteed current.

## Setup

```bash
pip install 'memcore[sdk]'
# Bring up a local stack (from the repo root):
cp .env.example .env && docker compose up -d --build
```

Defaults target the compose stack: `MEMCORE_URL=http://localhost:8000`,
`MEMCORE_API_KEY=dev-key` (the dev key maps to the `local` tenant when no
keys are configured; set `MEMCORE_API__KEYS` in `.env` for real keys).

## Scripts

| Script | Shows |
|---|---|
| `quickstart_async.py` | remember + hybrid recall (async client) |
| `quickstart_sync.py` | the same flow with the blocking client |
| `memory_lifecycle.py` | versioned correction, version chain, hard delete |
| `sessions_and_consolidation.py` | sessions, async consolidation job, recall of extracted facts |

Run any of them:

```bash
python examples/quickstart_async.py
```
```

- [ ] **Step 4: Run tests, then full gate**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_examples.py -v`
Expected: all PASS (async examples print real output through the in-process stack; sync example prints via canned transport).
Then the full gate. Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add examples/ tests/unit/test_examples.py
git commit -m "feat(docs): runnable SDK examples, CI-tested in-process (Phase 12)"
```

---

### Task 3: Operations guide + architecture refresh

**Files:**
- Create: `docs/guides/operations.md`
- Modify: `docs/design/architecture.md` (refresh — the doc predates Phases 6–11)

**Interfaces:** none — prose, but every claim must be verified against source at writing time (read `src/memcore/config.py`, `src/memcore/observability/metrics.py`, `src/memcore/api/routes.py`, `src/memcore/services/{importance,decay}.py`, ADRs 0015–0020 first).

- [ ] **Step 1: Write `docs/guides/operations.md`**

Sections (each with the real values from source — this outline names the facts; the writer verifies each one):

1. **Configuration reference** — env prefix `MEMCORE_`, nested delimiter `__`, `.env` support. One table per settings block from `config.py`: `redis`, `vector`, `graph`, `embedding`, `llm`, `scheduler`, `database`, `api` (JSON `MEMCORE_API__KEYS`, dev-key injection in `env=local` only), `retrieval` (incl. per-type recency taus), `consolidation` (dup_similarity 0.9, conflict_confidence 0.7), `importance` (saturation 5.0, max_boost 0.3, decay_tau_days 30.0), `retention` (prune_threshold 0.05, min_age_days 14.0, scan_limit 10_000). Also non-Settings env: `MEMCORE_METRICS_PORT` (worker exposition).
2. **Backing services** — what each store holds (Postgres = source of truth incl. audit; Qdrant = vector projection; Neo4j = entity/relation graph; Redis = working-memory buffer + Celery broker), that projections are rebuildable from the record store, provisioning pointers to compose/K8s.
3. **Observability runbook** — correlation ids (X-Request-ID honored/echoed; every log line carries `request_id`); access log fields; metric names (`memcore_http_requests_total`, `memcore_http_request_duration_seconds` — route-template labels, unmatched → `unmatched`; `memcore_operation_duration_seconds{operation=recall|consolidation|decay_sweep}`); `/metrics` 501-without-extra behavior; worker exposition on `MEMCORE_METRICS_PORT` and the `--concurrency=1` constraint; `/ready` semantics (per-component, 503 degraded, error class names only).
4. **Memory operations** — importance/reinforcement in one paragraph (ADR-0015); decay + prune rails (score < 0.05 AND not `pinned` AND age ≥ 14d), `pinned` tag exemption, `POST /v1/decay` (per tenant, in-process dedupe only — prefork workers give no cross-process dedupe yet), restore (`POST /v1/memories/{id}/restore`, soft-deleted only; superseded versions cannot be soft-deleted), hard delete = GDPR-style permanent.
5. **Troubleshooting** — `/metrics` 501 → install `memcore[observability]`; `/ready` degraded → check the named component + server logs (full error text is server-side); consolidation jobs failing → LLM key/failover config; recall returning nothing → check tenant key mapping and that consolidation ran; first API start downloads the bge model (startupProbe budget in K8s).
6. **Known limits** (honest) — cross-process sweep dedupe + in-app rate limiting not implemented (edge-only); Postgres path not covered by CI integration yet; single-process worker metrics.

- [ ] **Step 2: Refresh `docs/design/architecture.md`**

Keep the existing two-paths/layers content (verify it still matches); add/extend concise sections: **Importance & decay** (effective importance at read time, decay snapshots + rail-guarded pruning; ADR-0015/0016), **Evaluation** (`python -m memcore.evaluation`, ADR-0017), **SDK** (async+sync clients, GET-only retries; ADR-0018), **Observability** (ids/metrics/probes; ADR-0019), **Deployment shape** (one image two roles, compose/K8s; ADR-0020). Link each ADR. Fix anything stale (e.g. if the outbox mention doesn't match current code, align the wording with what exists).

- [ ] **Step 3: Verify and commit**

Verify: run `./.venv/Scripts/python.exe -m ruff check .` (docs don't affect it — expected clean) and skim every table against `config.py` one final time. Full pytest suite unchanged.

```bash
git add docs/guides/operations.md docs/design/architecture.md
git commit -m "docs: operations guide + architecture refresh (Phase 12)"
```

---

### Task 4: Deployment walkthrough

**Files:**
- Create: `docs/guides/deployment.md`

**Interfaces:** none — prose grounded in the real Phase 11 artifacts (read `docker-compose.yml`, `.env.example`, `Dockerfile`, `deploy/k8s/*` and its README first; commands must be copy-paste correct).

- [ ] **Step 1: Write `docs/guides/deployment.md`**

Sections:

1. **Local: Docker Compose** — prerequisites (Docker); `cp .env.example .env`, edit `MEMCORE_API__KEYS` + `MEMCORE_LLM__API_KEY`; `docker compose up -d --build` (note: first build downloads torch — expect ~15–20 min); verify `curl http://localhost:8000/health` then `/ready`; run `python examples/quickstart_async.py`; inspect worker logs (`docker compose logs -f worker`); where metrics live (API :8000/metrics, worker :9100 — both non-public by convention); teardown (`docker compose down`, `-v` to drop data).
2. **Kubernetes** — prerequisites (cluster, kubectl, registry, separately provisioned backends per `deploy/k8s/README.md`); build & push the image, set `image:`; create the namespace/config; copy `secret.example.yaml` → `secret.yaml`, fill real values (API keys, graph password, LLM key, DB URL), apply; apply deployments/service/ingress in the README's order; verify rollout (`kubectl -n memcore rollout status deploy/memcore-api`), probe behavior (startupProbe covers the first-boot model download), port-forward + run an example; scraping (`/metrics` blocked at ingress — scrape the Service internally; worker on :9100); the `--concurrency=1` worker constraint and scaling via replicas.
3. **Production checklist** — real API keys (never dev-key), Secret hygiene (`secret.yaml` is gitignored), edge rate limits (ingress annotations; no in-app limiter), TLS at the ingress, backup Postgres (source of truth — projections are rebuildable), pin image tags (not `:latest`), resource sizing starting points from the manifests.

- [ ] **Step 2: Verify and commit**

Cross-check every command against the actual files (compose service names, k8s file names, README apply order). Full gate unchanged.

```bash
git add docs/guides/deployment.md
git commit -m "docs: deployment walkthrough — compose to Kubernetes (Phase 12)"
```

---

### Task 5: README overhaul, ADR-0021, phase gate — project completion

**Files:**
- Modify: `README.md`
- Create: `docs/adr/0021-documentation-strategy.md`
- Create: `docs/design/phase-12.md`
- Modify: `docs/adr/README.md`, `docs/design/roadmap.md` (Phase 12 → ✅ Complete — all 12 phases done), `CHANGELOG.md`, `PROJECT_STATE.md`

**Interfaces:** none — final documentation of the phase and the project.

- [ ] **Step 1: Overhaul `README.md`**

Keep the existing voice/tables (Why / Default stack / Architecture). Update: status line → v0.1 feature-complete, all 12 roadmap phases done; add **Quickstart** (SDK install `pip install 'memcore[sdk]'` + 6-line async snippet from the quickstart example; local stack via `cp .env.example .env && docker compose up -d --build`); add **Documentation** section linking `docs/api-reference.md`, `docs/sdk-quickstart.md`, `docs/guides/operations.md`, `docs/guides/deployment.md`, `examples/`, ADR index; add extras table (`sdk`, `api`, `observability`, backend extras, `dev`); keep it under ~120 lines.

- [ ] **Step 2: Write ADR-0021**

`docs/adr/0021-documentation-strategy.md` (match ADR-0020's style):
- **Status:** accepted. **Context:** hand-written docs rot; the project ships an API, an SDK, and deploy artifacts that all change.
- **Decision:** docs-as-code — (1) the API reference is generated from the live OpenAPI schema (`scripts/generate_api_reference.py`) with a CI drift test comparing byte-for-byte (operational endpoints excluded from the schema get a hand-maintained section inside the generator); (2) examples are executable scripts with `main(client)` seams, executed in CI against the in-process ASGI app; (3) guides are hand-written but every factual claim is source-verified at writing/review time; (4) phase docs + ADRs remain the historical record; guides are the living surface.
- **Consequences:** route/schema changes and SDK breaks fail CI docs tests instead of rotting silently; guides can still drift between reviews (accepted; the generated/executed layers cover the highest-churn surfaces); the generator is repo tooling in `scripts/`, deliberately outside the package.

Add to `docs/adr/README.md` index: `- [ADR-0021](0021-documentation-strategy.md) — Documentation: generated API reference + CI-executed examples, source-verified guides`.

- [ ] **Step 3: Phase doc + CHANGELOG + roadmap + PROJECT_STATE**

`docs/design/phase-12.md` (structure of `phase-11.md`): Delivered = generated API reference + drift test; 4 CI-tested examples + README; operations guide; architecture refresh; deployment walkthrough; README overhaul; ADR-0021. Deferred/backlog (post-v1) = SDK `restore_memory` method; distributed sweep dedupe + in-app rate limiting; per-role slim images; Helm chart; Postgres-in-CI contract test; prometheus multiprocess; Grafana dashboards; real-corpus evaluation datasets. Record real gate numbers.

`CHANGELOG.md` — new block above Phase 11:

```markdown
### Added — Phase 12: Documentation & examples
- `docs/api-reference.md` generated from the OpenAPI schema by
  `scripts/generate_api_reference.py`; a CI drift test keeps it current —
  ADR-0021.
- `examples/`: four runnable SDK scripts (async/sync quickstarts, memory
  lifecycle, sessions + consolidation), each executed in CI against the
  in-process app.
- `docs/guides/operations.md` (config reference, backing services,
  observability runbook, memory ops, troubleshooting, known limits) and
  `docs/guides/deployment.md` (compose → Kubernetes walkthrough);
  `docs/design/architecture.md` refreshed through Phase 11.
- README overhauled: v0.1 feature-complete, quickstart, docs index, extras
  table. All 12 roadmap phases complete.
```

`docs/design/roadmap.md`: Phase 12 → `✅ Complete`. Add a closing line: all 12 phases complete (v0.1); future work tracked in `PROJECT_STATE.md` backlog.

`PROJECT_STATE.md`: current position → **ALL 12 PHASES COMPLETE — v0.1 feature-complete**; last gate numbers; replace "Next tasks" with a **Post-v1 backlog** (the deferred list from phase-12.md); open decisions → "define the post-v1 roadmap (none pending)".

- [ ] **Step 4: Run the phase gate and record numbers**

Run: `./.venv/Scripts/python.exe -m pytest` (record pass count + coverage %), `./.venv/Scripts/python.exe -m ruff check .`, `./.venv/Scripts/python.exe -m mypy`
Expected: all clean, coverage ≥ 85%. Copy the real numbers into `phase-12.md` and `PROJECT_STATE.md`.

- [ ] **Step 5: Phase commit**

```bash
git add README.md docs/adr/0021-documentation-strategy.md docs/adr/README.md docs/design/phase-12.md docs/design/roadmap.md CHANGELOG.md PROJECT_STATE.md
git commit -m "docs: Phase 12 gate — documentation & examples; roadmap complete (ADR-0021)"
```

Then STOP: the 12-phase roadmap is complete — report project completion to the user.
