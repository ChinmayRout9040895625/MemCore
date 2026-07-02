"""Smoke tests for package surface and port abstractness."""

from __future__ import annotations

import pytest

import memcore
from memcore.adapters.inmemory import (
    HashingEmbeddingProvider,
    InMemoryObjectStore,
    InMemoryVectorStore,
    InMemoryWorkingMemory,
)
from memcore.ports import (
    EmbeddingProvider,
    GraphStore,
    LLMProvider,
    ObjectStore,
    VectorStore,
    WorkflowEngine,
    WorkingMemory,
)


def test_version_exposed() -> None:
    assert memcore.__version__ == "0.1.0"


@pytest.mark.parametrize(
    "port",
    [
        VectorStore,
        GraphStore,
        WorkingMemory,
        EmbeddingProvider,
        LLMProvider,
        WorkflowEngine,
        ObjectStore,
    ],
)
def test_ports_are_abstract(port: type) -> None:
    with pytest.raises(TypeError):
        port()


def test_inmemory_adapters_satisfy_ports() -> None:
    assert issubclass(InMemoryVectorStore, VectorStore)
    assert issubclass(InMemoryWorkingMemory, WorkingMemory)
    assert issubclass(InMemoryObjectStore, ObjectStore)
    assert issubclass(HashingEmbeddingProvider, EmbeddingProvider)
