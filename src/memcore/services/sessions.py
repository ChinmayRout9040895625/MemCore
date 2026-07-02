"""SessionService — session lifecycle and the fast ingest path (ADR-0001).

``append`` is the hot write: push to working memory, archive the raw
interaction to the object store (the DR/rebuild source, ADR-0005), update
session stats. No LLM, no vector work — those happen at consolidation.
"""

from __future__ import annotations

from typing import Any

from memcore.domain.models import Interaction, Session, utcnow
from memcore.exceptions import NotFoundError, ValidationError
from memcore.ports.memory_store import MemoryStore
from memcore.ports.object_store import ObjectStore
from memcore.ports.working_memory import WorkingMemory


class SessionService:
    def __init__(
        self,
        store: MemoryStore,
        working_memory: WorkingMemory,
        object_store: ObjectStore,
    ) -> None:
        self._store = store
        self._working = working_memory
        self._objects = object_store

    async def open(self, tenant_id: str, agent_id: str) -> Session:
        session = Session(tenant_id=tenant_id, agent_id=agent_id)
        await self._store.put_session(session)
        return session

    async def get(self, tenant_id: str, session_id: str) -> Session:
        session = await self._store.get_session(tenant_id, session_id)
        if session is None:
            raise NotFoundError(f"session {session_id} not found")
        return session

    async def append(
        self,
        tenant_id: str,
        session_id: str,
        *,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        session = await self.get(tenant_id, session_id)
        if session.closed:
            raise ValidationError(f"session {session_id} is closed")

        interaction = Interaction(
            tenant_id=tenant_id,
            agent_id=session.agent_id,
            session_id=session_id,
            role=role,
            content=content,
            metadata=metadata or {},
        )
        await self._working.append(session_id, interaction)
        # Immutable raw archive — the ultimate rebuild source.
        await self._objects.put(
            f"raw/{tenant_id}/{session_id}/{interaction.id}.json",
            interaction.model_dump_json().encode(),
        )

        updated = session.model_copy(
            update={
                "turn_count": session.turn_count + 1,
                # Rough accounting until real tokenization lands with the SDK.
                "token_count": session.token_count + max(1, len(content) // 4),
                "last_activity": utcnow(),
            }
        )
        await self._store.put_session(updated)
        return updated

    async def close(self, tenant_id: str, session_id: str) -> Session:
        """Mark closed. Consolidation enqueue arrives with the workflow phase;
        until then closing only freezes the session."""
        session = await self.get(tenant_id, session_id)
        if session.closed:
            return session
        closed = session.model_copy(update={"closed": True, "last_activity": utcnow()})
        await self._store.put_session(closed)
        return closed
