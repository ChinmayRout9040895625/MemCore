"""Deterministic hashing :class:`EmbeddingProvider` for tests.

Produces stable, normalized pseudo-embeddings from token hashes — no model
download, no network. Similar texts share tokens and therefore direction, which
is enough to make retrieval tests meaningful while remaining fully offline. The
real bge-small / OpenAI adapters land in the retrieval phase.
"""

from __future__ import annotations

import hashlib
import re

from memcore.ports.embedding_provider import EmbeddingProvider

_TOKEN = re.compile(r"[a-z0-9]+")


class HashingEmbeddingProvider(EmbeddingProvider):
    def __init__(self, dimension: int = 64) -> None:
        self._dimension = dimension

    @property
    def model(self) -> str:
        return f"hashing-{self._dimension}"

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self._dimension
        for token in _TOKEN.findall(text.lower()):
            digest = hashlib.sha256(token.encode()).digest()
            idx = int.from_bytes(digest[:4], "big") % self._dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[idx] += sign
        norm = sum(v * v for v in vec) ** 0.5
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]
