"""In-memory :class:`WorkingMemory`.

Bounded per-session buffer with scratch KV. TTL semantics are a no-op here
(process-local); the Redis adapter in Phase 2 implements real expiry.
"""

from __future__ import annotations

from collections import deque

from memcore.domain.models import Interaction
from memcore.ports.working_memory import WorkingMemory


class InMemoryWorkingMemory(WorkingMemory):
    def __init__(self, buffer_max_turns: int = 200) -> None:
        self._max = buffer_max_turns
        self._buffers: dict[str, deque[Interaction]] = {}
        self._scratch: dict[str, dict[str, str]] = {}

    async def append(self, session_id: str, interaction: Interaction) -> None:
        buf = self._buffers.get(session_id)
        if buf is None:
            buf = deque(maxlen=self._max)
            self._buffers[session_id] = buf
        buf.append(interaction)

    async def recent(self, session_id: str, *, limit: int = 50) -> list[Interaction]:
        buf = self._buffers.get(session_id)
        if not buf:
            return []
        items = list(buf)
        return items[-limit:]

    async def set_scratch(self, session_id: str, key: str, value: str) -> None:
        self._scratch.setdefault(session_id, {})[key] = value

    async def get_scratch(self, session_id: str, key: str) -> str | None:
        return self._scratch.get(session_id, {}).get(key)

    async def clear(self, session_id: str) -> None:
        self._buffers.pop(session_id, None)
        self._scratch.pop(session_id, None)
