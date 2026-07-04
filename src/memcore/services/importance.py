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
    ``saturation`` accesses, asymptotically 1. Michaelis-Menten form keeps it
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
