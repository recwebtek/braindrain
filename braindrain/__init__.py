"""BRAINDRAIN - Intelligent MCP Context Hub"""

from __future__ import annotations

__version__ = "1.0.2"

from braindrain.config import Config
from braindrain.tool_registry import ToolRegistry

__all__ = ["mcp", "Config", "ToolRegistry"]


def __getattr__(name: str):
    """Lazy-load ``mcp`` so ``python -m braindrain.server`` does not trigger runpy RuntimeWarning."""
    if name == "mcp":
        from braindrain.server import mcp as _mcp

        return _mcp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
