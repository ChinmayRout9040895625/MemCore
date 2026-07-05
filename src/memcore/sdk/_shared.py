"""Transport-agnostic SDK logic: retry policy, backoff, error mapping.

Kept pure (no httpx, no I/O) so both clients share one tested implementation.
Retries are deliberately GET-only: a non-idempotent POST that fails midway
may have taken effect server-side, and replaying it could duplicate writes
(ADR-0018).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from memcore.sdk.exceptions import (
    APIError,
    AuthError,
    ConflictError,
    NotFoundError,
    ServerError,
    ValidationAPIError,
)

RETRYABLE_STATUSES: frozenset[int] = frozenset({429, 502, 503, 504})
_RETRYABLE_METHODS: frozenset[str] = frozenset({"GET"})


@dataclass(frozen=True)
class RetryPolicy:
    """Deterministic exponential backoff (no jitter — reproducible tests)."""

    max_attempts: int = 3
    backoff_base: float = 0.2
    backoff_cap: float = 5.0


def compute_backoff(attempt: int, policy: RetryPolicy) -> float:
    """Delay before retry number ``attempt`` (0-based): base * 2**attempt, capped."""
    return float(min(policy.backoff_cap, policy.backoff_base * (2**attempt)))


def is_retryable(method: str, status: int | None) -> bool:
    """Whether a failed request may be retried.

    ``status is None`` means the request never produced a response
    (transport failure) — retryable only for idempotent-safe methods.
    """
    if method.upper() not in _RETRYABLE_METHODS:
        return False
    return status is None or status in RETRYABLE_STATUSES


_ERROR_BY_STATUS: dict[int, type[APIError]] = {
    401: AuthError,
    404: NotFoundError,
    409: ConflictError,
    422: ValidationAPIError,
}


def error_from_response(status: int, payload: dict[str, Any] | None) -> APIError:
    """Map an RFC-7807 problem+json body to the typed exception hierarchy."""
    data = payload or {}
    title = str(data.get("title") or "APIError")
    detail = str(data.get("detail") or f"HTTP {status}")
    if status >= 500:
        cls: type[APIError] = ServerError
    else:
        cls = _ERROR_BY_STATUS.get(status, APIError)
    return cls(status=status, title=title, detail=detail)
