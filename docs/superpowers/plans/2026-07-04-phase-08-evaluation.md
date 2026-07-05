# Phase 8 — Evaluation Framework & Baselines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A deterministic, offline evaluation framework (`memcore.evaluation`) that measures retrieval quality against a naive-vector baseline, runs decay/importance ablations and a longitudinal age curve, and records reproducible baseline numbers — plus the two mechanical Phase 7 backlog fixes (oldest-first decay scan, `set_decay` clamp).

**Architecture:** `src/memcore/evaluation/` is a consumer/composition layer like `api/` (it may import in-memory adapters directly — same precedent as `api/app.py`; services/domain stay port-only). Everything is deterministic and offline: a hand-written synthetic dataset (token-overlap engineered, works with the hashing embedder), pure metric functions (recall@k, MRR, nDCG@k), a harness that builds a fresh in-memory stack per configuration (so recall's write-back reinforcement can't leak between configs), and scenario runners for the reinforcement ablation and the longitudinal decay curve. A tiny `python -m memcore.evaluation` CLI prints the baseline table that Task 5 records in the phase doc.

**Tech Stack:** Python 3.12, pydantic v2, pytest (anyio fixtures in `tests/conftest.py`), in-memory adapters only — no LLM, no network, no new dependencies.

## Global Constraints

- Quality gate (every task, before commit): `./.venv/Scripts/python.exe -m pytest` all pass, coverage ≥ 85%; `./.venv/Scripts/python.exe -m ruff check .` clean; `./.venv/Scripts/python.exe -m mypy` clean (strict).
- Hexagonal: `services/*` and `domain/*` import ports only. `evaluation/*` is a composition/consumer layer and MAY import `memcore.adapters.inmemory` directly (precedent: `api/app.py`). It must never be imported by `services/*`, `domain/*`, `ports/*`, or `adapters/*`.
- Determinism: no randomness, no network, no LLM calls, no time mocking — ages are simulated by backdating `created_at`. Two consecutive runs must produce identical numbers.
- The only port change in this phase: `list_records` gains keyword `oldest_first: bool = False` (Task 1), contract-kit covered. `set_decay` clamping is adapter-internal (no signature change).
- All metric values bounded [0, 1]. `memcore.domain.models.utcnow()` for "now".
- One commit per task; phase gate + docs in Task 5; WAIT for user approval after the phase commit.

---

### Task 1: Phase 7 backlog hardening — oldest-first decay scan + `set_decay` clamp

**Files:**
- Modify: `src/memcore/ports/memory_store.py` (`list_records` gains `oldest_first`)
- Modify: `src/memcore/adapters/inmemory/memory_store.py` (`list_records` sort; `set_decay` clamp)
- Modify: `src/memcore/adapters/sql/memory_store.py` (`list_records` order_by; `set_decay` clamp)
- Modify: `src/memcore/testing/contracts.py` (assertions for both)
- Modify: `src/memcore/services/decay.py` (sweep scans oldest-first)
- Modify: `docs/adr/0016-decay-and-pruning.md` (amend point 5 + accepted-risks: non-convergence resolved)
- Modify: `PROJECT_STATE.md` (drop the two backlog lines this task closes: oldest-first scan, set_decay clamp — leave dedupe/rate-limit and restore endpoint)
- Test: contract runners (`tests/unit/test_contracts_inmemory.py`, `tests/unit/test_memory_store_contract.py`) + `tests/unit/test_decay.py`

**Interfaces:**
- Consumes: existing `MemoryStore` port and `DecayService.sweep`.
- Produces: `MemoryStore.list_records(self, tenant_id: str, agent_id: str | None, *, type: MemoryType | None = None, status: MemoryStatus | None = MemoryStatus.ACTIVE, limit: int = 100, oldest_first: bool = False) -> list[MemoryRecord]`. `set_decay` silently clamps scores to [0, 1].

- [ ] **Step 1: Extend the contract kit (failing tests)**

In `src/memcore/testing/contracts.py`, `check_memory_store_contract`, directly after the existing `set_decay`/tenant-wide-listing block (after the `assert [r.id for r in await store.list_records(tenant, agent)] == [m1_v2.id]` line):

```python
    # set_decay clamps out-of-range scores to [0, 1] instead of persisting them
    await store.set_decay(tenant, {m1_v2.id: 1.7})
    clamped_high = await store.get(tenant, m1_v2.id)
    assert clamped_high is not None and clamped_high.decay_score == 1.0
    await store.set_decay(tenant, {m1_v2.id: -0.3})
    clamped_low = await store.get(tenant, m1_v2.id)
    assert clamped_low is not None and clamped_low.decay_score == 0.0

    # oldest_first flips the ordering (decay sweeps scan from the stale end)
    newest = await store.list_records(tenant, None)
    oldest = await store.list_records(tenant, None, oldest_first=True)
    assert [r.id for r in oldest] == [r.id for r in reversed(newest)]
```

- [ ] **Step 2: Add a sweep-order test to `tests/unit/test_decay.py`**

