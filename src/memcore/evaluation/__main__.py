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
    for a, b in zip(plain, swept, strict=True):
        lines.append(f"{a.age_days:>9.0f} {a.recall_at_5:>9.3f} {b.recall_at_5:>12.3f}")
    return "\n".join(lines)


def main() -> None:
    print(asyncio.run(render_report()))


if __name__ == "__main__":
    main()
