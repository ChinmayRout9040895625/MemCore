"""bge-small :class:`EmbeddingProvider` via sentence-transformers.

The default embedding model (ADR-0010): ``BAAI/bge-small-en-v1.5``, 384-dim,
runs locally with no API cost. ``sentence-transformers`` (and torch) are heavy,
so they live in the ``embeddings`` extra and are imported lazily; encoding is
CPU/GPU-bound and runs in a worker thread to keep the event loop free.
"""

from __future__ import annotations

import asyncio
from typing import Any

from memcore.exceptions import ConfigurationError, ProviderError
from memcore.ports.embedding_provider import EmbeddingProvider


class BgeEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model: str = "BAAI/bge-small-en-v1.5") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - depends on extras
            raise ConfigurationError(
                "sentence-transformers is not installed; "
                "install the embeddings extra: pip install 'memcore[embeddings]'"
            ) from exc
        self._model_name = model
        self._st: Any = SentenceTransformer(model)
        self._dimension = int(self._st.get_sentence_embedding_dimension())

    @property
    def model(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            vectors = await asyncio.to_thread(
                self._st.encode, texts, normalize_embeddings=True
            )
        except Exception as exc:
            raise ProviderError(f"bge embedding failed: {exc}") from exc
        return [[float(x) for x in vector] for vector in vectors]
