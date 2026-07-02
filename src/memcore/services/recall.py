"""RecallService — the hybrid retrieval engine (Phase 4).

Pipeline (hot path — no LLM, ADR-0001):

1. Embed the query (LRU-cached).
2. Candidate generation: filtered ANN (tenant/agent/status/type) plus, when a
   graph store is wired, bounded graph expansion — query tokens are matched to
   entities, their neighbourhood relations are walked (hops/limit capped), and
   the relations' provenance memory ids are injected as candidates. Graph
   candidates carry a relevance floor: they are related by *structure*, not
   necessarily by wording.
3. Scoring: ``relevance = (1-alpha)*vector + alpha*lexical`` (token overlap),
   then ``final = relevance^wr * recency^wt * importance^wi``. Exponent weights
   mean ``w=0`` neutralizes a factor and ``w>1`` sharpens it; recency uses
   ``exp(-age/tau)`` with per-type time constants.
4. Optional rerank: lexical re-sort of the top window — a deliberate placeholder
   slot for a cross-encoder/LLM reranker (budget-gated, off the default path).
5. Reinforcement: retrieved memories get their access stats bumped, feeding
   importance/decay (retrieval strengthens memory).

The metadata store stays authoritative: hits whose record is missing or not
active are dropped (index lag never resurrects deleted memories).
"""

from __future__ import annotations

import math
import re
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta

from memcore.config import RetrievalSettings
from memcore.domain.enums import MemoryStatus, MemoryType
from memcore.domain.models import MemoryRecord, ScoredMemory, utcnow
from memcore.ports.embedding_provider import EmbeddingProvider
from memcore.ports.graph_store import GraphStore
from memcore.ports.memory_store import MemoryStore
from memcore.ports.vector_store import VectorStore

_TOKEN = re.compile(r"[a-z0-9]+")
_EMBED_CACHE_MAX = 1024


@dataclass(frozen=True)
class ScoreWeights:
    """Exponent weights for the hybrid score."""

    relevance: float = 1.0
    recency: float = 1.0
    importance: float = 1.0


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if len(t) > 2}


def lexical_overlap(query: str, content: str) -> float:
    """Fraction of query tokens present in the content (0..1)."""
    q = _tokens(query)
    if not q:
        return 0.0
    return len(q & _tokens(content)) / len(q)


def blend_relevance(vector_score: float, lexical: float, alpha: float) -> float:
    """Hybrid relevance: vector similarity blended with lexical overlap."""
    vector_clamped = max(0.0, min(1.0, vector_score))
    return (1.0 - alpha) * vector_clamped + alpha * lexical


