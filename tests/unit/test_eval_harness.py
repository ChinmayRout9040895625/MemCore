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
