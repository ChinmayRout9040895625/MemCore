"""Generate docs/api-reference.md from the live FastAPI OpenAPI schema.

Usage:
    python scripts/generate_api_reference.py [OUTPUT_PATH]

Deterministic: paths and fields are emitted in sorted/declared order, output
uses LF newlines, and no timestamps are embedded — so regeneration is
byte-stable and the drift test can compare exactly.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Ensure src/ is importable when run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memcore.api import create_app
from memcore.config import (
    DatabaseSettings,
    EmbeddingSettings,
    GraphSettings,
    LLMSettings,
    RedisSettings,
    SchedulerSettings,
    Settings,
    VectorSettings,
)

METHOD_ORDER = {"get": 0, "post": 1, "patch": 2, "put": 3, "delete": 4}

# Each table row must render as a single Markdown line (a hard line break
# would split it into a new table), so the long rows are built by joining
# shorter Python string literals rather than written as one long source line.
_READY_ROW = (
    "| `GET /ready` | Readiness probe: pings each backing store "
    '(duck-typed adapter `ping()`); returns 200 `{"status": "ready"}` or 503 '
    '`{"status": "degraded"}` with per-component detail. No auth. |'
)
_METRICS_ROW = (
    "| `GET /metrics` | Prometheus exposition for the API process; 501 "
    "problem+json with an install hint when the `observability` extra is "
    "absent. No auth — keep it cluster-internal (the shipped ingress "
    "blocks it). |"
)
OPERATIONAL_SECTION = (
    "\n".join(
        [
            "## Operational endpoints (not in the OpenAPI schema)",
            "",
            "These are deliberately excluded from the schema "
            "(`include_in_schema=False`)",
            "because they are for probes and scrapers, not API clients:",
            "",
            "| Method & path | Purpose |",
            "|---|---|",
            _READY_ROW,
            _METRICS_ROW,
        ]
    )
    + "\n"
)


def _build_schema() -> dict[str, Any]:
    settings = Settings(
        _env_file=None,
        redis=RedisSettings(provider="inmemory"),
        vector=VectorSettings(provider="inmemory"),
        graph=GraphSettings(provider="inmemory"),
        embedding=EmbeddingSettings(provider="inmemory"),
        llm=LLMSettings(provider="inmemory", fallback_provider=None),
        scheduler=SchedulerSettings(provider="inmemory"),
        database=DatabaseSettings(provider="inmemory"),
    )
    app = create_app(settings)
    schema: dict[str, Any] = app.openapi()
    return schema


def _type_of(
    prop: dict[str, Any], schema: dict[str, Any], *, table: bool = False
) -> str:
    """Render an OpenAPI schema fragment as a short type string.

    ``table=True`` escapes the ``|`` separator used for ``anyOf`` alternatives
    (e.g. ``string \\| null``) so the result is safe inside a Markdown table
    cell — an unescaped ``|`` there would be parsed as an extra column.
    Prose call sites (e.g. the "Request body: `...`" line, which is not a
    table row) pass the default ``table=False`` and get a plain ``|``.
    """
    if "$ref" in prop:
        return prop["$ref"].rsplit("/", 1)[-1]
    if "anyOf" in prop:
        sep = " \\| " if table else " | "
        return sep.join(_type_of(p, schema, table=table) for p in prop["anyOf"])
    kind = prop.get("type", "any")
    if kind == "array":
        return f"array[{_type_of(prop.get('items', {}), schema, table=table)}]"
    if "enum" in prop:
        values = " \\| ".join(str(v) for v in prop["enum"])
        return f"{kind} ({values})"
    return str(kind)


def _model_table(name: str, schema: dict[str, Any], emitted: set[str]) -> list[str]:
    if name in emitted or name not in schema.get("components", {}).get("schemas", {}):
        return []
    emitted.add(name)
    model = schema["components"]["schemas"][name]
    lines = [f"### `{name}`", ""]
    if model.get("description"):
        lines += [model["description"].strip(), ""]
    properties: dict[str, Any] = model.get("properties", {})
    if not properties:
        enum_values = model.get("enum")
        if enum_values:
            values = ", ".join(f"`{v}`" for v in enum_values)
            lines += [f"Enum ({model.get('type', 'string')}): {values}", ""]
        else:
            lines += ["(no fields)", ""]
        return lines
    required = set(model.get("required", []))
    lines += ["| Field | Type | Required | Default |", "|---|---|---|---|"]
    for field, prop in properties.items():
        default = prop.get("default", "—")
        lines.append(
            f"| `{field}` | {_type_of(prop, schema, table=True)} | "
            f"{'yes' if field in required else 'no'} | `{default}` |"
        )
    lines.append("")
    return lines


def _collect_refs(node: Any, found: list[str]) -> None:
    if isinstance(node, dict):
        if "$ref" in node:
            found.append(node["$ref"].rsplit("/", 1)[-1])
        for value in node.values():
            _collect_refs(value, found)
    elif isinstance(node, list):
        for item in node:
            _collect_refs(item, found)


def render(schema: dict[str, Any]) -> str:
    lines: list[str] = [
        f"# {schema['info']['title']} API Reference",
        "",
        f"Version {schema['info']['version']} — generated from the OpenAPI "
        "schema by `scripts/generate_api_reference.py`; do not edit by hand "
        "(a drift test regenerates and compares this file).",
        "",
        "**Authentication:** every `/v1/*` endpoint requires the `X-API-Key` "
        "header; the key maps to a tenant (`MEMCORE_API__KEYS`). Errors are "
        "RFC-7807 `application/problem+json`.",
        "",
        "## Endpoints",
        "",
    ]
    referenced_models: list[str] = []
    for path in sorted(schema["paths"]):
        operations = schema["paths"][path]
        for method in sorted(operations, key=lambda m: METHOD_ORDER.get(m, 9)):
            op = operations[method]
            lines.append(f"### `{method.upper()} {path}`")
            lines.append("")
            summary = op.get("summary") or op.get("operationId", "")
            if summary:
                lines += [summary, ""]
            if op.get("description"):
                lines += [op["description"].strip(), ""]
            params = op.get("parameters", [])
            if params:
                lines += ["| Parameter | In | Type | Required |", "|---|---|---|---|"]
                for param in params:
                    lines.append(
                        f"| `{param['name']}` | {param['in']} | "
                        f"{_type_of(param.get('schema', {}), schema, table=True)} | "
                        f"{'yes' if param.get('required') else 'no'} |"
                    )
                lines.append("")
            body = op.get("requestBody", {})
            body_schema = (
                body.get("content", {}).get("application/json", {}).get("schema", {})
            )
            if body_schema:
                lines += [f"Request body: `{_type_of(body_schema, schema)}`", ""]
                _collect_refs(body_schema, referenced_models)
            responses = op.get("responses", {})
            resp_lines = []
            for status in sorted(responses):
                resp = responses[status]
                resp_schema = (
                    resp.get("content", {})
                    .get("application/json", {})
                    .get("schema", {})
                )
                # Not wrapped in backticks: a code span disables backslash-escape
                # processing, so an escaped `\|` (from an anyOf union type) would
                # render as a literal backslash instead of a pipe.
                kind = (
                    f" — {_type_of(resp_schema, schema, table=True)}"
                    if resp_schema
                    else ""
                )
                resp_lines.append(f"| {status} | {resp.get('description', '')}{kind} |")
                _collect_refs(resp_schema, referenced_models)
            if resp_lines:
                lines += ["| Status | Response |", "|---|---|", *resp_lines, ""]
    lines += [OPERATIONAL_SECTION, "## Models", ""]
    emitted: set[str] = set()
    # Emit referenced models first (stable order of first reference), then
    # transitively referenced ones discovered while emitting.
    queue = list(dict.fromkeys(referenced_models))
    while queue:
        name = queue.pop(0)
        model = schema.get("components", {}).get("schemas", {}).get(name, {})
        nested: list[str] = []
        _collect_refs(model, nested)
        lines += _model_table(name, schema, emitted)
        queue += [n for n in nested if n not in emitted]
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/api-reference.md")
    schema = _build_schema()
    with open(output, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render(schema))
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
