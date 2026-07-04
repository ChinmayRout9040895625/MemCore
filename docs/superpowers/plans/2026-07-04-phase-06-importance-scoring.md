# Phase 6 — Importance Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Memories carry an LLM-assessed base importance, get reinforced by usage at rank time, and can be pinned to resist decay.

**Architecture:** Base `importance` is set at write time (LLM per-fact score during consolidation; caller-provided via API). Reinforcement and decay are *pure, deterministic functions* in a new `services/importance.py`, computed at read time from stored raw signals (`access_count`, `last_accessed_at`, `created_at`, `tags`). Nothing derived is persisted in Phase 6 — the stored `decay_score` field remains a snapshot that Phase 7's prune job will maintain using these same functions. Recall ranks with the reinforced ("effective") importance instead of the raw stored value. Pinned memories (tag `"pinned"`) never decay.

**Tech Stack:** Python 3.12, pydantic v2, pytest (async via anyio fixtures already in `tests/conftest.py`), in-memory adapters for unit tests.

## Global Constraints

- Quality gate (every task, before commit): `./.venv/Scripts/python.exe -m pytest` all pass, coverage ≥ 85%; `./.venv/Scripts/python.exe -m ruff check .` clean; `./.venv/Scripts/python.exe -m mypy` clean (strict).
- Hexagonal rules: `services/*` and `domain/*` import ports only — no adapter imports. No changes to any `ports/*` signatures in this phase (the `reinforce` port already stores the raw signals we need).
- Records are immutable + versioned (ADR-0007): never mutate a `MemoryRecord`; changes go through `superseded_by` / `MemoryService.correct`.
- All scores are bounded [0, 1]. Use `memcore.domain.models.utcnow()` for "now"; all datetimes are aware UTC.
- Env-var config style: nested pydantic-settings blocks on `Settings` (see `config.py`).
- One commit per task; phase gate + docs in Task 4; WAIT for user approval after the phase commit.

---

### Task 1: Pure scoring module + settings

**Files:**
- Modify: `src/memcore/config.py` (add `ImportanceSettings`, wire into `Settings`)
- Create: `src/memcore/services/importance.py`
- Test: `tests/unit/test_importance.py`

**Interfaces:**
- Consumes: `MemoryRecord`, `utcnow` from `memcore.domain.models`.
- Produces (later tasks rely on these exact names):
  - `memcore.config.ImportanceSettings` — fields `reinforcement_saturation: float = 5.0`, `reinforcement_max_boost: float = 0.3`, `decay_tau_days: float = 30.0`; on `Settings` as `importance`.
  - `memcore.services.importance.PINNED_TAG: str = "pinned"`
  - `reinforcement(access_count: int, *, saturation: float) -> float`
  - `effective_importance(record: MemoryRecord, *, settings: ImportanceSettings) -> float`
  - `decay_score(record: MemoryRecord, now: datetime, *, settings: ImportanceSettings) -> float`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_importance.py`:

```python
"""Phase 6 — pure importance/decay math (no I/O)."""

from datetime import timedelta

from memcore.config import ImportanceSettings
from memcore.domain.models import MemoryRecord, utcnow
from memcore.services.importance import (
    PINNED_TAG,
    decay_score,
    effective_importance,
    reinforcement,
)


def make_record(**kwargs: object) -> MemoryRecord:
    defaults: dict[str, object] = {
        "tenant_id": "t1",
        "agent_id": "a1",
        "type": "semantic",
        "content": "Chinmay prefers dark mode.",
    }
    defaults.update(kwargs)
    return MemoryRecord.model_validate(defaults)


CFG = ImportanceSettings()


class TestReinforcement:
    def test_zero_accesses_is_zero(self) -> None:
        assert reinforcement(0, saturation=5.0) == 0.0

    def test_half_boost_at_saturation(self) -> None:
        assert reinforcement(5, saturation=5.0) == 0.5

    def test_monotonic_and_bounded(self) -> None:
        values = [reinforcement(n, saturation=5.0) for n in range(0, 200, 7)]
        assert values == sorted(values)
        assert all(0.0 <= v < 1.0 for v in values)


