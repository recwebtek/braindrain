"""A tiny stdio MCP tool server for tests.

Exposes a couple of tools matching the workflow steps we call:
- generate
- dependency_graph
- index
- get_affected_symbols

We keep it deterministic and small so tests don't depend on external tools.
"""

from __future__ import annotations

import json
from fastmcp import FastMCP

mcp = FastMCP("fake-mcp-tool-server")


@mcp.tool()
async def generate(path: str = "./", token_budget: int = 1000, mode: str = "new_project", since_commit: str = "") -> dict:
    return {
        "tool": "repo_mapper",
        "op": "generate",
        "path": path,
        "token_budget": token_budget,
        "mode": mode,
        "since_commit": since_commit,
        "symbols": [{"name": "A", "kind": "module"}, {"name": "B", "kind": "function"}],
    }


@mcp.tool()
async def dependency_graph(files: list[str] | None = None, symbol: str = "") -> dict:
    return {
        "tool": "repo_mapper",
        "op": "dependency_graph",
        "files": files or [],
        "symbol": symbol,
        "graph": {"nodes": ["A", "B"], "edges": [["A", "B"]]},
    }


@mcp.tool()
async def index(query: str = "", token_budget: int = 1500) -> dict:
    # Return a large payload to exercise routing
    big = {"items": [{"i": i, "text": "x" * 200} for i in range(80)]}
    return {"tool": "jcodemunch", "op": "index", "query": query, "token_budget": token_budget, "big": big}


@mcp.tool()
async def get_affected_symbols(files: list[str] | None = None, change_description: str = "", symbol: str = "", change_type: str = "") -> dict:
    return {
        "tool": "jcodemunch",
        "op": "get_affected_symbols",
        "files": files or [],
        "symbol": symbol,
        "change_description": change_description,
        "change_type": change_type,
        "affected": [{"symbol": "A", "reason": "depends on B"}, {"symbol": "B", "reason": "changed"}],
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

