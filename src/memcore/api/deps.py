"""Dependency wiring: application state and tenant authentication."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyHeader

from memcore.exceptions import TenantIsolationError
from memcore.ports.embedding_provider import EmbeddingProvider
from memcore.ports.graph_store import GraphStore
from memcore.ports.memory_store import MemoryStore
from memcore.ports.object_store import ObjectStore
from memcore.ports.vector_store import VectorStore
from memcore.ports.workflow_engine import WorkflowEngine
from memcore.ports.working_memory import WorkingMemory
from memcore.services import (
    ConsolidationService,
    MemoryService,
    RecallService,
    SessionService,
)


@dataclass
class AppState:
    """Everything the routes need, wired once at startup (or by tests)."""

    store: MemoryStore
    working: WorkingMemory
    objects: ObjectStore
    vectors: VectorStore
    graph: GraphStore
    embedder: EmbeddingProvider
    sessions: SessionService
    memories: MemoryService
    recall: RecallService
    consolidation: ConsolidationService
    workflow: WorkflowEngine
    api_keys: dict[str, str]  # api key -> tenant_id


def get_state(request: Request) -> AppState:
    state: AppState = request.app.state.memcore
    return state


_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_tenant(
    state: Annotated[AppState, Depends(get_state)],
    api_key: Annotated[str | None, Security(_api_key_header)],
) -> str:
    """Resolve the calling tenant from the API key. 401 on failure."""
    if api_key is None or api_key not in state.api_keys:
        # Raised as a domain error; the app maps it to a 401 problem response.
        raise TenantIsolationError("missing or invalid API key")
    return state.api_keys[api_key]


StateDep = Annotated[AppState, Depends(get_state)]
TenantDep = Annotated[str, Depends(get_tenant)]
