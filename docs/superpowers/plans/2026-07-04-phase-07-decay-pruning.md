# Phase 7 — Memory Decay & Pruning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A tenant-scoped decay job that snapshots `decay_score` into storage and soft-deletes decayed, unpinned records under configurable safety rails, triggerable via API/Celery.

**Architecture:** The math stays in `services/importance.py` (unchanged — ADR-0015 point 4); a new `DecayService.sweep(tenant_id)` computes scores, persists them via a new `MemoryStore.set_decay` port method (an in-place signal update like `reinforce`, not a new version), and prunes records whose score falls below `RetentionSettings.prune_threshold` — never pinned records, never records younger than `min_age_days`, soft-delete only (reversible; hard deletion stays a manual/GDPR operation). The sweep is exposed as Celery task `memcore.decay_tenant` and `POST /v1/decay` (mirroring consolidation); recurring scheduling is a deployment concern (Celery beat can call the task; MemCore has no tenant enumeration yet, so the trigger is per-tenant by design — recorded in ADR-0016).

**Tech Stack:** Python 3.12, pydantic v2, SQLAlchemy async (SQL adapter), Celery, FastAPI, pytest (anyio fixtures in `tests/conftest.py`), in-memory adapters for unit tests.

## Global Constraints

- Quality gate (every task, before commit): `./.venv/Scripts/python.exe -m pytest` all pass, coverage ≥ 85%; `./.venv/Scripts/python.exe -m ruff check .` clean; `./.venv/Scripts/python.exe -m mypy` clean (strict).
- Hexagonal: `services/*` and `domain/*` import ports only — no adapter imports. Port changes in this phase are limited to exactly two: `MemoryStore.set_decay` (new) and `list_records`'s `agent_id` becoming `str | None` (None = all agents in the tenant). Both must be covered by the contract kit (`memcore.testing.contracts`).
- Records are immutable + versioned (ADR-0007). `set_decay`, like `reinforce`, is an in-place *signal* update, not a content edit — it never creates versions.
- Decay math is imported from `memcore.services.importance` (`decay_score`, `PINNED_TAG`) — never re-derived (ADR-0015 point 4).
- Pruning is soft-delete only (`MemoryStatus.SOFT_DELETED` via `MemoryService.forget(mode="soft")`), with an audit trail. Pinned records (tag `"pinned"`) are never pruned.
- All scores bounded [0, 1]; `memcore.domain.models.utcnow()` for "now"; aware-UTC datetimes.
- One commit per task; phase gate + docs in Task 4; WAIT for user approval after the phase commit.

---

### Task 1: Port extensions — `set_decay` + tenant-wide `list_records`

**Files:**
- Modify: `src/memcore/ports/memory_store.py` (new abstract method; `list_records` signature)
- Modify: `src/memcore/adapters/inmemory/memory_store.py`
- Modify: `src/memcore/adapters/sql/memory_store.py:157-178` (list_records), after `reinforce` (~line 237) for `set_decay`
- Modify: `src/memcore/testing/contracts.py` (extend `check_memory_store_contract`)
- Modify: `src/memcore/domain/models.py` — the `decay_score` field comment currently says "maintained by the Phase 7 decay job"; keep it accurate (see Step 3).
- Test: existing contract runners `tests/unit/test_contracts_inmemory.py` and `tests/unit/test_memory_store_contract.py` (no new test files — the contract kit IS the test)

**Interfaces:**
- Consumes: existing `MemoryStore` port, `MemoryRecord.decay_score`.
- Produces (Task 2 relies on these exact signatures):
  - `MemoryStore.set_decay(self, tenant_id: str, scores: dict[str, float]) -> None` — persist `decay_score` snapshots in place; unknown/other-tenant ids silently ignored; empty dict is a no-op.
  - `MemoryStore.list_records(self, tenant_id: str, agent_id: str | None, *, type: MemoryType | None = None, status: MemoryStatus | None = MemoryStatus.ACTIVE, limit: int = 100) -> list[MemoryRecord]` — `agent_id=None` lists across all agents in the tenant.

- [ ] **Step 1: Extend the contract kit (the failing test)**

In `src/memcore/testing/contracts.py`, inside `check_memory_store_contract`, insert after the reinforce block (after the `assert reinforced.last_accessed_at is not None` line, ~line 229):

