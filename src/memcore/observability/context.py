"""Request/job correlation id — a contextvar visible to every log record.

The ASGI middleware binds one id per HTTP request (honoring an incoming
``X-Request-ID``); worker task shells bind one per job. ``memcore.logging``'s
context filter stamps the current value onto every record.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar, Token

_request_id: ContextVar[str | None] = ContextVar("memcore_request_id", default=None)


def new_request_id() -> str:
    """Fresh opaque correlation id (uuid4 hex, 32 chars)."""
    return uuid.uuid4().hex


def get_request_id() -> str | None:
    """The correlation id bound to the current context, if any."""
    return _request_id.get()


def bind_request_id(value: str) -> Token[str | None]:
    """Bind ``value`` for the current context; return the reset token."""
    return _request_id.set(value)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the binding that ``token``'s ``bind_request_id`` replaced."""
    _request_id.reset(token)
