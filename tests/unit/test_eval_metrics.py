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

    def test_non_positive_k_is_zero(self) -> None:
        assert recall_at_k({"a"}, ["a"], k=0) == 0.0
        assert recall_at_k({"a"}, ["a"], k=-1) == 0.0


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

    def test_duplicate_ids_gain_once_and_stay_bounded(self) -> None:
        assert ndcg_at_k({"a"}, ["a", "a", "a"], k=3) == pytest.approx(1.0)

    def test_non_positive_k_is_zero(self) -> None:
        assert ndcg_at_k({"a"}, ["a"], k=0) == 0.0
        assert ndcg_at_k({"a"}, ["a"], k=-1) == 0.0
