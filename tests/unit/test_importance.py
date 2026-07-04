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
