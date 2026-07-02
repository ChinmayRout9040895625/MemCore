"""WorkflowEngine port — schedules async pipelines (consolidation, decay).

Default adapter: Celery (ADR-004). Temporal is an approved *future* backend and
must slot in behind this interface without touching pipeline logic. Keeping the
surface minimal (enqueue + status) is what makes that swap cheap.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class JobState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class JobHandle:
    """An opaque reference to an enqueued job."""

    id: str
    state: JobState


class WorkflowEngine(ABC):
    """Port for enqueuing and tracking background jobs."""

    @abstractmethod
    async def enqueue(self, task: str, payload: dict[str, Any]) -> JobHandle:
        """Enqueue ``task`` with ``payload``; return a handle immediately."""

    @abstractmethod
    async def status(self, job_id: str) -> JobHandle:
        """Return the current state of a previously enqueued job."""
