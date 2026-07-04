"""Celery worker application.

Run with::

    celery -A memcore.workers.celery_app worker --loglevel=info

Tasks are thin shells: they build the service graph from ``Settings`` (once per
worker process) and run the async pipeline. Task names match what
:class:`CeleryWorkflowEngine` enqueues (``memcore.<task>``).
"""

from __future__ import annotations

import asyncio
from typing import Any

from celery import Celery

from memcore.config import Settings, load_settings
from memcore.logging import configure_logging, get_logger

logger = get_logger("workers")

_settings = load_settings()
configure_logging(_settings.log_level, json_output=_settings.log_json)

app = Celery(
    "memcore",
    broker=_settings.scheduler.broker_url,
    backend=_settings.scheduler.broker_url,
)
app.conf.task_serializer = "json"
app.conf.result_serializer = "json"
app.conf.accept_content = ["json"]

_cache: dict[str, Any] = {}


def _get_consolidation(settings: Settings) -> Any:
    """Build (once per worker process) the consolidation service graph."""
    if "service" not in _cache:
        from memcore.adapters.factory import (
            build_embedding_provider,
            build_graph_store,
            build_llm_provider,
            build_memory_store,
            build_vector_store,
            build_working_memory,
        )
        from memcore.services.consolidation import ConsolidationService
        from memcore.services.memories import MemoryService

        store = build_memory_store(settings)
        working = build_working_memory(settings)
        vectors = build_vector_store(settings)
        graph = build_graph_store(settings)
        embedder = build_embedding_provider(settings)
        llm = build_llm_provider(settings)
        collection = f"{settings.vector.collection_prefix}_{embedder.dimension}"
        memories = MemoryService(store, vectors, embedder, collection=collection)
        _cache["service"] = ConsolidationService(
            store, working, memories, vectors, graph, llm,
            settings=settings.consolidation,
        )
    return _cache["service"]


@app.task(name="memcore.consolidate_session")
def consolidate_session(tenant_id: str, session_id: str) -> dict[str, Any]:
    service = _get_consolidation(_settings)
    report = asyncio.run(service.consolidate_session(tenant_id, session_id))
    logger.info("consolidated", extra={"session_id": session_id})
    return report.model_dump()


def _get_decay(settings: Settings) -> Any:
    """Build (once per worker process) the decay service graph."""
    if "decay" not in _cache:
        from memcore.adapters.factory import (
            build_embedding_provider,
            build_memory_store,
            build_vector_store,
        )
        from memcore.services.decay import DecayService
        from memcore.services.memories import MemoryService

        store = build_memory_store(settings)
        vectors = build_vector_store(settings)
        embedder = build_embedding_provider(settings)
        collection = f"{settings.vector.collection_prefix}_{embedder.dimension}"
        memories = MemoryService(store, vectors, embedder, collection=collection)
        _cache["decay"] = DecayService(
            store, memories,
            importance=settings.importance,
            retention=settings.retention,
        )
    return _cache["decay"]


@app.task(name="memcore.decay_tenant")
def decay_tenant(tenant_id: str) -> dict[str, Any]:
    service = _get_decay(_settings)
    report = asyncio.run(service.sweep(tenant_id))
    logger.info("decay swept", extra={"tenant_id": tenant_id})
    return report.model_dump()
