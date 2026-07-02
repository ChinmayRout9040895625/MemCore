"""SQLAlchemy-async :class:`MemoryStore` (ADR-0012).

Portability conventions:
* Datetimes are stored as ISO-8601 strings (UTC), which sort correctly
  lexicographically and behave identically on SQLite and Postgres. Native
  timestamptz columns can arrive with a dedicated migration later without
  changing the port.
* Enums are stored by value; list/dict fields as JSON.
* ``supersede`` runs in a single transaction (atomicity of ADR-0007's
  version-flip is what keeps false overwrites recoverable).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Float, Integer, String, Text, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool

from memcore.domain.enums import AuditAction, MemoryStatus, MemoryType
from memcore.domain.models import AuditEvent, MemoryRecord, Session
from memcore.exceptions import ConflictError, NotFoundError
from memcore.ports.memory_store import MemoryStore


class Base(DeclarativeBase):
    pass


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class MemoryRow(Base):
    __tablename__ = "memory_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    type: Mapped[str] = mapped_column(String(16), index=True)
    content: Mapped[str] = mapped_column(Text)
    embedding_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    importance: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    created_at: Mapped[str] = mapped_column(String(40), index=True)
    last_accessed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    access_count: Mapped[int] = mapped_column(Integer)
    decay_score: Mapped[float] = mapped_column(Float)
    valid_from: Mapped[str] = mapped_column(String(40))
    valid_to: Mapped[str | None] = mapped_column(String(40), nullable=True)
    version: Mapped[int] = mapped_column(Integer)
    supersedes: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    source_refs: Mapped[list[str]] = mapped_column(JSON)
    tags: Mapped[list[str]] = mapped_column(JSON)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON)


class AuditRow(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    timestamp: Mapped[str] = mapped_column(String(40), index=True)
    before_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    after_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON)


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    opened_at: Mapped[str] = mapped_column(String(40))
    last_activity: Mapped[str] = mapped_column(String(40))
    token_count: Mapped[int] = mapped_column(Integer)
    turn_count: Mapped[int] = mapped_column(Integer)
    consolidation_watermark: Mapped[str | None] = mapped_column(String(40), nullable=True)
    closed: Mapped[int] = mapped_column(Integer)  # 0/1 for cross-engine bools
    meta: Mapped[dict[str, Any]] = mapped_column(JSON)


def _record_to_row(r: MemoryRecord) -> MemoryRow:
    return MemoryRow(
        id=r.id, tenant_id=r.tenant_id, agent_id=r.agent_id, type=r.type.value,
        content=r.content, embedding_ref=r.embedding_ref, importance=r.importance,
        confidence=r.confidence, created_at=r.created_at.isoformat(),
        last_accessed_at=_iso(r.last_accessed_at), access_count=r.access_count,
        decay_score=r.decay_score, valid_from=r.valid_from.isoformat(),
        valid_to=_iso(r.valid_to), version=r.version, supersedes=r.supersedes,
        status=r.status.value, source_refs=list(r.source_refs), tags=list(r.tags),
        meta=dict(r.metadata),
    )


def _row_to_record(row: MemoryRow) -> MemoryRecord:
    return MemoryRecord(
        id=row.id, tenant_id=row.tenant_id, agent_id=row.agent_id,
        type=MemoryType(row.type), content=row.content,
        embedding_ref=row.embedding_ref, importance=row.importance,
        confidence=row.confidence, created_at=_dt(row.created_at) or datetime.min,
        last_accessed_at=_dt(row.last_accessed_at), access_count=row.access_count,
        decay_score=row.decay_score, valid_from=_dt(row.valid_from) or datetime.min,
        valid_to=_dt(row.valid_to), version=row.version, supersedes=row.supersedes,
        status=MemoryStatus(row.status), source_refs=list(row.source_refs),
        tags=list(row.tags), metadata=dict(row.meta),
    )


class SqlMemoryStore(MemoryStore):
    def __init__(self, url: str) -> None:
        kwargs: dict[str, Any] = {}
        if url.startswith("sqlite") and ":memory:" in url:
            # A shared in-memory SQLite needs a single reused connection.
            kwargs = {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
        self._engine: AsyncEngine = create_async_engine(url, **kwargs)
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)

    async def init(self) -> None:
        """Create tables if absent (idempotent). Real deployments will move to
        migration tooling; called from app startup for now."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self._engine.dispose()

    # -- records -------------------------------------------------------------
    async def add(self, record: MemoryRecord) -> None:
        async with self._sessions() as db:
            existing = await db.get(MemoryRow, record.id)
            if existing is not None:
                raise ConflictError(f"memory {record.id} already exists")
            db.add(_record_to_row(record))
            await db.commit()

    async def get(self, tenant_id: str, memory_id: str) -> MemoryRecord | None:
        async with self._sessions() as db:
            row = await db.get(MemoryRow, memory_id)
            if row is None or row.tenant_id != tenant_id:
                return None
            return _row_to_record(row)

    async def list_records(
        self,
        tenant_id: str,
        agent_id: str,
        *,
        type: MemoryType | None = None,
        status: MemoryStatus | None = MemoryStatus.ACTIVE,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        stmt = (
            select(MemoryRow)
            .where(MemoryRow.tenant_id == tenant_id, MemoryRow.agent_id == agent_id)
            .order_by(MemoryRow.created_at.desc())
            .limit(limit)
        )
        if type is not None:
            stmt = stmt.where(MemoryRow.type == type.value)
        if status is not None:
            stmt = stmt.where(MemoryRow.status == status.value)
        async with self._sessions() as db:
            rows = (await db.scalars(stmt)).all()
        return [_row_to_record(row) for row in rows]

    async def versions(self, tenant_id: str, memory_id: str) -> list[MemoryRecord]:
        current = await self.get(tenant_id, memory_id)
        if current is None:
            return []
        chain = [current]
        async with self._sessions() as db:
            # Ancestors.
            while chain[0].supersedes:
                row = await db.get(MemoryRow, chain[0].supersedes)
                if row is None or row.tenant_id != tenant_id:
                    break
                chain.insert(0, _row_to_record(row))
            # Descendants.
            while True:
                stmt = select(MemoryRow).where(
                    MemoryRow.tenant_id == tenant_id,
                    MemoryRow.supersedes == chain[-1].id,
                )
                row = (await db.scalars(stmt)).first()
                if row is None:
                    break
                chain.append(_row_to_record(row))
        return chain

    async def supersede(
        self, tenant_id: str, old_id: str, new_record: MemoryRecord
    ) -> None:
        async with self._sessions() as db, db.begin():
            old = await db.get(MemoryRow, old_id)
            if old is None or old.tenant_id != tenant_id:
                raise NotFoundError(f"memory {old_id} not found")
            old.status = MemoryStatus.SUPERSEDED.value
            db.add(_record_to_row(new_record))

    async def set_status(
        self, tenant_id: str, memory_id: str, status: MemoryStatus
    ) -> None:
        async with self._sessions() as db, db.begin():
            row = await db.get(MemoryRow, memory_id)
            if row is None or row.tenant_id != tenant_id:
                raise NotFoundError(f"memory {memory_id} not found")
            row.status = status.value

    async def reinforce(
        self, tenant_id: str, memory_ids: list[str], accessed_at: datetime
    ) -> None:
        if not memory_ids:
            return
        stmt = (
            update(MemoryRow)
            .where(MemoryRow.tenant_id == tenant_id, MemoryRow.id.in_(memory_ids))
            .values(
                access_count=MemoryRow.access_count + 1,
                last_accessed_at=accessed_at.isoformat(),
            )
        )
        async with self._sessions() as db, db.begin():
            await db.execute(stmt)

    # -- audit ---------------------------------------------------------------
    async def add_audit(self, event: AuditEvent) -> None:
        row = AuditRow(
            id=event.id, tenant_id=event.tenant_id, actor=event.actor,
            action=event.action.value, target_id=event.target_id,
            timestamp=event.timestamp.isoformat(), before_hash=event.before_hash,
            after_hash=event.after_hash, reason=event.reason, meta=dict(event.metadata),
        )
        async with self._sessions() as db:
            db.add(row)
            await db.commit()

    async def list_audit(self, tenant_id: str, *, limit: int = 100) -> list[AuditEvent]:
        stmt = (
            select(AuditRow)
            .where(AuditRow.tenant_id == tenant_id)
            .order_by(AuditRow.timestamp.desc())
            .limit(limit)
        )
        async with self._sessions() as db:
            rows = (await db.scalars(stmt)).all()
        return [
            AuditEvent(
                id=r.id, tenant_id=r.tenant_id, actor=r.actor,
                action=AuditAction(r.action), target_id=r.target_id,
                timestamp=_dt(r.timestamp) or datetime.min,
                before_hash=r.before_hash, after_hash=r.after_hash,
                reason=r.reason, metadata=dict(r.meta),
            )
            for r in rows
        ]

    # -- sessions ------------------------------------------------------------
    async def put_session(self, session: Session) -> None:
        async with self._sessions() as db, db.begin():
            row = await db.get(SessionRow, session.id)
            if row is None:
                row = SessionRow(id=session.id)
                db.add(row)
            row.tenant_id = session.tenant_id
            row.agent_id = session.agent_id
            row.opened_at = session.opened_at.isoformat()
            row.last_activity = session.last_activity.isoformat()
            row.token_count = session.token_count
            row.turn_count = session.turn_count
            row.consolidation_watermark = _iso(session.consolidation_watermark)
            row.closed = 1 if session.closed else 0
            row.meta = dict(session.metadata)

    async def get_session(self, tenant_id: str, session_id: str) -> Session | None:
        async with self._sessions() as db:
            row = await db.get(SessionRow, session_id)
        if row is None or row.tenant_id != tenant_id:
            return None
        return Session(
            id=row.id, tenant_id=row.tenant_id, agent_id=row.agent_id,
            opened_at=_dt(row.opened_at) or datetime.min,
            last_activity=_dt(row.last_activity) or datetime.min,
            token_count=row.token_count, turn_count=row.turn_count,
            consolidation_watermark=_dt(row.consolidation_watermark),
            closed=bool(row.closed), metadata=dict(row.meta),
        )