```python
    # set_decay: in-place snapshot, tenant-scoped, unknown ids ignored
    await store.set_decay(tenant, {m1_v2.id: 0.25, "missing-id": 0.5})
    decayed = await store.get(tenant, m1_v2.id)
    assert decayed is not None and decayed.decay_score == 0.25
    assert decayed.version == m1_v2.version  # signal update, not a new version
    await store.set_decay("other-tenant", {m1_v2.id: 0.9})
    unchanged = await store.get(tenant, m1_v2.id)
    assert unchanged is not None and unchanged.decay_score == 0.25
    await store.set_decay(tenant, {})  # empty snapshot is a no-op

    # list_records with agent_id=None spans all agents in the tenant
    other_agent = make("Bruno lives in Pune.").model_copy(update={"agent_id": "a2"})
    await store.add(other_agent)
    tenant_wide = await store.list_records(tenant, None)
    assert {r.id for r in tenant_wide} == {m1_v2.id, other_agent.id}
    # (compare ids, not models: m1_v2's stored copy now carries reinforcement
    # and decay signals)
    assert [r.id for r in await store.list_records(tenant, agent)] == [m1_v2.id]
```

Also update the function docstring on line 167 to mention decay snapshots:
`"""Verify versioning, isolation, listing, reinforcement, decay snapshots, audit, sessions."""`

(Context for the assertion values: at this point in the contract, tenant has `m1` SUPERSEDED, `m1_v2` ACTIVE, `m2` SOFT_DELETED — so the ACTIVE-status default returns exactly `m1_v2` plus the new `other_agent` record.)