class TestEffectiveImportance:
    def test_unaccessed_record_keeps_base_importance(self) -> None:
        record = make_record(importance=0.4)
        assert effective_importance(record, settings=CFG) == 0.4

    def test_access_raises_importance(self) -> None:
        cold = make_record(importance=0.4)
        hot = make_record(importance=0.4, access_count=10)
        assert effective_importance(hot, settings=CFG) > effective_importance(
            cold, settings=CFG
        )

    def test_never_exceeds_one(self) -> None:
        record = make_record(importance=1.0, access_count=1_000_000)
        assert effective_importance(record, settings=CFG) == 1.0

    def test_boost_is_capped(self) -> None:
        record = make_record(importance=0.5, access_count=1_000_000)
        # base + max_boost * (1 - base) = 0.5 + 0.3 * 0.5 = 0.65 is the ceiling
        assert effective_importance(record, settings=CFG) < 0.65


class TestDecayScore:
    def test_fresh_record_near_one(self) -> None:
        record = make_record()
        assert decay_score(record, utcnow(), settings=CFG) > 0.99

    def test_old_untouched_record_decays(self) -> None:
        old = utcnow() - timedelta(days=90)  # 3x tau
        record = make_record(created_at=old, valid_from=old)
        assert decay_score(record, utcnow(), settings=CFG) < 0.1

    def test_recent_access_resets_the_clock(self) -> None:
        old = utcnow() - timedelta(days=90)
        stale = make_record(created_at=old, valid_from=old)
        refreshed = make_record(
            created_at=old, valid_from=old, last_accessed_at=utcnow(), access_count=1
        )
        now = utcnow()
        assert decay_score(refreshed, now, settings=CFG) > decay_score(
            stale, now, settings=CFG
        )
        assert decay_score(refreshed, now, settings=CFG) > 0.99

    def test_pinned_record_never_decays(self) -> None:
        old = utcnow() - timedelta(days=3650)
        record = make_record(created_at=old, valid_from=old, tags=[PINNED_TAG])
        assert decay_score(record, utcnow(), settings=CFG) == 1.0

    def test_bounded_zero_one(self) -> None:
        future = make_record(created_at=utcnow() + timedelta(hours=1))
        # Clock skew must not produce scores above 1.
        assert decay_score(future, utcnow(), settings=CFG) <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_importance.py -v`
Expected: FAIL — `ImportError: cannot import name 'ImportanceSettings'`.

- [ ] **Step 3: Add `ImportanceSettings` to config**

In `src/memcore/config.py`, insert after `RetrievalSettings` (before `LLMSettings`):

```python
class ImportanceSettings(BaseModel):
    """Knobs for importance reinforcement and decay (Phase 6).

    Reinforcement is a saturating curve of access_count; decay is exponential
    in time since last access. Both are computed at read time from raw
    signals — Phase 7's prune job persists snapshots with the same functions.
    """

    # Access count at which the reinforcement curve reaches half its ceiling.
    reinforcement_saturation: float = Field(default=5.0, gt=0)
    # Ceiling of the importance boost: effective <= base + boost * (1 - base).
    reinforcement_max_boost: float = Field(default=0.3, ge=0.0, le=1.0)
    # Time constant for decay of untouched memories.
    decay_tau_days: float = Field(default=30.0, gt=0)
```

And in `class Settings`, after the `consolidation` field:

```python
    importance: ImportanceSettings = Field(default_factory=ImportanceSettings)
```

- [ ] **Step 4: Write the scoring module**

Create `src/memcore/services/importance.py`:

```python
"""Importance reinforcement + decay — pure functions over raw signals.

Design (ADR-0015):

* ``MemoryRecord.importance`` stores the write-time *base* importance
  (LLM-assessed at consolidation, caller-provided via the API). It is never
  silently rewritten by usage.
* Usage feeds back at *read* time: ``effective_importance`` blends the base
  with a saturating function of ``access_count`` (retrieval strengthens
  memory, with diminishing returns — never past 1.0).
* ``decay_score`` is exponential in time since the memory was last touched
  (``last_accessed_at``, falling back to ``created_at``). Records tagged
  ``pinned`` are exempt and always score 1.0.
* Nothing here is persisted in Phase 6. Phase 7's decay/prune job will
  snapshot ``decay_score`` into the store using these same functions, so the
  math lives in exactly one place.
"""

from __future__ import annotations

import math
from datetime import datetime

from memcore.config import ImportanceSettings
from memcore.domain.models import MemoryRecord

PINNED_TAG = "pinned"


def reinforcement(access_count: int, *, saturation: float) -> float:
    """Saturating usage curve in [0, 1): 0 at no accesses, 0.5 at
    ``saturation`` accesses, asymptotically 1. Michaelis–Menten form keeps it
    monotonic with diminishing returns."""
    if access_count <= 0:
        return 0.0
    return access_count / (access_count + saturation)


