"""Retrieval engine tests: weights, lexical hybrid, graph expansion, rerank,
embed cache, and context assembly."""

from __future__ import annotations

from datetime import timedelta

import pytest

from memcore.adapters.inmemory import (
    HashingEmbeddingProvider,
    InMemoryGraphStore,
    InMemoryMemoryStore,
    InMemoryVectorStore,
)
from memcore.config import RetrievalSettings
from memcore.domain.enums import EntityType, MemoryType
from memcore.domain.models import Entity, MemoryRecord, Relation, ScoredMemory, utcnow
from memcore.ports.vector_store import VectorRecord
from memcore.services.context import assemble_context, estimate_tokens
from memcore.services.recall import (
    RecallService,
    ScoreWeights,
    blend_relevance,
    lexical_overlap,
)

TENANT, AGENT = "t1", "a1"
COLLECTION = "mem_test"


class _Env:
    """A recall environment with direct control over records and vectors."""

    def __init__(self, settings: RetrievalSettings | None = None) -> None:
        self.store = InMemoryMemoryStore()
        self.vectors = InMemoryVectorStore()
        self.graph = InMemoryGraphStore()
        self.embedder = HashingEmbeddingProvider(dimension=64)
        self.recall = RecallService(
            self.store,
            self.vectors,
            self.embedder,
            collection=COLLECTION,
            graph=self.graph,
            settings=settings,
        )

    async def seed(
        self,
        content: str,
        *,
        importance: float = 0.5,
        age: timedelta = timedelta(0),
        type_: MemoryType = MemoryType.SEMANTIC,
        index: bool = True,
    ) -> MemoryRecord:
        record = MemoryRecord(
            tenant_id=TENANT,
            agent_id=AGENT,
            type=type_,
            content=content,
            importance=importance,
            created_at=utcnow() - age,
        )
        await self.store.add(record)
        if index:
            vector = await self.embedder.embed_one(content)
            await self.vectors.upsert(
                COLLECTION,
                [
                    VectorRecord(
                        id=record.id,
                        vector=vector,
                        payload={
                            "tenant_id": TENANT,
                            "agent_id": AGENT,
                            "type": type_.value,
                            "status": "active",
                        },
                    )
                ],
            )
        return record


# -- scoring primitives -------------------------------------------------------
def test_lexical_overlap() -> None:
    assert lexical_overlap("dark mode editor", "chinmay uses dark mode") == pytest.approx(2 / 3)
    assert lexical_overlap("dark", "nothing related") == 0.0
    assert lexical_overlap("", "anything") == 0.0
    assert lexical_overlap("a of", "a of") == 0.0  # short tokens ignored


def test_blend_relevance_clamps_and_mixes() -> None:
    assert blend_relevance(-0.5, 0.0, 0.3) == 0.0  # negative sim clamped
    assert blend_relevance(1.5, 1.0, 0.3) == 1.0  # over-1 clamped
    assert blend_relevance(0.8, 0.2, 0.0) == pytest.approx(0.8)  # alpha 0: vector only
    assert blend_relevance(0.8, 0.2, 1.0) == pytest.approx(0.2)  # alpha 1: lexical only
    assert blend_relevance(0.6, 0.4, 0.5) == pytest.approx(0.5)


# -- weights -------------------------------------------------------------------
async def test_zero_weight_neutralizes_factor() -> None:
    env = _Env()
    old_important = await env.seed(
        "python packaging guidelines", importance=1.0, age=timedelta(days=60)
    )
    new_unimportant = await env.seed(
        "python packaging notes", importance=0.2, age=timedelta(0)
    )

    # Recency-neutral, importance-heavy: the old-but-important memory wins.
    by_importance = await env.recall.recall(
        TENANT, AGENT, "python packaging",
        weights=ScoreWeights(relevance=1.0, recency=0.0, importance=2.0),
    )
    assert by_importance[0].memory.id == old_important.id

    # Importance-neutral, recency-heavy: the fresh memory wins.
    by_recency = await env.recall.recall(
        TENANT, AGENT, "python packaging",
        weights=ScoreWeights(relevance=1.0, recency=2.0, importance=0.0),
    )
    assert by_recency[0].memory.id == new_unimportant.id


# -- graph expansion -----------------------------------------------------------
async def test_graph_expansion_injects_provenance_linked_memory() -> None:
    env = _Env()
    # A memory whose wording shares nothing with the query.
    hidden = await env.seed(
        "The quarterly report deadline moved to Friday.", index=False
    )
    await env.seed("Alice enjoys hiking on weekends.")  # vector distractor

    alice = Entity(
        tenant_id=TENANT, agent_id=AGENT, name="Alice", canonical_name="alice",
        type=EntityType.PERSON,
    )
    project = Entity(
        tenant_id=TENANT, agent_id=AGENT, name="Apollo", canonical_name="apollo",
        type=EntityType.CONCEPT,
    )
    await env.graph.upsert_entity(alice)
    await env.graph.upsert_entity(project)
    await env.graph.upsert_relation(
        Relation(
            tenant_id=TENANT, agent_id=AGENT, subject_id=alice.id,
            predicate="works_on", object_id=project.id, provenance=[hidden.id],
        )
    )

    results = await env.recall.recall(TENANT, AGENT, "what is alice working on")
    ids = {r.memory.id for r in results}
    assert hidden.id in ids  # surfaced via graph, not wording
    injected = next(r for r in results if r.memory.id == hidden.id)
    assert injected.relevance >= 0.45  # graph relevance floor

    # With expansion disabled, the hidden memory stays hidden.
    no_graph = await env.recall.recall(
        TENANT, AGENT, "what is alice working on", graph_expand=False
    )
    assert hidden.id not in {r.memory.id for r in no_graph}


