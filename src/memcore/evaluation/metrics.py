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
