"""Adapter factory: build storage adapters from :class:`Settings`.

This is where "pluggable storage" (FR-10) becomes concrete wiring. Backend
drivers are imported lazily inside each branch so that a deployment only needs
the extras for the backends it actually selects (e.g. an in-memory/local run
requires none of qdrant-client/neo4j/redis).
"""

from __future__ import annotations

from memcore.config import Settings
from memcore.exceptions import ConfigurationError
from memcore.ports.embedding_provider import EmbeddingProvider
from memcore.ports.graph_store import GraphStore
from memcore.ports.llm_provider import LLMProvider
from memcore.ports.memory_store import MemoryStore
from memcore.ports.vector_store import VectorStore
from memcore.ports.workflow_engine import WorkflowEngine
from memcore.ports.working_memory import WorkingMemory


def build_vector_store(settings: Settings) -> VectorStore:
    provider = settings.vector.provider.lower()
    if provider == "inmemory":
        from memcore.adapters.inmemory import InMemoryVectorStore

        return InMemoryVectorStore()
    if provider == "qdrant":
        from memcore.adapters.qdrant import QdrantVectorStore

        return QdrantVectorStore(settings.vector.url, settings.vector.api_key)
    if provider == "pgvector":
        raise ConfigurationError("pgvector vector adapter is not implemented yet")
    raise ConfigurationError(f"unknown vector provider: {settings.vector.provider!r}")


def build_working_memory(settings: Settings) -> WorkingMemory:
    provider = settings.redis.provider.lower()
    if provider == "inmemory":
        from memcore.adapters.inmemory import InMemoryWorkingMemory

        return InMemoryWorkingMemory(buffer_max_turns=settings.redis.buffer_max_turns)
    if provider == "redis":
        from memcore.adapters.redis import RedisWorkingMemory

        return RedisWorkingMemory(
            settings.redis.url,
            ttl_seconds=settings.redis.session_ttl_seconds,
            buffer_max_turns=settings.redis.buffer_max_turns,
        )
    raise ConfigurationError(f"unknown working-memory provider: {settings.redis.provider!r}")


def build_graph_store(settings: Settings) -> GraphStore:
    provider = settings.graph.provider.lower()
    if provider == "inmemory":
        from memcore.adapters.inmemory import InMemoryGraphStore

        return InMemoryGraphStore()
    if provider == "neo4j":
        from memcore.adapters.neo4j import Neo4jGraphStore

        return Neo4jGraphStore(
            settings.graph.url, settings.graph.user, settings.graph.password
        )
    raise ConfigurationError(f"unknown graph provider: {settings.graph.provider!r}")


def build_memory_store(settings: Settings) -> MemoryStore:
    provider = settings.database.provider.lower()
    if provider == "inmemory":
        from memcore.adapters.inmemory import InMemoryMemoryStore

        return InMemoryMemoryStore()
    if provider == "sql":
        from memcore.adapters.sql import SqlMemoryStore

        return SqlMemoryStore(settings.database.url)
    raise ConfigurationError(f"unknown database provider: {settings.database.provider!r}")


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    provider = settings.embedding.provider.lower()
    if provider == "inmemory":
        from memcore.adapters.inmemory import HashingEmbeddingProvider

        return HashingEmbeddingProvider(dimension=settings.embedding.dimension)
    if provider == "bge":
        from memcore.adapters.embeddings import BgeEmbeddingProvider

        return BgeEmbeddingProvider(settings.embedding.model)
    if provider == "openai":
        from memcore.adapters.embeddings import OpenAIEmbeddingProvider

        model = settings.embedding.model
        if not model.startswith("text-embedding"):
            model = "text-embedding-3-large"
        return OpenAIEmbeddingProvider(model, api_key=settings.embedding.api_key)
    raise ConfigurationError(
        f"unknown embedding provider: {settings.embedding.provider!r}"
    )


def _build_single_llm(provider: str, model: str, settings: Settings) -> LLMProvider:
    if provider == "inmemory":
        from memcore.adapters.inmemory import ScriptedLLMProvider

        return ScriptedLLMProvider(responses=["{}"])
    if provider == "anthropic":
        from memcore.adapters.llm import AnthropicLLMProvider

        return AnthropicLLMProvider(model, api_key=settings.llm.api_key)
    if provider == "ollama":
        from memcore.adapters.llm import OllamaLLMProvider

        return OllamaLLMProvider(model, base_url=settings.llm.ollama_url)
    raise ConfigurationError(f"unknown llm provider: {provider!r}")


def build_llm_provider(settings: Settings) -> LLMProvider:
    """Primary LLM, wrapped with fallback failover when configured (ADR-0009)."""
    primary = _build_single_llm(
        settings.llm.provider.lower(), settings.llm.model, settings
    )
    fallback_provider = (settings.llm.fallback_provider or "").lower()
    if not fallback_provider or fallback_provider == settings.llm.provider.lower():
        return primary

    from memcore.adapters.llm import FailoverLLMProvider

    fallback = _build_single_llm(
        fallback_provider, settings.llm.fallback_model, settings
    )
    return FailoverLLMProvider(primary, fallback)


def build_workflow_engine(settings: Settings) -> WorkflowEngine:
    provider = settings.scheduler.provider.lower()
    if provider == "inmemory":
        from memcore.adapters.inmemory import ImmediateWorkflowEngine

        return ImmediateWorkflowEngine()
    if provider == "celery":
        from memcore.adapters.celery import CeleryWorkflowEngine

        return CeleryWorkflowEngine(settings.scheduler.broker_url)
    if provider == "temporal":
        raise ConfigurationError(
            "temporal is an approved future backend; use 'celery' or 'inmemory'"
        )
    raise ConfigurationError(f"unknown scheduler provider: {settings.scheduler.provider!r}")
