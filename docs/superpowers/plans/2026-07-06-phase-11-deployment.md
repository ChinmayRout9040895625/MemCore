# Phase 11 — Deployment (Docker, K8s, CI/CD) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship MemCore as a deployable system — restore endpoint + sweep-dedupe + worker metric exposition (the carried operational backlog), a multi-stage Dockerfile and full docker-compose stack, Kubernetes manifests wiring the `/health` and `/ready` probes, and a CI pipeline that runs the full gate plus the integration suite against live backend containers.

**Architecture:** Three small code tasks first (all TDD, hexagonal-clean: a `restore` service method + route; an in-process per-tenant asyncio lock serialising decay sweeps; a lazy `start_metrics_server` so Celery workers expose their recorded metrics over HTTP). Then three infra tasks: a distroless-ish multi-stage `Dockerfile` serving `memcore.api:create_app` via uvicorn (worker shares the image, different command); `docker-compose.yml` extended from the current backends-only file to a full API+worker+Postgres+Qdrant+Neo4j+Redis stack; `deploy/k8s/` manifests with liveness=`/health`, readiness=`/ready`; and a CI expansion (integration job with service containers + image build). Rate limiting is placed at the ingress layer (K8s annotations + documented) rather than in-app — a correct distributed limiter needs Redis and is disproportionate here.

**Tech Stack:** Python 3.11+ (existing), uvicorn (`api` extra), prometheus-client (`observability` extra), Docker multi-stage (python:3.12-slim), docker-compose v2, Kubernetes (plain manifests, no Helm), GitHub Actions.

## Global Constraints

