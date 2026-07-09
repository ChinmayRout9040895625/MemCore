"""Core enumerations shared across the MemCore domain.

These values are part of MemCore's public contract: they are persisted, exposed
over the API, and referenced by every adapter. Treat additions as backward
compatible and removals/renames as breaking changes.
"""

from __future__ import annotations

from enum import StrEnum


class MemoryType(StrEnum):
    """The three cognitive memory tiers (see docs/design/taxonomy.md)."""

    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"


class MemoryStatus(StrEnum):
    """Lifecycle status of a memory record.

    Records are immutable and versioned (ADR-007): an UPDATE writes a new
    version and marks the prior one ``SUPERSEDED``. Forgetting is reversible
    (``SOFT_DELETED``) until a retention/GDPR job makes it ``HARD_DELETED``.
    """

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    SOFT_DELETED = "soft_deleted"
    HARD_DELETED = "hard_deleted"


class Operation(StrEnum):
    """Consolidation operation chosen for a candidate memory."""

    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"
    NOOP = "noop"


class EntityType(StrEnum):
    """Coarse entity classes for the knowledge graph."""

    PERSON = "person"
    ORG = "org"
    PLACE = "place"
    CONCEPT = "concept"
    EVENT = "event"
    OBJECT = "object"
    OTHER = "other"


class AuditAction(StrEnum):
    """Actions recorded in the append-only audit log."""

    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    CONSOLIDATE = "consolidate"
    PRUNE = "prune"
    FORGET = "forget"
    ERASE = "erase"
    RESTORE = "restore"


class Role(StrEnum):
    """RBAC roles bound per tenant (elaborated in the security phase)."""

    OWNER = "owner"
    ADMIN = "admin"
    WRITER = "writer"
    READER = "reader"
    AUDITOR = "auditor"
