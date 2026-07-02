"""Embedding adapter tests using faked backends (no torch, no network)."""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass

import pytest

from memcore.exceptions import ConfigurationError, ProviderError


# -- bge (sentence-transformers faked at the module level) --------------------
class _FakeSentenceTransformer:
    def __init__(self, model: str) -> None:
        self.model = model

    def get_sentence_embedding_dimension(self) -> int:
        return 4

    def encode(self, texts: list[str], normalize_embeddings: bool = False) -> list[list[float]]:
        assert normalize_embeddings is True
        return [[float(len(t)), 0.0, 0.0, 0.0] for t in texts]


@pytest.fixture
def fake_sentence_transformers(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("sentence_transformers")
    module.SentenceTransformer = _FakeSentenceTransformer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)


async def test_bge_provider_embeds_via_sentence_transformers(
    fake_sentence_transformers: None,
) -> None:
    from memcore.adapters.embeddings import BgeEmbeddingProvider

    provider = BgeEmbeddingProvider("BAAI/bge-small-en-v1.5")
    assert provider.model == "BAAI/bge-small-en-v1.5"
    assert provider.dimension == 4
    vectors = await provider.embed(["ab", "abcd"])
    assert vectors == [[2.0, 0.0, 0.0, 0.0], [4.0, 0.0, 0.0, 0.0]]
    assert await provider.embed([]) == []


async def test_bge_factory_wiring(
    fake_sentence_transformers: None,
) -> None:
    from memcore.adapters.embeddings import BgeEmbeddingProvider
    from memcore.adapters.factory import build_embedding_provider
    from memcore.config import Settings

    s = Settings(_env_file=None)
    s.embedding.provider = "bge"
    provider = build_embedding_provider(s)
    assert isinstance(provider, BgeEmbeddingProvider)


# -- openai (client injected) --------------------------------------------------
@dataclass
class _Item:
    index: int
    embedding: list[float]


class _FakeEmbeddingsAPI:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    async def create(self, *, model: str, input: list[str]) -> object:
        if self.fail:
            raise RuntimeError("rate limited")
        self.calls.append({"model": model, "input": input})
        # Return items deliberately out of order to verify re-sorting.
        data = [
            _Item(index=i, embedding=[float(i), 1.0])
            for i in reversed(range(len(input)))
        ]
        return types.SimpleNamespace(data=data)


class _FakeOpenAIClient:
    def __init__(self, fail: bool = False) -> None:
        self.embeddings = _FakeEmbeddingsAPI(fail=fail)


async def test_openai_provider_orders_by_index() -> None:
    from memcore.adapters.embeddings import OpenAIEmbeddingProvider

    provider = OpenAIEmbeddingProvider(
        "text-embedding-3-large", client=_FakeOpenAIClient()
    )
    assert provider.dimension == 3072
    vectors = await provider.embed(["a", "b", "c"])
    assert vectors == [[0.0, 1.0], [1.0, 1.0], [2.0, 1.0]]  # input order restored
    assert await provider.embed([]) == []


async def test_openai_provider_wraps_errors() -> None:
    from memcore.adapters.embeddings import OpenAIEmbeddingProvider

    provider = OpenAIEmbeddingProvider(
        "text-embedding-3-small", client=_FakeOpenAIClient(fail=True)
    )
    with pytest.raises(ProviderError, match="openai embedding failed"):
        await provider.embed(["x"])


def test_openai_unknown_model_requires_dimension() -> None:
    from memcore.adapters.embeddings import OpenAIEmbeddingProvider

    with pytest.raises(ConfigurationError, match="pass dimension"):
        OpenAIEmbeddingProvider("mystery-model", client=_FakeOpenAIClient())
    provider = OpenAIEmbeddingProvider(
        "mystery-model", dimension=8, client=_FakeOpenAIClient()
    )
    assert provider.dimension == 8
