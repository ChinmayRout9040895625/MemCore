"""ObjectStore port — durable blob storage.

Backs the immutable raw-interaction archive, backups, and eval datasets
(S3-compatible in production). Used as the ultimate source for rebuilding the
vector/graph projections during disaster recovery.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ObjectStore(ABC):
    """Port for a blob store keyed by string path."""

    @abstractmethod
    async def put(self, key: str, data: bytes) -> None:
        """Store ``data`` at ``key`` (overwrites)."""

    @abstractmethod
    async def get(self, key: str) -> bytes | None:
        """Fetch bytes at ``key``, or ``None`` if absent."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete the object at ``key`` (no error if absent)."""

    @abstractmethod
    async def list_keys(self, prefix: str) -> list[str]:
        """List keys under ``prefix``."""
