"""Tests for the adapter factory's provider selection."""

from __future__ import annotations

import pytest

from memcore.adapters.factory import (
    build_embedding_provider,
    build_graph_store,
    build_memory_store,
    build_vector_store,
    build_working_memory,
)
from memcore.adapters.inmemory import (
    HashingEmbeddingProvider,
    InMemoryGraphStore,
    InMemoryMemoryStore,
    InMemoryVectorStore,
    InMemoryWorkingMemory,
)
from memcore.config import Settings
from memcore.exceptions import ConfigurationError


def _settings(**overrides: str) -> Settings:
    s = Settings(_env_file=None)
    s.vector.provider = overrides.get("vector", "inmemory")
    s.redis.provider = overrides.get("redis", "inmemory")
    s.graph.provider = overrides.get("graph", "inmemory")
    s.database.provider = overrides.get("database", "inmemory")
    s.embedding.provider = overrides.get("embedding", "inmemory")
    return s


def test_inmemory_selection() -> None:
    s = _settings()
    assert isinstance(build_vector_store(s), InMemoryVectorStore)
    assert isinstance(build_working_memory(s), InMemoryWorkingMemory)
    assert isinstance(build_graph_store(s), InMemoryGraphStore)
    assert isinstance(build_memory_store(s), InMemoryMemoryStore)
    assert isinstance(build_embedding_provider(s), HashingEmbeddingProvider)


async def test_sql_memory_store_selection() -> None:
    from memcore.adapters.sql import SqlMemoryStore

    s = _settings(database="sql")
    s.database.url = "sqlite+aiosqlite:///:memory:"
    store = build_memory_store(s)
    assert isinstance(store, SqlMemoryStore)
    await store.close()


def test_llm_and_workflow_selection() -> None:
    from memcore.adapters.factory import build_llm_provider, build_workflow_engine
    from memcore.adapters.inmemory import ImmediateWorkflowEngine, ScriptedLLMProvider
    from memcore.adapters.llm import FailoverLLMProvider

    s = _settings()
    s.llm.provider = "inmemory"
    s.llm.fallback_provider = None
    assert isinstance(build_llm_provider(s), ScriptedLLMProvider)

    # inmemory primary + ollama fallback -> failover wrapper.
    s.llm.fallback_provider = "ollama"
    provider = build_llm_provider(s)
    assert isinstance(provider, FailoverLLMProvider)

    # Same provider for primary and fallback -> no pointless wrapper.
    s.llm.provider = "ollama"
    s.llm.fallback_provider = "ollama"
    from memcore.adapters.llm import OllamaLLMProvider

    assert isinstance(build_llm_provider(s), OllamaLLMProvider)

    s.scheduler.provider = "inmemory"
    assert isinstance(build_workflow_engine(s), ImmediateWorkflowEngine)

    s.scheduler.provider = "temporal"
    with pytest.raises(ConfigurationError, match="future backend"):
        build_workflow_engine(s)
    s.scheduler.provider = "bogus"
    with pytest.raises(ConfigurationError):
        build_workflow_engine(s)
    s.llm.provider = "bogus"
    with pytest.raises(ConfigurationError):
        build_llm_provider(s)


def test_unknown_embedding_and_database_providers_raise() -> None:
    with pytest.raises(ConfigurationError):
        build_embedding_provider(_settings(embedding="bogus"))
    with pytest.raises(ConfigurationError):
        build_memory_store(_settings(database="bogus"))


async def test_real_provider_selection_constructs_adapters() -> None:
    # Construction must not require a running server (drivers connect lazily).
    from memcore.adapters.neo4j import Neo4jGraphStore
    from memcore.adapters.qdrant import QdrantVectorStore
    from memcore.adapters.redis import RedisWorkingMemory

    s = _settings(vector="qdrant", redis="redis", graph="neo4j")
    vec = build_vector_store(s)
    wm = build_working_memory(s)
    graph = build_graph_store(s)
    assert isinstance(vec, QdrantVectorStore)
    assert isinstance(wm, RedisWorkingMemory)
    assert isinstance(graph, Neo4jGraphStore)
    # Release the underlying clients so no resource warnings leak.
    await vec.close()
    await wm.close()
    await graph.close()


def test_unknown_provider_raises() -> None:
    with pytest.raises(ConfigurationError):
        build_vector_store(_settings(vector="bogus"))
    with pytest.raises(ConfigurationError):
        build_working_memory(_settings(redis="bogus"))
    with pytest.raises(ConfigurationError):
        build_graph_store(_settings(graph="bogus"))


def test_pgvector_not_implemented() -> None:
    with pytest.raises(ConfigurationError, match="pgvector"):
        build_vector_store(_settings(vector="pgvector"))
