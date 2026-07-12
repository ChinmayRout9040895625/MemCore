"""Regression tests for the Celery worker's event-loop handling.

The worker caches an async service graph (incl. an asyncpg connection pool)
once per process, but used to run every task via ``asyncio.run()`` — which
creates and tears down a *new* event loop on each call. After the first task,
the cached pool was bound to a now-closed loop, and the second task crashed
with ``RuntimeError: ... got Future ... attached to a different loop``.

The fix runs every task on one persistent loop (``_get_loop()``). These tests
lock that guarantee in: two sequential tasks must share a loop, and a cached
loop-bound async resource must survive into the second task.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("celery")

from memcore.workers import celery_app


def teardown_function() -> None:
    """Don't leak the module-level loop between tests."""
    loop = celery_app._cache.pop("loop", None)
    if loop is not None and not loop.is_closed():
        loop.close()


def test_get_loop_is_persistent() -> None:
    loop1 = celery_app._get_loop()
    loop2 = celery_app._get_loop()
    assert loop1 is loop2
    assert not loop1.is_closed()


def test_get_loop_recreates_after_close() -> None:
    loop1 = celery_app._get_loop()
    loop1.close()
    loop2 = celery_app._get_loop()
    assert loop2 is not loop1
    assert not loop2.is_closed()


def test_sequential_tasks_share_the_loop() -> None:
    seen: list[asyncio.AbstractEventLoop] = []

    async def capture() -> None:
        seen.append(asyncio.get_running_loop())

    # Two task invocations, the way the worker runs them.
    celery_app._get_loop().run_until_complete(capture())
    celery_app._get_loop().run_until_complete(capture())

    assert seen[0] is seen[1]


def test_cached_loop_bound_resource_survives_second_task() -> None:
    """Reproduces the real failure shape (a loop-bound Future).

    An ``asyncio.Future`` is hard-bound to the loop that created it — the same
    class of resource asyncpg's pool holds. It is created in the first task
    and reused in the second. On one shared loop this works; under a fresh
    loop per task (the old ``asyncio.run`` bug) the second task raises
    "The future belongs to a different loop" — the production crash's shape.
    """
    cache: dict[str, asyncio.Future[str]] = {}
    loop = celery_app._get_loop()

    async def create_future() -> None:
        cache["fut"] = asyncio.get_running_loop().create_future()

    loop.run_until_complete(create_future())  # task 1: future binds to loop
    loop.call_soon(cache["fut"].set_result, "ok")
    result = loop.run_until_complete(cache["fut"])  # task 2: reuse it
    assert result == "ok"
