"""Context assembly: turn recall results into a prompt-ready block.

Dedupes near-identical memories, orders by score, annotates provenance (type +
date + score), and packs to a token budget (~4 chars/token heuristic until real
tokenization arrives with the SDK phase).
"""

from __future__ import annotations

from memcore.domain.models import ScoredMemory


def _norm(content: str) -> str:
    return " ".join(content.lower().split())


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (chars/4), biased slightly high for safety."""
    return max(1, len(text) // 4 + 1)


def assemble_context(
    results: list[ScoredMemory], *, token_budget: int = 2000
) -> tuple[str, int]:
    """Build a memory-context block from ranked results.

    Returns ``(context, token_estimate)``. Results are assumed score-ordered;
    duplicates (same normalized content) are dropped, and packing stops when
    the budget would be exceeded.
    """
    lines: list[str] = []
    seen: set[str] = set()
    used = 0

    for item in results:
        normalized = _norm(item.memory.content)
        if normalized in seen:
            continue
        line = (
            f"- [{item.memory.type.value} | "
            f"{item.memory.created_at.date().isoformat()} | "
            f"score {item.final:.2f}] {item.memory.content.strip()}"
        )
        cost = estimate_tokens(line)
        if used + cost > token_budget:
            break
        seen.add(normalized)
        lines.append(line)
        used += cost

    if not lines:
        return "", 0
    header = "Relevant memories (most relevant first):"
    block = header + "\n" + "\n".join(lines)
    return block, estimate_tokens(block)
