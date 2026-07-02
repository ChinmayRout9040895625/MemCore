"""Tests for configuration loading and the approved default stack."""

from __future__ import annotations

import pytest

from memcore.config import Settings


def test_defaults_reflect_approved_stack() -> None:
    # ``_env_file=None`` isolates the test from any local .env file.
    settings = Settings(_env_file=None)
    assert settings.vector.provider == "qdrant"
    assert settings.scheduler.provider == "celery"
    assert settings.embedding.model == "BAAI/bge-small-en-v1.5"
    assert settings.embedding.dimension == 384
    assert settings.llm.model == "claude-sonnet-5"
    assert settings.llm.fallback_provider == "ollama"


def test_nested_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMCORE_VECTOR__URL", "http://qdrant:6333")
    monkeypatch.setenv("MEMCORE_EMBEDDING__DIMENSION", "1024")
    monkeypatch.setenv("MEMCORE_LLM__MODEL", "claude-opus-4-8")
    settings = Settings(_env_file=None)
    assert settings.vector.url == "http://qdrant:6333"
    assert settings.embedding.dimension == 1024
    assert settings.llm.model == "claude-opus-4-8"


def test_invalid_ttl_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMCORE_REDIS__SESSION_TTL_SECONDS", "0")
    with pytest.raises(ValueError):
        Settings(_env_file=None)
