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
from memcore.exceptions import NotFoundError
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


async def test_empty_tenant_sweep_still_emits_prune_summary() -> None:
    env = _Env()

    report = await env.decay.sweep(TENANT)

    assert report.scanned == 0
    assert report.snapshotted == 0
    assert report.pruned == 0
    assert report.failed == 0
    events = await env.store.list_audit(TENANT)
    prune_summaries = [e for e in events if e.action is AuditAction.PRUNE]
    assert len(prune_summaries) == 1
    assert prune_summaries[0].metadata == {
        "scanned": 0, "snapshotted": 0, "pruned": 0, "failed": 0, "pinned": 0,
    }


async def test_sweep_scans_oldest_first_under_scan_limit() -> None:
    # With scan_limit=1 the page must contain the OLDEST record, so the
    # ancient prunable record is swept even though a fresh one exists.
    env = _Env(retention=RetentionSettings(scan_limit=1))
    ancient = await env.seed("forgotten trivia", age=timedelta(days=365))
    fresh = await env.seed("fresh fact")

    report = await env.decay.sweep(TENANT)

    assert report.scanned == 1
    assert report.pruned == 1
    pruned = await env.store.get(TENANT, ancient.id)
    assert pruned is not None and pruned.status is MemoryStatus.SOFT_DELETED
    kept = await env.store.get(TENANT, fresh.id)
    assert kept is not None and kept.status is MemoryStatus.ACTIVE


async def test_prune_failure_does_not_abort_sweep() -> None:
    env = _Env()
    await env.seed("forgotten trivia one", age=timedelta(days=365))
    await env.seed("forgotten trivia two", age=timedelta(days=365))

    original_forget = env.memories.forget
    calls = {"n": 0}

    async def flaky_forget(
        tenant_id: str, memory_id: str, *, mode: str = "soft",
        reason: str | None = None,
    ) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise NotFoundError("simulated concurrent deletion")
        await original_forget(tenant_id, memory_id, mode=mode, reason=reason)

    env.memories.forget = flaky_forget  # type: ignore[method-assign]

    report = await env.decay.sweep(TENANT)

    assert report.failed == 1
    assert report.pruned == 1
    events = await env.store.list_audit(TENANT)
    prune_summaries = [e for e in events if e.action is AuditAction.PRUNE]
    assert len(prune_summaries) == 1
    assert prune_summaries[0].metadata["failed"] == 1
    assert prune_summaries[0].metadata["pruned"] == 1
