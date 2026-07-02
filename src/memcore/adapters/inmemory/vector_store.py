"""In-memory :class:`VectorStore` using exact cosine similarity.

Brute-force and O(N) per query — intended for tests and small local runs, not
production. Payload filtering mirrors the equality/`in` semantics adapters like
Qdrant provide, so tests exercising tenant isolation are meaningful.
"""

from __future__ import annotations

import math
from typing import Any

from memcore.ports.vector_store import VectorHit, VectorRecord, VectorStore


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"dimension mismatch: {len(a)} != {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _matches(payload: dict[str, Any], filters: dict[str, Any]) -> bool:
    """Equality match; a list filter value means 'payload value in list'."""
    for key, expected in filters.items():
        actual = payload.get(key)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


class InMemoryVectorStore(VectorStore):
    def __init__(self) -> None:
        # collection -> id -> VectorRecord
        self._data: dict[str, dict[str, VectorRecord]] = {}
        self._dims: dict[str, int] = {}

    async def ensure_collection(self, name: str, dimension: int) -> None:
        self._data.setdefault(name, {})
        self._dims[name] = dimension

    async def upsert(self, collection: str, records: list[VectorRecord]) -> None:
        store = self._data.setdefault(collection, {})
        dim = self._dims.get(collection)
        for record in records:
            if dim is not None and len(record.vector) != dim:
                raise ValueError(
                    f"vector dim {len(record.vector)} != collection dim {dim}"
                )
            store[record.id] = record

    async def search(
        self,
        collection: str,
        query: list[float],
        *,
        limit: int,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorHit]:
        store = self._data.get(collection, {})
        filters = filters or {}
        hits = [
            VectorHit(id=rec.id, score=_cosine(query, rec.vector), payload=rec.payload)
            for rec in store.values()
            if _matches(rec.payload, filters)
        ]
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    async def delete(self, collection: str, ids: list[str]) -> None:
        store = self._data.get(collection, {})
        for id_ in ids:
            store.pop(id_, None)

    async def count(self, collection: str, filters: dict[str, Any] | None = None) -> int:
        store = self._data.get(collection, {})
        if not filters:
            return len(store)
        return sum(1 for rec in store.values() if _matches(rec.payload, filters))
