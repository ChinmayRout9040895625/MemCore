"""Tests for structured logging configuration."""

from __future__ import annotations

import json
import logging

import pytest

from memcore.logging import configure_logging, get_logger


def test_get_logger_is_namespaced() -> None:
    log = get_logger("retrieval")
    assert log.name == "memcore.retrieval"


def test_configure_logging_is_idempotent() -> None:
    configure_logging("INFO")
    configure_logging("DEBUG")  # reconfigure
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert root.level == logging.DEBUG


def test_json_formatter_emits_valid_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_output=True)
    get_logger("test").info("hello", extra={"tenant_id": "t1"})
    line = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["msg"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["tenant_id"] == "t1"
    # Restore plain logging so other tests are unaffected.
    configure_logging("INFO", json_output=False)
