"""Observability plumbing (Phase 10, ADR-0019).

Dependency-light by design: ``context`` is stdlib contextvars, ``metrics``
lazy-imports prometheus-client behind the ``observability`` extra and no-ops
without it. This package must never import services/ports/adapters/api —
the API layer consumes it, not the other way around.
"""

from memcore.observability.context import (
    bind_request_id,
    get_request_id,
    new_request_id,
    reset_request_id,
)

__all__ = [
    "bind_request_id",
    "get_request_id",
    "new_request_id",
    "reset_request_id",
]
