"""VectorStore port — filtered approximate nearest-neighbour search.

Default adapter: Qdrant (ADR-002). All methods are tenant/agent scoped via the
``filters`` argument; adapters MUST enforce isolation on every query.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VectorRecord:
    """A vector plus the payload used for filtering and back-reference."""

    id: str
    vector: list[float]
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorHit:
    """A search result: the stored id/payload and its similarity score."""

    id: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)


class VectorStore(ABC):
    """Port for a vector database backing semantic/episodic retrieval."""

    @abstractmethod
    async def ensure_collection(self, name: str, dimension: int) -> None:
        """Idempotently create the collection/index if it does not exist."""

    @abstractmethod
    async def upsert(self, collection: str, records: list[VectorRecord]) -> None:
        """Insert or replace vectors by id."""

    @abstractmethod
    async def search(
        self,
        collection: str,
        query: list[float],
        *,
        limit: int,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorHit]:
        """Return up to ``limit`` nearest neighbours matching ``filters``."""

    @abstractmethod
    async def delete(self, collection: str, ids: list[str]) -> None:
        """Hard-delete vectors by id."""

    @abstractmethod
    async def count(self, collection: str, filters: dict[str, Any] | None = None) -> int:
        """Count vectors matching ``filters`` (for tests/observability)."""
