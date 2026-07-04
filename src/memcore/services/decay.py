"""DecayService — snapshot decay scores and prune what has faded (Phase 7).

Design (ADR-0016):

* The math lives in :mod:`memcore.services.importance` and is imported, never
  re-derived (ADR-0015 point 4). This service only orchestrates: score every
  ACTIVE record in the tenant, persist the snapshots via ``set_decay`` (an
  in-place signal update, like ``reinforce`` — no new versions), then prune.
* Prune policy, all rails must agree: score below ``prune_threshold`` AND not
  pinned AND older than ``min_age_days``. Pruning is a *soft* delete through
  :class:`MemoryService` (audit + vector-index removal in one place); hard
  deletion remains a manual/GDPR operation.
* One PRUNE audit event summarizes each sweep. Re-running immediately is
  idempotent: soft-deleted records are no longer ACTIVE, so a second sweep
  prunes nothing.
"""

from __future__ import annotations

from pydantic import BaseModel

from memcore.config import ImportanceSettings, RetentionSettings
from memcore.domain.enums import AuditAction, MemoryStatus
from memcore.domain.models import AuditEvent, MemoryRecord, utcnow
from memcore.exceptions import MemCoreError
from memcore.logging import get_logger
from memcore.ports.memory_store import MemoryStore
from memcore.services.importance import PINNED_TAG, decay_score
from memcore.services.memories import MemoryService

logger = get_logger("decay")


class DecayReport(BaseModel):
    tenant_id: str
    scanned: int = 0
    snapshotted: int = 0
    pruned: int = 0
    failed: int = 0
    skipped_pinned: int = 0


class DecayService:
    def __init__(
        self,
        store: MemoryStore,
        memories: MemoryService,
        *,
        importance: ImportanceSettings | None = None,
        retention: RetentionSettings | None = None,
    ) -> None:
        self._store = store
        self._memories = memories
        self._importance = importance or ImportanceSettings()
        self._retention = retention or RetentionSettings()

    async def sweep(self, tenant_id: str) -> DecayReport:
        now = utcnow()
        records = await self._store.list_records(
            tenant_id, None,
            status=MemoryStatus.ACTIVE,
            limit=self._retention.scan_limit,
            oldest_first=True,
        )
        report = DecayReport(tenant_id=tenant_id, scanned=len(records))

        scores: dict[str, float] = {}
        candidates: list[tuple[MemoryRecord, float]] = []
        for record in records:
            score = decay_score(record, now, settings=self._importance)
            scores[record.id] = score
            if PINNED_TAG in record.tags:
                report.skipped_pinned += 1
                continue
            age_days = (now - record.created_at).total_seconds() / 86400.0
            if (
                score < self._retention.prune_threshold
                and age_days >= self._retention.min_age_days
            ):
                candidates.append((record, score))

        if scores:
            await self._store.set_decay(tenant_id, scores)
            report.snapshotted = len(scores)

        for record, score in candidates:
            try:
                await self._memories.forget(
                    tenant_id, record.id, mode="soft",
                    reason=f"decay prune (score={score:.3f})",
                )
                report.pruned += 1
            except MemCoreError:
                report.failed += 1
                logger.warning("prune failed", extra={"memory_id": record.id})

        await self._store.add_audit(
            AuditEvent(
                tenant_id=tenant_id,
                actor="decay",
                action=AuditAction.PRUNE,
                reason=(
                    f"scanned={report.scanned} snapshotted={report.snapshotted} "
                    f"pruned={report.pruned} failed={report.failed} "
                    f"pinned={report.skipped_pinned}"
                ),
                metadata={
                    "scanned": report.scanned,
                    "snapshotted": report.snapshotted,
                    "pruned": report.pruned,
                    "failed": report.failed,
                    "pinned": report.skipped_pinned,
                },
            )
        )
        logger.info("decay sweep", extra={"tenant_id": tenant_id,
                                          "pruned": report.pruned})
        return report
