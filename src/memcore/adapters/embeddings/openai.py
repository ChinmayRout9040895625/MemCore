"""OpenAI :class:`EmbeddingProvider` (production alternative, ADR-0010).

Supports ``text-embedding-3-large`` (default) and ``-small``. The client is
injectable so unit tests run without the SDK or network; batches preserve input
order via the API's ``index`` field.
"""

from __future__ import annotations

from typing import Any

from memcore.exceptions import ConfigurationError, ProviderError
from memcore.ports.embedding_provider import EmbeddingProvider

_KNOWN_DIMENSIONS = {
    "text-embedding-3-large": 3072,
    "text-embedding-3-small": 1536,
}


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        model: str = "text-embedding-3-large",
        *,
        api_key: str | None = None,
        dimension: int | None = None,
        client: Any | None = None,
    ) -> None:
        self._model_name = model
        resolved = dimension or _KNOWN_DIMENSIONS.get(model)
        if resolved is None:
            raise ConfigurationError(
                f"unknown OpenAI embedding model {model!r}; pass dimension explicitly"
            )
        self._dimension = resolved
        if client is None:  # pragma: no cover - requires the openai extra
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise ConfigurationError(
                    "openai is not installed; install the llm extra: "
                    "pip install 'memcore[llm]'"
                ) from exc
            client = AsyncOpenAI(api_key=api_key)
        self._client = client

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
            response = await self._client.embeddings.create(
                model=self._model_name, input=texts
            )
        except Exception as exc:
            raise ProviderError(f"openai embedding failed: {exc}") from exc
        ordered = sorted(response.data, key=lambda item: item.index)
        return [[float(x) for x in item.embedding] for item in ordered]
