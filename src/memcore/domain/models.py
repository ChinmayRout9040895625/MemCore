"""Domain models — the contract every layer of MemCore agrees on.

Design notes
------------
* Models are ``pydantic`` v2 ``BaseModel`` with ``extra="forbid"`` so typos in
  payloads fail loudly rather than silently vanishing.
* Records carry versioning + provenance from day one (ADR-007). Nothing is
  edited in place: an update produces a new :class:`MemoryRecord` whose
  ``supersedes`` points at the prior version.
* Times are timezone-aware UTC. We track *bitemporality*: ``created_at`` /
  ``version`` capture when MemCore learned something, while ``valid_from`` /
  ``valid_to`` capture when it is true in the world.
* These models are pure data — no I/O, no persistence logic. Adapters translate
  them to/from Qdrant payloads, Neo4j nodes, Redis entries, etc.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from memcore.domain.enums import (
    AuditAction,
    EntityType,
    MemoryStatus,
    MemoryType,
    Operation,
)


def utcnow() -> datetime:
    """Timezone-aware current UTC timestamp (single source of 'now')."""
    return datetime.now(UTC)


def new_id() -> str:
    """Generate a fresh opaque identifier."""
    return str(uuid.uuid4())


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=False)


class Interaction(_Base):
    """A single raw turn/event as ingested, before consolidation.

    Immutable archive unit; the ground truth from which memories are derived.
    """

    id: str = Field(default_factory=new_id)
    tenant_id: str
    agent_id: str
    session_id: str
    role: str  # e.g. "user", "assistant", "tool", "system"
    content: str
    timestamp: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryRecord(_Base):
    """A single versioned unit of memory (working, episodic or semantic).

    ``embedding_ref`` is the id of the vector in the vector store (if any);
    the vector itself is not carried on the model to keep it lightweight.
    """

    id: str = Field(default_factory=new_id)
    tenant_id: str
    agent_id: str
    type: MemoryType
    content: str

    embedding_ref: str | None = None
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    # Reinforcement / decay signals.
    created_at: datetime = Field(default_factory=utcnow)
    last_accessed_at: datetime | None = None
    access_count: int = Field(default=0, ge=0)
    # Snapshot maintained by the decay job (services/decay.py), not recomputed
    # live (ADR-0015, ADR-0016).
    decay_score: float = Field(default=1.0, ge=0.0, le=1.0)

    # Bitemporal validity (world-time).
    valid_from: datetime = Field(default_factory=utcnow)
    valid_to: datetime | None = None

    # Versioning / provenance (knowledge-time).
    version: int = Field(default=1, ge=1)
    supersedes: str | None = None
    status: MemoryStatus = MemoryStatus.ACTIVE
    source_refs: list[str] = Field(default_factory=list)

    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_validity_window(self) -> MemoryRecord:
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to must not precede valid_from")
        return self

    def superseded_by(self, **changes: Any) -> MemoryRecord:
        """Return a new version of this record carrying ``changes``.

        The returned record has ``version + 1`` and ``supersedes`` set to this
        record's id. This record is expected to be marked ``SUPERSEDED`` by the
        caller/persistence layer. Purely functional — no mutation here.
        """
        data = self.model_dump()
        data.update(changes)
        data["id"] = new_id()
        data["version"] = self.version + 1
        data["supersedes"] = self.id
        data["status"] = MemoryStatus.ACTIVE
        data["created_at"] = utcnow()
        return MemoryRecord.model_validate(data)


class Entity(_Base):
    """A node in the knowledge graph (person, org, concept, ...)."""

    id: str = Field(default_factory=new_id)
    tenant_id: str
    agent_id: str
    name: str
    canonical_name: str
    type: EntityType = EntityType.OTHER
    aliases: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    first_seen: datetime = Field(default_factory=utcnow)
    last_seen: datetime = Field(default_factory=utcnow)
    source_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Relation(_Base):
    """A directed, temporal, versioned edge between two entities.

    Encodes ``subject_id -[predicate]-> object_id`` with provenance and a
    validity window so contradictory relations can coexist across time.
    """

    id: str = Field(default_factory=new_id)
    tenant_id: str
    agent_id: str
    subject_id: str
    predicate: str
    object_id: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    valid_from: datetime = Field(default_factory=utcnow)
    valid_to: datetime | None = None
    version: int = Field(default=1, ge=1)
    status: MemoryStatus = MemoryStatus.ACTIVE
    provenance: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Session(_Base):
    """A session groups interactions and tracks consolidation progress."""

    id: str = Field(default_factory=new_id)
    tenant_id: str
    agent_id: str
    opened_at: datetime = Field(default_factory=utcnow)
    last_activity: datetime = Field(default_factory=utcnow)
    token_count: int = Field(default=0, ge=0)
    turn_count: int = Field(default=0, ge=0)
    # Watermark: interactions up to this timestamp are already consolidated.
    consolidation_watermark: datetime | None = None
    closed: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditEvent(_Base):
    """An append-only audit entry. ``before_hash``/``after_hash`` support
    tamper-evidence; the chain is elaborated in the security phase."""

    id: str = Field(default_factory=new_id)
    tenant_id: str
    actor: str
    action: AuditAction
    target_id: str | None = None
    timestamp: datetime = Field(default_factory=utcnow)
    before_hash: str | None = None
    after_hash: str | None = None
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScoredMemory(_Base):
    """A memory returned from retrieval with its hybrid-score breakdown.

    ``final`` is the blended score; the components are exposed so callers can
    audit *why* a memory ranked where it did (a first-class product feature).
    """

    memory: MemoryRecord
    relevance: float = Field(ge=0.0, le=1.0)
    recency: float = Field(ge=0.0, le=1.0)
    importance: float = Field(ge=0.0, le=1.0)
    final: float = Field(ge=0.0)


class ConsolidationCandidate(_Base):
    """A proposed memory change emitted by the consolidation agent."""

    operation: Operation
    memory: MemoryRecord | None = None
    target_id: str | None = None  # for UPDATE/DELETE
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    rationale: str | None = None
