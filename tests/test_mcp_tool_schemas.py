"""Regression: every native MCP tool parameter must expose a schema description."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from braindrain.server import mcp

SNAPSHOT_PATH = Path(__file__).resolve().parent / "fixtures" / "mcp_tool_schemas_snapshot.json"


def _tool_schema_records(tools: list) -> list[dict]:
    records: list[dict] = []
    for tool in sorted(tools, key=lambda item: item.name):
        payload = tool.model_dump() if hasattr(tool, "model_dump") else tool.dict()
        records.append(
            {
                "name": payload.get("name"),
                "description": payload.get("description"),
                "parameters": payload.get("parameters"),
                "outputSchema": payload.get("outputSchema") or payload.get("output_schema"),
            }
        )
    return records


def _missing_param_descriptions(tools: list) -> list[str]:
    missing: list[str] = []
    for tool in tools:
        params = getattr(tool, "parameters", None) or {}
        properties = params.get("properties") or {}
        if not properties:
            continue
        for param_name, spec in properties.items():
            description = (spec.get("description") or "").strip()
            if not description:
                missing.append(f"{tool.name}.{param_name}")
    return missing


def test_all_mcp_tool_parameters_have_descriptions() -> None:
    tools = asyncio.run(mcp.list_tools())
    assert tools, "expected at least one native MCP tool"

    missing = _missing_param_descriptions(tools)
    assert not missing, "MCP tool parameters missing Args: docstring descriptions: " + ", ".join(
        sorted(missing)
    )


def test_parameterized_tools_have_tool_description() -> None:
    tools = asyncio.run(mcp.list_tools())
    for tool in tools:
        params = getattr(tool, "parameters", None) or {}
        if not params.get("properties"):
            continue
        description = (getattr(tool, "description", None) or "").strip()
        assert description, f"{tool.name} has parameters but no tool description"


def test_mcp_tool_schemas_match_snapshot() -> None:
    tools = asyncio.run(mcp.list_tools())
    live = _tool_schema_records(tools)
    expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert live == expected, (
        "MCP tool schemas drifted from snapshot; update "
        "tests/fixtures/mcp_tool_schemas_snapshot.json intentionally if schemas changed"
    )