def effective_importance(
    record: MemoryRecord, *, settings: ImportanceSettings
) -> float:
    """Base importance boosted toward 1.0 by usage; bounded [0, 1].

    ``base + max_boost * reinforcement * (1 - base)`` — the boost closes at
    most ``max_boost`` of the gap to 1.0, so ranking never saturates and base
    importance keeps mattering.
    """
    base = record.importance
    boost = settings.reinforcement_max_boost * reinforcement(
        record.access_count, saturation=settings.reinforcement_saturation
    )
    return min(1.0, base + boost * (1.0 - base))


def decay_score(
    record: MemoryRecord, now: datetime, *, settings: ImportanceSettings
) -> float:
    """Exponential decay since the memory was last touched; pinned exempt.

    Returns ``exp(-age / tau)`` where age counts from ``last_accessed_at``
    (or ``created_at`` if never recalled). Clamped to [0, 1] so clock skew
    cannot inflate scores.
    """
    if PINNED_TAG in record.tags:
        return 1.0
    reference = record.last_accessed_at or record.created_at
    age = max(0.0, (now - reference).total_seconds())
    tau = settings.decay_tau_days * 86400.0
    return math.exp(-age / tau)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_importance.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the full gate**

Run: `./.venv/Scripts/python.exe -m pytest && ./.venv/Scripts/python.exe -m ruff check . && ./.venv/Scripts/python.exe -m mypy`
Expected: all pass (coverage ≥ 85%), ruff clean, mypy clean.

- [ ] **Step 7: Commit**

```bash
git add src/memcore/config.py src/memcore/services/importance.py tests/unit/test_importance.py
git commit -m "feat(importance): reinforcement + decay scoring module (Phase 6)"
```

---

### Task 2: LLM-assessed importance at consolidation

**Files:**
- Modify: `src/memcore/services/memories.py` (`remember`/`correct` gain `confidence`)
- Modify: `src/memcore/services/consolidation.py` (prompt, `ExtractedFact`, `_apply_fact`)
- Test: `tests/unit/test_services.py`, `tests/unit/test_consolidation.py`

**Interfaces:**
- Consumes: nothing from Task 1 (independent of the scoring module).
- Produces:
  - `MemoryService.remember(..., confidence: float = 1.0, ...)` and `MemoryService.correct(..., confidence: float | None = None, ...)` — keyword-only, mapped straight onto `MemoryRecord.confidence`.
  - `ExtractedFact.importance: float` (default 0.5, ge=0, le=1) parsed from extraction JSON.
- Background: Phase 5 stuffed `fact.confidence` into `importance` as a shortcut. This task separates them: `importance` = LLM's long-term-value score, `confidence` = how directly the fact was stated. Existing tests that assert `record.importance == <confidence value>` on consolidated facts must be updated to assert against the extracted `importance` instead — that assertion change is the point of the task, not collateral damage.

- [ ] **Step 1: Write the failing test for `confidence` plumbing**

Add to `tests/unit/test_services.py`, using its existing `memory_setup` fixture (defined at `tests/unit/test_services.py:31-40`; it returns `tuple[MemoryService, RecallService, InMemoryVectorStore]`) and its module constants `TENANT, AGENT`:

```python
async def test_remember_stores_confidence(
    memory_setup: tuple[MemoryService, RecallService, InMemoryVectorStore],
) -> None:
    memories, _, _ = memory_setup
    record = await memories.remember(
        TENANT, AGENT, "Chinmay's dog is called Bruno.", confidence=0.8
    )
    assert record.confidence == 0.8


async def test_correct_updates_confidence(
    memory_setup: tuple[MemoryService, RecallService, InMemoryVectorStore],
) -> None:
    memories, _, _ = memory_setup
    original = await memories.remember(
        TENANT, AGENT, "Bruno is a beagle.", confidence=0.6
    )
    updated = await memories.correct(TENANT, original.id, confidence=0.9)
    assert updated.confidence == 0.9
    assert updated.supersedes == original.id
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_services.py -v -k confidence`
Expected: FAIL — `TypeError: remember() got an unexpected keyword argument 'confidence'`.

- [ ] **Step 3: Plumb `confidence` through `MemoryService`**

In `src/memcore/services/memories.py`:

`remember` — add the parameter and pass it to the record:

