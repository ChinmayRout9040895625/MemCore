"""v1 API routes. Thin: parse → service call → shape response."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from memcore import __version__
from memcore.api.deps import StateDep, TenantDep
from memcore.api.schemas import (
    AppendMessageRequest,
    ConsolidateRequest,
    CorrectMemoryRequest,
    HealthResponse,
    JobResponse,
    MemoryResponse,
    OpenSessionRequest,
    RecallRequest,
    RecallResponse,
    RememberRequest,
    SessionResponse,
    VersionsResponse,
)
from memcore.exceptions import ConfigurationError
from memcore.observability import metrics as obs_metrics
from memcore.services import ScoreWeights, assemble_context

router = APIRouter(prefix="/v1")
health_router = APIRouter()


@health_router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)


@health_router.get("/metrics", include_in_schema=False)
async def metrics_endpoint() -> Response:
    try:
        payload, content_type = obs_metrics.render()
    except ConfigurationError as exc:
        return JSONResponse(
            status_code=501,
            media_type="application/problem+json",
            content={
                "type": "https://memcore.dev/errors/ConfigurationError",
                "title": "ConfigurationError",
                "status": 501,
                "detail": str(exc),
                "instance": "/metrics",
            },
        )
    return Response(content=payload, media_type=content_type)


@health_router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    components: dict[str, str] = {}
    degraded = False
    for name, component in request.app.state.memcore_probes.items():
        ping = getattr(component, "ping", None)
        if not callable(ping):
            components[name] = "ok"
            continue
        try:
            await ping()
            components[name] = "ok"
        except Exception as exc:  # any component failure means "not ready"
            components[name] = f"error: {exc}"
            degraded = True
    status = 503 if degraded else 200
    return JSONResponse(
        status_code=status,
        content={
            "status": "degraded" if degraded else "ready",
            "components": components,
        },
    )


# -- sessions -----------------------------------------------------------------
@router.post("/sessions", response_model=SessionResponse, status_code=201)
async def open_session(
    body: OpenSessionRequest, state: StateDep, tenant: TenantDep
) -> SessionResponse:
    session = await state.sessions.open(tenant, body.agent_id)
    return SessionResponse(session=session)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str, state: StateDep, tenant: TenantDep
) -> SessionResponse:
    return SessionResponse(session=await state.sessions.get(tenant, session_id))


@router.post(
    "/sessions/{session_id}/messages", response_model=SessionResponse, status_code=202
)
async def append_message(
    session_id: str, body: AppendMessageRequest, state: StateDep, tenant: TenantDep
) -> SessionResponse:
    session = await state.sessions.append(
        tenant, session_id, role=body.role, content=body.content, metadata=body.metadata
    )
    return SessionResponse(session=session)


@router.post("/sessions/{session_id}/close", response_model=SessionResponse)
async def close_session(
    session_id: str, state: StateDep, tenant: TenantDep
) -> SessionResponse:
    session = await state.sessions.close(tenant, session_id)
    # Closing a session triggers async consolidation (ADR-0001).
    await state.workflow.enqueue(
        "consolidate_session", {"tenant_id": tenant, "session_id": session_id}
    )
    return SessionResponse(session=session)


# -- memories -------------------------------------------------------------------
@router.post("/memories", response_model=MemoryResponse, status_code=201)
async def remember(
    body: RememberRequest, state: StateDep, tenant: TenantDep
) -> MemoryResponse:
    record = await state.memories.remember(
        tenant,
        body.agent_id,
        body.content,
        type=body.type,
        importance=body.importance,
        confidence=body.confidence,
        tags=body.tags,
    )
    return MemoryResponse(memory=record)


@router.get("/memories/{memory_id}", response_model=MemoryResponse)
async def get_memory(
    memory_id: str, state: StateDep, tenant: TenantDep
) -> MemoryResponse:
    return MemoryResponse(memory=await state.memories.get(tenant, memory_id))


@router.get("/memories/{memory_id}/versions", response_model=VersionsResponse)
async def get_versions(
    memory_id: str, state: StateDep, tenant: TenantDep
) -> VersionsResponse:
    return VersionsResponse(versions=await state.memories.versions(tenant, memory_id))


@router.patch("/memories/{memory_id}", response_model=MemoryResponse)
async def correct_memory(
    memory_id: str, body: CorrectMemoryRequest, state: StateDep, tenant: TenantDep
) -> MemoryResponse:
    record = await state.memories.correct(
        tenant,
        memory_id,
        content=body.content,
        importance=body.importance,
        confidence=body.confidence,
        tags=body.tags,
    )
    return MemoryResponse(memory=record)


@router.delete("/memories/{memory_id}", status_code=204)
async def forget_memory(
    memory_id: str,
    state: StateDep,
    tenant: TenantDep,
    mode: str = Query(default="soft", pattern="^(soft|hard)$"),
) -> None:
    await state.memories.forget(tenant, memory_id, mode=mode)


# -- consolidation ------------------------------------------------------------
@router.post("/consolidate", response_model=JobResponse, status_code=202)
async def consolidate(
    body: ConsolidateRequest, state: StateDep, tenant: TenantDep
) -> JobResponse:
    # Verify the session belongs to this tenant before enqueueing.
    await state.sessions.get(tenant, body.session_id)
    handle = await state.workflow.enqueue(
        "consolidate_session", {"tenant_id": tenant, "session_id": body.session_id}
    )
    return JobResponse(job_id=handle.id, state=handle.state.value)


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def job_status(job_id: str, state: StateDep, tenant: TenantDep) -> JobResponse:
    handle = await state.workflow.status(job_id)
    return JobResponse(job_id=handle.id, state=handle.state.value)


# -- decay ---------------------------------------------------------------------
@router.post("/decay", response_model=JobResponse, status_code=202)
async def run_decay(state: StateDep, tenant: TenantDep) -> JobResponse:
    """Enqueue a decay sweep for the calling tenant (snapshot + prune)."""
    handle = await state.workflow.enqueue("decay_tenant", {"tenant_id": tenant})
    return JobResponse(job_id=handle.id, state=handle.state.value)


# -- recall -----------------------------------------------------------------
@router.post("/recall", response_model=RecallResponse)
async def recall(
    body: RecallRequest, state: StateDep, tenant: TenantDep
) -> RecallResponse:
    weights = None
    if body.weights is not None:
        weights = ScoreWeights(
            relevance=body.weights.relevance,
            recency=body.weights.recency,
            importance=body.weights.importance,
        )
    results = await state.recall.recall(
        tenant,
        body.agent_id,
        body.query,
        k=body.k,
        types=body.types,
        weights=weights,
        graph_expand=body.graph_expand,
        rerank=body.rerank,
    )
    context: str | None = None
    context_tokens: int | None = None
    if body.as_context:
        context, context_tokens = assemble_context(results)
    return RecallResponse(
        results=results, context=context, context_tokens=context_tokens
    )
