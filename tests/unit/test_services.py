"""Service-layer tests: session ingest, memory lifecycle, recall v1."""

from __future__ import annotations

import pytest

from memcore.adapters.inmemory import (
    HashingEmbeddingProvider,
    InMemoryMemoryStore,
    InMemoryObjectStore,
    InMemoryVectorStore,
    InMemoryWorkingMemory,
)
from memcore.domain.enums import AuditAction, MemoryStatus, MemoryType
from memcore.exceptions import NotFoundError, ValidationError
from memcore.services import MemoryService, RecallService, SessionService

TENANT, AGENT = "t1", "a1"


@pytest.fixture
def store() -> InMemoryMemoryStore:
    return InMemoryMemoryStore()


@pytest.fixture
def session_service(store: InMemoryMemoryStore) -> SessionService:
    return SessionService(store, InMemoryWorkingMemory(), InMemoryObjectStore())


@pytest.fixture
async def memory_setup(
    store: InMemoryMemoryStore,
) -> tuple[MemoryService, RecallService, InMemoryVectorStore]:
    vectors = InMemoryVectorStore()
    embedder = HashingEmbeddingProvider(dimension=64)
    memories = MemoryService(store, vectors, embedder, collection="mem_test")
    recall = RecallService(store, vectors, embedder, collection="mem_test")
    await memories.ensure_ready()
    return memories, recall, vectors


# -- sessions -----------------------------------------------------------------
async def test_session_lifecycle(session_service: SessionService) -> None:
    session = await session_service.open(TENANT, AGENT)
    assert not session.closed

    updated = await session_service.append(
        TENANT, session.id, role="user", content="hello world"
    )
    assert updated.turn_count == 1
    assert updated.token_count > 0

    closed = await session_service.close(TENANT, session.id)
    assert closed.closed
    # Appending to a closed session is rejected.
    with pytest.raises(ValidationError):
        await session_service.append(TENANT, session.id, role="user", content="more")
    # Closing again is idempotent.
    assert (await session_service.close(TENANT, session.id)).closed


async def test_session_tenant_isolation(session_service: SessionService) -> None:
    session = await session_service.open(TENANT, AGENT)
    with pytest.raises(NotFoundError):
        await session_service.get("t2", session.id)


async def test_append_archives_raw_interaction(store: InMemoryMemoryStore) -> None:
    objects = InMemoryObjectStore()
    svc = SessionService(store, InMemoryWorkingMemory(), objects)
    session = await svc.open(TENANT, AGENT)
    await svc.append(TENANT, session.id, role="user", content="archive me")
    keys = await objects.list_keys(f"raw/{TENANT}/{session.id}/")
    assert len(keys) == 1


# -- memories -----------------------------------------------------------------
async def test_remember_get_and_audit(
    memory_setup: tuple[MemoryService, RecallService, InMemoryVectorStore],
    store: InMemoryMemoryStore,
) -> None:
    memories, _, vectors = memory_setup
    record = await memories.remember(
        TENANT, AGENT, "Chinmay prefers dark mode.", tags=["prefs"]
    )
    assert record.embedding_ref == record.id
    assert (await memories.get(TENANT, record.id)).content == record.content
    assert await vectors.count("mem_test", {"tenant_id": TENANT}) == 1

    events = await store.list_audit(TENANT)
    assert events and events[0].action is AuditAction.CREATE

    with pytest.raises(ValidationError):
        await memories.remember(TENANT, AGENT, "   ")


async def test_correct_creates_version_and_reindexes(
    memory_setup: tuple[MemoryService, RecallService, InMemoryVectorStore],
) -> None:
    memories, _, vectors = memory_setup
    v1 = await memories.remember(TENANT, AGENT, "Chinmay lives in Delhi.")
    v2 = await memories.correct(TENANT, v1.id, content="Chinmay lives in Bangalore.")

    assert v2.version == 2 and v2.supersedes == v1.id
    old = await memories.get(TENANT, v1.id)
    assert old.status is MemoryStatus.SUPERSEDED
    # Old vector removed; only the new version is retrievable.
    assert await vectors.count("mem_test", {"tenant_id": TENANT}) == 1
    chain = await memories.versions(TENANT, v2.id)
    assert [r.id for r in chain] == [v1.id, v2.id]

    # Correcting a superseded record is rejected; empty patch is rejected.
    with pytest.raises(ValidationError):
        await memories.correct(TENANT, v1.id, content="nope")
    with pytest.raises(ValidationError):
        await memories.correct(TENANT, v2.id)


async def test_remember_stores_confidence(
    memory_setup: tuple[MemoryService, RecallService, InMemoryVectorStore],
) -> None:
    memories, _, _ = memory_setup
    record = await memories.remember(
        TENANT, AGENT, "Chinmay's dog is called Bruno.", confidence=0.8
    )
    assert record.confidence == 0.8


