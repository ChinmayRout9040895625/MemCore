"""Redis-backed :class:`WorkingMemory`.

Key schema (ADR-0011), all under a configurable prefix:
* ``{prefix}:{session}:buffer``  — a capped list of JSON-encoded interactions.
* ``{prefix}:{session}:scratch`` — a hash of scratch key/values.

Both keys share a TTL that is refreshed on every write, so an idle session's
working memory expires (it is consolidated into durable memory before then).
The buffer is bounded with ``LTRIM`` to the newest ``buffer_max_turns`` entries.
"""

from __future__ import annotations

from typing import cast

import redis.asyncio as redis

from memcore.domain.models import Interaction
from memcore.exceptions import StorageError
from memcore.ports.working_memory import WorkingMemory


class RedisWorkingMemory(WorkingMemory):
    def __init__(
        self,
        url: str,
        *,
        prefix: str = "memcore",
        ttl_seconds: int = 3600,
        buffer_max_turns: int = 200,
    ) -> None:
        self._redis = redis.from_url(url, decode_responses=True)
        self._prefix = prefix
        self._ttl = ttl_seconds
        self._max = buffer_max_turns

    def _buffer_key(self, session_id: str) -> str:
        return f"{self._prefix}:{session_id}:buffer"

    def _scratch_key(self, session_id: str) -> str:
        return f"{self._prefix}:{session_id}:scratch"

    async def append(self, session_id: str, interaction: Interaction) -> None:
        key = self._buffer_key(session_id)
        try:
            pipe = self._redis.pipeline()
            pipe.rpush(key, interaction.model_dump_json())
            pipe.ltrim(key, -self._max, -1)
            pipe.expire(key, self._ttl)
            await pipe.execute()
        except Exception as exc:  # pragma: no cover - network path
            raise StorageError(f"redis append failed: {exc}") from exc

    async def recent(self, session_id: str, *, limit: int = 50) -> list[Interaction]:
        key = self._buffer_key(session_id)
        try:
            raw = await self._redis.lrange(key, -limit, -1)
        except Exception as exc:  # pragma: no cover - network path
            raise StorageError(f"redis recent failed: {exc}") from exc
        return [Interaction.model_validate_json(item) for item in raw]

    async def set_scratch(self, session_id: str, key: str, value: str) -> None:
        skey = self._scratch_key(session_id)
        try:
            pipe = self._redis.pipeline()
            pipe.hset(skey, key, value)
            pipe.expire(skey, self._ttl)
            await pipe.execute()
        except Exception as exc:  # pragma: no cover - network path
            raise StorageError(f"redis set_scratch failed: {exc}") from exc

    async def get_scratch(self, session_id: str, key: str) -> str | None:
        try:
            # decode_responses=True guarantees str values (or None).
            value = await self._redis.hget(self._scratch_key(session_id), key)
            return cast("str | None", value)
        except Exception as exc:  # pragma: no cover - network path
            raise StorageError(f"redis get_scratch failed: {exc}") from exc

    async def clear(self, session_id: str) -> None:
        try:
            await self._redis.delete(
                self._buffer_key(session_id), self._scratch_key(session_id)
            )
        except Exception as exc:  # pragma: no cover - network path
            raise StorageError(f"redis clear failed: {exc}") from exc

    async def close(self) -> None:
        await self._redis.aclose()

    async def ping(self) -> None:
        """Cheap liveness probe: the client's own PING command."""
        try:
            await self._redis.ping()
        except Exception as exc:  # pragma: no cover - network path
            raise StorageError(f"redis ping failed: {exc}") from exc
