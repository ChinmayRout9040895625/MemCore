"""Lazy Prometheus wrapper — real metrics with the extra, no-ops without.

Metric objects live in a module-level cache keyed off one process-wide
registry: multiple app instances in one process share it (tests assert
presence, never exact counts). Without prometheus-client, ``observe_*`` are
silent no-ops and only ``render`` raises, so instrumented code paths never
need to branch on availability.
"""

from __future__ import annotations

from typing import Any

from memcore.exceptions import ConfigurationError

_INSTALL_HINT = (
    "prometheus-client is not installed; install the observability extra: "
    "pip install 'memcore[observability]'"
)

# Test-visible cache: {"available": bool, "registry": ..., metric objects...}
_cache: dict[str, Any] = {}

_HTTP_LABELS = ("method", "route", "status")
_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


def _load() -> dict[str, Any] | None:
    """Build (once) the registry + metric objects; None when unavailable."""
    if "available" in _cache:
        return _cache if _cache["available"] else None
    try:
        from prometheus_client import (
            CollectorRegistry,
            Counter,
            Histogram,
        )
    except ImportError:
        _cache["available"] = False
        return None
    registry = CollectorRegistry()
    _cache.update(
        available=True,
        registry=registry,
        http_total=Counter(
            "memcore_http_requests_total",
            "HTTP requests processed",
            _HTTP_LABELS,
            registry=registry,
        ),
        http_seconds=Histogram(
            "memcore_http_request_duration_seconds",
            "HTTP request latency",
            _HTTP_LABELS,
            buckets=_BUCKETS,
            registry=registry,
        ),
        operation_seconds=Histogram(
            "memcore_operation_duration_seconds",
            "Core operation latency (recall / consolidation / decay_sweep)",
            ("operation",),
            buckets=_BUCKETS,
            registry=registry,
        ),
    )
    return _cache


def metrics_available() -> bool:
    """Whether prometheus-client is importable (cached per process)."""
    return _load() is not None


def observe_http(method: str, route: str, status: int, seconds: float) -> None:
    """Record one HTTP request; silent no-op without the extra."""
    cache = _load()
    if cache is None:
        return
    labels = {"method": method, "route": route, "status": str(status)}
    cache["http_total"].labels(**labels).inc()
    cache["http_seconds"].labels(**labels).observe(seconds)


def observe_operation(operation: str, seconds: float) -> None:
    """Record one core-operation latency; silent no-op without the extra."""
    cache = _load()
    if cache is None:
        return
    cache["operation_seconds"].labels(operation=operation).observe(seconds)


def render() -> tuple[bytes, str]:
    """Prometheus exposition text and its content type.

    Raises :class:`ConfigurationError` with the install hint when the
    ``observability`` extra is absent — the /metrics route maps it to 501.
    """
    cache = _load()
    if cache is None:
        raise ConfigurationError(_INSTALL_HINT)
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return generate_latest(cache["registry"]), CONTENT_TYPE_LATEST
