"""Phase 8 — ablation + longitudinal scenarios (deterministic outcomes)."""

from itertools import pairwise

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
    assert all(later <= earlier for earlier, later in pairwise(finals))
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