Append (uses the file's existing `_Env` and imports; add `RetentionSettings` usage as in `test_min_age_rail_blocks_young_records`):

```python
async def test_sweep_scans_oldest_first_under_scan_limit() -> None:
    # With scan_limit=1 the page must contain the OLDEST record, so the
    # ancient prunable record is swept even though a fresh one exists.
    env = _Env(retention=RetentionSettings(scan_limit=1))
    ancient = await env.seed("forgotten trivia", age=timedelta(days=365))
    fresh = await env.seed("fresh fact")

    report = await env.decay.sweep(TENANT)

    assert report.scanned == 1
    assert report.pruned == 1
    pruned = await env.store.get(TENANT, ancient.id)
    assert pruned is not None and pruned.status is MemoryStatus.SOFT_DELETED
    kept = await env.store.get(TENANT, fresh.id)
    assert kept is not None and kept.status is MemoryStatus.ACTIVE
```

- [ ] **Step 3: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_contracts_inmemory.py tests/unit/test_memory_store_contract.py tests/unit/test_decay.py -v`
Expected: FAIL — `TypeError: list_records() got an unexpected keyword argument 'oldest_first'`, clamp assertions fail, and the sweep-order test prunes the wrong record (newest-first page holds `fresh`).

- [ ] **Step 4: Port + adapters + service**

1. `src/memcore/ports/memory_store.py` — `list_records` signature adds `oldest_first: bool = False` after `limit`, docstring:

```python
    @abstractmethod
    async def list_records(
        self,
        tenant_id: str,
        agent_id: str | None,
        *,
        type: MemoryType | None = None,
        status: MemoryStatus | None = MemoryStatus.ACTIVE,
        limit: int = 100,
        oldest_first: bool = False,
    ) -> list[MemoryRecord]:
        """List records, newest-first by default. ``status=None`` means all
        statuses; ``agent_id=None`` means all agents in the tenant;
        ``oldest_first=True`` reverses the order so bounded scans (decay
        sweeps) start from the stale end."""
```

2. `src/memcore/adapters/inmemory/memory_store.py` — signature likewise; sort line becomes:

```python
        rows.sort(key=lambda r: r.created_at, reverse=not oldest_first)
```

`set_decay` loop body clamps:

```python
    async def set_decay(self, tenant_id: str, scores: dict[str, float]) -> None:
        for memory_id, score in scores.items():
            record = await self.get(tenant_id, memory_id)
            if record is not None:
                self._records[(tenant_id, memory_id)] = record.model_copy(
                    update={"decay_score": min(1.0, max(0.0, score))}
                )
```

3. `src/memcore/adapters/sql/memory_store.py` — signature likewise; order_by becomes:

```python
            .order_by(
                MemoryRow.created_at.asc() if oldest_first
                else MemoryRow.created_at.desc()
            )
```

`set_decay` update values clamp:

```python
                    .values(decay_score=min(1.0, max(0.0, score)))
```

4. `src/memcore/services/decay.py` — the sweep's `list_records` call gains `oldest_first=True`:

```python
        records = await self._store.list_records(
            tenant_id, None,
            status=MemoryStatus.ACTIVE,
            limit=self._retention.scan_limit,
            oldest_first=True,
        )
```

- [ ] **Step 5: Amend ADR-0016 and PROJECT_STATE**

In `docs/adr/0016-decay-and-pruning.md`:
- Decision point 5: replace the "will NOT converge … deferred to the deployment phase" sentence block with: "v1 scans a single `scan_limit` (default `10_000`) page, **oldest-first** (amended in Phase 8): the page always contains the tenant's most-decayed records, so tenants above `scan_limit` converge across sweeps — `scan_limit` now only bounds per-sweep work, and snapshots for records beyond the page catch up on subsequent sweeps."
- Add below the Status line: `**Amended:** 2026-07-04 (Phase 8) — sweep scans oldest-first; `set_decay` clamps scores to [0, 1] at the adapter layer.`

In `PROJECT_STATE.md`, edit the Phase 8 backlog line to remove the two items this task closes, leaving: "Backlog (from Phase 7 final review): per-tenant sweep dedupe + rate limiting; restore endpoint for soft-deleted records."

- [ ] **Step 6: Run tests, then full gate**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_contracts_inmemory.py tests/unit/test_memory_store_contract.py tests/unit/test_decay.py -v`
Expected: all PASS.
Then: `./.venv/Scripts/python.exe -m pytest && ./.venv/Scripts/python.exe -m ruff check . && ./.venv/Scripts/python.exe -m mypy`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/memcore/ports/memory_store.py src/memcore/adapters/inmemory/memory_store.py src/memcore/adapters/sql/memory_store.py src/memcore/testing/contracts.py src/memcore/services/decay.py tests/unit/test_decay.py docs/adr/0016-decay-and-pruning.md PROJECT_STATE.md
git commit -m "feat(decay): oldest-first sweep scan + set_decay clamp (Phase 7 backlog)"
```

---

### Task 2: Metric primitives — `evaluation/metrics.py`

**Files:**
- Create: `src/memcore/evaluation/__init__.py`
- Create: `src/memcore/evaluation/metrics.py`
- Test: `tests/unit/test_eval_metrics.py`

**Interfaces:**
- Consumes: nothing project-specific (pure functions over id lists).
- Produces (Tasks 3–4 rely on):
  - `recall_at_k(relevant: set[str], ranked: list[str], k: int) -> float`
  - `mrr(relevant: set[str], ranked: list[str]) -> float`
  - `ndcg_at_k(relevant: set[str], ranked: list[str], k: int) -> float`
  All return 0.0 when `relevant` is empty; all bounded [0, 1].

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_eval_metrics.py`:

```python
"""Phase 8 — retrieval-quality metric primitives (pure, hand-computed cases)."""

import math

import pytest

from memcore.evaluation.metrics import mrr, ndcg_at_k, recall_at_k


class TestRecallAtK:
    def test_full_hit(self) -> None:
        assert recall_at_k({"a", "b"}, ["a", "b", "c"], k=3) == 1.0

    def test_partial_hit(self) -> None:
        assert recall_at_k({"a", "b"}, ["a", "x", "y"], k=3) == 0.5

    def test_hit_outside_k_ignored(self) -> None:
        assert recall_at_k({"a"}, ["x", "y", "a"], k=2) == 0.0

    def test_empty_relevant_is_zero(self) -> None:
        assert recall_at_k(set(), ["a"], k=5) == 0.0


class TestMrr:
    def test_first_position(self) -> None:
        assert mrr({"a"}, ["a", "b"]) == 1.0

    def test_third_position(self) -> None:
        assert mrr({"a"}, ["x", "y", "a"]) == pytest.approx(1 / 3)

    def test_no_hit(self) -> None:
        assert mrr({"a"}, ["x", "y"]) == 0.0

    def test_empty_relevant_is_zero(self) -> None:
        assert mrr(set(), ["a"]) == 0.0


class TestNdcgAtK:
    def test_perfect_ranking(self) -> None:
        assert ndcg_at_k({"a", "b"}, ["a", "b", "x"], k=3) == pytest.approx(1.0)

    def test_hand_computed(self) -> None:
        # Hits at ranks 1 and 3: DCG = 1/log2(2) + 1/log2(4) = 1 + 0.5 = 1.5
        # IDCG (2 relevant in top-3) = 1/log2(2) + 1/log2(3)
        expected = 1.5 / (1.0 + 1.0 / math.log2(3))
        assert ndcg_at_k({"a", "b"}, ["a", "x", "b"], k=3) == pytest.approx(expected)

    def test_no_hit_is_zero(self) -> None:
        assert ndcg_at_k({"a"}, ["x", "y"], k=2) == 0.0

    def test_empty_relevant_is_zero(self) -> None:
        assert ndcg_at_k(set(), ["a"], k=1) == 0.0

    def test_bounded(self) -> None:
        for ranked in (["a"], ["x", "a"], ["a", "b", "c"]):
            value = ndcg_at_k({"a", "b"}, ranked, k=3)
            assert 0.0 <= value <= 1.0
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_eval_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'memcore.evaluation'`.

- [ ] **Step 3: Implement**

Create `src/memcore/evaluation/__init__.py`:

```python
"""Offline evaluation framework (Phase 8, ADR-0017).

Deterministic, in-process measurement of retrieval quality: pure metric
primitives, a synthetic token-overlap dataset, a harness that runs named
scoring configurations against a fresh in-memory stack, and scenario runners
for the reinforcement ablation and the longitudinal decay curve.

This package is a consumer/composition layer (like ``memcore.api``): it may
build in-memory adapters directly, and nothing inside ``services``/``domain``
/``ports``/``adapters`` may import it.
"""

from memcore.evaluation.metrics import mrr, ndcg_at_k, recall_at_k

__all__ = ["mrr", "ndcg_at_k", "recall_at_k"]
```

Create `src/memcore/evaluation/metrics.py`:

```python
"""Retrieval-quality metric primitives — pure functions, binary relevance."""

from __future__ import annotations

import math


def recall_at_k(relevant: set[str], ranked: list[str], k: int) -> float:
    """Fraction of ``relevant`` ids present in the top ``k`` of ``ranked``."""
    if not relevant:
        return 0.0
    return len(relevant & set(ranked[:k])) / len(relevant)


def mrr(relevant: set[str], ranked: list[str]) -> float:
    """Reciprocal rank of the first relevant hit (0.0 when none)."""
    if not relevant:
        return 0.0
    for index, item in enumerate(ranked):
        if item in relevant:
            return 1.0 / (index + 1)
    return 0.0


def ndcg_at_k(relevant: set[str], ranked: list[str], k: int) -> float:
    """Normalized discounted cumulative gain at ``k`` (binary gains)."""
    if not relevant:
        return 0.0
    dcg = sum(
        1.0 / math.log2(index + 2)
        for index, item in enumerate(ranked[:k])
        if item in relevant
    )
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
    return dcg / idcg if idcg > 0 else 0.0
```

- [ ] **Step 4: Run to verify pass, then full gate**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_eval_metrics.py -v`
Expected: all PASS.
Then the full gate. Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/memcore/evaluation/__init__.py src/memcore/evaluation/metrics.py tests/unit/test_eval_metrics.py
git commit -m "feat(eval): metric primitives — recall@k, MRR, nDCG@k (Phase 8)"
```

---

### Task 3: Dataset + harness — `evaluation/datasets.py`, `evaluation/harness.py`

**Files:**
- Create: `src/memcore/evaluation/datasets.py`
- Create: `src/memcore/evaluation/harness.py`
- Modify: `src/memcore/evaluation/__init__.py` (exports)
- Test: `tests/unit/test_eval_harness.py`

**Interfaces:**
- Consumes: Task 2 metrics; `MemoryService`, `RecallService`, `ScoreWeights` from `memcore.services`; `ImportanceSettings`, `RetrievalSettings` from `memcore.config`; in-memory adapters.
- Produces (Task 4 relies on):
  - `EvalRecord(key: str, content: str, age_days: float = 0.0, importance: float = 0.5, reinforce_count: int = 0, tags: list[str] = [])`
  - `EvalCase(query: str, relevant_keys: list[str])`
  - `EvalDataset(name: str, records: list[EvalRecord], cases: list[EvalCase])`
  - `synthetic_dataset() -> EvalDataset` (deterministic, 12 records / 8 cases)
  - `EvalConfig(name: str, relevance: float = 1.0, recency: float = 1.0, importance: float = 1.0, lexical_alpha: float | None = None)`
  - `STANDARD_CONFIGS: list[EvalConfig]` — names exactly: `"naive-vector"`, `"hybrid"`, `"no-importance"`, `"no-recency"`
  - `ConfigResult(config: str, cases: int, recall_at_5: float, mrr: float, ndcg_at_5: float)`
  - `EvalHarness()` with:
    - `async def seed(self, dataset: EvalDataset) -> None` (fresh internal stack each call; backdates `created_at` by `age_days`; applies `reinforce_count` via `store.reinforce`)
    - `async def run_config(self, dataset: EvalDataset, config: EvalConfig, *, k: int = 5) -> ConfigResult` (re-seeds a FRESH stack first — configs never share state)
    - `async def run(self, dataset: EvalDataset, configs: list[EvalConfig]) -> list[ConfigResult]`
    - attributes usable by Task 4 after `seed`: `harness.store`, `harness.memories`, `harness.recall_service(config)` (returns a `RecallService` bound to the current stack for that config), `harness.ids: dict[str, str]` (dataset key → record id), `harness.tenant`, `harness.agent`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_eval_harness.py`:

```python
"""Phase 8 — synthetic dataset + evaluation harness (deterministic, offline)."""

from memcore.evaluation.datasets import EvalCase, EvalDataset, EvalRecord, synthetic_dataset
from memcore.evaluation.harness import STANDARD_CONFIGS, EvalConfig, EvalHarness


def test_synthetic_dataset_shape_and_referential_integrity() -> None:
    dataset = synthetic_dataset()
    keys = {r.key for r in dataset.records}
    assert len(dataset.records) == 12
    assert len(keys) == 12  # keys unique
    assert len(dataset.cases) == 8
    for case in dataset.cases:
        assert case.relevant_keys, "every case names at least one relevant record"
        assert set(case.relevant_keys) <= keys


def test_standard_configs_names() -> None:
    assert [c.name for c in STANDARD_CONFIGS] == [
        "naive-vector", "hybrid", "no-importance", "no-recency",
    ]


async def test_run_produces_bounded_metrics_for_all_configs() -> None:
    harness = EvalHarness()
    results = await harness.run(synthetic_dataset(), STANDARD_CONFIGS)
    assert [r.config for r in results] == [c.name for c in STANDARD_CONFIGS]
    for result in results:
        assert result.cases == 8
        for value in (result.recall_at_5, result.mrr, result.ndcg_at_5):
            assert 0.0 <= value <= 1.0
    # The dataset is engineered for strong token overlap: the full hybrid
    # config must find at least most targets in the top 5 of 12 records.
    hybrid = next(r for r in results if r.config == "hybrid")
    assert hybrid.recall_at_5 >= 0.75


async def test_runs_are_deterministic() -> None:
    dataset = synthetic_dataset()
    first = await EvalHarness().run(dataset, STANDARD_CONFIGS)
    second = await EvalHarness().run(dataset, STANDARD_CONFIGS)
    assert first == second


async def test_configs_do_not_share_state() -> None:
    # A reinforced record boosts ranking under "hybrid" but the later
    # "no-importance" run must start from a fresh, unreinforced stack:
    # its per-record access counts must all be zero after re-seeding.
    dataset = EvalDataset(
        name="tiny",
        records=[
            EvalRecord(key="hot", content="alpha beta gamma", reinforce_count=5),
            EvalRecord(key="cold", content="alpha beta delta"),
        ],
        cases=[EvalCase(query="alpha beta", relevant_keys=["hot"])],
    )
    harness = EvalHarness()
    await harness.run_config(dataset, EvalConfig(name="hybrid"))
    await harness.run_config(dataset, EvalConfig(name="no-importance", importance=0.0))
    # After the second run_config, the stack was rebuilt: the seeded
    # reinforce_count is applied fresh (5), not accumulated across runs.
    hot = await harness.store.get(harness.tenant, harness.ids["hot"])
    assert hot is not None
    # 5 seeded + at most 1 from the single recall call of the second config.
    assert hot.access_count <= 6
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_eval_harness.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'memcore.evaluation.datasets'`.

- [ ] **Step 3: Implement the dataset module**

Create `src/memcore/evaluation/datasets.py`:

```python
"""Evaluation datasets — deterministic, token-overlap engineered.

The synthetic dataset is hand-written so that each query shares distinctive
tokens with exactly its target record and only generic tokens with
distractors. That makes it meaningful under the deterministic hashing
embedder (token-based) as well as real embedding models.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvalRecord(_Base):
    key: str
    content: str
    age_days: float = Field(default=0.0, ge=0.0)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    reinforce_count: int = Field(default=0, ge=0)
    tags: list[str] = Field(default_factory=list)


class EvalCase(_Base):
    query: str
    relevant_keys: list[str]


class EvalDataset(_Base):
    name: str
    records: list[EvalRecord]
    cases: list[EvalCase]


def synthetic_dataset() -> EvalDataset:
    """12 semantic facts, 8 queries with known targets, 4 pure distractors."""
    records = [
        EvalRecord(key="editor-pref",
                   content="Chinmay prefers dark mode themes in the vim editor."),
        EvalRecord(key="editor-font",
                   content="The vim editor font is set to fira code."),
        EvalRecord(key="dog-name",
                   content="Chinmay's dog is named Bruno and likes long walks."),
        EvalRecord(key="dog-vet",
                   content="Bruno the dog visits the vet clinic every march."),
        EvalRecord(key="city-home",
                   content="Chinmay lives in Pune near the river."),
        EvalRecord(key="city-work",
                   content="The office is in Mumbai near the harbour."),
        EvalRecord(key="lang-pref",
                   content="Chinmay writes most backend services in Python."),
        EvalRecord(key="lang-legacy",
                   content="An old billing service is written in Java."),
        EvalRecord(key="coffee",
                   content="Chinmay drinks black coffee without sugar every morning."),
        EvalRecord(key="pantry",
                   content="The office pantry stocks green tea and sugar."),
        EvalRecord(key="meeting",
                   content="The weekly team meeting happens on tuesday morning."),
        EvalRecord(key="hobby",
                   content="Chinmay plays chess online on weekend mornings."),
    ]
    cases = [
        EvalCase(query="which editor theme does chinmay prefer",
                 relevant_keys=["editor-pref"]),
        EvalCase(query="what font is the vim editor set to",
                 relevant_keys=["editor-font"]),
        EvalCase(query="what is the name of chinmay's dog",
                 relevant_keys=["dog-name"]),
        EvalCase(query="where does chinmay live",
                 relevant_keys=["city-home"]),
        EvalCase(query="which language does chinmay write backend services in",
                 relevant_keys=["lang-pref"]),
        EvalCase(query="how does chinmay drink his coffee",
                 relevant_keys=["coffee"]),
        EvalCase(query="when does the weekly team meeting happen",
                 relevant_keys=["meeting"]),
        EvalCase(query="what does chinmay play on weekend mornings",
                 relevant_keys=["hobby"]),
    ]
    return EvalDataset(name="synthetic-v1", records=records, cases=cases)
```

- [ ] **Step 4: Implement the harness**

Create `src/memcore/evaluation/harness.py`:

```python
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
        self.__init__()  # fresh stores: no state survives re-seeding
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
```

Update `src/memcore/evaluation/__init__.py` exports:

```python
from memcore.evaluation.datasets import EvalCase, EvalDataset, EvalRecord, synthetic_dataset
from memcore.evaluation.harness import (
    STANDARD_CONFIGS,
    ConfigResult,
    EvalConfig,
    EvalHarness,
)
from memcore.evaluation.metrics import mrr, ndcg_at_k, recall_at_k

__all__ = [
    "STANDARD_CONFIGS",
    "ConfigResult",
    "EvalCase",
    "EvalConfig",
    "EvalDataset",
    "EvalHarness",
    "EvalRecord",
    "mrr",
    "ndcg_at_k",
    "recall_at_k",
    "synthetic_dataset",
]
```

(Note: `self.__init__()` inside `seed` is deliberate and simple — it resets every stack attribute in one place. If ruff/mypy object, extract the constructor body into a private `_reset(self) -> None` called from both `__init__` and `seed`.)

- [ ] **Step 5: Run to verify pass, then full gate**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_eval_harness.py -v`
Expected: all PASS. If `hybrid.recall_at_5 >= 0.75` fails, the dataset/query token overlap needs strengthening (add distinctive query tokens mirroring the target's content) — do NOT weaken the assertion below 0.75.
Then the full gate. Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/memcore/evaluation/__init__.py src/memcore/evaluation/datasets.py src/memcore/evaluation/harness.py tests/unit/test_eval_harness.py
git commit -m "feat(eval): synthetic dataset + config harness (Phase 8)"
```

---

### Task 4: Scenarios + CLI — ablation, longitudinal curve, `python -m memcore.evaluation`

**Files:**
- Create: `src/memcore/evaluation/scenarios.py`
- Create: `src/memcore/evaluation/__main__.py`
- Modify: `src/memcore/evaluation/__init__.py` (exports)
- Test: `tests/unit/test_eval_scenarios.py`

**Interfaces:**
- Consumes (Task 3): `EvalHarness` (incl. `seed`, `recall_service`, `store`, `memories`, `ids`, `tenant`, `agent`), `EvalConfig`, `EvalDataset`/`EvalRecord`/`EvalCase`, `synthetic_dataset`, `STANDARD_CONFIGS`; `DecayService` from `memcore.services`.
- Produces:
  - `AblationOutcome(config: str, pairs: int, wins: int, ties: int, losses: int)`
  - `async def reinforcement_ablation(pairs: int = 6, boosts: int = 10) -> list[AblationOutcome]` — outcomes for configs `"hybrid"` then `"no-importance"`.
  - `AgePoint(age_days: float, recall_at_5: float, mean_final: float)`
  - `async def longitudinal_curve(ages: list[float] | None = None, *, sweep: bool = False) -> list[AgePoint]` — default ages `[0.0, 7.0, 30.0, 90.0, 180.0]`; `sweep=True` runs `DecayService.sweep` after seeding, before recall.
  - `async def render_report() -> str` in `__main__.py` — the full text report; `main()` prints it.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_eval_scenarios.py`:

```python
"""Phase 8 — ablation + longitudinal scenarios (deterministic outcomes)."""

from memcore.evaluation.scenarios import (
    AgePoint,
    longitudinal_curve,
    reinforcement_ablation,
)


async def test_reinforcement_ablation_hybrid_wins_no_importance_ties() -> None:
    outcomes = await reinforcement_ablation(pairs=4, boosts=10)
    by_config = {o.config: o for o in outcomes}

    hybrid = by_config["hybrid"]
    assert hybrid.pairs == 4
    # Identical content, one twin reinforced: with importance active the
    # reinforced twin must outrank its cold twin in every pair.
    assert hybrid.wins == 4 and hybrid.losses == 0

    ablated = by_config["no-importance"]
    # With the importance factor neutralized (x**0 == 1) the twins tie.
    assert ablated.ties == 4 and ablated.wins == 0 and ablated.losses == 0


async def test_longitudinal_curve_decays_and_sweep_prunes() -> None:
    no_sweep = await longitudinal_curve()
    with_sweep = await longitudinal_curve(sweep=True)

    ages = [point.age_days for point in no_sweep]
    assert ages == [0.0, 7.0, 30.0, 90.0, 180.0]

    # Aged targets score strictly less; the mean final score never rises.
    finals = [point.mean_final for point in no_sweep]
    assert all(later <= earlier for earlier, later in zip(finals, finals[1:]))
    assert finals[-1] < finals[0]

    # Fresh targets are found either way.
    assert no_sweep[0].recall_at_5 > 0.0
    assert with_sweep[0].recall_at_5 == no_sweep[0].recall_at_5

    # Past the prune horizon (~90 days at tau=30d, threshold=0.05) the decay
    # sweep removes the targets entirely: recall collapses to zero.
    assert with_sweep[-1].recall_at_5 == 0.0
    assert with_sweep[-2].recall_at_5 == 0.0  # age 90: exp(-3) ~ 0.0498 < 0.05
    assert no_sweep[-1].recall_at_5 >= with_sweep[-1].recall_at_5

    for point in no_sweep + with_sweep:
        assert isinstance(point, AgePoint)
        assert 0.0 <= point.recall_at_5 <= 1.0


async def test_cli_report_renders_all_sections() -> None:
    from memcore.evaluation.__main__ import render_report

    report = await render_report()
    for expected in ("naive-vector", "hybrid", "no-importance", "no-recency",
                     "recall@5", "reinforcement ablation", "longitudinal"):
        assert expected in report
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_eval_scenarios.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'memcore.evaluation.scenarios'`.

- [ ] **Step 3: Implement scenarios**

Create `src/memcore/evaluation/scenarios.py`:

```python
"""Evaluation scenarios — reinforcement ablation and longitudinal decay curve.

Both scenarios are deterministic: fixed datasets, fixed order, no randomness.
They demonstrate (and regression-guard) the Phase 6/7 behaviors end to end:
retrieval strengthens memory (ablation) and unused memories fade and are
eventually pruned (longitudinal).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from memcore.evaluation.datasets import EvalCase, EvalDataset, EvalRecord, synthetic_dataset
from memcore.evaluation.harness import EvalConfig, EvalHarness
from memcore.evaluation.metrics import recall_at_k
from memcore.services import DecayService, ScoreWeights

_PAIR_WORDS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]
_TIE_TOLERANCE = 1e-6


class AblationOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: str
    pairs: int
    wins: int    # reinforced twin ranked strictly above its cold twin
    ties: int    # final scores within relative tolerance
    losses: int  # cold twin ranked above


class AgePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    age_days: float
    recall_at_5: float
    mean_final: float


def _pair_dataset(pairs: int, boosts: int) -> EvalDataset:
    records: list[EvalRecord] = []
    cases: list[EvalCase] = []
    for word in _PAIR_WORDS[:pairs]:
        content = f"pair {word} concerns the {word} project milestone."
        records.append(EvalRecord(key=f"{word}-hot", content=content,
                                  reinforce_count=boosts))
        records.append(EvalRecord(key=f"{word}-cold", content=content))
        cases.append(EvalCase(query=f"what concerns the {word} project",
                              relevant_keys=[f"{word}-hot"]))
    return EvalDataset(name=f"pairs-{pairs}", records=records, cases=cases)


async def reinforcement_ablation(
    pairs: int = 6, boosts: int = 10
) -> list[AblationOutcome]:
    if not 1 <= pairs <= len(_PAIR_WORDS):
        raise ValueError(f"pairs must be 1..{len(_PAIR_WORDS)}")
    dataset = _pair_dataset(pairs, boosts)
    outcomes: list[AblationOutcome] = []
    for config in (EvalConfig(name="hybrid"),
                   EvalConfig(name="no-importance", importance=0.0)):
        harness = EvalHarness()
        await harness.seed(dataset)
        recall = harness.recall_service(config)
        weights = ScoreWeights(relevance=config.relevance,
                               recency=config.recency,
                               importance=config.importance)
        wins = ties = losses = 0
        for word in _PAIR_WORDS[:pairs]:
            results = await recall.recall(
                harness.tenant, harness.agent,
                f"what concerns the {word} project",
                k=pairs * 2, weights=weights,
            )
            by_id = {s.memory.id: s for s in results}
            hot = by_id.get(harness.ids[f"{word}-hot"])
            cold = by_id.get(harness.ids[f"{word}-cold"])
            if hot is None or cold is None:
                losses += 1  # a missing twin counts against the config
                continue
            if abs(hot.final - cold.final) <= _TIE_TOLERANCE * max(
                hot.final, cold.final, 1e-12
            ):
                ties += 1
            elif hot.final > cold.final:
                wins += 1
            else:
                losses += 1
        outcomes.append(AblationOutcome(config=config.name, pairs=pairs,
                                        wins=wins, ties=ties, losses=losses))
    return outcomes


