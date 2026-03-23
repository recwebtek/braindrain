"""BRAINDRAIN - Intelligent MCP Context Hub"""

__version__ = "1.0.1"

from braindrain.server import mcp
from braindrain.config import Config
from braindrain.tool_registry import ToolRegistry

__all__ = ["mcp", "Config", "ToolRegistry"]
