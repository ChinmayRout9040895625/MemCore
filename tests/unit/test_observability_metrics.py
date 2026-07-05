"""Phase 10 — lazy Prometheus wrapper: real metrics with the extra, no-ops without."""

from __future__ import annotations

import builtins
from typing import Any

import pytest

from memcore.exceptions import ConfigurationError
from memcore.observability import metrics


def test_metrics_available_in_dev_env() -> None:
    # prometheus-client ships with the dev extra, so this env has it.
    assert metrics.metrics_available() is True


def test_observe_and_render_exposition() -> None:
    metrics.observe_http("GET", "/v1/memories/{memory_id}", 200, 0.012)
    metrics.observe_operation("recall", 0.034)
    payload, content_type = metrics.render()
    text = payload.decode()
    assert "memcore_http_requests_total" in text
    assert 'route="/v1/memories/{memory_id}"' in text
    assert 'status="200"' in text
    assert "memcore_http_request_duration_seconds" in text
    assert 'memcore_operation_duration_seconds' in text
    assert 'operation="recall"' in text
    assert content_type.startswith("text/plain")


def test_noop_without_prometheus(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("prometheus_client"):
            raise ImportError("no prometheus")
        return real_import(name, *args, **kwargs)

    saved = dict(metrics._cache)
    metrics._cache.clear()
    monkeypatch.setattr(builtins, "__import__", fake_import)
    try:
        assert metrics.metrics_available() is False
        # Record calls must be silent no-ops, not errors.
        metrics.observe_http("GET", "/health", 200, 0.001)
        metrics.observe_operation("recall", 0.001)
        with pytest.raises(ConfigurationError, match=r"memcore\[observability\]"):
            metrics.render()
    finally:
        monkeypatch.undo()
        metrics._cache.clear()
        metrics._cache.update(saved)


def test_unavailability_is_cached_per_process_state() -> None:
    # After the no-op test restored the cache, metrics work again.
    assert metrics.metrics_available() is True
    metrics.observe_operation("decay_sweep", 0.5)
    payload, _ = metrics.render()
    assert 'operation="decay_sweep"' in payload.decode()