def _aged_dataset(base: EvalDataset, age_days: float) -> EvalDataset:
    """Targets aged to ``age_days``; distractors stay fresh."""
    target_keys = {key for case in base.cases for key in case.relevant_keys}
    records = [
        record.model_copy(update={"age_days": age_days})
        if record.key in target_keys else record
        for record in base.records
    ]
    return EvalDataset(name=f"{base.name}-aged-{age_days}",
                       records=records, cases=base.cases)


async def longitudinal_curve(
    ages: list[float] | None = None, *, sweep: bool = False
) -> list[AgePoint]:
    ages = ages if ages is not None else [0.0, 7.0, 30.0, 90.0, 180.0]
    base = synthetic_dataset()
    config = EvalConfig(name="hybrid")
    weights = ScoreWeights()
    points: list[AgePoint] = []
    for age in ages:
        harness = EvalHarness()
        await harness.seed(_aged_dataset(base, age))
        if sweep:
            decay = DecayService(harness.store, harness.memories)
            await decay.sweep(harness.tenant)
        recall = harness.recall_service(config)
        key_by_id = {rid: key for key, rid in harness.ids.items()}
        recall_total = 0.0
        final_total = 0.0
        for case in base.cases:
            results = await recall.recall(
                harness.tenant, harness.agent, case.query, k=5, weights=weights
            )
            ranked = [key_by_id[s.memory.id] for s in results
                      if s.memory.id in key_by_id]
            relevant = set(case.relevant_keys)
            recall_total += recall_at_k(relevant, ranked, 5)
            final_total += sum(
                s.final for s in results if key_by_id.get(s.memory.id) in relevant
            )
        n = len(base.cases)
        points.append(AgePoint(age_days=age,
                               recall_at_5=recall_total / n,
                               mean_final=final_total / n))
    return points
