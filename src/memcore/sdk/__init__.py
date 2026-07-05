"""MemCore Python SDK (Phase 9, ADR-0018).

Typed async + sync clients over the v1 HTTP API. This package is a consumer
layer: it depends only on ``memcore.domain`` models and ``httpx`` (installed
via the ``sdk`` extra: ``pip install 'memcore[sdk]'``); it never imports
services, ports, adapters, or the server app.
"""

from memcore.sdk.exceptions import (
    APIError,
    AuthError,
    ConflictError,
    JobTimeout,
    MemCoreClientError,
    NotFoundError,
    ServerError,
    TransportError,
    ValidationAPIError,
)
from memcore.sdk.models import Job, RecallOutcome

__all__ = [
    "APIError",
    "AuthError",
    "ConflictError",
    "Job",
    "JobTimeout",
    "MemCoreClientError",
    "NotFoundError",
    "RecallOutcome",
    "ServerError",
    "TransportError",
    "ValidationAPIError",
]
