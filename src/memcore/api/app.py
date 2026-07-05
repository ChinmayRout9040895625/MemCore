"""FastAPI application factory.

``create_app`` accepts a prebuilt :class:`AppState` (tests, embedded use) or
builds one from :class:`Settings` via the adapter factories. Domain exceptions
are mapped to RFC-7807 problem+json responses.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from memcore.adapters.factory import (
    build_embedding_provider,
    build_graph_store,
    build_llm_provider,
    build_memory_store,
    build_vector_store,
    build_workflow_engine,
    build_working_memory,
)
from memcore.adapters.inmemory import ImmediateWorkflowEngine, InMemoryObjectStore
from memcore.api.deps import AppState
from memcore.api.middleware import ObservabilityMiddleware
from memcore.api.routes import health_router, router
from memcore.config import Settings, load_settings
from memcore.exceptions import (
    ConfigurationError,
    ConflictError,
    MemCoreError,
    NotFoundError,
    StorageError,
    TenantIsolationError,
    ValidationError,
)
from memcore.logging import configure_logging, get_logger
from memcore.services import (
    ConsolidationService,
    DecayService,
    MemoryService,
    RecallService,
    SessionService,
)

logger = get_logger("api")

_STATUS_BY_ERROR: list[tuple[type[MemCoreError], int]] = [
    (TenantIsolationError, 401),
    (NotFoundError, 404),
    (ConflictError, 409),
    (ValidationError, 422),
    (ConfigurationError, 500),
    (StorageError, 503),
]


def build_state(settings: Settings) -> AppState:
    store = build_memory_store(settings)
    working = build_working_memory(settings)
    vectors = build_vector_store(settings)
    graph = build_graph_store(settings)
    embedder = build_embedding_provider(settings)
    # S3-compatible object store adapter arrives with the deployment phase.
    objects = InMemoryObjectStore()

    collection = f"{settings.vector.collection_prefix}_{embedder.dimension}"

    api_keys = dict(settings.api.keys)
    if not api_keys and settings.env == "local":
        api_keys["dev-key"] = "local"
        logger.warning(
            "no API keys configured; injected dev-key -> 'local' (env=local only)"
        )

    memories = MemoryService(store, vectors, embedder, collection=collection)
    consolidation = ConsolidationService(
        store, working, memories, vectors, graph,
        build_llm_provider(settings),
        settings=settings.consolidation,
    )
    decay = DecayService(
        store, memories,
        importance=settings.importance,
        retention=settings.retention,
    )
    workflow = build_workflow_engine(settings)
    if isinstance(workflow, ImmediateWorkflowEngine):

        async def _consolidate(payload: dict[str, object]) -> None:
            await consolidation.consolidate_session(
                str(payload["tenant_id"]), str(payload["session_id"])
            )

        workflow.register("consolidate_session", _consolidate)

        async def _decay(payload: dict[str, object]) -> None:
            await decay.sweep(str(payload["tenant_id"]))

        workflow.register("decay_tenant", _decay)

    return AppState(
        store=store,
        working=working,
        objects=objects,
        vectors=vectors,
        graph=graph,
        embedder=embedder,
        sessions=SessionService(store, working, objects),
        memories=memories,
        recall=RecallService(
            store,
            vectors,
            embedder,
            collection=collection,
            graph=graph,
            settings=settings.retrieval,
            importance_settings=settings.importance,
        ),
        consolidation=consolidation,
        workflow=workflow,
        api_keys=api_keys,
    )


def create_app(
    settings: Settings | None = None, *, state: AppState | None = None
) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)
    app_state = state or build_state(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        init = getattr(app_state.store, "init", None)
        if callable(init):
            await init()
        await app_state.memories.ensure_ready()
        yield

    app = FastAPI(
        title="MemCore",
        version="0.1.0",
        description="Long-term memory infrastructure for AI agents.",
        lifespan=lifespan,
    )
    app.state.memcore = app_state
    app.state.memcore_probes = {
        "store": app_state.store,
        "vectors": app_state.vectors,
        "graph": app_state.graph,
        "working": app_state.working,
    }
    app.add_middleware(ObservabilityMiddleware)
    app.include_router(health_router)
    app.include_router(router)

    @app.exception_handler(MemCoreError)
    async def memcore_error_handler(request: Request, exc: MemCoreError) -> JSONResponse:
        status = 500
        for error_type, code in _STATUS_BY_ERROR:
            if isinstance(exc, error_type):
                status = code
                break
        # RFC-7807 problem+json.
        return JSONResponse(
            status_code=status,
            media_type="application/problem+json",
            content={
                "type": f"https://memcore.dev/errors/{type(exc).__name__}",
                "title": type(exc).__name__,
                "status": status,
                "detail": str(exc),
                "instance": str(request.url.path),
            },
        )

    return app