```python
    async def remember(
        self,
        tenant_id: str,
        agent_id: str,
        content: str,
        *,
        type: MemoryType = MemoryType.SEMANTIC,
        importance: float = 0.5,
        confidence: float = 1.0,
        tags: list[str] | None = None,
        source_refs: list[str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> MemoryRecord:
        if not content.strip():
            raise ValidationError("memory content must not be empty")
        record = MemoryRecord(
            tenant_id=tenant_id,
            agent_id=agent_id,
            type=type,
            content=content,
            importance=importance,
            confidence=confidence,
            tags=tags or [],
            source_refs=source_refs or [],
            metadata=dict(metadata or {}),
        )
```

`correct` — add the optional parameter and include it in `changes`:

```python
    async def correct(
        self,
        tenant_id: str,
        memory_id: str,
        *,
        content: str | None = None,
        importance: float | None = None,
        confidence: float | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> MemoryRecord:
        """Create a new version superseding ``memory_id`` (ADR-0007)."""
        old = await self._get_active(tenant_id, memory_id)
        changes: dict[str, object] = {}
        if content is not None:
            changes["content"] = content
        if importance is not None:
            changes["importance"] = importance
        if confidence is not None:
            changes["confidence"] = confidence
```

(rest of both methods unchanged)

- [ ] **Step 4: Run to verify the new tests pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_services.py -v`
Expected: all PASS.

- [ ] **Step 5: Write the failing consolidation test**

Add to `tests/unit/test_consolidation.py`, using its existing `_Env` class and `_extraction(**overrides)` helper (`tests/unit/test_consolidation.py:35-72`):

```python
async def test_fact_importance_and_confidence_stored_separately() -> None:
    env = _Env([
        _extraction(facts=[{
            "content": "Chinmay's home city is Pune.",
            "subject": "Chinmay", "predicate": "home city", "object": "Pune",
            "confidence": 0.9, "importance": 0.8,
        }])
    ])
    session_id = await env.session_with_turns("I live in Pune.")
    await env.service.consolidate_session(TENANT, session_id)

    semantic = await env.store.list_records(TENANT, AGENT, type=MemoryType.SEMANTIC)
    assert len(semantic) == 1
    assert semantic[0].importance == 0.8
    assert semantic[0].confidence == 0.9


async def test_fact_importance_defaults_when_llm_omits_it() -> None:
    env = _Env([
        _extraction(facts=[{
            "content": "Chinmay's home city is Pune.",
            "subject": "Chinmay", "predicate": "home city", "object": "Pune",
            "confidence": 0.9,
        }])
    ])
    session_id = await env.session_with_turns("I live in Pune.")
    await env.service.consolidate_session(TENANT, session_id)

    semantic = await env.store.list_records(TENANT, AGENT, type=MemoryType.SEMANTIC)
    assert semantic[0].importance == 0.5
    assert semantic[0].confidence == 0.9
```

- [ ] **Step 6: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_consolidation.py -v -k importance`
Expected: FAIL — record.importance equals the confidence value (old behaviour), and/or `ExtractedFact` has no `importance` field.

- [ ] **Step 7: Extend extraction prompt + models + `_apply_fact`**

In `src/memcore/services/consolidation.py`:

1. In `_SYSTEM_PROMPT`, change the fact line and add a rule:

```
  "facts": [
    {"content": "natural-language statement of a durable fact",
     "subject": "who/what it is about", "predicate": "the property/relation",
     "object": "the value", "confidence": 0.0-1.0, "importance": 0.0-1.0}
  ],
```

and append to the `Rules:` block:

```
- Importance scores long-term value for future sessions, independent of
  confidence: identity, stable preferences, goals and commitments are high
  (0.7-1.0); situational details are medium; trivia and transient states are
  low (0.0-0.3).
```

2. `ExtractedFact` gains:

```python
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
```

3. In `_apply_fact`, all three write paths separate the two signals:

- UPDATE path:

```python
                updated = await self._memories.correct(
                    tenant_id,
                    existing.id,
                    content=fact.content.strip(),
                    importance=fact.importance,
                    confidence=fact.confidence,
                    metadata=metadata,
                )
```

- needs_review path: replace `importance=fact.confidence,` with:

```python
                importance=fact.importance,
                confidence=fact.confidence,
```

- ADD path: replace `importance=fact.confidence,` with:

```python
            importance=fact.importance,
            confidence=fact.confidence,
```

