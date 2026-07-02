"""WorkingMemory port — fast, session-scoped, ephemeral memory.

Default adapter: Redis. Backs the recent-turn buffer and per-session scratch KV.
Entries are TTL'd; nothing here is durable (it is consolidated into episodic /
semantic memory before expiry).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from memcore.domain.models import Interaction


class WorkingMemory(ABC):
    """Port for session-scoped short-term memory."""

    @abstractmethod
    async def append(self, session_id: str, interaction: Interaction) -> None:
        """Append a turn to the session buffer (bounded + TTL refreshed)."""

    @abstractmethod
    async def recent(self, session_id: str, *, limit: int = 50) -> list[Interaction]:
        """Return the most recent ``limit`` turns, oldest-first."""

    @abstractmethod
    async def set_scratch(self, session_id: str, key: str, value: str) -> None:
        """Set a scratch key-value pair for the session."""

    @abstractmethod
    async def get_scratch(self, session_id: str, key: str) -> str | None:
        """Get a scratch value, or ``None``."""

    @abstractmethod
    async def clear(self, session_id: str) -> None:
        """Drop all buffer + scratch data for the session."""
