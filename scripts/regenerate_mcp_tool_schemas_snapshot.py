#!/usr/bin/env python3
"""Regenerate tests/fixtures/mcp_tool_schemas_snapshot.json.

Run after intentional native MCP tool schema changes (parameters, descriptions,
outputSchema). Commit the updated fixture with the code change.

Usage (from repo root):
    uv run python scripts/regenerate_mcp_tool_schemas_snapshot.py

Then verify:
    uv run pytest tests/test_mcp_tool_schemas.py -q
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = REPO_ROOT / "tests" / "fixtures" / "mcp_tool_schemas_snapshot.json"


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


def regenerate_snapshot(path: Path = SNAPSHOT_PATH) -> Path:
    from braindrain.server import mcp

    tools = asyncio.run(mcp.list_tools())
    records = _tool_schema_records(tools)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    path = regenerate_snapshot()
    print(f"Wrote {len(json.loads(path.read_text(encoding='utf-8')))} tool schemas to {path}")
    print("Next: uv run pytest tests/test_mcp_tool_schemas.py -q")
    return 0


if __name__ == "__main__":
    sys.exit(main())
