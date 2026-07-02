"""Request/response schemas for the v1 API.

Domain models (``MemoryRecord``, ``Session``, ``ScoredMemory``) are pydantic
and are returned directly as response bodies in v1; these schemas cover the
request side and thin response wrappers.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from memcore.domain.enums import MemoryType
from memcore.domain.models import MemoryRecord, ScoredMemory, Session


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OpenSessionRequest(_Req):
    agent_id: str = Field(min_length=1, max_length=64)


class AppendMessageRequest(_Req):
    role: str = Field(min_length=1, max_length=32)
    content: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RememberRequest(_Req):
    agent_id: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1)
    type: MemoryType = MemoryType.SEMANTIC
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)


class CorrectMemoryRequest(_Req):
    content: str | None = None
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    tags: list[str] | None = None


class RecallWeights(_Req):
    """Exponent weights: 0 neutralizes a factor, >1 sharpens it."""

    relevance: float = Field(default=1.0, ge=0.0, le=4.0)
    recency: float = Field(default=1.0, ge=0.0, le=4.0)
    importance: float = Field(default=1.0, ge=0.0, le=4.0)


class RecallRequest(_Req):
    agent_id: str = Field(min_length=1, max_length=64)
    query: str = Field(min_length=1)
    k: int = Field(default=8, ge=1, le=100)
    types: list[MemoryType] | None = None
    weights: RecallWeights | None = None
    graph_expand: bool | None = None  # None -> server default
    rerank: bool = False
    as_context: bool = False


class SessionResponse(BaseModel):
    session: Session


class MemoryResponse(BaseModel):
    memory: MemoryRecord


class VersionsResponse(BaseModel):
    versions: list[MemoryRecord]


class RecallResponse(BaseModel):
    results: list[ScoredMemory]
    context: str | None = None
    context_tokens: int | None = None


class ConsolidateRequest(_Req):
    session_id: str = Field(min_length=1)


class JobResponse(BaseModel):
    job_id: str
    state: str


class HealthResponse(BaseModel):
    status: str
    version: str
