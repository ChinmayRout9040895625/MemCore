"""Shared pytest fixtures for MemCore."""

from __future__ import annotations

import pytest

from memcore.adapters.inmemory import (
    HashingEmbeddingProvider,
    InMemoryObjectStore,
    InMemoryVectorStore,
    InMemoryWorkingMemory,
)
from memcore.domain.enums import MemoryType
from memcore.domain.models import Interaction, MemoryRecord


@pytest.fixture
def embedder() -> HashingEmbeddingProvider:
    return HashingEmbeddingProvider(dimension=64)


@pytest.fixture
def vector_store() -> InMemoryVectorStore:
    return InMemoryVectorStore()


@pytest.fixture
def working_memory() -> InMemoryWorkingMemory:
    return InMemoryWorkingMemory(buffer_max_turns=5)


@pytest.fixture
def object_store() -> InMemoryObjectStore:
    return InMemoryObjectStore()


@pytest.fixture
def sample_memory() -> MemoryRecord:
    return MemoryRecord(
        tenant_id="t1",
        agent_id="a1",
        type=MemoryType.SEMANTIC,
        content="Chinmay is building MemCore.",
    )


@pytest.fixture
def sample_interaction() -> Interaction:
    return Interaction(
        tenant_id="t1",
        agent_id="a1",
        session_id="s1",
        role="user",
        content="Remember that I prefer dark mode.",
    )
