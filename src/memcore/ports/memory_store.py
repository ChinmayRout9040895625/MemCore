"""MemoryStore port — the metadata source of truth (ADR-0005).

Holds authoritative, versioned memory records plus the append-only audit log
and session bookkeeping. Vector/graph stores are derived projections; this
store is what they can be rebuilt from (together with the raw archive).

Every method is tenant-scoped. Records are immutable: ``supersede`` is the only
sanctioned "update" and it atomically inserts the new version while marking the
old one ``SUPERSEDED`` (ADR-0007).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from memcore.domain.enums import MemoryStatus, MemoryType
from memcore.domain.models import AuditEvent, MemoryRecord, Session


class MemoryStore(ABC):
    """Port for the authoritative memory-record / audit / session store."""

    # -- records -------------------------------------------------------------
    @abstractmethod
    async def add(self, record: MemoryRecord) -> None:
        """Insert a new record (fails on duplicate id)."""

    @abstractmethod
    async def get(self, tenant_id: str, memory_id: str) -> MemoryRecord | None:
        """Fetch one record; ``None`` if absent or belonging to another tenant."""

    @abstractmethod
    async def list_records(
        self,
        tenant_id: str,
        agent_id: str | None,
        *,
        type: MemoryType | None = None,
        status: MemoryStatus | None = MemoryStatus.ACTIVE,
        limit: int = 100,
        oldest_first: bool = False,
    ) -> list[MemoryRecord]:
        """List records, newest-first by default. ``status=None`` means all
        statuses; ``agent_id=None`` means all agents in the tenant;
        ``oldest_first=True`` reverses the order so bounded scans (decay
        sweeps) start from the stale end. Ordering is deterministic: ties on
        ``created_at`` break by ``id``."""

    @abstractmethod
    async def versions(self, tenant_id: str, memory_id: str) -> list[MemoryRecord]:
        """Full version chain containing ``memory_id``, oldest-first."""

    @abstractmethod
    async def supersede(
        self, tenant_id: str, old_id: str, new_record: MemoryRecord
    ) -> None:
        """Atomically insert ``new_record`` and mark ``old_id`` SUPERSEDED."""

    @abstractmethod
    async def set_status(
        self, tenant_id: str, memory_id: str, status: MemoryStatus
    ) -> None:
        """Change a record's lifecycle status (soft/hard delete, restore)."""

    @abstractmethod
    async def reinforce(
        self, tenant_id: str, memory_ids: list[str], accessed_at: datetime
    ) -> None:
        """Bump ``access_count`` / ``last_accessed_at`` after successful recall."""

    @abstractmethod
    async def set_decay(self, tenant_id: str, scores: dict[str, float]) -> None:
        """Persist ``decay_score`` snapshots in place (Phase 7 decay job).

        Like ``reinforce`` this is a signal update, never a new version.
        Ids missing or belonging to another tenant are silently ignored.
        """

    # -- audit ---------------------------------------------------------------
    @abstractmethod
    async def add_audit(self, event: AuditEvent) -> None:
        """Append an audit event (append-only; never updated)."""

    @abstractmethod
    async def list_audit(self, tenant_id: str, *, limit: int = 100) -> list[AuditEvent]:
        """List audit events, newest-first."""

    # -- sessions ------------------------------------------------------------
    @abstractmethod
    async def put_session(self, session: Session) -> None:
        """Insert or replace session bookkeeping."""

    @abstractmethod
    async def get_session(self, tenant_id: str, session_id: str) -> Session | None:
        """Fetch a session; ``None`` if absent or another tenant's."""
