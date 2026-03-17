"""Tool registry with defer_loading and BM25 search"""

import asyncio
from typing import Optional
from dataclasses import dataclass

try:
    from rank_bm25 import BM25Okapi

    BM25_AVAILABLE = True
except ImportError:
    BM25_AVAILABLE = False

from braindrain.types import MCPToolConfig, ConfigData


@dataclass
class ToolReference:
    """Lightweight reference to a tool, returned by search"""

    name: str
    description: str
    tags: list[str]
    defer_loading: bool


class ToolRegistry:
    """Manages MCP tools with defer_loading and search capabilities"""

    def __init__(self, config: ConfigData):
        self.config = config
        self._tools: dict[str, MCPToolConfig] = {}
        self._search_index: Optional[BM25Okapi] = None
        self._tool_refs: list[ToolReference] = []
        self._load_tools()

    def _load_tools(self) -> None:
        """Load tools from config"""
        for tool in self.config.mcp_tools:
            self._tools[tool.name] = tool

        self._build_search_index()

    def _build_search_index(self) -> None:
        """Build BM25 search index from tool descriptions"""
        if not BM25_AVAILABLE:
            return

        self._tool_refs = [
            ToolReference(
                name=tool.name,
                description=tool.description,
                tags=tool.tags,
                defer_loading=tool.defer_loading,
            )
            for tool in self._tools.values()
        ]

        if not self._tool_refs:
            return

        corpus = [
            f"{ref.name} {' '.join(ref.tags)} {ref.description}"
            for ref in self._tool_refs
        ]

        tokenized_corpus = [doc.lower().split() for doc in corpus]
        self._search_index = BM25Okapi(tokenized_corpus)

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Search tools by query using BM25.
        Returns lightweight references (~300 tokens total), not full schemas.
        """
        if not self._search_index:
            return self._get_all_tools(top_k)

        query_lower = query.lower()
        query_tokens = query_lower.split()

        scores = self._search_index.get_scores(query_tokens)

        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[
            :top_k
        ]

        results = []
        for idx in top_indices:
            if scores[idx] > 0:
                ref = self._tool_refs[idx]
                results.append(
                    {
                        "name": ref.name,
                        "description": ref.description,
                        "tags": ref.tags,
                        "defer_loading": ref.defer_loading,
                        "score": float(scores[idx]),
                    }
                )

        if not results:
            return self._get_all_tools(top_k)

        return results

    def _get_all_tools(self, top_k: int) -> list[dict]:
        """Fallback: return all tools if search fails"""
        return [
            {
                "name": ref.name,
                "description": ref.description,
                "tags": ref.tags,
                "defer_loading": ref.defer_loading,
            }
            for ref in self._tool_refs[:top_k]
        ]

    async def search_async(self, query: str, top_k: int = 5) -> list[dict]:
        """Async version of search"""
        return await asyncio.to_thread(self.search, query, top_k)

    def count(self) -> int:
        """Return total number of registered tools"""
        return len(self._tools)

    def get_tool(self, name: str) -> Optional[MCPToolConfig]:
        """Get a tool by name"""
        return self._tools.get(name)

    def get_hot_tools(self) -> list[MCPToolConfig]:
        """Get all tools that are hot (not deferred)"""
        return [t for t in self._tools.values() if t.hot]

    def get_deferred_tools(self) -> list[MCPToolConfig]:
        """Get all tools with defer_loading enabled"""
        return [t for t in self._tools.values() if t.defer_loading]

    def build_api_tools(self) -> list[dict]:
        """
        Build tool list for Anthropic API with defer_loading.
        Returns only tool references, not full definitions.
        """
        api_tools = []

        for tool in self._tools.values():
            api_tools.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": {"type": "object", "properties": {}},
                    "input_examples": tool.input_examples,
                    "defer_loading": tool.defer_loading,
                }
            )

        return api_tools

    def get_tool_definitions_for_client(self) -> list[dict]:
        """
        Get full tool definitions for MCP client.
        Only includes HOT tools for initial context.
        Deferred tools will be loaded on-demand.
        """
        definitions = []

        for tool in self._tools.values():
            if tool.hot:
                definitions.append(
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "input_schema": self._infer_schema(tool),
                        "input_examples": tool.input_examples,
                        "defer_loading": False,
                    }
                )

        return definitions

    def _infer_schema(self, tool: MCPToolConfig) -> dict:
        """Infer JSON schema from tool config"""
        schema = {
            "type": "object",
            "properties": {},
            "required": [],
        }

        for example in tool.input_examples:
            if isinstance(example, dict):
                for key in example.keys():
                    if key not in schema["properties"]:
                        schema["properties"][key] = {"type": "string"}

        return schema

    def reload(self) -> None:
        """Reload tools from config"""
        self._tools.clear()
        self._load_tools()

    def get_stats(self) -> dict:
        """Get registry statistics"""
        hot_count = len(self.get_hot_tools())
        deferred_count = len(self.get_deferred_tools())

        return {
            "total_tools": self.count(),
            "hot_tools": hot_count,
            "deferred_tools": deferred_count,
            "search_index_ready": self._search_index is not None,
        }