```

- [ ] **Step 4: Implement the CLI**

Create `src/memcore/evaluation/__main__.py`:

```python
"""``python -m memcore.evaluation`` — print the baseline evaluation report."""

from __future__ import annotations

import asyncio

from memcore.evaluation.datasets import synthetic_dataset
from memcore.evaluation.harness import STANDARD_CONFIGS, EvalHarness
from memcore.evaluation.scenarios import longitudinal_curve, reinforcement_ablation


async def render_report() -> str:
    lines: list[str] = []
    lines.append("MemCore evaluation — synthetic-v1 (deterministic, in-memory)")
    lines.append("")
    lines.append(f"{'config':<15} {'recall@5':>9} {'mrr':>7} {'ndcg@5':>7}")
    for result in await EvalHarness().run(synthetic_dataset(), STANDARD_CONFIGS):
        lines.append(
            f"{result.config:<15} {result.recall_at_5:>9.3f} "
            f"{result.mrr:>7.3f} {result.ndcg_at_5:>7.3f}"
        )
    lines.append("")
    lines.append("reinforcement ablation (identical twins, one reinforced x10):")
    for outcome in await reinforcement_ablation():
        lines.append(
            f"  {outcome.config:<15} wins={outcome.wins} "
            f"ties={outcome.ties} losses={outcome.losses} of {outcome.pairs}"
        )
    lines.append("")
    lines.append("longitudinal recall@5 by target age (hybrid config):")
    plain = await longitudinal_curve()
    swept = await longitudinal_curve(sweep=True)
    lines.append(f"{'age_days':>9} {'no sweep':>9} {'after sweep':>12}")
    for a, b in zip(plain, swept):
        lines.append(f"{a.age_days:>9.0f} {a.recall_at_5:>9.3f} {b.recall_at_5:>12.3f}")
    return "\n".join(lines)