4. Update the one existing assertion that encoded the old shortcut — `tests/unit/test_consolidation.py:101-106` (`test_add_facts_entities_relations_end_to_end`): the comment says "importance=confidence" and asserts `fact.importance == 0.9`. Its scripted fact has `confidence: 0.9` and no `importance` key, so it becomes:

```python
    # Fact record carries the SPO metadata; confidence and importance are
    # separate signals (importance defaults to 0.5 when the LLM omits it).
    assert fact.confidence == 0.9
    assert fact.importance == 0.5
```

Scan the rest of the file for any other `importance ==` assertions against a confidence value and update them the same way.

- [ ] **Step 8: Run consolidation + services tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_consolidation.py tests/unit/test_services.py -v`
Expected: all PASS.

- [ ] **Step 9: Full gate**

Run: `./.venv/Scripts/python.exe -m pytest && ./.venv/Scripts/python.exe -m ruff check . && ./.venv/Scripts/python.exe -m mypy`
Expected: clean.

- [ ] **Step 10: Commit**

```bash
git add src/memcore/services/memories.py src/memcore/services/consolidation.py tests/unit/test_services.py tests/unit/test_consolidation.py
git commit -m "feat(consolidation): LLM-assessed fact importance, confidence stored separately (Phase 6)"
```

---

### Task 3: Recall ranks with reinforced importance + calibration tests

**Files:**
- Modify: `src/memcore/services/recall.py`
- Modify: `src/memcore/api/app.py:101-108` (pass `importance_settings`)
- Test: `tests/unit/test_recall_engine.py`

**Interfaces:**
- Consumes (from Task 1): `ImportanceSettings`, `effective_importance(record, *, settings)`.
- Produces: `RecallService.__init__(..., importance_settings: ImportanceSettings | None = None)`. `ScoredMemory.importance` now carries the *effective* importance (base + usage boost) — the score-breakdown contract's meaning sharpens but its shape is unchanged.

- [ ] **Step 1: Write the failing calibration tests**

Add to `tests/unit/test_recall_engine.py`, using its existing `_Env` class (`tests/unit/test_recall_engine.py:32-84` — `env.seed(content, importance=...)` creates + indexes a record; `env.store` is the `InMemoryMemoryStore`, whose `reinforce` bumps `access_count`/`last_accessed_at`). Identical content gives identical vectors (deterministic `HashingEmbeddingProvider`) and identical lexical overlap, so relevance and (up to microseconds) recency cancel out — isolating the importance factor:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_recall_engine.py -v -k reinforc`
Expected: the outranking test FAILS (both records tie — raw importance ignores access_count). The neutralization tests may pass already; keep them as regression guards.

- [ ] **Step 3: Integrate effective importance into `RecallService`**

In `src/memcore/services/recall.py`:

1. Imports: add `ImportanceSettings` to the `memcore.config` import and add

```python
from memcore.services.importance import effective_importance
```

2. Constructor — add the keyword and store it:

```python
        settings: RetrievalSettings | None = None,
        importance_settings: ImportanceSettings | None = None,
    ) -> None:
        ...
        self._cfg = settings or RetrievalSettings()
        self._imp = importance_settings or ImportanceSettings()
```

3. In the scoring loop (`recall.py:152`), replace

```python
            importance = record.importance
```

with

```python
            importance = effective_importance(record, settings=self._imp)
```

4. Update the module docstring's step 3/5 lines to say importance is the usage-reinforced effective importance (retrieval strengthens memory — the loop is now closed).

- [ ] **Step 4: Wire settings in the app factory**

In `src/memcore/api/app.py`, the `RecallService(...)` construction gains one line:

```python
        recall=RecallService(
            store,
            vectors,
            embedder,
            collection=collection,
            graph=graph,
            settings=settings.retrieval,
            importance_settings=settings.importance,
        ),
```

- [ ] **Step 5: Run recall tests, then the full gate**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_recall_engine.py -v`
Expected: all PASS (including pre-existing ranking tests — the boost is bounded and zero for unaccessed records, so existing fixtures with `access_count == 0` are unaffected).

Then: `./.venv/Scripts/python.exe -m pytest && ./.venv/Scripts/python.exe -m ruff check . && ./.venv/Scripts/python.exe -m mypy`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/memcore/services/recall.py src/memcore/api/app.py tests/unit/test_recall_engine.py
git commit -m "feat(recall): rank with usage-reinforced effective importance (Phase 6)"
```