async def test_correct_updates_confidence(
    memory_setup: tuple[MemoryService, RecallService, InMemoryVectorStore],
) -> None:
    memories, _, _ = memory_setup
    original = await memories.remember(
        TENANT, AGENT, "Bruno is a beagle.", confidence=0.6
    )
    updated = await memories.correct(TENANT, original.id, confidence=0.9)
    assert updated.confidence == 0.9
    assert updated.supersedes == original.id


async def test_forget_soft_and_hard(
    memory_setup: tuple[MemoryService, RecallService, InMemoryVectorStore],
) -> None:
    memories, _, vectors = memory_setup
    rec = await memories.remember(TENANT, AGENT, "temporary fact")

    await memories.forget(TENANT, rec.id, mode="soft")
    soft = await memories.get(TENANT, rec.id)  # soft-deleted is still visible
    assert soft.status is MemoryStatus.SOFT_DELETED
    assert await vectors.count("mem_test") == 0

    await memories.forget(TENANT, rec.id, mode="hard")
    with pytest.raises(NotFoundError):  # hard-deleted is gone from reads
        await memories.get(TENANT, rec.id)

    with pytest.raises(ValidationError):
        await memories.forget(TENANT, rec.id, mode="bogus")
    with pytest.raises(NotFoundError):
        await memories.forget(TENANT, "missing", mode="soft")


async def test_forget_soft_rejects_superseded_record(
    memory_setup: tuple[MemoryService, RecallService, InMemoryVectorStore],
) -> None:
    """Soft-deleting a SUPERSEDED record is meaningless and would let
    ``restore`` later resurrect it into a second ACTIVE version, violating
    ADR-0007's immutable+versioned invariant. Hard delete (GDPR erase of an
    old version) must still be allowed."""
    memories, _, _ = memory_setup
    v1 = await memories.remember(TENANT, AGENT, "Chinmay lives in Delhi.")
    await memories.correct(TENANT, v1.id, content="Chinmay lives in Bangalore.")

    old = await memories.get(TENANT, v1.id)
    assert old.status is MemoryStatus.SUPERSEDED

    with pytest.raises(ValidationError):
        await memories.forget(TENANT, v1.id, mode="soft")

    # Hard delete of the superseded version is still allowed.
    await memories.forget(TENANT, v1.id, mode="hard")
    with pytest.raises(NotFoundError):
        await memories.get(TENANT, v1.id)


async def test_restore_hard_deleted_is_not_found(
    memory_setup: tuple[MemoryService, RecallService, InMemoryVectorStore],
) -> None:
    memories, _, _ = memory_setup
    rec = await memories.remember(TENANT, AGENT, "will be hard-deleted")
    await memories.forget(TENANT, rec.id, mode="hard")

    with pytest.raises(NotFoundError):
        await memories.restore(TENANT, rec.id)


# -- recall -------------------------------------------------------------------
async def test_recall_ranks_and_reinforces(
    memory_setup: tuple[MemoryService, RecallService, InMemoryVectorStore],
) -> None:
    memories, recall, _ = memory_setup
    target = await memories.remember(
        TENANT, AGENT, "Chinmay prefers dark mode in all editors."
    )
    await memories.remember(TENANT, AGENT, "The weather in Bangalore is rainy.")

    results = await recall.recall(TENANT, AGENT, "what editor theme does chinmay like?")
    assert results
    assert results[0].memory.id == target.id
    assert 0.0 <= results[0].final <= 1.0
    assert results[0].relevance >= results[0].final  # multiplicative blend shrinks

    # Reinforcement happened.
    reinforced = await memories.get(TENANT, target.id)
    assert reinforced.access_count == 1
    assert reinforced.last_accessed_at is not None


async def test_recall_respects_type_filter_and_isolation(
    memory_setup: tuple[MemoryService, RecallService, InMemoryVectorStore],
) -> None:
    memories, recall, _ = memory_setup
    await memories.remember(
        TENANT, AGENT, "semantic fact about python", type=MemoryType.SEMANTIC
    )
    episodic = await memories.remember(
        TENANT, AGENT, "yesterday we discussed python", type=MemoryType.EPISODIC
    )

    only_episodic = await recall.recall(
        TENANT, AGENT, "python", types=[MemoryType.EPISODIC]
    )
    assert {r.memory.id for r in only_episodic} == {episodic.id}

    # Another tenant sees nothing.
    assert await recall.recall("t2", AGENT, "python") == []


async def test_recall_skips_records_missing_from_store(
    memory_setup: tuple[MemoryService, RecallService, InMemoryVectorStore],
    store: InMemoryMemoryStore,
) -> None:
    """Index lag: a vector hit whose record was hard-deleted is dropped."""
    memories, recall, vectors = memory_setup
    await memories.remember(TENANT, AGENT, "stale index entry about python")
    # Simulate drift: record removed from source of truth, vector left behind.
    store._records.clear()
    assert await vectors.count("mem_test") == 1
    assert await recall.recall(TENANT, AGENT, "python") == []


async def test_restore_soft_deleted_record(
    memory_setup: tuple[MemoryService, RecallService, InMemoryVectorStore],
) -> None:
    memories, recall, _vectors = memory_setup
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
