"""In-memory :class:`MemoryStore` reference adapter."""

from __future__ import annotations

from datetime import datetime

from memcore.domain.enums import MemoryStatus, MemoryType
from memcore.domain.models import AuditEvent, MemoryRecord, Session
from memcore.exceptions import ConflictError, NotFoundError
from memcore.ports.memory_store import MemoryStore


class InMemoryMemoryStore(MemoryStore):
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], MemoryRecord] = {}
        self._audit: list[AuditEvent] = []
        self._sessions: dict[tuple[str, str], Session] = {}

    # -- records -------------------------------------------------------------
    async def add(self, record: MemoryRecord) -> None:
        key = (record.tenant_id, record.id)
        if key in self._records:
            raise ConflictError(f"memory {record.id} already exists")
        self._records[key] = record

    async def get(self, tenant_id: str, memory_id: str) -> MemoryRecord | None:
        return self._records.get((tenant_id, memory_id))

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
        rows = [
            r
            for (tid, _), r in self._records.items()
            if tid == tenant_id
            and (agent_id is None or r.agent_id == agent_id)
            and (type is None or r.type == type)
            and (status is None or r.status == status)
        ]
        rows.sort(key=lambda r: r.created_at, reverse=not oldest_first)
        return rows[:limit]

    async def versions(self, tenant_id: str, memory_id: str) -> list[MemoryRecord]:
        current = await self.get(tenant_id, memory_id)
        if current is None:
            return []
        # Walk back to the chain root.
        chain = [current]
        while chain[0].supersedes:
            prior = await self.get(tenant_id, chain[0].supersedes)
            if prior is None:
                break
            chain.insert(0, prior)
        # Walk forward through descendants.
        by_supersedes = {
            r.supersedes: r
            for (tid, _), r in self._records.items()
            if tid == tenant_id and r.supersedes
        }
        while chain[-1].id in by_supersedes:
            chain.append(by_supersedes[chain[-1].id])
        return chain

    async def supersede(
        self, tenant_id: str, old_id: str, new_record: MemoryRecord
    ) -> None:
        old = await self.get(tenant_id, old_id)
        if old is None:
            raise NotFoundError(f"memory {old_id} not found")
        await self.add(new_record)
        self._records[(tenant_id, old_id)] = old.model_copy(
            update={"status": MemoryStatus.SUPERSEDED}
        )

    async def set_status(
        self, tenant_id: str, memory_id: str, status: MemoryStatus
    ) -> None:
        record = await self.get(tenant_id, memory_id)
        if record is None:
            raise NotFoundError(f"memory {memory_id} not found")
        self._records[(tenant_id, memory_id)] = record.model_copy(
            update={"status": status}
        )

    async def reinforce(
        self, tenant_id: str, memory_ids: list[str], accessed_at: datetime
    ) -> None:
        for memory_id in memory_ids:
            record = await self.get(tenant_id, memory_id)
            if record is not None:
                self._records[(tenant_id, memory_id)] = record.model_copy(
                    update={
                        "access_count": record.access_count + 1,
                        "last_accessed_at": accessed_at,
                    }
                )

    async def set_decay(self, tenant_id: str, scores: dict[str, float]) -> None:
        for memory_id, score in scores.items():
            record = await self.get(tenant_id, memory_id)
            if record is not None:
                self._records[(tenant_id, memory_id)] = record.model_copy(
                    update={"decay_score": min(1.0, max(0.0, score))}
                )

    # -- audit ---------------------------------------------------------------
    async def add_audit(self, event: AuditEvent) -> None:
        self._audit.append(event)

    async def list_audit(self, tenant_id: str, *, limit: int = 100) -> list[AuditEvent]:
        rows = [e for e in self._audit if e.tenant_id == tenant_id]
        rows.sort(key=lambda e: e.timestamp, reverse=True)
        return rows[:limit]

    # -- sessions ------------------------------------------------------------
    async def put_session(self, session: Session) -> None:
        self._sessions[(session.tenant_id, session.id)] = session

    async def get_session(self, tenant_id: str, session_id: str) -> Session | None:
        return self._sessions.get((tenant_id, session_id))
