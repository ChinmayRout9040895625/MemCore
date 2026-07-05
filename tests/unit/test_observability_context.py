"""Phase 10 — request-id context propagation + log injection."""

from __future__ import annotations

import asyncio
import json
import logging

from memcore.logging import configure_logging, get_logger
from memcore.observability.context import (
    bind_request_id,
    get_request_id,
    new_request_id,
    reset_request_id,
)


def test_new_request_id_is_32_hex() -> None:
    rid = new_request_id()
    assert len(rid) == 32
    assert int(rid, 16) >= 0  # valid hex
    assert new_request_id() != rid  # unique


def test_bind_get_reset_roundtrip() -> None:
    assert get_request_id() is None
    token = bind_request_id("abc123")
    assert get_request_id() == "abc123"
    reset_request_id(token)
    assert get_request_id() is None


async def test_context_is_task_isolated() -> None:
    async def worker(rid: str) -> str | None:
        bind_request_id(rid)
        await asyncio.sleep(0)
        return get_request_id()

    first, second = await asyncio.gather(worker("rid-1"), worker("rid-2"))
    assert first == "rid-1"
    assert second == "rid-2"
    assert get_request_id() is None  # outer context untouched


def test_json_logs_carry_request_id(capsys: object) -> None:
    import pytest

    assert isinstance(capsys, pytest.CaptureFixture)
    configure_logging("INFO", json_output=True)
    token = bind_request_id("rid-json")
    try:
        get_logger("obs-test").info("hello")
    finally:
        reset_request_id(token)
        configure_logging("INFO", json_output=False)  # restore default
    line = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["request_id"] == "rid-json"
    assert payload["msg"] == "hello"


def test_plain_logs_show_dash_when_unbound(capsys: object) -> None:
    import pytest

    assert isinstance(capsys, pytest.CaptureFixture)
    configure_logging("INFO", json_output=False)
    get_logger("obs-test").info("plain hello")
    out = capsys.readouterr().out
    assert "[-]" in out
    assert "plain hello" in out


def test_filter_does_not_clobber_explicit_extra() -> None:
    # A caller passing extra={"request_id": ...} wins over the contextvar.
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    configure_logging("INFO", json_output=False)
    root = logging.getLogger()
    capture = Capture()
    for f in root.handlers[0].filters:
        capture.addFilter(f)
    root.addHandler(capture)
    try:
        get_logger("obs-test").info("x", extra={"request_id": "explicit"})
    finally:
        root.removeHandler(capture)
    assert records[-1].request_id == "explicit"  # type: ignore[attr-defined]
