"""Immediate (in-process) :class:`WorkflowEngine`.

Default for local/dev/tests: registered handlers run inline at ``enqueue``
time, with success/failure captured in the job table. Celery provides the
distributed implementation behind the same port (ADR-0004).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from memcore.domain.models import new_id
from memcore.exceptions import ValidationError
from memcore.logging import get_logger
from memcore.ports.workflow_engine import JobHandle, JobState, WorkflowEngine

logger = get_logger("workflow.immediate")

Handler = Callable[[dict[str, Any]], Awaitable[Any]]


class ImmediateWorkflowEngine(WorkflowEngine):
    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}
        self._jobs: dict[str, JobHandle] = {}

    def register(self, task: str, handler: Handler) -> None:
        self._handlers[task] = handler

    async def enqueue(self, task: str, payload: dict[str, Any]) -> JobHandle:
        handler = self._handlers.get(task)
        if handler is None:
            raise ValidationError(f"no handler registered for task {task!r}")
        job_id = new_id()
        try:
            await handler(payload)
            handle = JobHandle(id=job_id, state=JobState.SUCCEEDED)
        except Exception:
            logger.exception("job failed", extra={"task": task, "job_id": job_id})
            handle = JobHandle(id=job_id, state=JobState.FAILED)
        self._jobs[job_id] = handle
        return handle

    async def status(self, job_id: str) -> JobHandle:
        handle = self._jobs.get(job_id)
        if handle is None:
            return JobHandle(id=job_id, state=JobState.PENDING)
        return handle
