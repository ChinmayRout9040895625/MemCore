"""EmbeddingProvider port — turns text into vectors.

Default adapter: ``BAAI/bge-small-en-v1.5`` (384-dim). Pluggable; OpenAI
``text-embedding-3-large`` is a supported production alternative. The stored
``model`` id travels with each vector so re-embedding after a model change is
safe (Risk R-9).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Port for a text embedding model."""

    @property
    @abstractmethod
    def model(self) -> str:
        """Identifier of the underlying embedding model."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Dimensionality of returned vectors."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts, preserving order."""

    async def embed_one(self, text: str) -> list[float]:
        """Convenience: embed a single text."""
        result = await self.embed([text])
        return result[0]
