"""Phase 12 — the committed API reference must match the live OpenAPI schema.

The reference is generated, not hand-written (ADR-0021): this test regenerates
it and compares byte-for-byte, so any route/schema change that forgets to
re-run the generator fails CI with a clear message.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts" / "generate_api_reference.py"
COMMITTED = REPO_ROOT / "docs" / "api-reference.md"


def test_api_reference_is_current(tmp_path: Path) -> None:
    output = tmp_path / "api-reference.md"
    subprocess.run(
        [sys.executable, str(GENERATOR), str(output)],
        check=True,
        cwd=REPO_ROOT,
        timeout=120,
    )
    generated = output.read_text(encoding="utf-8")
    committed = COMMITTED.read_text(encoding="utf-8")
    assert generated == committed, (
        "docs/api-reference.md is stale — regenerate it:\n"
        "  ./.venv/Scripts/python.exe scripts/generate_api_reference.py"
    )


def test_reference_covers_every_route(tmp_path: Path) -> None:
    text = COMMITTED.read_text(encoding="utf-8")
    # Spot-check the full v1 surface is present.
    for fragment in (
        "POST /v1/sessions",
        "POST /v1/sessions/{session_id}/messages",
        "POST /v1/sessions/{session_id}/close",
        "POST /v1/memories",
        "GET /v1/memories/{memory_id}",
        "GET /v1/memories/{memory_id}/versions",
        "PATCH /v1/memories/{memory_id}",
        "DELETE /v1/memories/{memory_id}",
        "POST /v1/memories/{memory_id}/restore",
        "POST /v1/recall",
        "POST /v1/consolidate",
        "GET /v1/jobs/{job_id}",
        "POST /v1/decay",
        "GET /health",
        "GET /ready",
    ):
        assert fragment in text, f"missing from api-reference.md: {fragment}"
