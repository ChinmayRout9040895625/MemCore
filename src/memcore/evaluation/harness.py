"""Evaluation harness — runs scoring configurations over a fresh in-memory
stack and aggregates retrieval-quality metrics.

Each ``run_config`` rebuilds and re-seeds the stack from scratch: recall's
write-back reinforcement (retrieval strengthens memory) is part of the system
under test, so results within one configuration reflect it, but it must never
leak *between* configurations. Determinism note: within a configuration,
cases run in dataset order, and earlier recalls reinforce their hits — the
order is fixed, so runs are exactly reproducible.
"""

from __future__ import annotations

from datetime import timedelta

from pydantic import BaseModel, ConfigDict

from memcore.adapters.inmemory import (
    HashingEmbeddingProvider,
    InMemoryMemoryStore,
    InMemoryVectorStore,
)
from memcore.config import ImportanceSettings, RetrievalSettings
from memcore.domain.enums import MemoryType
from memcore.domain.models import MemoryRecord, utcnow
from memcore.evaluation.datasets import EvalDataset
from memcore.evaluation.metrics import mrr, ndcg_at_k, recall_at_k
from memcore.ports.vector_store import VectorRecord
from memcore.services import MemoryService, RecallService, ScoreWeights

_DIMENSION = 64


class EvalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    relevance: float = 1.0
    recency: float = 1.0
    importance: float = 1.0
    # None -> RetrievalSettings default (0.3). 0.0 -> pure vector relevance.
    lexical_alpha: float | None = None


STANDARD_CONFIGS: list[EvalConfig] = [
    EvalConfig(name="naive-vector", recency=0.0, importance=0.0, lexical_alpha=0.0),
    EvalConfig(name="hybrid"),
    EvalConfig(name="no-importance", importance=0.0),
    EvalConfig(name="no-recency", recency=0.0),
]


class ConfigResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: str
    cases: int
    recall_at_5: float
    mrr: float
    ndcg_at_5: float


class EvalHarness:
    """Owns one in-memory stack at a time; rebuilt on every ``seed``."""

    tenant = "eval"
    agent = "eval-agent"

    def __init__(self) -> None:
        self._reset()

    def _reset(self) -> None:
        """Rebuild every stack attribute (shared by ``__init__`` and ``seed``)."""
        self.store = InMemoryMemoryStore()
        self.vectors = InMemoryVectorStore()
        self.embedder = HashingEmbeddingProvider(dimension=_DIMENSION)
        self.collection = f"eval_{_DIMENSION}"
        self.memories = MemoryService(
            self.store, self.vectors, self.embedder, collection=self.collection
        )
        self.ids: dict[str, str] = {}

    async def seed(self, dataset: EvalDataset) -> None:
        """Rebuild the stack and load ``dataset`` (backdating + reinforcement)."""
        self._reset()  # fresh stores: no state survives re-seeding
        now = utcnow()
        for item in dataset.records:
            created = now - timedelta(days=item.age_days)
            record = MemoryRecord(
                tenant_id=self.tenant,
                agent_id=self.agent,
                type=MemoryType.SEMANTIC,
                content=item.content,
                importance=item.importance,
                tags=list(item.tags),
                created_at=created,
                valid_from=created,
            )
            await self.store.add(record)
            vector = await self.embedder.embed_one(item.content)
            await self.vectors.upsert(
                self.collection,
                [VectorRecord(id=record.id, vector=vector, payload={
                    "tenant_id": self.tenant, "agent_id": self.agent,
                    "type": MemoryType.SEMANTIC.value, "status": "active",
                })],
            )
            for _ in range(item.reinforce_count):
                await self.store.reinforce(self.tenant, [record.id], now)
            self.ids[item.key] = record.id

    def recall_service(self, config: EvalConfig) -> RecallService:
        retrieval = (
            RetrievalSettings() if config.lexical_alpha is None
            else RetrievalSettings(lexical_alpha=config.lexical_alpha)
        )
        return RecallService(
            self.store, self.vectors, self.embedder,
            collection=self.collection,
            graph=None,
            settings=retrieval,
            importance_settings=ImportanceSettings(),
        )

    async def run_config(
        self, dataset: EvalDataset, config: EvalConfig, *, k: int = 5
    ) -> ConfigResult:
        await self.seed(dataset)
        recall = self.recall_service(config)
        weights = ScoreWeights(
            relevance=config.relevance,
            recency=config.recency,
            importance=config.importance,
        )
        key_by_id = {record_id: key for key, record_id in self.ids.items()}
        totals = {"recall": 0.0, "mrr": 0.0, "ndcg": 0.0}
        for case in dataset.cases:
            results = await recall.recall(
                self.tenant, self.agent, case.query, k=k, weights=weights
            )
            ranked = [key_by_id[s.memory.id] for s in results
                      if s.memory.id in key_by_id]
            relevant = set(case.relevant_keys)
            totals["recall"] += recall_at_k(relevant, ranked, k)
            totals["mrr"] += mrr(relevant, ranked)
            totals["ndcg"] += ndcg_at_k(relevant, ranked, k)
        n = len(dataset.cases)
        return ConfigResult(
            config=config.name,
            cases=n,
            recall_at_5=totals["recall"] / n,
            mrr=totals["mrr"] / n,
            ndcg_at_5=totals["ndcg"] / n,
        )

    async def run(
        self, dataset: EvalDataset, configs: list[EvalConfig]
    ) -> list[ConfigResult]:
        return [await self.run_config(dataset, config) for config in configs]