- Quality gate for CODE tasks (1–3), before commit: `./.venv/Scripts/python.exe -m pytest` all pass, coverage ≥ 85%; `./.venv/Scripts/python.exe -m ruff check .` clean; `./.venv/Scripts/python.exe -m mypy` clean (strict).
- Verification gate for INFRA tasks (4–6): the named validation command must succeed (`docker compose config`, `python -c "import yaml; ..."` parse of every manifest, `docker build` where Docker is available); INFRA tasks add no Python and must not change the pytest/coverage numbers.
- Hexagonal: `services/*`, `domain/*`, `ports/*` keep importing ports/stdlib only. Task 3's HTTP server lives in `memcore.observability.metrics` (already the lazy-prometheus home) and is invoked from the worker entrypoint — not from services.
- No secrets in the repo: compose uses dev-only defaults with clear "change in production" comments; K8s reads credentials from a `Secret` (a committed `*.example` template with placeholders, never real values).
- Image runs as a non-root user; `.dockerignore` excludes `.venv`, `.git`, tests, caches, `docs`.
- Env-var config unchanged: `MEMCORE_*` nested delimiter `__` (e.g. `MEMCORE_DATABASE__URL`). Worker metrics port via `MEMCORE_METRICS_PORT` (unset = disabled) — read directly from env in the worker entrypoint, no new `Settings` block (consistent with ADR-0019's "log level + extra gate observability, no new Settings").
- One commit per task; phase gate + docs in Task 6; WAIT for user approval after the phase commit.

---

### Task 1: Restore endpoint for soft-deleted records

**Files:**
- Modify: `src/memcore/domain/enums.py` (add `AuditAction.RESTORE`)
- Modify: `src/memcore/services/memories.py` (add `restore`)
- Modify: `src/memcore/api/routes.py` (add `POST /v1/memories/{memory_id}/restore`)
- Test: `tests/unit/test_services.py`, `tests/unit/test_api.py`

**Interfaces:**
- Consumes: `MemoryStore.get`/`set_status`, `MemoryService._index`, `MemoryStatus`, `AuditAction`.
- Produces (Task references, docs):
  - `AuditAction.RESTORE = "restore"`.
  - `MemoryService.restore(self, tenant_id: str, memory_id: str) -> MemoryRecord` — flips a `SOFT_DELETED` record back to `ACTIVE`, re-indexes its vector, audits `RESTORE`; raises `NotFoundError` if absent/hard-deleted, `ValidationError` if the record is not `SOFT_DELETED`.
  - `POST /v1/memories/{memory_id}/restore` → 200 `MemoryResponse`.

- [ ] **Step 1: Write the failing service tests**

Add to `tests/unit/test_services.py` (uses the existing `memory_setup` fixture returning `(MemoryService, RecallService, InMemoryVectorStore)` and module constants `TENANT, AGENT`; imports already include `MemoryStatus`, `NotFoundError`, `ValidationError`):

```python
async def test_restore_soft_deleted_record(
    memory_setup: tuple[MemoryService, RecallService, InMemoryVectorStore],
) -> None:
    memories, recall, vectors = memory_setup
    record = await memories.remember(TENANT, AGENT, "Bruno is a beagle.")
    await memories.forget(TENANT, record.id, mode="soft")

    restored = await memories.restore(TENANT, record.id)
    assert restored.id == record.id
    assert restored.status is MemoryStatus.ACTIVE
    # Re-indexed: recall can surface it again.
    results = await recall.recall(TENANT, AGENT, "beagle")
    assert record.id in {s.memory.id for s in results}
    # Audit trail records the restore.
    events = await memories._store.list_audit(TENANT)
    assert any(
        e.action is AuditAction.RESTORE and e.target_id == record.id for e in events
    )


async def test_restore_rejects_active_record(
    memory_setup: tuple[MemoryService, RecallService, InMemoryVectorStore],
) -> None:
    memories, _, _ = memory_setup
    record = await memories.remember(TENANT, AGENT, "still active")
    with pytest.raises(ValidationError):
        await memories.restore(TENANT, record.id)


async def test_restore_missing_record_is_not_found(
    memory_setup: tuple[MemoryService, RecallService, InMemoryVectorStore],
) -> None:
    memories, _, _ = memory_setup
    with pytest.raises(NotFoundError):
        await memories.restore(TENANT, "no-such-id")
```

Add `AuditAction` to the `from memcore.domain.enums import ...` line in that test file if not already imported.

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_services.py -v -k restore`
Expected: FAIL — `AttributeError: 'MemoryService' object has no attribute 'restore'`.

- [ ] **Step 3: Implement the enum + service method**

`src/memcore/domain/enums.py` — add to `AuditAction` after `ERASE`:

```python
    RESTORE = "restore"
```

`src/memcore/services/memories.py` — add after `forget`:

```python
    async def restore(self, tenant_id: str, memory_id: str) -> MemoryRecord:
        """Bring a soft-deleted record back to ACTIVE and re-index it.

        The inverse of ``forget(mode="soft")``. Hard-deleted records are gone
        (``NotFoundError``); a record that is not soft-deleted cannot be
        restored (``ValidationError``).
        """
        record = await self._store.get(tenant_id, memory_id)
        if record is None or record.status is MemoryStatus.HARD_DELETED:
            raise NotFoundError(f"memory {memory_id} not found")
        if record.status is not MemoryStatus.SOFT_DELETED:
            raise ValidationError(
                f"memory {memory_id} is {record.status.value}, not soft-deleted"
            )
        await self._store.set_status(tenant_id, memory_id, MemoryStatus.ACTIVE)
        restored = record.model_copy(update={"status": MemoryStatus.ACTIVE})
        await self._index(restored)  # re-add to the retrievable vector index
        await self._audit(tenant_id, AuditAction.RESTORE, memory_id,
                          reason="restore soft-deleted")
        return restored
```

- [ ] **Step 4: Run service tests to verify pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_services.py -v -k restore`
Expected: all PASS.

- [ ] **Step 5: Write the failing API test**

Add to `tests/unit/test_api.py` (uses the `client` fixture + `_h()` helper + `KEY_T1`):

```python
async def test_restore_endpoint_round_trip(client: AsyncClient) -> None:
    created = await client.post(
        "/v1/memories", json={"agent_id": "a1", "content": "restore me"},
        headers=_h(),
    )
    memory_id = created.json()["memory"]["id"]
    # Soft delete, then restore.
    deleted = await client.delete(f"/v1/memories/{memory_id}", headers=_h())
    assert deleted.status_code == 204
    restored = await client.post(
        f"/v1/memories/{memory_id}/restore", headers=_h()
    )
    assert restored.status_code == 200
    assert restored.json()["memory"]["status"] == "active"
    # A restored record is fetchable again.
    got = await client.get(f"/v1/memories/{memory_id}", headers=_h())
    assert got.status_code == 200


async def test_restore_is_tenant_scoped(client: AsyncClient) -> None:
    created = await client.post(
        "/v1/memories", json={"agent_id": "a1", "content": "tenant one only"},
        headers=_h(),
    )
    memory_id = created.json()["memory"]["id"]
    await client.delete(f"/v1/memories/{memory_id}", headers=_h())
    # Tenant 2 cannot restore tenant 1's record.
    other = await client.post(
        f"/v1/memories/{memory_id}/restore", headers=_h(KEY_T2)
    )
    assert other.status_code == 404
```

(Add `KEY_T2` to the test's imports/usage if not already referenced — it is defined at module top alongside `KEY_T1`.)

- [ ] **Step 6: Implement the route**

`src/memcore/api/routes.py` — add after `forget_memory`:

```python
@router.post("/memories/{memory_id}/restore", response_model=MemoryResponse)
async def restore_memory(
    memory_id: str, state: StateDep, tenant: TenantDep
) -> MemoryResponse:
    record = await state.memories.restore(tenant, memory_id)
    return MemoryResponse(memory=record)
```

- [ ] **Step 7: Run tests, then full gate**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_api.py tests/unit/test_services.py -v`
Expected: all PASS.
Then: `./.venv/Scripts/python.exe -m pytest && ./.venv/Scripts/python.exe -m ruff check . && ./.venv/Scripts/python.exe -m mypy`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/memcore/domain/enums.py src/memcore/services/memories.py src/memcore/api/routes.py tests/unit/test_services.py tests/unit/test_api.py
git commit -m "feat(api): restore endpoint for soft-deleted records (Phase 11)"
```

---

### Task 2: Per-tenant sweep dedupe (in-process concurrency guard)

**Files:**
- Modify: `src/memcore/services/decay.py` (per-tenant asyncio lock)
- Test: `tests/unit/test_decay.py`

**Interfaces:**
- Consumes: existing `DecayService.sweep`.
- Produces: `DecayService.sweep` is serialised per tenant within one process — concurrent sweeps for the same tenant run one-at-a-time (the later one finds candidates already pruned; idempotent). Cross-tenant sweeps still run concurrently. Cross-process dedupe (multiple workers) is a documented deferral (needs a Redis lock).

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_decay.py` (uses the file's `_Env`, `TENANT`, `utcnow`, `timedelta`, `MemoryStatus`):

```python
async def test_concurrent_sweeps_same_tenant_prune_once() -> None:
    import asyncio

    env = _Env()
    ancient = await env.seed("forgotten trivia", age=timedelta(days=365))

    # Two overlapping sweeps for the same tenant must not double-prune or race
    # the audit trail: the per-tenant lock serialises them.
    first, second = await asyncio.gather(
        env.decay.sweep(TENANT), env.decay.sweep(TENANT)
    )

    total_pruned = first.pruned + second.pruned
    assert total_pruned == 1  # exactly one sweep pruned the record
    pruned = await env.store.get(TENANT, ancient.id)
    assert pruned is not None and pruned.status is MemoryStatus.SOFT_DELETED


async def test_different_tenants_are_not_serialised() -> None:
    # A lock keyed per tenant must not block a different tenant's sweep.
    env = _Env()
    await env.seed("t1 fact", age=timedelta(days=365))
    report_a = await env.decay.sweep(TENANT)
    report_b = await env.decay.sweep("t2")  # empty tenant, independent lock
    assert report_a.pruned == 1
    assert report_b.scanned == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_decay.py -v -k "concurrent or serialised"`
Expected: `test_concurrent_sweeps_same_tenant_prune_once` may already pass by luck (single-threaded ordering) OR flake; the `different_tenants` test passes trivially. The lock makes the concurrent-sweep guarantee deterministic rather than incidental. If the concurrent test already passes, keep it as a regression guard and proceed — the lock's value is preventing interleaved audit/prune races under real concurrency.

(Note to implementer: this test documents intended behaviour; the lock is the mechanism that makes it hold under genuine interleaving. Do not weaken the `total_pruned == 1` assertion.)

- [ ] **Step 3: Implement the per-tenant lock**

`src/memcore/services/decay.py` — in `DecayService.__init__`, add a lock registry:

```python
        self._locks: dict[str, asyncio.Lock] = {}
```

(add `import asyncio` at the top of the file.) Add a helper and wrap `sweep`'s body:

```python
    def _lock_for(self, tenant_id: str) -> asyncio.Lock:
        lock = self._locks.get(tenant_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[tenant_id] = lock
        return lock

    async def sweep(self, tenant_id: str) -> DecayReport:
        async with self._lock_for(tenant_id):
            return await self._sweep(tenant_id)

    async def _sweep(self, tenant_id: str) -> DecayReport:
        # (the existing sweep body, renamed — no logic change)
        ...
```

Rename the current `sweep` body to `_sweep` verbatim (no other change). The public `sweep` now acquires the per-tenant lock first. Update the class docstring's idempotency paragraph to note the in-process per-tenant serialisation (and that cross-process dedupe via a distributed lock is deferred).

- [ ] **Step 4: Run decay tests, then full gate**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_decay.py -v`
Expected: all PASS (existing sweep tests unaffected — behaviour is identical, just serialised).
Then the full gate. Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/memcore/services/decay.py tests/unit/test_decay.py
git commit -m "feat(decay): per-tenant in-process sweep dedupe lock (Phase 11)"
```

---

### Task 3: Worker metric exposition

**Files:**
- Modify: `src/memcore/observability/metrics.py` (add `start_metrics_server`)
- Modify: `src/memcore/observability/__init__.py` (export)
- Modify: `src/memcore/workers/celery_app.py` (start the server on worker init when `MEMCORE_METRICS_PORT` is set)
- Test: `tests/unit/test_observability_metrics.py`

**Interfaces:**
- Consumes: the module's `_load()` cache + registry.
- Produces: `start_metrics_server(port: int) -> None` — serves the custom registry's exposition over HTTP on `port`; raises `ConfigurationError` (install hint) when the extra is absent; the Celery worker calls it on `worker_process_init` when `MEMCORE_METRICS_PORT` is set.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_observability_metrics.py`:

```python
def test_start_metrics_server_serves_exposition() -> None:
    import urllib.request

    from memcore.observability import metrics

    metrics.observe_operation("recall", 0.01)
    # Port 0 asks the OS for a free port; capture it from the returned server.
    server = metrics.start_metrics_server(0)
    try:
        port = server.server_port  # http.server.HTTPServer attribute
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            body = resp.read().decode()
        assert "memcore_operation_duration_seconds" in body
    finally:
        server.shutdown()


def test_start_metrics_server_raises_without_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    from memcore.observability import metrics

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("prometheus_client"):
            raise ImportError("no prometheus")
        return real_import(name, *args, **kwargs)

    saved = dict(metrics._cache)
    metrics._cache.clear()
    monkeypatch.setattr(builtins, "__import__", fake_import)
    try:
        with pytest.raises(ConfigurationError, match=r"memcore\[observability\]"):
            metrics.start_metrics_server(0)
    finally:
        monkeypatch.undo()
        metrics._cache.clear()
        metrics._cache.update(saved)
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_observability_metrics.py -v -k start_metrics`
Expected: FAIL — `AttributeError: module 'memcore.observability.metrics' has no attribute 'start_metrics_server'`.

- [ ] **Step 3: Implement `start_metrics_server`**

`src/memcore/observability/metrics.py` — add after `render`:

```python
def start_metrics_server(port: int) -> Any:
    """Start an HTTP server exposing this process's metric registry.

    Used by the Celery worker (which has no ASGI app) so its recorded
    operation latencies are scrapeable. Returns the ``HTTPServer`` so callers
    can shut it down; raises :class:`ConfigurationError` without the extra.
    """
    cache = _load()
    if cache is None:
        raise ConfigurationError(_INSTALL_HINT)
    from prometheus_client import start_http_server

    server, _thread = start_http_server(port, registry=cache["registry"])
    return server
```

(Note: `prometheus_client.start_http_server` returns `(server, thread)` in modern versions. If the installed version returns `None`, adapt: bind via `prometheus_client.exposition.make_server` — but the pinned `>=0.20` returns the tuple. Verify the return shape at implementation time and adjust the unpack + test's `server.server_port` accordingly; the test needs a handle exposing `server_port` and `shutdown()`.)

Export from `src/memcore/observability/__init__.py`: add `start_metrics_server` to the `from memcore.observability.metrics import ...`? No — `metrics` is exported as a module. Add nothing new to `__all__`; callers use `metrics.start_metrics_server`. (Leave `__init__.py` unchanged unless it re-exports individual functions — it exports the `metrics` module, which already surfaces this.)

- [ ] **Step 4: Wire the worker entrypoint**

`src/memcore/workers/celery_app.py` — after `configure_logging(...)` near the top, add:

```python
import os

from celery.signals import worker_process_init


@worker_process_init.connect
def _start_worker_metrics(**_kwargs: Any) -> None:
    """Expose per-worker metrics when MEMCORE_METRICS_PORT is set."""
    port = os.getenv("MEMCORE_METRICS_PORT")
    if not port:
        return
    from memcore.observability import metrics

    try:
        metrics.start_metrics_server(int(port))
        logger.info("worker metrics server started", extra={"port": port})
    except Exception as exc:  # noqa: BLE001 - never let metrics kill a worker
        logger.warning("worker metrics server failed", extra={"error": str(exc)})
```

(place the `import os` and signal import with the other imports; keep the existing mypy override for this file.)

- [ ] **Step 5: Run tests, then full gate**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_observability_metrics.py -v`
Expected: all PASS.
Then the full gate. Expected: clean. (The worker signal handler is exercised indirectly; if coverage on `celery_app.py` drops the gate, note it — that module already carries a mypy override and is largely integration-shaped.)

- [ ] **Step 6: Commit**

```bash
git add src/memcore/observability/metrics.py src/memcore/observability/__init__.py src/memcore/workers/celery_app.py tests/unit/test_observability_metrics.py
git commit -m "feat(obs): worker Prometheus exposition via MEMCORE_METRICS_PORT (Phase 11)"
```

---

### Task 4: Dockerfile + full docker-compose stack

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Modify: `docker-compose.yml` (add `postgres`, `api`, `worker` services to the existing backends)
- Create: `.env.example` (compose env template — dev defaults, placeholder secrets)

**Interfaces:**
- Produces: an image running the API (`uvicorn --factory memcore.api:create_app`) or the worker (`celery -A memcore.workers.celery_app worker`) via command override; a compose stack bringing up the whole system.

- [ ] **Step 1: Write the Dockerfile**

Create `Dockerfile`:

```dockerfile
# Multi-stage build for MemCore. Stage 1 installs the package + runtime extras
# into a venv; stage 2 is a slim runtime that copies only the venv + source.
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy metadata first for layer caching, then source.
COPY pyproject.toml README.md ./
COPY src ./src
# Runtime extras: full default backend set + api server + observability.
RUN pip install ".[api,sql,postgres,vector,graph,working,scheduler,llm,embeddings,observability]"

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Non-root runtime user.
RUN useradd --create-home --uid 10001 memcore
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/src /app/src
WORKDIR /app
ENV PYTHONPATH=/app/src
USER memcore

EXPOSE 8000
# Default command runs the API; the worker service overrides `command`.
CMD ["uvicorn", "--factory", "memcore.api:create_app", \
     "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Write `.dockerignore`**

Create `.dockerignore`:

```
.git
.github
.venv
venv
**/__pycache__
**/*.pyc
.pytest_cache
.mypy_cache
.ruff_cache
htmlcov
.coverage
tests
docs
.superpowers
*.md
!README.md
.env
.env.*
!.env.example
```

- [ ] **Step 3: Write `.env.example`**

Create `.env.example`:

```dotenv
# Copy to .env for `docker compose up`. DEV DEFAULTS — change before production.
MEMCORE_ENV=local
MEMCORE_LOG_JSON=true

# API auth: JSON map of api-key -> tenant_id. CHANGE THIS.
MEMCORE_API__KEYS={"dev-key":"local"}

# Backends (compose service DNS names).
MEMCORE_DATABASE__URL=postgresql+asyncpg://memcore:memcore@postgres:5432/memcore
MEMCORE_VECTOR__URL=http://qdrant:6333
MEMCORE_GRAPH__URL=bolt://neo4j:7687
MEMCORE_GRAPH__PASSWORD=memcore-dev-password
MEMCORE_REDIS__URL=redis://redis:6379/0
MEMCORE_SCHEDULER__BROKER_URL=redis://redis:6379/1

# LLM: set a real key to enable consolidation; blank falls back to Ollama/none.
MEMCORE_LLM__API_KEY=

# Worker metric exposition (Prometheus scrape port); unset = disabled.
MEMCORE_METRICS_PORT=9100
```

- [ ] **Step 4: Extend docker-compose**

Modify `docker-compose.yml` — keep the existing `qdrant`/`neo4j`/`redis` services and `volumes`, add `postgres`, `api`, `worker`. Add after the `redis` service (before `volumes:`):

```yaml
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: memcore
      POSTGRES_PASSWORD: memcore
      POSTGRES_DB: memcore
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U memcore"]
      interval: 10s
      timeout: 5s
      retries: 5

  api:
    build: .
    env_file: .env
    ports:
      - "8000:8000"
    depends_on:
      postgres: {condition: service_healthy}
      qdrant: {condition: service_healthy}
      neo4j: {condition: service_healthy}
      redis: {condition: service_healthy}
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\""]
      interval: 15s
      timeout: 5s
      retries: 5

  worker:
    build: .
    command: ["celery", "-A", "memcore.workers.celery_app", "worker", "--loglevel=info"]
    env_file: .env
    depends_on:
      redis: {condition: service_healthy}
      postgres: {condition: service_healthy}
```

And add `postgres_data:` to the `volumes:` block.

- [ ] **Step 5: Validate the compose file**

Run: `docker compose config >/dev/null && echo "compose OK"`
Expected: `compose OK` (validates YAML + interpolation; needs a `.env` — `cp .env.example .env` first, or `docker compose --env-file .env.example config`).
If Docker is unavailable in this environment, fall back to: `python -c "import yaml,sys; yaml.safe_load(open('docker-compose.yml')); print('yaml OK')"` and note that `docker build`/`compose config` run in CI (Task 6).

- [ ] **Step 6: Validate the Dockerfile builds (best-effort)**

Run: `docker build -t memcore:phase11-test . && echo "build OK"`
Expected: `build OK`. If Docker is unavailable, note it — the build is exercised by CI's image job (Task 6). Do not fake success.

- [ ] **Step 7: Commit**

```bash
git add Dockerfile .dockerignore docker-compose.yml .env.example
git commit -m "feat(deploy): multi-stage Dockerfile + full docker-compose stack (Phase 11)"
```

---

### Task 5: Kubernetes manifests

**Files:**
- Create: `deploy/k8s/namespace.yaml`
- Create: `deploy/k8s/configmap.yaml`
- Create: `deploy/k8s/secret.example.yaml`
- Create: `deploy/k8s/api-deployment.yaml`
- Create: `deploy/k8s/api-service.yaml`
- Create: `deploy/k8s/worker-deployment.yaml`
- Create: `deploy/k8s/ingress.yaml`
- Create: `deploy/k8s/README.md`

**Interfaces:**
- Produces: applyable manifests; the API Deployment wires `livenessProbe → /health`, `readinessProbe → /ready`; worker Deployment runs the celery command with the metrics port; ingress terminates external traffic and keeps `/ready` + `/metrics` internal.

- [ ] **Step 1: Namespace + config**

Create `deploy/k8s/namespace.yaml`:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: memcore
```

Create `deploy/k8s/configmap.yaml` (non-secret env — backend DNS, ports):

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: memcore-config
  namespace: memcore
data:
  MEMCORE_ENV: "production"
  MEMCORE_LOG_JSON: "true"
  MEMCORE_DATABASE__URL: "postgresql+asyncpg://memcore:memcore@postgres:5432/memcore"
  MEMCORE_VECTOR__URL: "http://qdrant:6333"
  MEMCORE_GRAPH__URL: "bolt://neo4j:7687"
  MEMCORE_REDIS__URL: "redis://redis:6379/0"
  MEMCORE_SCHEDULER__BROKER_URL: "redis://redis:6379/1"
  MEMCORE_METRICS_PORT: "9100"
```

Create `deploy/k8s/secret.example.yaml` (TEMPLATE — placeholders, never real values; copy to `secret.yaml`, fill, and keep out of git):

```yaml
# Copy to secret.yaml, fill in real values, apply separately. DO NOT COMMIT secret.yaml.
apiVersion: v1
kind: Secret
metadata:
  name: memcore-secrets
  namespace: memcore
type: Opaque
stringData:
  MEMCORE_API__KEYS: '{"REPLACE-WITH-REAL-KEY":"tenant-id"}'
  MEMCORE_GRAPH__PASSWORD: "REPLACE-ME"
  MEMCORE_LLM__API_KEY: "REPLACE-ME"
```

- [ ] **Step 2: API deployment + service with probes**

Create `deploy/k8s/api-deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: memcore-api
  namespace: memcore
  labels: {app: memcore, component: api}
spec:
  replicas: 2
  selector:
    matchLabels: {app: memcore, component: api}
  template:
    metadata:
      labels: {app: memcore, component: api}
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
      containers:
        - name: api
          image: memcore:latest   # replace with your registry tag
          ports:
            - {name: http, containerPort: 8000}
          envFrom:
            - configMapRef: {name: memcore-config}
            - secretRef: {name: memcore-secrets}
          livenessProbe:
            httpGet: {path: /health, port: http}
            initialDelaySeconds: 10
            periodSeconds: 15
          readinessProbe:
            httpGet: {path: /ready, port: http}
            initialDelaySeconds: 5
            periodSeconds: 10
            failureThreshold: 3
          resources:
            requests: {cpu: "250m", memory: "512Mi"}
            limits: {cpu: "1", memory: "1Gi"}
```

Create `deploy/k8s/api-service.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: memcore-api
  namespace: memcore
  labels: {app: memcore, component: api}
spec:
  selector: {app: memcore, component: api}
  ports:
    - {name: http, port: 80, targetPort: http}
```

- [ ] **Step 3: Worker deployment**

Create `deploy/k8s/worker-deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: memcore-worker
  namespace: memcore
  labels: {app: memcore, component: worker}
spec:
  replicas: 1
  selector:
    matchLabels: {app: memcore, component: worker}
  template:
    metadata:
      labels: {app: memcore, component: worker}
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
      containers:
        - name: worker
          image: memcore:latest   # replace with your registry tag
          command: ["celery", "-A", "memcore.workers.celery_app", "worker", "--loglevel=info"]
          ports:
            - {name: metrics, containerPort: 9100}
          envFrom:
            - configMapRef: {name: memcore-config}
            - secretRef: {name: memcore-secrets}
          resources:
            requests: {cpu: "250m", memory: "512Mi"}
            limits: {cpu: "1", memory: "1Gi"}
```

- [ ] **Step 4: Ingress (external traffic + rate limiting; probes stay internal)**

Create `deploy/k8s/ingress.yaml`:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: memcore-api
  namespace: memcore
  annotations:
    # Rate limiting lives at the edge (nginx-ingress). Per-client cap:
    nginx.ingress.kubernetes.io/limit-rps: "20"
    nginx.ingress.kubernetes.io/limit-burst-multiplier: "3"
    # Keep ops-only endpoints off the public path.
    nginx.ingress.kubernetes.io/server-snippet: |
      location = /ready { deny all; return 404; }
      location = /metrics { deny all; return 404; }
spec:
  rules:
    - host: memcore.example.com   # replace
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: memcore-api
                port: {name: http}
```

- [ ] **Step 5: Deploy README**

Create `deploy/k8s/README.md`: apply order (`namespace` → `configmap` → `secret` (from your filled copy) → deployments → service → ingress), the `kubectl -n memcore apply -f deploy/k8s/` one-liner (excluding `secret.example.yaml`), how to build/push the image and set `image:`, and the note that `/ready` + `/metrics` are cluster-internal (blocked at ingress; scrape `/metrics` via a `ServiceMonitor`/internal Service, worker metrics on `:9100`).

- [ ] **Step 6: Validate every manifest parses**

Run (validates YAML syntax for every manifest — works without a cluster):
```bash
for f in deploy/k8s/*.yaml; do python -c "import yaml,sys; list(yaml.safe_load_all(open('$f'))); print('OK', '$f')"; done
```
Expected: `OK` for each file.
If `kubectl` is available, additionally: `kubectl apply --dry-run=client -f deploy/k8s/ --validate=false` (server validation runs in a real cluster). Do not fake success if the tools are absent — the YAML parse is the guaranteed check.

- [ ] **Step 7: Commit**

```bash
git add deploy/k8s/
git commit -m "feat(deploy): Kubernetes manifests with /health + /ready probes (Phase 11)"
```

---

### Task 6: CI expansion + docs, ADR-0020 — phase gate

**Files:**
- Modify: `.github/workflows/ci.yml` (integration job + image-build job)
- Create: `docs/adr/0020-deployment.md`
- Create: `docs/design/phase-11.md`
- Modify: `docs/adr/README.md`, `docs/design/roadmap.md` (Phase 11 → ✅ Complete, Phase 12 → ⏳ Next), `CHANGELOG.md`, `PROJECT_STATE.md`

**Interfaces:** none — CI + documentation of Tasks 1–5 exactly as built.

- [ ] **Step 1: Expand CI**

Modify `.github/workflows/ci.yml` — keep the existing `test` matrix job, add two jobs:

```yaml
  integration:
    runs-on: ubuntu-latest
    services:
      qdrant:
        image: qdrant/qdrant:v1.12.1
        ports: ["6333:6333"]
      neo4j:
        image: neo4j:5.24-community
        env:
          NEO4J_AUTH: neo4j/memcore-dev-password
        ports: ["7687:7687"]
      redis:
        image: redis:7.4-alpine
        ports: ["6379:6379"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12", cache: pip}
      - name: Install
        run: pip install -e ".[dev,vector,graph,working,api,sql,scheduler,observability]"
      - name: Wait for backends
        run: |
          for i in $(seq 1 30); do
            (exec 3<>/dev/tcp/localhost/6333) 2>/dev/null && \
            (exec 3<>/dev/tcp/localhost/7687) 2>/dev/null && \
            redis-cli -h localhost ping 2>/dev/null | grep -q PONG && break
            sleep 2
          done
      - name: Integration tests
        env:
          MEMCORE_GRAPH__PASSWORD: memcore-dev-password
        run: pytest -m integration

  docker:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build image
        run: docker build -t memcore:ci .
      - name: Validate compose
        run: docker compose --env-file .env.example config >/dev/null
```

(the existing `test` job already runs `pytest`, which excludes integration by the `-m integration` marker default-skip — confirm the default `pytest` run does not require live backends; it doesn't, per the integration suite's skip-on-unreachable design.)

- [ ] **Step 2: Write ADR-0020**

`docs/adr/0020-deployment.md` (match ADR-0019's style):
- **Status:** accepted. **Context:** MemCore ran only from a dev checkout; no container image, no orchestration, no CI coverage of live backends.
- **Decision:** (1) one multi-stage image (python:3.12-slim, non-root uid 10001) serves the API via `uvicorn --factory memcore.api:create_app` and, with a command override, the Celery worker — one artifact, two roles; (2) `docker-compose.yml` is the full local stack (API+worker+Postgres+Qdrant+Neo4j+Redis) with healthchecks + `depends_on: service_healthy`; (3) Kubernetes manifests under `deploy/k8s/` wire `livenessProbe→/health` and `readinessProbe→/ready` (Phase 10's endpoints), config via ConfigMap, credentials via a Secret template (real `secret.yaml` never committed); (4) rate limiting is an edge concern — nginx-ingress `limit-rps` annotations — not an in-app limiter (a correct distributed limiter needs Redis and is out of proportion; documented, revisitable); `/ready` + `/metrics` are blocked at the ingress and scraped cluster-internally; (5) worker metric exposition via `start_metrics_server` on `worker_process_init` when `MEMCORE_METRICS_PORT` is set (workers have no ASGI app); (6) CI gains an integration job (service containers) and an image-build job; (7) operational backlog closed: restore endpoint (`POST /v1/memories/{id}/restore`) and per-tenant in-process sweep dedupe (cross-process distributed dedupe deferred — needs a Redis lock).
- **Consequences:** deployable to any Docker/K8s target; probes give the orchestrator real readiness; CI now catches adapter regressions against real backends; the image carries all default-stack extras (larger image, simpler ops) — a slimmer per-role image is a future optimisation.

Add to `docs/adr/README.md` index: `- [ADR-0020](0020-deployment.md) — Deployment: one image/two roles, compose stack, K8s probes, CI integration + image build`.

- [ ] **Step 3: Phase doc + CHANGELOG + roadmap + PROJECT_STATE**

`docs/design/phase-11.md`, same structure as `phase-10.md`: Delivered = restore endpoint; per-tenant sweep dedupe; worker metric exposition; Dockerfile + `.dockerignore` + `.env.example`; full docker-compose stack; `deploy/k8s/` manifests; CI integration + docker jobs. Deferred = distributed (cross-process) sweep dedupe via Redis lock; in-app/distributed rate limiting; per-role slim images; Helm chart; slimmer image. Record the actual gate numbers.

`CHANGELOG.md` — new block above Phase 10:

```markdown
### Added — Phase 11: Deployment (Docker, K8s, CI/CD)
- Multi-stage `Dockerfile` (non-root) serving the API via uvicorn or the
  Celery worker by command override; `.dockerignore`, `.env.example` — ADR-0020.
- Full `docker-compose.yml` stack: API + worker + Postgres + Qdrant + Neo4j
  + Redis with healthchecks and `depends_on: service_healthy`.
- Kubernetes manifests (`deploy/k8s/`): API/worker Deployments, Service,
  ConfigMap, Secret template, Ingress; `livenessProbe→/health`,
  `readinessProbe→/ready`; edge rate limiting + internal-only ops endpoints.
- Worker Prometheus exposition via `start_metrics_server` on worker init
  (`MEMCORE_METRICS_PORT`).
- CI: integration job (Qdrant/Neo4j/Redis service containers) + image build.
- Operational backlog closed: `POST /v1/memories/{id}/restore` for
  soft-deleted records; per-tenant in-process decay-sweep dedupe lock.
```

`docs/design/roadmap.md`: Phase 11 → `✅ Complete`, Phase 12 → `⏳ Next`.

`PROJECT_STATE.md`: current position → Phase 11 complete / Phase 12 (Documentation & examples) not started, awaiting approval; record the gate numbers; next tasks → Phase 12 outline (API reference from the OpenAPI schema, architecture/operations guides, runnable end-to-end examples using the SDK, deployment walkthrough); remaining deferrals → distributed sweep dedupe + in-app rate limiting, per-role slim images, Helm chart; open decision → approve Phase 12 start.

- [ ] **Step 4: Run the phase gate and record numbers**

Run: `./.venv/Scripts/python.exe -m pytest` (record pass count + coverage %), `./.venv/Scripts/python.exe -m ruff check .`, `./.venv/Scripts/python.exe -m mypy`
Expected: all clean, coverage ≥ 85%. Copy the real numbers into `phase-11.md` and `PROJECT_STATE.md`. Also validate the CI YAML parses: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('ci yaml OK')"`.

- [ ] **Step 5: Phase commit**

```bash
git add .github/workflows/ci.yml docs/adr/0020-deployment.md docs/adr/README.md docs/design/phase-11.md docs/design/roadmap.md CHANGELOG.md PROJECT_STATE.md
git commit -m "docs: Phase 11 gate — deployment (ADR-0020, Docker/K8s/CI)"
```

Then STOP: per the phase gate, WAIT for user approval before any Phase 12 work.