def main() -> None:
    print(asyncio.run(render_report()))


if __name__ == "__main__":
    main()
```

Update `src/memcore/evaluation/__init__.py`: add to the imports/`__all__` —
`AblationOutcome`, `AgePoint`, `longitudinal_curve`, `reinforcement_ablation`
(from `memcore.evaluation.scenarios`), keeping the list alphabetized.

- [ ] **Step 5: Run tests, the CLI, then full gate**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_eval_scenarios.py -v`
Expected: all PASS.
Run: `./.venv/Scripts/python.exe -m memcore.evaluation`
Expected: the report prints with all three sections and no traceback.
Then the full gate. Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/memcore/evaluation/scenarios.py src/memcore/evaluation/__main__.py src/memcore/evaluation/__init__.py tests/unit/test_eval_scenarios.py
git commit -m "feat(eval): ablation + longitudinal scenarios and CLI report (Phase 8)"
```

---

### Task 5: Docs, ADR-0017, baselines — phase gate

**Files:**
- Create: `docs/adr/0017-evaluation-framework.md`
- Create: `docs/design/phase-08.md`
- Modify: `docs/adr/README.md` (index line), `docs/design/roadmap.md` (Phase 8 → ✅ Complete, Phase 9 → ⏳ Next), `CHANGELOG.md`, `PROJECT_STATE.md`

**Interfaces:** none — documentation of Tasks 1–4 exactly as built.

- [ ] **Step 1: Capture the real baseline numbers**

Run: `./.venv/Scripts/python.exe -m memcore.evaluation > .superpowers/sdd/phase-08-baselines.txt` and read the file. These numbers go verbatim into `phase-08.md`.

- [ ] **Step 2: Write ADR-0017**

`docs/adr/0017-evaluation-framework.md` (match the style of `docs/adr/0016-decay-and-pruning.md`):
- **Status:** accepted. **Context:** Phases 4–7 shipped ranking behaviors (hybrid scoring, reinforcement, decay/pruning) with unit tests but no way to measure retrieval quality as a system or compare against a baseline; regressions in ranking quality would be invisible.
- **Decision:** (1) `memcore.evaluation` is a consumer/composition layer (like `memcore.api`) allowed to build in-memory adapters directly; nothing in services/domain/ports/adapters may import it; (2) evaluation is deterministic and offline — hand-written token-overlap dataset (`synthetic-v1`, 12 records/8 cases), no LLM/network/randomness, ages simulated by backdating `created_at`; (3) binary-relevance metrics recall@k / MRR / nDCG@k; (4) each configuration runs on a freshly rebuilt+re-seeded stack so recall's write-back reinforcement is measured within a config but never leaks between configs (within a config, cases run in fixed order — reproducible by construction); (5) standard configs: `naive-vector` (vector-only: recency/importance weights 0, lexical_alpha 0) as the baseline, `hybrid` (full defaults), `no-importance`, `no-recency` ablations; (6) two scenario runners double as regression guards: reinforcement ablation (reinforced twin must win under hybrid, tie under no-importance) and longitudinal curve (score decay with age; decay sweep collapses recall to 0 past the ~90-day prune horizon); (7) `python -m memcore.evaluation` prints the reproducible baseline report recorded in phase docs.
- **Consequences:** ranking changes now have a measurable, versioned quality baseline; the synthetic dataset is embedder-honest (token overlap) but small — real-corpus datasets and LLM-judged relevance are future work (Phase 12 examples / post-v1); scenario tests make Phase 6/7 behaviors regression-visible end to end.

Add to `docs/adr/README.md` index: `- [ADR-0017](0017-evaluation-framework.md) — Evaluation framework: deterministic offline harness, baseline + ablations`.

- [ ] **Step 3: Write the phase doc**

`docs/design/phase-08.md`, same structure as `phase-07.md` (Objective / Delivered / Gate / Deferred / Self-review):
- Delivered: Phase 7 backlog hardening (oldest-first sweep — non-convergence limitation resolved, ADR-0016 amended; `set_decay` clamp); `evaluation/` package (metrics, `synthetic-v1` dataset, harness with per-config stack isolation, ablation + longitudinal scenarios, CLI).
- **Baselines (2026-07-04, `python -m memcore.evaluation`):** paste the full report from Step 1 verbatim in a code block.
- Gate: real numbers from Step 5.
- Deferred: real-corpus/LLM-judged datasets; per-tenant sweep dedupe + rate limiting and restore endpoint (deployment/security phases); pgvector/qdrant-backed eval runs.

- [ ] **Step 4: Update CHANGELOG, roadmap, PROJECT_STATE**

`CHANGELOG.md` — new block above Phase 7:

```markdown
### Added — Phase 8: Evaluation framework & baselines
- `memcore.evaluation`: deterministic offline harness — binary-relevance
  metrics (recall@k, MRR, nDCG@k), token-overlap dataset `synthetic-v1`,
  per-config stack isolation, standard configs (naive-vector baseline,
  hybrid, no-importance, no-recency) — ADR-0017.
