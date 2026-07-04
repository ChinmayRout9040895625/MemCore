"""MemoryService — explicit memory writes with versioning + audit.

Owns the record/vector pair: the metadata store is the source of truth
(ADR-0005); the vector store is a projection kept in step here. When the
consolidation phase lands, its writes flow through this same service so the
invariants live in exactly one place.
"""

from __future__ import annotations

from memcore.domain.enums import AuditAction, MemoryStatus, MemoryType
from memcore.domain.models import AuditEvent, MemoryRecord, utcnow
from memcore.exceptions import NotFoundError, ValidationError
from memcore.ports.embedding_provider import EmbeddingProvider
from memcore.ports.memory_store import MemoryStore
from memcore.ports.vector_store import VectorRecord, VectorStore


class MemoryService:
    def __init__(
        self,
        store: MemoryStore,
        vectors: VectorStore,
        embedder: EmbeddingProvider,
        *,
        collection: str,
    ) -> None:
        self._store = store
        self._vectors = vectors
        self._embedder = embedder
        self._collection = collection

    @property
    def collection(self) -> str:
        return self._collection

    async def ensure_ready(self) -> None:
        await self._vectors.ensure_collection(self._collection, self._embedder.dimension)

    async def embed(self, text: str) -> list[float]:
        """Embed arbitrary text with the service's embedder (used by
        consolidation for related-memory lookups against this collection)."""
        return await self._embedder.embed_one(text)

    # -- writes ----------------------------------------------------------------
    async def remember(
        self,
        tenant_id: str,
        agent_id: str,
        content: str,
        *,
        type: MemoryType = MemoryType.SEMANTIC,
        importance: float = 0.5,
        confidence: float = 1.0,
        tags: list[str] | None = None,
        source_refs: list[str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> MemoryRecord:
        if not content.strip():
            raise ValidationError("memory content must not be empty")
        record = MemoryRecord(
            tenant_id=tenant_id,
            agent_id=agent_id,
            type=type,
            content=content,
            importance=importance,
            confidence=confidence,
            tags=tags or [],
            source_refs=source_refs or [],
            metadata=dict(metadata or {}),
        )
        record = record.model_copy(update={"embedding_ref": record.id})
        await self._index(record)
        await self._store.add(record)
        await self._audit(tenant_id, AuditAction.CREATE, record.id)
        return record

    async def correct(
        self,
        tenant_id: str,
        memory_id: str,
        *,
        content: str | None = None,
        importance: float | None = None,
        confidence: float | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> MemoryRecord:
        """Create a new version superseding ``memory_id`` (ADR-0007)."""
        old = await self._get_active(tenant_id, memory_id)
        changes: dict[str, object] = {}
        if content is not None:
            changes["content"] = content
        if importance is not None:
            changes["importance"] = importance
        if confidence is not None:
            changes["confidence"] = confidence
        if tags is not None:
            changes["tags"] = tags
        if metadata is not None:
            changes["metadata"] = dict(metadata)
        if not changes:
            raise ValidationError("no changes provided")

        new = old.superseded_by(**changes)
        new = new.model_copy(update={"embedding_ref": new.id})
        await self._index(new)
        await self._store.supersede(tenant_id, old.id, new)
        # Superseded versions must not be retrievable via vector search.
        await self._vectors.delete(self._collection, [old.id])
        await self._audit(tenant_id, AuditAction.UPDATE, new.id,
                          reason=f"supersedes {old.id}")
        return new

    async def forget(
        self, tenant_id: str, memory_id: str, *, mode: str = "soft",
        reason: str | None = None,
    ) -> None:
        if mode not in ("soft", "hard"):
            raise ValidationError(f"invalid delete mode: {mode!r}")
        record = await self._store.get(tenant_id, memory_id)
        if record is None:
            raise NotFoundError(f"memory {memory_id} not found")
        status = (
            MemoryStatus.SOFT_DELETED if mode == "soft" else MemoryStatus.HARD_DELETED
        )
        await self._store.set_status(tenant_id, memory_id, status)
        # Either way it leaves the retrievable index immediately.
        await self._vectors.delete(self._collection, [memory_id])
        await self._audit(
            tenant_id,
            AuditAction.DELETE if mode == "soft" else AuditAction.ERASE,
            memory_id,
            reason=reason or f"{mode} delete",
        )

    # -- reads -------------------------------------------------------------------
    async def get(self, tenant_id: str, memory_id: str) -> MemoryRecord:
        record = await self._store.get(tenant_id, memory_id)
        if record is None or record.status is MemoryStatus.HARD_DELETED:
            raise NotFoundError(f"memory {memory_id} not found")
        return record

    async def versions(self, tenant_id: str, memory_id: str) -> list[MemoryRecord]:
        chain = await self._store.versions(tenant_id, memory_id)
        if not chain:
            raise NotFoundError(f"memory {memory_id} not found")
        return chain

    # -- internals -----------------------------------------------------------
    async def _get_active(self, tenant_id: str, memory_id: str) -> MemoryRecord:
        record = await self._store.get(tenant_id, memory_id)
        if record is None:
            raise NotFoundError(f"memory {memory_id} not found")
        if record.status is not MemoryStatus.ACTIVE:
            raise ValidationError(
                f"memory {memory_id} is {record.status.value}, not active"
            )
        return record

    async def _index(self, record: MemoryRecord) -> None:
        vector = await self._embedder.embed_one(record.content)
        await self._vectors.upsert(
            self._collection,
            [
                VectorRecord(
                    id=record.id,
                    vector=vector,
                    payload={
                        "tenant_id": record.tenant_id,
                        "agent_id": record.agent_id,
                        "type": record.type.value,
                        "status": record.status.value,
                        "embedding_model": self._embedder.model,
                    },
                )
            ],
        )

    async def _audit(
        self,
        tenant_id: str,
        action: AuditAction,
        target_id: str,
        *,
        reason: str | None = None,
    ) -> None:
        await self._store.add_audit(
            AuditEvent(
                tenant_id=tenant_id,
                actor="api",
                action=action,
                target_id=target_id,
                timestamp=utcnow(),
                reason=reason,
            )
        )
