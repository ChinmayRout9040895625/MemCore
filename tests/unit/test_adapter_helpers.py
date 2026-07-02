"""Unit tests for pure helpers inside the live-backend adapters.

These need no running server: they exercise the filter builder and the Neo4j
property (de)serialization in isolation. The adapters' network paths are covered
by the integration suite.
"""

from __future__ import annotations

from datetime import timedelta

from qdrant_client import models

from memcore.adapters.neo4j.graph_store import (
    _entity_from_props,
    _entity_to_props,
    _relation_from_props,
    _relation_to_props,
)
from memcore.adapters.qdrant.vector_store import _to_filter
from memcore.domain.enums import EntityType
from memcore.domain.models import Entity, Relation, utcnow


def test_to_filter_none_when_empty() -> None:
    assert _to_filter(None) is None
    assert _to_filter({}) is None


def test_to_filter_equality_and_membership() -> None:
    flt = _to_filter({"tenant_id": "t1", "type": ["semantic", "episodic"]})
    assert flt is not None
    assert flt.must is not None

    by_key: dict[str, models.FieldCondition] = {}
    for cond in flt.must:
        assert isinstance(cond, models.FieldCondition)  # narrows the union
        by_key[cond.key] = cond

    tenant_match = by_key["tenant_id"].match
    assert isinstance(tenant_match, models.MatchValue)
    assert tenant_match.value == "t1"

    type_match = by_key["type"].match
    assert isinstance(type_match, models.MatchAny)
    assert type_match.any == ["semantic", "episodic"]


def test_entity_props_roundtrip() -> None:
    ent = Entity(
        tenant_id="t1",
        agent_id="a1",
        name="Alice",
        canonical_name="alice",
        type=EntityType.PERSON,
        aliases=["Ally", "Al"],
        metadata={"note": "primary contact"},
    )
    restored = _entity_from_props(_entity_to_props(ent))
    assert restored == ent


def test_relation_props_roundtrip_both_validity_states() -> None:
    now = utcnow()
    open_rel = Relation(
        tenant_id="t1", agent_id="a1", subject_id="e1",
        predicate="knows", object_id="e2", metadata={"src": "chat"},
    )
    closed_rel = Relation(
        tenant_id="t1", agent_id="a1", subject_id="e1",
        predicate="lived_in", object_id="e3",
        valid_from=now - timedelta(days=10), valid_to=now,
    )
    assert _relation_from_props(_relation_to_props(open_rel)) == open_rel
    assert _relation_from_props(_relation_to_props(closed_rel)) == closed_rel
