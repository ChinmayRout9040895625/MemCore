"""In-memory :class:`ObjectStore` backed by a dict."""

from __future__ import annotations

from memcore.ports.object_store import ObjectStore


class InMemoryObjectStore(ObjectStore):
    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> None:
        self._data[key] = data

    async def get(self, key: str) -> bytes | None:
        return self._data.get(key)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def list_keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self._data if k.startswith(prefix))
