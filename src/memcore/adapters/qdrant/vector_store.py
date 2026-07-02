"""Qdrant-backed :class:`VectorStore`.

Maps the port's generic ``payload`` dict onto Qdrant payload filters. Tenant and
agent scoping are the caller's responsibility via ``filters`` — but because every
retrieval path passes them, isolation is enforced on every query (ADR-0008).

Conventions (ADR-0011):
* Cosine distance; one collection per embedding dimension.
* Point ids are UUID strings (MemCore's native id format).
* Equality filters map to ``MatchValue``; list filters to ``MatchAny``.
"""

from __future__ import annotations

from typing import Any

from qdrant_client import AsyncQdrantClient, models

from memcore.exceptions import StorageError
from memcore.ports.vector_store import VectorHit, VectorRecord, VectorStore


def _to_filter(filters: dict[str, Any] | None) -> models.Filter | None:
    if not filters:
        return None
    conditions: list[models.FieldCondition] = []
    for key, value in filters.items():
        if isinstance(value, list):
            conditions.append(
                models.FieldCondition(key=key, match=models.MatchAny(any=value))
            )
        else:
            conditions.append(
                models.FieldCondition(key=key, match=models.MatchValue(value=value))
            )
    return models.Filter(must=conditions)


class QdrantVectorStore(VectorStore):
    def __init__(
        self, url: str, api_key: str | None = None, *, prefer_grpc: bool = False
    ) -> None:
        self._client = AsyncQdrantClient(
            url=url,
            api_key=api_key,
            prefer_grpc=prefer_grpc,
            check_compatibility=False,
        )

    async def ensure_collection(self, name: str, dimension: int) -> None:
        try:
            if await self._client.collection_exists(name):
                return
            await self._client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=dimension, distance=models.Distance.COSINE
                ),
            )
        except Exception as exc:  # pragma: no cover - network path
            raise StorageError(f"qdrant ensure_collection failed: {exc}") from exc

    async def upsert(self, collection: str, records: list[VectorRecord]) -> None:
        if not records:
            return
        points = [
            models.PointStruct(id=r.id, vector=r.vector, payload=r.payload)
            for r in records
        ]
        try:
            await self._client.upsert(collection_name=collection, points=points)
        except Exception as exc:  # pragma: no cover - network path
            raise StorageError(f"qdrant upsert failed: {exc}") from exc

    async def search(
        self,
        collection: str,
        query: list[float],
        *,
        limit: int,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorHit]:
        try:
            response = await self._client.query_points(
                collection_name=collection,
                query=query,
                query_filter=_to_filter(filters),
                limit=limit,
                with_payload=True,
            )
        except Exception as exc:  # pragma: no cover - network path
            raise StorageError(f"qdrant search failed: {exc}") from exc
        return [
            VectorHit(id=str(p.id), score=p.score, payload=dict(p.payload or {}))
            for p in response.points
        ]

    async def delete(self, collection: str, ids: list[str]) -> None:
        if not ids:
            return
        try:
            await self._client.delete(
                collection_name=collection,
                points_selector=models.PointIdsList(points=list(ids)),
            )
        except Exception as exc:  # pragma: no cover - network path
            raise StorageError(f"qdrant delete failed: {exc}") from exc

    async def count(self, collection: str, filters: dict[str, Any] | None = None) -> int:
        try:
            result = await self._client.count(
                collection_name=collection,
                count_filter=_to_filter(filters),
                exact=True,
            )
        except Exception as exc:  # pragma: no cover - network path
            raise StorageError(f"qdrant count failed: {exc}") from exc
        return int(result.count)

    async def close(self) -> None:
        await self._client.close()