- [ ] **Step 2: Run contract tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_contracts_inmemory.py tests/unit/test_memory_store_contract.py -v`
Expected: FAIL — `AttributeError: ... no attribute 'set_decay'` (or `TypeError` on instantiating the ABC).

- [ ] **Step 3: Update the port**

In `src/memcore/ports/memory_store.py`:

1. `list_records` signature and docstring:

```python
    @abstractmethod
    async def list_records(
        self,
        tenant_id: str,
        agent_id: str | None,
        *,
        type: MemoryType | None = None,
        status: MemoryStatus | None = MemoryStatus.ACTIVE,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        """List records, newest-first. ``status=None`` means all statuses;
        ``agent_id=None`` means all agents in the tenant (decay sweeps)."""
```

2. New abstract method directly after `reinforce`:

```python
    @abstractmethod
    async def set_decay(self, tenant_id: str, scores: dict[str, float]) -> None:
        """Persist ``decay_score`` snapshots in place (Phase 7 decay job).

        Like ``reinforce`` this is a signal update, never a new version.
        Ids missing or belonging to another tenant are silently ignored.
        """
```

3. In `src/memcore/domain/models.py`, the comment above `decay_score` should read (adjust if wording differs):

```python
    # Snapshot maintained by the decay job (services/decay.py), not recomputed
    # live (ADR-0015, ADR-0016).
```

- [ ] **Step 4: Implement in the in-memory adapter**

In `src/memcore/adapters/inmemory/memory_store.py` — `list_records` filter line changes from `and r.agent_id == agent_id` to:

```python
            and (agent_id is None or r.agent_id == agent_id)
```

(and the signature's `agent_id: str` becomes `agent_id: str | None`). Add after `reinforce`:

```python
    async def set_decay(self, tenant_id: str, scores: dict[str, float]) -> None:
        for memory_id, score in scores.items():
            record = await self.get(tenant_id, memory_id)
            if record is not None:
                self._records[(tenant_id, memory_id)] = record.model_copy(
                    update={"decay_score": score}
                )
```

- [ ] **Step 5: Implement in the SQL adapter**

In `src/memcore/adapters/sql/memory_store.py` — `list_records` builds the agent filter conditionally:

```python
    async def list_records(
        self,
        tenant_id: str,
        agent_id: str | None,
        *,
        type: MemoryType | None = None,
        status: MemoryStatus | None = MemoryStatus.ACTIVE,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        stmt = (
            select(MemoryRow)
            .where(MemoryRow.tenant_id == tenant_id)
            .order_by(MemoryRow.created_at.desc())
            .limit(limit)
        )
        if agent_id is not None:
            stmt = stmt.where(MemoryRow.agent_id == agent_id)
        if type is not None:
            stmt = stmt.where(MemoryRow.type == type.value)
        if status is not None:
            stmt = stmt.where(MemoryRow.status == status.value)
        async with self._sessions() as db:
            rows = (await db.scalars(stmt)).all()
        return [_row_to_record(row) for row in rows]
```

Add after `reinforce`:

```python
    async def set_decay(self, tenant_id: str, scores: dict[str, float]) -> None:
        if not scores:
            return
        async with self._sessions() as db, db.begin():
            for memory_id, score in scores.items():
                await db.execute(
                    update(MemoryRow)
                    .where(MemoryRow.tenant_id == tenant_id, MemoryRow.id == memory_id)
                    .values(decay_score=score)
                )
```

- [ ] **Step 6: Run contract tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_contracts_inmemory.py tests/unit/test_memory_store_contract.py -v`
Expected: PASS.

- [ ] **Step 7: Full gate**

Run: `./.venv/Scripts/python.exe -m pytest && ./.venv/Scripts/python.exe -m ruff check . && ./.venv/Scripts/python.exe -m mypy`
Expected: clean. (mypy will catch any other `MemoryStore` implementation missing `set_decay` — there are exactly the two adapters.)

- [ ] **Step 8: Commit**

```bash
git add src/memcore/ports/memory_store.py src/memcore/adapters/inmemory/memory_store.py src/memcore/adapters/sql/memory_store.py src/memcore/testing/contracts.py src/memcore/domain/models.py
git commit -m "feat(store): set_decay snapshots + tenant-wide list_records (Phase 7)"
```

---

### Task 2: `RetentionSettings` + `DecayService` (sweep, prune, audit)

**Files:**
- Modify: `src/memcore/config.py` (add `RetentionSettings`, wire into `Settings`)
- Modify: `src/memcore/domain/enums.py` (add `AuditAction.PRUNE`)
- Modify: `src/memcore/services/memories.py` (`forget` gains `reason`)
- Create: `src/memcore/services/decay.py`
- Modify: `src/memcore/services/__init__.py` (export `DecayService`, `DecayReport` — match the file's existing export style)
- Test: `tests/unit/test_decay.py` (new)

**Interfaces:**
- Consumes (Task 1): `MemoryStore.set_decay(tenant_id, scores)`, `list_records(tenant_id, None, ...)`. From Phase 6 (unchanged): `memcore.services.importance.decay_score(record, now, *, settings: ImportanceSettings)`, `PINNED_TAG`.
- Produces (Task 3 relies on):
  - `memcore.config.RetentionSettings` — `prune_threshold: float = 0.05`, `min_age_days: float = 14.0`, `scan_limit: int = 10_000`; on `Settings` as `retention`.
  - `DecayService(store: MemoryStore, memories: MemoryService, *, importance: ImportanceSettings | None = None, retention: RetentionSettings | None = None)` with `async def sweep(self, tenant_id: str) -> DecayReport`.
  - `DecayReport` (pydantic): `tenant_id: str`, `scanned: int = 0`, `snapshotted: int = 0`, `pruned: int = 0`, `skipped_pinned: int = 0`.
  - `MemoryService.forget(..., reason: str | None = None)` — overrides the default audit reason string.
  - `AuditAction.PRUNE = "prune"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_decay.py`:

```python
"""Phase 7 — decay sweep: snapshots, prune policy, safety rails, idempotency."""

from __future__ import annotations

from datetime import timedelta

from memcore.adapters.inmemory import (
    HashingEmbeddingProvider,
    InMemoryMemoryStore,
    InMemoryVectorStore,
)
from memcore.config import ImportanceSettings, RetentionSettings
from memcore.domain.enums import AuditAction, MemoryStatus, MemoryType
from memcore.domain.models import MemoryRecord, utcnow
from memcore.ports.vector_store import VectorRecord
from memcore.services.decay import DecayService
from memcore.services.importance import PINNED_TAG
from memcore.services.memories import MemoryService

TENANT, AGENT = "t1", "a1"
COLLECTION = "mem_test"


class _Env:
    def __init__(
        self,
        *,
        importance: ImportanceSettings | None = None,
        retention: RetentionSettings | None = None,
    ) -> None:
        self.store = InMemoryMemoryStore()
        self.vectors = InMemoryVectorStore()
        self.embedder = HashingEmbeddingProvider(dimension=64)
        self.memories = MemoryService(
            self.store, self.vectors, self.embedder, collection=COLLECTION
        )
        self.decay = DecayService(
            self.store, self.memories, importance=importance, retention=retention
        )

    async def seed(
        self,
        content: str,
        *,
        age: timedelta = timedelta(0),
        tags: list[str] | None = None,
        agent_id: str = AGENT,
    ) -> MemoryRecord:
        record = MemoryRecord(
            tenant_id=TENANT,
            agent_id=agent_id,
            type=MemoryType.SEMANTIC,
            content=content,
            created_at=utcnow() - age,
            valid_from=utcnow() - age,
            tags=tags or [],
        )
        await self.store.add(record)
        vector = await self.embedder.embed_one(content)
        await self.vectors.upsert(
            COLLECTION,
            [VectorRecord(id=record.id, vector=vector,
                          payload={"tenant_id": TENANT, "agent_id": agent_id,
                                   "type": "semantic", "status": "active"})],
        )
        return record


async def test_sweep_snapshots_decay_scores() -> None:
    env = _Env()
    fresh = await env.seed("fresh fact")
    old = await env.seed("old fact", age=timedelta(days=60))

    report = await env.decay.sweep(TENANT)

    assert report.scanned == 2
    assert report.snapshotted == 2
    stored_fresh = await env.store.get(TENANT, fresh.id)
    stored_old = await env.store.get(TENANT, old.id)
    assert stored_fresh is not None and stored_fresh.decay_score > 0.99
    # 60 days at tau=30d -> exp(-2) ~ 0.135
    assert stored_old is not None and 0.10 < stored_old.decay_score < 0.15


async def test_prune_soft_deletes_decayed_records_with_audit() -> None:
    env = _Env()
    ancient = await env.seed("forgotten trivia", age=timedelta(days=365))
    keeper = await env.seed("recent fact")

    report = await env.decay.sweep(TENANT)

    assert report.pruned == 1
    pruned = await env.store.get(TENANT, ancient.id)
    assert pruned is not None and pruned.status is MemoryStatus.SOFT_DELETED
    kept = await env.store.get(TENANT, keeper.id)
    assert kept is not None and kept.status is MemoryStatus.ACTIVE
    # Pruned records leave the vector index (soft delete goes through forget).
    hits = await env.vectors.search(
        COLLECTION, await env.embedder.embed_one("forgotten trivia"), limit=10
    )
    assert ancient.id not in {h.id for h in hits}

    events = await env.store.list_audit(TENANT)
    prune_summaries = [e for e in events if e.action is AuditAction.PRUNE]
    assert len(prune_summaries) == 1 and prune_summaries[0].actor == "decay"
    deletes = [e for e in events if e.action is AuditAction.DELETE
               and e.target_id == ancient.id]
    assert deletes and "decay prune" in (deletes[0].reason or "")


async def test_pinned_records_are_never_pruned() -> None:
    env = _Env()
    pinned = await env.seed("pinned forever", age=timedelta(days=365),
                            tags=[PINNED_TAG])

    report = await env.decay.sweep(TENANT)

    assert report.pruned == 0
    assert report.skipped_pinned == 1
    stored = await env.store.get(TENANT, pinned.id)
    assert stored is not None
    assert stored.status is MemoryStatus.ACTIVE
    assert stored.decay_score == 1.0  # snapshot reflects the pinned exemption


async def test_min_age_rail_blocks_young_records() -> None:
    # Aggressive tau makes a 5-day-old record decay below threshold, but the
    # min_age rail must protect it.
    env = _Env(
        importance=ImportanceSettings(decay_tau_days=0.5),
        retention=RetentionSettings(min_age_days=14.0),
    )
    young = await env.seed("young but idle", age=timedelta(days=5))

    report = await env.decay.sweep(TENANT)

    assert report.pruned == 0
    stored = await env.store.get(TENANT, young.id)
    assert stored is not None and stored.status is MemoryStatus.ACTIVE
    assert stored.decay_score < 0.05  # snapshot still records the true score


async def test_sweep_is_idempotent() -> None:
    env = _Env()
    await env.seed("forgotten trivia", age=timedelta(days=365))

    first = await env.decay.sweep(TENANT)
    second = await env.decay.sweep(TENANT)

    assert first.pruned == 1
    assert second.pruned == 0  # soft-deleted records are no longer ACTIVE
    assert second.scanned == first.scanned - 1


async def test_sweep_spans_agents_but_not_tenants() -> None:
    env = _Env()
    await env.seed("agent one fact", age=timedelta(days=365))
    await env.seed("agent two fact", age=timedelta(days=365), agent_id="a2")
    foreign = MemoryRecord(
        tenant_id="t2", agent_id="a1", type=MemoryType.SEMANTIC,
        content="other tenant", created_at=utcnow() - timedelta(days=365),
        valid_from=utcnow() - timedelta(days=365),
    )
    await env.store.add(foreign)

    report = await env.decay.sweep(TENANT)

    assert report.scanned == 2 and report.pruned == 2
    untouched = await env.store.get("t2", foreign.id)
    assert untouched is not None
    assert untouched.status is MemoryStatus.ACTIVE
    assert untouched.decay_score == 1.0  # never snapshotted


async def test_forget_reason_overrides_default_audit_reason() -> None:
    env = _Env()
    record = await env.memories.remember(TENANT, AGENT, "to be forgotten")
    await env.memories.forget(TENANT, record.id, mode="soft",
                              reason="decay prune (score=0.010)")
    events = await env.store.list_audit(TENANT)
    delete = next(e for e in events if e.action is AuditAction.DELETE)
    assert delete.reason == "decay prune (score=0.010)"
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_decay.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'memcore.services.decay'` (and `ImportError` for `RetentionSettings`).

- [ ] **Step 3: Config, enum, forget-reason**

1. `src/memcore/config.py` — insert after `ImportanceSettings` (before `LLMSettings`):

```python
class RetentionSettings(BaseModel):
    """Knobs for the decay sweep and prune policy (Phase 7).

    Defaults are deliberately conservative: with the default decay tau of 30
    days, a never-recalled memory crosses ``prune_threshold=0.05`` only after
    ~90 days untouched, and ``min_age_days`` protects young records outright.
    """

    # Records whose decay snapshot falls below this are prune candidates.
    prune_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    # Never prune records younger than this, regardless of score.
    min_age_days: float = Field(default=14.0, gt=0)
    # Max records fetched per sweep (v1: single page, newest-first).
    scan_limit: int = Field(default=10_000, ge=1)
```

And in `class Settings`, after the `importance` field:

```python
    retention: RetentionSettings = Field(default_factory=RetentionSettings)
```

2. `src/memcore/domain/enums.py` — add to `AuditAction` (after `CONSOLIDATE`):

```python
    PRUNE = "prune"
```

3. `src/memcore/services/memories.py` — `forget` gains a keyword:

```python
    async def forget(
        self, tenant_id: str, memory_id: str, *, mode: str = "soft",
        reason: str | None = None,
    ) -> None:
```

and the audit call's reason becomes:

```python
            reason=reason or f"{mode} delete",
```

- [ ] **Step 4: Write `DecayService`**

Create `src/memcore/services/decay.py`:

```python
"""DecayService — snapshot decay scores and prune what has faded (Phase 7).

Design (ADR-0016):

* The math lives in :mod:`memcore.services.importance` and is imported, never
  re-derived (ADR-0015 point 4). This service only orchestrates: score every
  ACTIVE record in the tenant, persist the snapshots via ``set_decay`` (an
  in-place signal update, like ``reinforce`` — no new versions), then prune.
* Prune policy, all rails must agree: score below ``prune_threshold`` AND not
  pinned AND older than ``min_age_days``. Pruning is a *soft* delete through
  :class:`MemoryService` (audit + vector-index removal in one place); hard
  deletion remains a manual/GDPR operation.
* One PRUNE audit event summarizes each sweep. Re-running immediately is
  idempotent: soft-deleted records are no longer ACTIVE, so a second sweep
  prunes nothing.
"""

from __future__ import annotations

from pydantic import BaseModel

from memcore.config import ImportanceSettings, RetentionSettings
from memcore.domain.enums import AuditAction, MemoryStatus
from memcore.domain.models import AuditEvent, MemoryRecord, utcnow
from memcore.logging import get_logger
from memcore.ports.memory_store import MemoryStore
from memcore.services.importance import PINNED_TAG, decay_score
from memcore.services.memories import MemoryService

logger = get_logger("decay")


class DecayReport(BaseModel):
    tenant_id: str
    scanned: int = 0
    snapshotted: int = 0
    pruned: int = 0
    skipped_pinned: int = 0


class DecayService:
    def __init__(
        self,
        store: MemoryStore,
        memories: MemoryService,
        *,
        importance: ImportanceSettings | None = None,
        retention: RetentionSettings | None = None,
    ) -> None:
        self._store = store
        self._memories = memories
        self._importance = importance or ImportanceSettings()
        self._retention = retention or RetentionSettings()

    async def sweep(self, tenant_id: str) -> DecayReport:
        now = utcnow()
        records = await self._store.list_records(
            tenant_id, None,
            status=MemoryStatus.ACTIVE,
            limit=self._retention.scan_limit,
        )
        report = DecayReport(tenant_id=tenant_id, scanned=len(records))

        scores: dict[str, float] = {}
        candidates: list[tuple[MemoryRecord, float]] = []
        for record in records:
            score = decay_score(record, now, settings=self._importance)
            scores[record.id] = score
            if PINNED_TAG in record.tags:
                report.skipped_pinned += 1
                continue
            age_days = (now - record.created_at).total_seconds() / 86400.0
            if (
                score < self._retention.prune_threshold
                and age_days >= self._retention.min_age_days
            ):
                candidates.append((record, score))

        if scores:
            await self._store.set_decay(tenant_id, scores)
            report.snapshotted = len(scores)

        for record, score in candidates:
            await self._memories.forget(
                tenant_id, record.id, mode="soft",
                reason=f"decay prune (score={score:.3f})",
            )
            report.pruned += 1

        await self._store.add_audit(
            AuditEvent(
                tenant_id=tenant_id,
                actor="decay",
                action=AuditAction.PRUNE,
                reason=(
                    f"scanned={report.scanned} snapshotted={report.snapshotted} "
                    f"pruned={report.pruned} pinned={report.skipped_pinned}"
                ),
            )
        )
        logger.info("decay sweep", extra={"tenant_id": tenant_id,
                                          "pruned": report.pruned})
        return report
```

Export from `src/memcore/services/__init__.py` following the file's existing pattern (add `DecayReport`, `DecayService` to the imports and `__all__`).

- [ ] **Step 5: Run the new tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_decay.py -v`
Expected: all 7 PASS.

- [ ] **Step 6: Full gate**

Run: `./.venv/Scripts/python.exe -m pytest && ./.venv/Scripts/python.exe -m ruff check . && ./.venv/Scripts/python.exe -m mypy`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/memcore/config.py src/memcore/domain/enums.py src/memcore/services/memories.py src/memcore/services/decay.py src/memcore/services/__init__.py tests/unit/test_decay.py
git commit -m "feat(decay): DecayService sweep — snapshots, prune rails, audit (Phase 7)"
```

---

### Task 3: Wiring — Celery task, API endpoint, `confidence` exposure

**Files:**
- Modify: `src/memcore/workers/celery_app.py` (new `memcore.decay_tenant` task)
- Modify: `src/memcore/api/app.py:76-113` (build `DecayService`, register immediate handler)
- Modify: `src/memcore/api/routes.py` (POST `/v1/decay`; `confidence` pass-through on remember/correct)
- Modify: `src/memcore/api/schemas.py:32-43` (`confidence` on `RememberRequest`/`CorrectMemoryRequest`)
- Test: `tests/unit/test_api.py`

**Interfaces:**
- Consumes (Task 2): `DecayService(store, memories, *, importance=..., retention=...)`, `sweep(tenant_id) -> DecayReport`, `RetentionSettings` on `Settings.retention`. From Phase 6: `MemoryService.remember/correct` already accept `confidence`.
- Produces: Celery task name `memcore.decay_tenant(tenant_id: str)`; workflow task name `"decay_tenant"` with payload `{"tenant_id": ...}`; `POST /v1/decay` → 202 `JobResponse`; API fields `RememberRequest.confidence: float = 1.0`, `CorrectMemoryRequest.confidence: float | None = None`.

- [ ] **Step 1: Write the failing API tests**

Add to `tests/unit/test_api.py`. Two changes: (a) inside its `_state()` helper, after the `workflow.register("consolidate_session", _consolidate)` line, register the decay handler (imports: add `DecayService` to the `memcore.services` import list):

```python
    decay = DecayService(store, memories)

    async def _decay(payload: dict[str, object]) -> None:
        await decay.sweep(str(payload["tenant_id"]))

    workflow.register("decay_tenant", _decay)
```

(b) new tests at the end of the file:

```python
async def test_decay_endpoint_enqueues_sweep(client: AsyncClient) -> None:
    response = await client.post("/v1/decay", headers=_h())
    assert response.status_code == 202
    body = response.json()
    assert body["state"] == "succeeded"  # immediate engine runs inline
    job = await client.get(f"/v1/jobs/{body['job_id']}", headers=_h())
    assert job.status_code == 200


async def test_remember_and_correct_accept_confidence(client: AsyncClient) -> None:
    created = await client.post(
        "/v1/memories",
        json={"agent_id": "a1", "content": "Bruno is a beagle.",
              "confidence": 0.7},
        headers=_h(),
    )
    assert created.status_code == 201
    memory = created.json()["memory"]
    assert memory["confidence"] == 0.7

    corrected = await client.patch(
        f"/v1/memories/{memory['id']}",
        json={"confidence": 0.9},
        headers=_h(),
    )
    assert corrected.status_code == 200
    assert corrected.json()["memory"]["confidence"] == 0.9
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_api.py -v -k "decay or confidence"`
Expected: FAIL — 404 for `/v1/decay`; 422 for the unknown `confidence` field (`extra="forbid"`).

- [ ] **Step 3: Schemas + routes**

1. `src/memcore/api/schemas.py`:

`RememberRequest` gains (after `importance`):

```python
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
```

`CorrectMemoryRequest` gains (after `importance`):

```python
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
```

2. `src/memcore/api/routes.py`:

`remember` route passes `confidence=body.confidence` (after `importance=body.importance`); `correct_memory` route passes `confidence=body.confidence` likewise. New route after the consolidation block:

```python
# -- decay ---------------------------------------------------------------------
@router.post("/decay", response_model=JobResponse, status_code=202)
async def run_decay(state: StateDep, tenant: TenantDep) -> JobResponse:
    """Enqueue a decay sweep for the calling tenant (snapshot + prune)."""
    handle = await state.workflow.enqueue("decay_tenant", {"tenant_id": tenant})
    return JobResponse(job_id=handle.id, state=handle.state.value)
```

- [ ] **Step 4: App factory wiring**

In `src/memcore/api/app.py` `build_state`, after the `consolidation = ...` assignment add:

```python
    decay = DecayService(
        store, memories,
        importance=settings.importance,
        retention=settings.retention,
    )
```

(add `DecayService` to the `memcore.services` import list). Inside the `if isinstance(workflow, ImmediateWorkflowEngine):` block, after `workflow.register("consolidate_session", _consolidate)`:

```python
        async def _decay(payload: dict[str, object]) -> None:
            await decay.sweep(str(payload["tenant_id"]))

        workflow.register("decay_tenant", _decay)
```

- [ ] **Step 5: Celery worker task**

In `src/memcore/workers/celery_app.py`, after `_get_consolidation` add:

```python
def _get_decay(settings: Settings) -> Any:
    """Build (once per worker process) the decay service graph."""
    if "decay" not in _cache:
        from memcore.adapters.factory import (
            build_embedding_provider,
            build_memory_store,
            build_vector_store,
        )
        from memcore.services.decay import DecayService
        from memcore.services.memories import MemoryService

        store = build_memory_store(settings)
        vectors = build_vector_store(settings)
        embedder = build_embedding_provider(settings)
        collection = f"{settings.vector.collection_prefix}_{embedder.dimension}"
        memories = MemoryService(store, vectors, embedder, collection=collection)
        _cache["decay"] = DecayService(
            store, memories,
            importance=settings.importance,
            retention=settings.retention,
        )
    return _cache["decay"]
```

and after the `consolidate_session` task:

```python
@app.task(name="memcore.decay_tenant")
def decay_tenant(tenant_id: str) -> dict[str, Any]:
    service = _get_decay(_settings)
    report = asyncio.run(service.sweep(tenant_id))
    logger.info("decay swept", extra={"tenant_id": tenant_id})
    return report.model_dump()
```

- [ ] **Step 6: Run API tests, then full gate**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_api.py -v`
Expected: all PASS.

Then: `./.venv/Scripts/python.exe -m pytest && ./.venv/Scripts/python.exe -m ruff check . && ./.venv/Scripts/python.exe -m mypy`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/memcore/workers/celery_app.py src/memcore/api/app.py src/memcore/api/routes.py src/memcore/api/schemas.py tests/unit/test_api.py
git commit -m "feat(api): POST /v1/decay + Celery decay_tenant task; expose confidence (Phase 7)"
```

---

### Task 4: Docs, ADR-0016, state — phase gate

**Files:**
- Create: `docs/adr/0016-decay-and-pruning.md`
- Create: `docs/design/phase-07.md`
- Modify: `docs/adr/README.md` (index line), `docs/design/roadmap.md` (Phase 7 → ✅ Complete, Phase 8 → ⏳ Next), `CHANGELOG.md`, `PROJECT_STATE.md`

**Interfaces:** none — documentation of Tasks 1–3 exactly as built.

- [ ] **Step 1: Write ADR-0016**

`docs/adr/0016-decay-and-pruning.md` (match the header/section style of `docs/adr/0015-importance-scoring.md`):

- **Status:** accepted. **Context:** ADR-0015 defined decay math but persisted nothing; without pruning, dead memories accumulate and the stored `decay_score` field stays a constant 1.0.
- **Decision:** (1) `DecayService.sweep(tenant_id)` scores every ACTIVE record with `services/importance.py`'s functions (imported, never re-derived) and persists snapshots via the new `MemoryStore.set_decay` — an in-place signal update like `reinforce`, exempt from ADR-0007 versioning; (2) prune policy requires ALL rails: `decay < prune_threshold` (default 0.05 ≈ 90 days untouched at τ=30d) AND not `pinned` AND age ≥ `min_age_days` (default 14); (3) pruning is soft-delete only, through `MemoryService.forget` (single place for audit + vector-index removal), with per-record DELETE audits (`reason="decay prune (score=…)"`) plus one PRUNE summary event per sweep; hard deletion remains a manual/GDPR operation; (4) the sweep is per-tenant (`POST /v1/decay`, Celery `memcore.decay_tenant`); recurring scheduling is a deployment concern (Celery beat may call the task per tenant) because MemCore has no tenant-enumeration facility — revisit when it does; (5) `list_records` gained `agent_id=None` (tenant-wide) for the sweep; v1 scans a single `scan_limit` page, newest-first — explicitly noted as the accepted v1 limitation (oldest records can be missed only if a tenant exceeds `scan_limit` ACTIVE records; the next sweeps converge as pruned records free the page).
- **Consequences:** decayed memories leave the retrievable set reversibly and auditable; `decay_score` in API responses is now a live-ish snapshot (age = time since last sweep); pinning gives users a hard opt-out; storage cost of the sweep is one bulk update + one soft delete per pruned record.

Add to `docs/adr/README.md` index: `- [ADR-0016](0016-decay-and-pruning.md) — Decay & pruning: per-tenant sweep, snapshot via set_decay, rail-guarded soft-delete prune`.

- [ ] **Step 2: Write the phase doc**

`docs/design/phase-07.md`, same structure as `phase-06.md` (Objective / Delivered / Gate / Deferred / Self-review): Delivered = port extensions (`set_decay`, tenant-wide `list_records`) + contract-kit coverage; `RetentionSettings`; `DecayService` (sweep/prune/audit, `DecayReport`); `AuditAction.PRUNE`; `forget(reason=…)`; Celery task + `POST /v1/decay`; API `confidence` exposure (closing the Phase 6 backlog item). Deferred = paged scanning beyond `scan_limit`; tenant enumeration + beat schedule shipping in the deployment phase; hard-delete retention job (GDPR) — security phase. Record the actual gate numbers from Step 4.

- [ ] **Step 3: Update CHANGELOG, roadmap, PROJECT_STATE**

`CHANGELOG.md` — new block above Phase 6:

```markdown
### Added — Phase 7: Memory decay & pruning
- `MemoryStore.set_decay` (in-place decay snapshots) and tenant-wide
  `list_records(agent_id=None)`; contract kit covers both — ADR-0016.
- `services/decay.py`: `DecayService.sweep` scores ACTIVE records with the
  Phase 6 functions, snapshots `decay_score`, and soft-deletes records that
  fail every rail (score < threshold, not pinned, older than `min_age_days`);
  per-record DELETE audits + one PRUNE summary event per sweep.
- `RetentionSettings` (`prune_threshold=0.05`, `min_age_days=14`,
  `scan_limit=10000`) on `Settings.retention`; `AuditAction.PRUNE`;
  `MemoryService.forget` accepts `reason`.
- `POST /v1/decay` (202 + job handle) and Celery task `memcore.decay_tenant`.
- API: `confidence` exposed on remember/correct requests (Phase 6 backlog).
```

`docs/design/roadmap.md`: Phase 7 → `✅ Complete`, Phase 8 → `⏳ Next`.

`PROJECT_STATE.md`: current position → Phase 7 complete / Phase 8 (Evaluation framework & baselines) not started, awaiting approval; record the Phase 7 gate numbers; next tasks → Phase 8 outline (eval harness + retrieval-quality baselines vs. naive vector search, decay/importance ablations, longitudinal memory-quality metrics); open decision → approve Phase 8 start.

- [ ] **Step 4: Run the phase gate and record numbers**

Run: `./.venv/Scripts/python.exe -m pytest` (record pass count + coverage %), `./.venv/Scripts/python.exe -m ruff check .`, `./.venv/Scripts/python.exe -m mypy`
Expected: all clean, coverage ≥ 85%. Copy the real numbers into `phase-07.md` and `PROJECT_STATE.md`.

- [ ] **Step 5: Phase commit**

```bash
git add docs/adr/0016-decay-and-pruning.md docs/adr/README.md docs/design/phase-07.md docs/design/roadmap.md CHANGELOG.md PROJECT_STATE.md
git commit -m "docs: Phase 7 gate — decay & pruning (ADR-0016, phase doc, state)"
```

Then STOP: per the phase gate, WAIT for user approval before any Phase 8 work.
