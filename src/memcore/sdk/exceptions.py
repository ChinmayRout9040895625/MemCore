"""SDK exception hierarchy — every client failure is a MemCoreClientError."""

from __future__ import annotations


class MemCoreClientError(Exception):
    """Base for all SDK errors."""


class TransportError(MemCoreClientError):
    """Network-level failure (connect/read) after retries were exhausted."""


class JobTimeout(MemCoreClientError):
    """A polled job did not reach a terminal state within the timeout."""


class APIError(MemCoreClientError):
    """A non-2xx response from the server (RFC-7807 problem+json)."""

    def __init__(self, *, status: int, title: str, detail: str) -> None:
        super().__init__(f"{status} {title}: {detail}")
        self.status = status
        self.title = title
        self.detail = detail


class AuthError(APIError):
    """401 — missing or invalid API key."""


class NotFoundError(APIError):
    """404 — resource does not exist (or belongs to another tenant)."""


class ConflictError(APIError):
    """409 — duplicate or conflicting write."""


class ValidationAPIError(APIError):
    """422 — request failed validation."""


class ServerError(APIError):
    """5xx — server-side failure (retried automatically for GETs)."""
