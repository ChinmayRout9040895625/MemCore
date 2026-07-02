"""Application configuration via ``pydantic-settings``.

Configuration is declared here for the *whole* default stack even though most
adapters land in later phases — this pins the approved decisions (Qdrant +
Celery + Redis + Neo4j; Claude Sonnet consolidation with Ollama fallback;
bge-small embeddings) in one auditable place.

Env vars are prefixed ``MEMCORE_`` and nested with ``__``, e.g.::

    MEMCORE_VECTOR__URL=http://localhost:6333
    MEMCORE_LLM__MODEL=claude-sonnet-5
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RedisSettings(BaseModel):
    provider: str = "redis"  # redis (default) | inmemory
    url: str = "redis://localhost:6379/0"
    session_ttl_seconds: int = Field(default=3600, ge=1)
    buffer_max_turns: int = Field(default=200, ge=1)


class VectorSettings(BaseModel):
    provider: str = "qdrant"  # qdrant (default) | pgvector | inmemory
    url: str = "http://localhost:6333"
    api_key: str | None = None
    collection_prefix: str = "memcore"


class GraphSettings(BaseModel):
    provider: str = "neo4j"  # neo4j (default) | inmemory
    url: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = "neo4j"


class EmbeddingSettings(BaseModel):
    provider: str = "bge"  # bge (default) | openai | inmemory
    model: str = "BAAI/bge-small-en-v1.5"
    # Used by the inmemory provider; bge/openai adapters self-declare their
    # dimension from the model (ADR-0010).
    dimension: int = Field(default=384, ge=1)
    api_key: str | None = None  # openai provider only


class RetrievalSettings(BaseModel):
    """Knobs for the hybrid retrieval engine (Phase 4)."""

    candidate_multiplier: int = Field(default=4, ge=1)
    min_candidates: int = Field(default=32, ge=1)
    # relevance = (1-alpha)*vector + alpha*lexical
    lexical_alpha: float = Field(default=0.3, ge=0.0, le=1.0)
    graph_expand: bool = True
    graph_max_hops: int = Field(default=2, ge=1, le=3)
    graph_limit: int = Field(default=25, ge=1)
    graph_max_entities: int = Field(default=5, ge=1)
    # Graph-injected candidates get at least this relevance: they are related
    # by structure, not necessarily by wording.
    graph_relevance_floor: float = Field(default=0.45, ge=0.0, le=1.0)
    rerank_window: int = Field(default=20, ge=1)
    context_token_budget: int = Field(default=2000, ge=50)
    # Recency time constants per memory type.
    tau_working_hours: float = Field(default=6.0, gt=0)
    tau_episodic_days: float = Field(default=7.0, gt=0)
    tau_semantic_days: float = Field(default=30.0, gt=0)


class LLMSettings(BaseModel):
    provider: str = "anthropic"  # anthropic (default) | ollama | inmemory
    model: str = "claude-sonnet-5"
    fallback_provider: str | None = "ollama"  # None disables failover
    fallback_model: str = "llama3.1"
    api_key: str | None = None
    ollama_url: str = "http://localhost:11434"


class ConsolidationSettings(BaseModel):
    """Knobs for the consolidation agent (Phase 5)."""

    max_turns: int = Field(default=200, ge=1)
    # Same subject+predicate and vector-similar object/content => NOOP.
    dup_similarity: float = Field(default=0.9, ge=0.0, le=1.0)
    # Conflicting fact needs at least this confidence to supersede; below it
    # the fact is stored flagged `needs_review` instead (false-overwrite guard).
    conflict_confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    candidate_matches: int = Field(default=5, ge=1)
    extraction_max_tokens: int = Field(default=2048, ge=256)


class SchedulerSettings(BaseModel):
    provider: str = "celery"  # celery (default) | temporal (future)
    broker_url: str = "redis://localhost:6379/1"


class DatabaseSettings(BaseModel):
    """Metadata source of truth (ADR-0005). Any SQLAlchemy-async URL works;
    Postgres in production, SQLite for tests/self-host."""

    provider: str = "sql"  # sql (default) | inmemory
    url: str = "postgresql+asyncpg://memcore:memcore@localhost:5432/memcore"


class ApiSettings(BaseModel):
    """API-key auth (v1): maps key -> tenant_id.

    No default credentials ship. In ``env=local`` only, an empty map causes the
    app to inject a ``dev-key`` -> ``local`` binding at startup (with a warning)
    so quickstarts work. Set via JSON env:  MEMCORE_API__KEYS={"k1": "tenant1"}
    """

    keys: dict[str, str] = Field(default_factory=dict)


class Settings(BaseSettings):
    """Root settings object. Instantiate once and inject downstream."""

    model_config = SettingsConfigDict(
        env_prefix="MEMCORE_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "local"  # local | staging | production
    log_level: str = "INFO"
    log_json: bool = False

    redis: RedisSettings = Field(default_factory=RedisSettings)
    vector: VectorSettings = Field(default_factory=VectorSettings)
    graph: GraphSettings = Field(default_factory=GraphSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    consolidation: ConsolidationSettings = Field(default_factory=ConsolidationSettings)


def load_settings() -> Settings:
    """Load settings from environment/.env. Kept as a function so tests can
    monkeypatch the environment before construction."""
    return Settings()
