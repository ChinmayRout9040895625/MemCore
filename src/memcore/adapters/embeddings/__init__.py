"""Embedding provider adapters (ADR-0010).

Default: bge-small via sentence-transformers (local, free, offline-capable).
Production alternative: OpenAI ``text-embedding-3-large``.
"""

from memcore.adapters.embeddings.bge import BgeEmbeddingProvider
from memcore.adapters.embeddings.openai import OpenAIEmbeddingProvider

__all__ = ["BgeEmbeddingProvider", "OpenAIEmbeddingProvider"]