---

### Task 4: Docs, ADR, state — phase gate

**Files:**
- Create: `docs/adr/0015-importance-scoring.md`
- Create: `docs/design/phase-06.md`
- Modify: `docs/adr/README.md` (index line), `docs/design/roadmap.md` (Phase 6 → ✅ Complete, Phase 7 → ⏳ Next), `CHANGELOG.md`, `PROJECT_STATE.md`

**Interfaces:** none — documentation of Tasks 1–3 exactly as built.

- [ ] **Step 1: Write ADR-0015**

`docs/adr/0015-importance-scoring.md` (match the header/section style of `docs/adr/0013-retrieval-engine.md`):

- **Status:** accepted. **Context:** ranking treated importance as a static write-time value; Phase 5 stuffed extraction confidence into it.
- **Decision:** (1) base importance is write-time, LLM-assessed per fact (prompt-scored 0–1, default 0.5; confidence stored separately on the record); (2) usage reinforcement and time decay are pure read-time functions over raw stored signals (`access_count`, `last_accessed_at`, `created_at`, `tags`) in `services/importance.py` — formulas: `reinforcement = n/(n+s)`, `effective = base + max_boost·reinforcement·(1−base)`, `decay = exp(−age/τ)` from last touch; (3) `pinned` tag exempts a record from decay; (4) nothing derived is persisted in Phase 6 — Phase 7's prune job snapshots `decay_score` with the same functions (single source of the math).
- **Consequences:** ranking closes the retrieval-strengthens-memory loop with bounded, monotonic boosts; stored records stay raw/replayable; recomputation cost is O(candidates) arithmetic on the hot path (negligible); changing curve constants is a config change, not a migration.

Add to `docs/adr/README.md` index: `- [ADR-0015](0015-importance-scoring.md) — Importance scoring: LLM-assessed base + read-time reinforcement/decay, pinning`.

- [ ] **Step 2: Write the phase doc**

`docs/design/phase-06.md`, same structure as `phase-05.md` (Objective / Delivered / Gate): Delivered = `ImportanceSettings`; `services/importance.py` (three pure functions + `PINNED_TAG`); extraction prompt + `ExtractedFact.importance`; `remember`/`correct` `confidence` plumbing; recall effective-importance integration; calibration tests. Record the actual gate numbers from Step 4.

- [ ] **Step 3: Update CHANGELOG, roadmap, PROJECT_STATE**

`CHANGELOG.md` — new block above Phase 5:

```markdown
### Added — Phase 6: Importance scoring
- `services/importance.py`: pure reinforcement (`n/(n+s)` saturating curve),
  `effective_importance` (bounded boost toward 1.0), `decay_score`
  (exp(−age/τ) from last access; `pinned` tag exempt) — ADR-0015.
- Consolidation: extraction prompt scores per-fact `importance` (0–1,
  long-term value, independent of confidence); fact `confidence` now stored
  on `MemoryRecord.confidence` instead of overloading `importance`.
- `MemoryService.remember`/`correct` accept `confidence`.
- Recall ranks with usage-reinforced effective importance
  (`ImportanceSettings` wired via `Settings.importance`).
```

`docs/design/roadmap.md`: Phase 6 → `✅ Complete`, Phase 7 → `⏳ Next`.

`PROJECT_STATE.md`: current position → Phase 6 complete / Phase 7 (decay & pruning) not started, awaiting approval; record the Phase 6 gate numbers; next tasks → Phase 7 outline (decay job persisting `decay_score` snapshots via `services/importance.py`, prune policy, retention); open decision → approve Phase 7 start.

- [ ] **Step 4: Run the phase gate and record numbers**

Run: `./.venv/Scripts/python.exe -m pytest` (record pass count + coverage %), `./.venv/Scripts/python.exe -m ruff check .`, `./.venv/Scripts/python.exe -m mypy`
Expected: all clean, coverage ≥ 85%. Copy the real numbers into `phase-06.md` and `PROJECT_STATE.md`.

- [ ] **Step 5: Phase commit**

```bash
git add docs/adr/0015-importance-scoring.md docs/adr/README.md docs/design/phase-06.md docs/design/roadmap.md CHANGELOG.md PROJECT_STATE.md
git commit -m "docs: Phase 6 gate — importance scoring (ADR-0015, phase doc, state)"
```

Then STOP: per the phase gate, WAIT for user approval before any Phase 7 work.
