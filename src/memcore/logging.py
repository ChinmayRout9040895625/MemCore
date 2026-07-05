"""Structured logging setup.

Provides a single :func:`configure_logging` entry point that all executables
(API, workers, SDK examples) call once at startup. Supports plain human-readable
output for local dev and JSON for production log aggregation.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from memcore.observability.context import get_request_id


class _ContextFilter(logging.Filter):
    """Stamp the correlation id onto every record (``"-"`` when unbound).

    An explicit ``extra={"request_id": ...}`` from the caller wins.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id() or "-"
        return True


class _JsonFormatter(logging.Formatter):
    """Minimal, dependency-free JSON log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Attach structured extras (anything not part of the base record).
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__)


def configure_logging(level: str = "INFO", *, json_output: bool = False) -> None:
    """Configure the root logger idempotently."""
    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_ContextFilter())
    if json_output:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s %(name)s [%(request_id)s]: %(message)s"
            )
        )
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger (``memcore.<name>``)."""
    return logging.getLogger(f"memcore.{name}")
