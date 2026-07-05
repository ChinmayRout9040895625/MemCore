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
    """Age point in longitudinal curve.

    mean_final embeds real recency factors and may vary across runs at ~1e-9;
    the reproducibility guarantee covers rank-derived metrics only.
    """
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
            # k covers pair set; boosts >> pairs, so reinforcing all is fine.
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
