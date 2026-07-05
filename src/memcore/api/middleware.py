"""Pure-ASGI observability middleware (Phase 10, ADR-0019).

Per HTTP request: bind a correlation id (honoring an incoming
``X-Request-ID``), stamp it on the response, emit one structured access-log
line, and record HTTP metrics labeled by *route template* (bounded
cardinality; unmatched 404s fall back to the raw path, an accepted
low-volume exception).
"""

from __future__ import annotations

import time
from typing import Any

from memcore.logging import get_logger
from memcore.observability import metrics
from memcore.observability.context import bind_request_id, new_request_id, reset_request_id

_access_log = get_logger("api.access")

Scope = dict[str, Any]


class ObservabilityMiddleware:
    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v for k, v in scope.get("headers", [])}
        incoming = headers.get("x-request-id")
        request_id = incoming.decode("latin-1") if incoming else new_request_id()
        token = bind_request_id(request_id)
        status_holder = {"status": 500}
        started = time.perf_counter()

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                raw = list(message.get("headers", []))
                raw.append((b"x-request-id", request_id.encode("latin-1")))
                message = {**message, "headers": raw}
            await send(message)

        try:
            await self._app(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - started
            # Starlette stamps the matched route onto the scope during
            # routing; template beats raw path for label cardinality.
            route = scope.get("route")
            template = getattr(route, "path_format", None) or scope.get("path", "?")
            status = status_holder["status"]
            metrics.observe_http(scope.get("method", "?"), template, status, duration)
            _access_log.info(
                "request",
                extra={
                    "request_id": request_id,
                    "method": scope.get("method", "?"),
                    "path": scope.get("path", "?"),
                    "route": template,
                    "status": status,
                    "duration_ms": round(duration * 1000, 2),
                },
            )
            reset_request_id(token)
