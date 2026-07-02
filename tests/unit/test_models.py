"""Tests for domain models and their invariants."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError as PydanticValidationError

from memcore.domain.enums import MemoryStatus, MemoryType
from memcore.domain.models import (
    Entity,
    MemoryRecord,
    Relation,
    ScoredMemory,
    utcnow,
)


def test_memory_record_defaults(sample_memory: MemoryRecord) -> None:
    assert sample_memory.version == 1
    assert sample_memory.status is MemoryStatus.ACTIVE
    assert sample_memory.importance == 0.5
    assert sample_memory.supersedes is None
    assert sample_memory.created_at.tzinfo is not None  # tz-aware


def test_extra_fields_forbidden() -> None:
    with pytest.raises(PydanticValidationError):
        MemoryRecord(
            tenant_id="t1",
            agent_id="a1",
            type=MemoryType.SEMANTIC,
            content="x",
            bogus_field="nope",  # type: ignore[call-arg]
        )


def test_importance_bounds() -> None:
    with pytest.raises(PydanticValidationError):
        MemoryRecord(
            tenant_id="t1",
            agent_id="a1",
            type=MemoryType.SEMANTIC,
            content="x",
            importance=1.5,
        )


def test_superseded_by_creates_new_version(sample_memory: MemoryRecord) -> None:
    v2 = sample_memory.superseded_by(content="Chinmay finished MemCore Phase 1.")
    assert v2.version == 2
    assert v2.supersedes == sample_memory.id
    assert v2.id != sample_memory.id
    assert v2.status is MemoryStatus.ACTIVE
    assert v2.content != sample_memory.content
    # Original is untouched (immutability by version).
    assert sample_memory.version == 1
    assert sample_memory.content == "Chinmay is building MemCore."


def test_validity_window_rejected_when_inverted() -> None:
    now = utcnow()
    with pytest.raises(PydanticValidationError):
        MemoryRecord(
            tenant_id="t1",
            agent_id="a1",
            type=MemoryType.SEMANTIC,
            content="x",
            valid_from=now,
            valid_to=now - timedelta(days=1),
        )


def test_relation_roundtrip() -> None:
    rel = Relation(
        tenant_id="t1",
        agent_id="a1",
        subject_id="e1",
        predicate="works_on",
        object_id="e2",
    )
    dumped = rel.model_dump()
    restored = Relation.model_validate(dumped)
    assert restored == rel


def test_entity_defaults() -> None:
    ent = Entity(tenant_id="t1", agent_id="a1", name="Chinmay", canonical_name="chinmay")
    assert ent.aliases == []
    assert ent.confidence == 1.0


def test_scored_memory_breakdown(sample_memory: MemoryRecord) -> None:
    scored = ScoredMemory(
        memory=sample_memory,
        relevance=0.8,
        recency=0.6,
        importance=0.5,
        final=0.8 * 0.6 * 0.5,
    )
    assert 0.0 <= scored.final <= 1.0
    assert scored.memory is sample_memory
