"""Celery-backed :class:`WorkflowEngine` (ADR-0004).

The API process uses this to enqueue jobs by name (``send_task``) and poll
state (``AsyncResult``); it never imports task code. Workers run separately via
``celery -A memcore.workers.celery_app worker``. Celery calls are synchronous,
so they are pushed to a thread to keep the event loop free.
"""

from __future__ import annotations

import asyncio
from typing import Any

from memcore.exceptions import ConfigurationError, StorageError
from memcore.ports.workflow_engine import JobHandle, JobState, WorkflowEngine

_STATE_MAP = {
    "PENDING": JobState.PENDING,
    "RECEIVED": JobState.PENDING,
    "RETRY": JobState.PENDING,
    "STARTED": JobState.RUNNING,
    "SUCCESS": JobState.SUCCEEDED,
    "FAILURE": JobState.FAILED,
    "REVOKED": JobState.FAILED,
}


class CeleryWorkflowEngine(WorkflowEngine):
    def __init__(self, broker_url: str, *, task_prefix: str = "memcore") -> None:
        try:
            from celery import Celery
        except ImportError as exc:  # pragma: no cover - requires the extra
            raise ConfigurationError(
                "celery is not installed; install the scheduler extra: "
                "pip install 'memcore[scheduler]'"
            ) from exc
        # The broker doubles as the result backend (Redis) so ``status`` works.
        self._app = Celery("memcore", broker=broker_url, backend=broker_url)
        self._prefix = task_prefix

    async def enqueue(self, task: str, payload: dict[str, Any]) -> JobHandle:
        def _send() -> str:
            result = self._app.send_task(f"{self._prefix}.{task}", kwargs=payload)
            return str(result.id)

        try:
            job_id = await asyncio.to_thread(_send)
        except Exception as exc:
            raise StorageError(f"celery enqueue failed: {exc}") from exc
        return JobHandle(id=job_id, state=JobState.PENDING)

    async def status(self, job_id: str) -> JobHandle:
        def _state() -> str:
            return str(self._app.AsyncResult(job_id).state)

        try:
            state = await asyncio.to_thread(_state)
        except Exception as exc:
            raise StorageError(f"celery status failed: {exc}") from exc
        return JobHandle(id=job_id, state=_STATE_MAP.get(state, JobState.PENDING))
