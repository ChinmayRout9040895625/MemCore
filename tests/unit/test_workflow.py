"""Workflow engine tests: immediate engine semantics + Celery adapter mapping."""

from __future__ import annotations

from typing import Any

import pytest

from memcore.adapters.celery.workflow import _STATE_MAP, CeleryWorkflowEngine
from memcore.adapters.inmemory import ImmediateWorkflowEngine
from memcore.exceptions import ValidationError
from memcore.ports.workflow_engine import JobState


async def test_immediate_engine_runs_and_records_success() -> None:
    engine = ImmediateWorkflowEngine()
    ran: list[dict[str, Any]] = []

    async def handler(payload: dict[str, Any]) -> None:
        ran.append(payload)

    engine.register("task", handler)
    handle = await engine.enqueue("task", {"x": 1})
    assert handle.state is JobState.SUCCEEDED
    assert ran == [{"x": 1}]
    assert (await engine.status(handle.id)).state is JobState.SUCCEEDED


async def test_immediate_engine_captures_failure() -> None:
    engine = ImmediateWorkflowEngine()

    async def boom(payload: dict[str, Any]) -> None:
        raise RuntimeError("nope")

    engine.register("task", boom)
    handle = await engine.enqueue("task", {})
    assert handle.state is JobState.FAILED


async def test_immediate_engine_unknown_task_and_job() -> None:
    engine = ImmediateWorkflowEngine()
    with pytest.raises(ValidationError):
        await engine.enqueue("nope", {})
    assert (await engine.status("unknown")).state is JobState.PENDING


def test_celery_worker_task_runs_pipeline() -> None:
    from memcore.services.consolidation import ConsolidationReport
    from memcore.workers import celery_app

    class _FakeService:
        async def consolidate_session(
            self, tenant_id: str, session_id: str
        ) -> ConsolidationReport:
            return ConsolidationReport(session_id=session_id, added=2)

    celery_app._cache["service"] = _FakeService()
    try:
        result = celery_app.consolidate_session.run(
            tenant_id="t1", session_id="s1"
        )
        assert result["added"] == 2 and result["session_id"] == "s1"
    finally:
        celery_app._cache.clear()


def test_celery_engine_constructs_and_maps_states() -> None:
    # Construction needs no running broker (connections are lazy).
    engine = CeleryWorkflowEngine("redis://localhost:6379/1")
    assert engine is not None
    assert _STATE_MAP["SUCCESS"] is JobState.SUCCEEDED
    assert _STATE_MAP["FAILURE"] is JobState.FAILED
    assert _STATE_MAP["STARTED"] is JobState.RUNNING
    assert _STATE_MAP["PENDING"] is JobState.PENDING
    assert _STATE_MAP["REVOKED"] is JobState.FAILED
