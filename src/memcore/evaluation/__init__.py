"""Offline evaluation framework (Phase 8, ADR-0017).

Deterministic, in-process measurement of retrieval quality: pure metric
primitives, a synthetic token-overlap dataset, a harness that runs named
scoring configurations against a fresh in-memory stack, and scenario runners
for the reinforcement ablation and the longitudinal decay curve.

This package is a consumer/composition layer (like ``memcore.api``): it may
build in-memory adapters directly, and nothing inside ``services``/``domain``
/``ports``/``adapters`` may import it.
"""

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