class RecallService:
    def __init__(
        self,
        store: MemoryStore,
        vectors: VectorStore,
        embedder: EmbeddingProvider,
        *,
        collection: str,
        graph: GraphStore | None = None,
        settings: RetrievalSettings | None = None,
    ) -> None:
        self._store = store
        self._vectors = vectors
        self._embedder = embedder
        self._collection = collection
        self._graph = graph
        self._cfg = settings or RetrievalSettings()
        self._embed_cache: OrderedDict[str, list[float]] = OrderedDict()

    async def recall(
        self,
        tenant_id: str,
        agent_id: str,
        query: str,
        *,
        k: int = 8,
        types: list[MemoryType] | None = None,
        weights: ScoreWeights | None = None,
        graph_expand: bool | None = None,
        rerank: bool = False,
    ) -> list[ScoredMemory]:
        cfg = self._cfg
        w = weights or ScoreWeights()
        expand = cfg.graph_expand if graph_expand is None else graph_expand

        query_vector = await self._embed_cached(query)
        filters: dict[str, object] = {
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "status": MemoryStatus.ACTIVE.value,
        }
        if types:
            filters["type"] = [t.value for t in types]

        candidate_limit = max(k * cfg.candidate_multiplier, cfg.min_candidates)
        hits = await self._vectors.search(
            self._collection, query_vector, limit=candidate_limit, filters=filters
        )
        vector_scores = {hit.id: hit.score for hit in hits}

        graph_ids: set[str] = set()
        if expand and self._graph is not None:
            graph_ids = await self._graph_candidates(tenant_id, agent_id, query)

        candidate_ids = list(vector_scores.keys()) + [
            gid for gid in graph_ids if gid not in vector_scores
        ]
        if not candidate_ids:
            return []

        now = utcnow()
        allowed_types = set(types) if types else None
        scored: list[ScoredMemory] = []
        for memory_id in candidate_ids:
            record = await self._store.get(tenant_id, memory_id)
            if record is None or record.status is not MemoryStatus.ACTIVE:
                continue
            if record.agent_id != agent_id:
                continue  # graph edges may cross agents; recall must not
            if allowed_types is not None and record.type not in allowed_types:
                continue

            lexical = lexical_overlap(query, record.content)
            relevance = blend_relevance(
                vector_scores.get(memory_id, 0.0), lexical, cfg.lexical_alpha
            )
            if memory_id in graph_ids:
                relevance = max(relevance, cfg.graph_relevance_floor)

            recency = self._recency(record, now)
            importance = record.importance
            final = (
                relevance**w.relevance
                * recency**w.recency
                * importance**w.importance
            )
            scored.append(
                ScoredMemory(
                    memory=record,
                    relevance=relevance,
                    recency=recency,
                    importance=importance,
                    final=final,
                )
            )

        scored.sort(key=lambda s: s.final, reverse=True)
        if rerank:
            scored = self._lexical_rerank(query, scored)
        top = scored[:k]

        if top:
            await self._store.reinforce(
                tenant_id, [s.memory.id for s in top], accessed_at=now
            )
        return top

    # -- internals -------------------------------------------------------------
    def _recency(self, record: MemoryRecord, now: datetime) -> float:
        taus = {
            MemoryType.WORKING: timedelta(hours=self._cfg.tau_working_hours),
            MemoryType.EPISODIC: timedelta(days=self._cfg.tau_episodic_days),
            MemoryType.SEMANTIC: timedelta(days=self._cfg.tau_semantic_days),
        }
        age = max(0.0, (now - record.created_at).total_seconds())
        return math.exp(-age / taus[record.type].total_seconds())

    async def _embed_cached(self, query: str) -> list[float]:
        key = f"{self._embedder.model}::{query}"
        cached = self._embed_cache.get(key)
        if cached is not None:
            self._embed_cache.move_to_end(key)
            return cached
        vector = await self._embedder.embed_one(query)
        self._embed_cache[key] = vector
        if len(self._embed_cache) > _EMBED_CACHE_MAX:
            self._embed_cache.popitem(last=False)
        return vector

    async def _graph_candidates(
        self, tenant_id: str, agent_id: str, query: str
    ) -> set[str]:
        """Query tokens -> entities -> bounded neighbourhood -> provenance ids."""
        assert self._graph is not None
        cfg = self._cfg
        memory_ids: set[str] = set()
        entity_ids: list[str] = []
        seen_entities: set[str] = set()

        for token in sorted(_tokens(query))[:6]:
            for entity in await self._graph.find_entities(
                tenant_id, agent_id, token, limit=3
            ):
                if entity.id not in seen_entities:
                    seen_entities.add(entity.id)
                    entity_ids.append(entity.id)

        for entity_id in entity_ids[: cfg.graph_max_entities]:
            relations = await self._graph.neighbors(
                tenant_id,
                entity_id,
                max_hops=cfg.graph_max_hops,
                limit=cfg.graph_limit,
            )
            for relation in relations:
                memory_ids.update(relation.provenance)
        return memory_ids

    def _lexical_rerank(
        self, query: str, scored: list[ScoredMemory]
    ) -> list[ScoredMemory]:
        """Re-sort the top window by (lexical overlap, hybrid score).

        Placeholder for a cross-encoder/LLM reranker: same slot, same contract.
        """
        window = scored[: self._cfg.rerank_window]
        rest = scored[self._cfg.rerank_window :]
        window.sort(
            key=lambda s: (lexical_overlap(query, s.memory.content), s.final),
            reverse=True,
        )
        return window + rest