- Scenario regression guards: reinforcement ablation (reinforced twin wins
  under hybrid, ties under no-importance) and longitudinal decay curve
  (sweep collapses recall past the prune horizon).
- `python -m memcore.evaluation` prints the reproducible baseline report
  (recorded in docs/design/phase-08.md).
- Phase 7 backlog closed: decay sweep scans oldest-first (convergence for
  tenants above `scan_limit`; ADR-0016 amended) and `set_decay` clamps
  scores to [0, 1]; `list_records` gained `oldest_first`.
```

`docs/design/roadmap.md`: Phase 8 → `✅ Complete`, Phase 9 → `⏳ Next`.

`PROJECT_STATE.md`: current position → Phase 8 complete / Phase 9 (Python SDK) not started, awaiting approval; record the Phase 8 gate numbers; next tasks → Phase 9 outline (typed async+sync client over the v1 API, retries/backoff, pagination helpers, packaging extras, quickstart docs); remaining backlog carries over (sweep dedupe + rate limiting, restore endpoint — deployment/security); open decision → approve Phase 9 start.

- [ ] **Step 5: Run the phase gate and record numbers**

Run: `./.venv/Scripts/python.exe -m pytest` (record pass count + coverage %), `./.venv/Scripts/python.exe -m ruff check .`, `./.venv/Scripts/python.exe -m mypy`
Expected: all clean, coverage ≥ 85%. Copy the real numbers into `phase-08.md` and `PROJECT_STATE.md`.

- [ ] **Step 6: Phase commit**

```bash
git add docs/adr/0017-evaluation-framework.md docs/adr/README.md docs/design/phase-08.md docs/design/roadmap.md CHANGELOG.md PROJECT_STATE.md
git commit -m "docs: Phase 8 gate — evaluation framework & baselines (ADR-0017)"
```

Then STOP: per the phase gate, WAIT for user approval before any Phase 9 work.
