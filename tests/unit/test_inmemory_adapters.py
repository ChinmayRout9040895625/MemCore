"""Tests for the in-memory reference adapters."""

from __future__ import annotations

import pytest

from memcore.adapters.inmemory import (
    HashingEmbeddingProvider,
    InMemoryObjectStore,
    InMemoryVectorStore,
    InMemoryWorkingMemory,
)
from memcore.domain.models import Interaction
from memcore.ports.vector_store import VectorRecord


# --- Vector store -----------------------------------------------------------
async def test_vector_search_ranks_by_similarity(
    vector_store: InMemoryVectorStore,
) -> None:
    await vector_store.ensure_collection("mem", 3)
    await vector_store.upsert(
        "mem",
        [
            VectorRecord(id="a", vector=[1.0, 0.0, 0.0], payload={"tenant_id": "t1"}),
            VectorRecord(id="b", vector=[0.0, 1.0, 0.0], payload={"tenant_id": "t1"}),
        ],
    )
    hits = await vector_store.search("mem", [0.9, 0.1, 0.0], limit=2)
    assert [h.id for h in hits] == ["a", "b"]
    assert hits[0].score > hits[1].score


async def test_vector_filter_enforces_isolation(
    vector_store: InMemoryVectorStore,
) -> None:
    await vector_store.ensure_collection("mem", 2)
    await vector_store.upsert(
        "mem",
        [
            VectorRecord(id="a", vector=[1.0, 0.0], payload={"tenant_id": "t1"}),
            VectorRecord(id="b", vector=[1.0, 0.0], payload={"tenant_id": "t2"}),
        ],
    )
    hits = await vector_store.search(
        "mem", [1.0, 0.0], limit=10, filters={"tenant_id": "t1"}
    )
    assert [h.id for h in hits] == ["a"]


async def test_vector_dimension_mismatch_rejected(
    vector_store: InMemoryVectorStore,
) -> None:
    await vector_store.ensure_collection("mem", 3)
    with pytest.raises(ValueError):
        await vector_store.upsert(
            "mem", [VectorRecord(id="a", vector=[1.0, 0.0])]
        )


async def test_vector_delete_and_count(vector_store: InMemoryVectorStore) -> None:
    await vector_store.ensure_collection("mem", 2)
    await vector_store.upsert(
        "mem", [VectorRecord(id="a", vector=[1.0, 0.0], payload={"tenant_id": "t1"})]
    )
    assert await vector_store.count("mem") == 1
    await vector_store.delete("mem", ["a"])
    assert await vector_store.count("mem") == 0


# --- Working memory ---------------------------------------------------------
async def test_working_memory_buffer_is_bounded(
    working_memory: InMemoryWorkingMemory,
) -> None:
    for i in range(10):  # buffer_max_turns=5 in fixture
        await working_memory.append(
            "s1",
            Interaction(
                tenant_id="t1", agent_id="a1", session_id="s1", role="user",
                content=f"turn {i}",
            ),
        )
    recent = await working_memory.recent("s1", limit=100)
    assert len(recent) == 5
    assert recent[-1].content == "turn 9"
    assert recent[0].content == "turn 5"


async def test_working_memory_scratch_and_clear(
    working_memory: InMemoryWorkingMemory, sample_interaction: Interaction
) -> None:
    await working_memory.append("s1", sample_interaction)
    await working_memory.set_scratch("s1", "theme", "dark")
    assert await working_memory.get_scratch("s1", "theme") == "dark"
    await working_memory.clear("s1")
    assert await working_memory.recent("s1") == []
    assert await working_memory.get_scratch("s1", "theme") is None


# --- Object store -----------------------------------------------------------
async def test_object_store_roundtrip(object_store: InMemoryObjectStore) -> None:
    await object_store.put("raw/s1.json", b"{}")
    assert await object_store.get("raw/s1.json") == b"{}"
    assert await object_store.list_keys("raw/") == ["raw/s1.json"]
    await object_store.delete("raw/s1.json")
    assert await object_store.get("raw/s1.json") is None


# --- Embedding provider -----------------------------------------------------
async def test_embedding_is_deterministic_and_normalized(
    embedder: HashingEmbeddingProvider,
) -> None:
    v1 = await embedder.embed_one("dark mode preference")
    v2 = await embedder.embed_one("dark mode preference")
    assert v1 == v2
    assert len(v1) == embedder.dimension
    norm = sum(x * x for x in v1) ** 0.5
    assert norm == pytest.approx(1.0, abs=1e-9)


async def test_embedding_similar_texts_closer_than_dissimilar(
    embedder: HashingEmbeddingProvider,
) -> None:
    def cos(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=True))

    base = await embedder.embed_one("chinmay builds memcore memory system")
    similar = await embedder.embed_one("chinmay builds memcore memory engine")
    different = await embedder.embed_one("the weather today is sunny")
    assert cos(base, similar) > cos(base, different)