async def test_graph_expansion_never_crosses_agents() -> None:
    env = _Env()
    other_agent_memory = MemoryRecord(
        tenant_id=TENANT, agent_id="other-agent", type=MemoryType.SEMANTIC,
        content="secret of another agent",
    )
    await env.store.add(other_agent_memory)
    bob = Entity(
        tenant_id=TENANT, agent_id=AGENT, name="Bob", canonical_name="bob",
        type=EntityType.PERSON,
    )
    await env.graph.upsert_entity(bob)
    await env.graph.upsert_relation(
        Relation(
            tenant_id=TENANT, agent_id=AGENT, subject_id=bob.id,
            predicate="knows", object_id=bob.id,
            provenance=[other_agent_memory.id],
        )
    )
    results = await env.recall.recall(TENANT, AGENT, "tell me about bob")
    assert other_agent_memory.id not in {r.memory.id for r in results}


# -- rerank ---------------------------------------------------------------------
async def test_rerank_prefers_exact_lexical_match() -> None:
    env = _Env(RetrievalSettings(lexical_alpha=0.0))  # isolate rerank's effect
    exact = await env.seed("error code E42 means disk full", importance=0.4)
    await env.seed("general troubleshooting advice for errors", importance=1.0)

    reranked = await env.recall.recall(TENANT, AGENT, "what is E42", rerank=True)
    assert reranked[0].memory.id == exact.id


# -- embed cache -----------------------------------------------------------------
async def test_query_embedding_is_cached() -> None:
    env = _Env()
    await env.seed("cache test memory")
    calls = 0
    original = env.embedder.embed

    async def counting_embed(texts: list[str]) -> list[list[float]]:
        nonlocal calls
        calls += 1
        return await original(texts)

    env.embedder.embed = counting_embed  # type: ignore[method-assign]
    await env.recall.recall(TENANT, AGENT, "cache test")
    await env.recall.recall(TENANT, AGENT, "cache test")
    assert calls == 1  # second query served from cache


# -- importance reinforcement (Phase 6 calibration) ----------------------------
async def test_reinforced_memory_outranks_identical_cold_one() -> None:
    env = _Env()
    cold = await env.seed("chinmay uses the vim editor", importance=0.5)
    hot = await env.seed("chinmay uses the vim editor", importance=0.5)
    for _ in range(10):
        await env.store.reinforce(TENANT, [hot.id], utcnow())

    results = await env.recall.recall(TENANT, AGENT, "which editor does chinmay use")
    ranked = [s.memory.id for s in results]
    assert ranked.index(hot.id) < ranked.index(cold.id)

    by_id = {s.memory.id: s for s in results}
    assert by_id[hot.id].importance > by_id[cold.id].importance


async def test_unaccessed_importance_is_exactly_base() -> None:
    # Zero accesses => reinforcement term is zero, not a constant offset.
    env = _Env()
    record = await env.seed("rust ownership rules", importance=0.42)
    results = await env.recall.recall(TENANT, AGENT, "rust ownership")
    assert results[0].memory.id == record.id
    assert results[0].importance == pytest.approx(0.42)


async def test_importance_weight_zero_neutralizes_reinforcement() -> None:
    # The x**0 == 1 neutralization contract must hold for effective importance.
    env = _Env()
    cold = await env.seed("chinmay uses the vim editor", importance=0.5)
    hot = await env.seed("chinmay uses the vim editor", importance=0.5)
    for _ in range(10):
        await env.store.reinforce(TENANT, [hot.id], utcnow())

    results = await env.recall.recall(
        TENANT, AGENT, "which editor does chinmay use",
        weights=ScoreWeights(importance=0.0),
    )
    by_id = {s.memory.id: s for s in results}
    assert by_id[hot.id].final == pytest.approx(by_id[cold.id].final, rel=1e-6)


# -- context assembly -------------------------------------------------------------
def _scored(content: str, final: float = 0.5) -> ScoredMemory:
    return ScoredMemory(
        memory=MemoryRecord(
            tenant_id=TENANT, agent_id=AGENT, type=MemoryType.SEMANTIC,
            content=content,
        ),
        relevance=final, recency=1.0, importance=1.0, final=final,
    )


def test_assemble_context_dedupes_and_annotates() -> None:
    results = [
        _scored("Chinmay prefers dark mode.", 0.9),
        _scored("chinmay  prefers dark MODE."),  # duplicate after normalization
        _scored("MemCore uses Qdrant.", 0.7),
    ]
    context, tokens = assemble_context(results)
    assert context.startswith("Relevant memories")
    assert context.count("dark mode.") + context.count("dark MODE.") == 1
    assert "[semantic |" in context
    assert tokens == estimate_tokens(context)


def test_assemble_context_respects_budget() -> None:
    results = [_scored(f"unique fact number {i} " + "x" * 200, 0.5) for i in range(50)]
    context, tokens = assemble_context(results, token_budget=100)
    assert tokens <= 100 + 20  # header allowance
    assert 0 < context.count("unique fact") < 50


def test_assemble_context_empty() -> None:
    assert assemble_context([]) == ("", 0)
