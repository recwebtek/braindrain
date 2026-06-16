"""Tool registry with defer_loading and BM25 search"""

import asyncio
from dataclasses import dataclass

try:
    from rank_bm25 import BM25Okapi

    BM25_AVAILABLE = True
except ImportError:
    BM25_AVAILABLE = False

from braindrain.types import ConfigData, MCPToolConfig


@dataclass
class ToolReference:
    """Lightweight reference to a tool, returned by search"""

    name: str
    description: str
    tags: list[str]
    defer_loading: bool
    roles: list[str]
    bundles: list[str]


class ToolRegistry:
    """Manages MCP tools with defer_loading and search capabilities"""

    def __init__(self, config: ConfigData):
        self.config = config
        self._tools: dict[str, MCPToolConfig] = {}
        self._search_index: BM25Okapi | None = None
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
                roles=tool.roles,
                bundles=tool.bundles,
            )
            for tool in self._tools.values()
        ]

        if not self._tool_refs:
            return

        corpus = [f"{ref.name} {' '.join(ref.tags)} {ref.description}" for ref in self._tool_refs]

        tokenized_corpus = [doc.lower().split() for doc in corpus]
        self._search_index = BM25Okapi(tokenized_corpus)

    def search(
        self,
        query: str,
        top_k: int = 5,
        role: str | None = None,
        bundle: str | None = None,
    ) -> list[dict]:
        """
        Search tools by query using BM25.
        Returns lightweight references (~300 tokens total), not full schemas.
        """
        if not self._search_index:
            return self._get_all_tools(top_k, role=role, bundle=bundle)

        query_lower = query.lower()
        query_tokens = query_lower.split()

        scores = self._search_index.get_scores(query_tokens)

        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

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
                        "roles": ref.roles,
                        "bundles": ref.bundles,
                        "score": float(scores[idx]),
                    }
                )

        results = self._filter_results(results, role=role, bundle=bundle)
        if not results:
            return self._get_all_tools(top_k, role=role, bundle=bundle)

        return results

    def _get_all_tools(
        self, top_k: int, role: str | None = None, bundle: str | None = None
    ) -> list[dict]:
        """Fallback: return all tools if search fails"""
        results = [
            {
                "name": ref.name,
                "description": ref.description,
                "tags": ref.tags,
                "defer_loading": ref.defer_loading,
                "roles": ref.roles,
                "bundles": ref.bundles,
            }
            for ref in self._tool_refs
        ]
        filtered = self._filter_results(results, role=role, bundle=bundle)
        return filtered[:top_k]

    def _filter_results(
        self, results: list[dict], role: str | None = None, bundle: str | None = None
    ) -> list[dict]:
        if not role and not bundle:
            return results
        out: list[dict] = []
        for item in results:
            roles = item.get("roles") or []
            bundles = item.get("bundles") or []
            role_ok = True if not role else (not roles or role in roles)
            bundle_ok = True if not bundle else (not bundles or bundle in bundles)
            if role_ok and bundle_ok:
                out.append(item)
        return out

    async def search_async(
        self,
        query: str,
        top_k: int = 5,
        role: str | None = None,
        bundle: str | None = None,
    ) -> list[dict]:
        """Async version of search"""
        return await asyncio.to_thread(self.search, query, top_k, role, bundle)

    def count(self) -> int:
        """Return total number of registered tools"""
        return len(self._tools)

    def get_tool(self, name: str) -> MCPToolConfig | None:
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
        """Infer JSON schema from tool input_examples with basic type merging."""
        schema: dict = {"type": "object", "properties": {}, "required": []}
        required_keys: set[str] | None = None

        dict_examples = [example for example in tool.input_examples if isinstance(example, dict)]
        if not dict_examples:
            return schema

        for example in dict_examples:
            keys = set(example.keys())
            required_keys = keys if required_keys is None else (required_keys & keys)
            for key, value in example.items():
                inferred = self._infer_value_schema(value)
                existing = schema["properties"].get(key)
                schema["properties"][key] = (
                    self._merge_schemas(existing, inferred) if existing else inferred
                )

        schema["required"] = sorted(required_keys or [])
        return schema

    def _infer_value_schema(self, value) -> dict:
        if value is None:
            return {"type": "null"}
        if isinstance(value, bool):
            return {"type": "boolean"}
        if isinstance(value, int):
            return {"type": "integer"}
        if isinstance(value, float):
            return {"type": "number"}
        if isinstance(value, str):
            return {"type": "string"}
        if isinstance(value, dict):
            properties = {k: self._infer_value_schema(v) for k, v in value.items()}
            return {
                "type": "object",
                "properties": properties,
                "required": sorted(value.keys()),
            }
        if isinstance(value, list):
            if not value:
                return {"type": "array", "items": {}}
            item_schema = self._infer_value_schema(value[0])
            for item in value[1:]:
                item_schema = self._merge_schemas(item_schema, self._infer_value_schema(item))
            return {"type": "array", "items": item_schema}
        return {"type": "string"}

    def _merge_schemas(self, left: dict, right: dict) -> dict:
        if left == right:
            return left

        left_type = left.get("type")
        right_type = right.get("type")
        if left_type == right_type == "object":
            keys = set((left.get("properties") or {}).keys()) | set((right.get("properties") or {}).keys())
            properties = {}
            for key in keys:
                l_prop = (left.get("properties") or {}).get(key)
                r_prop = (right.get("properties") or {}).get(key)
                if l_prop and r_prop:
                    properties[key] = self._merge_schemas(l_prop, r_prop)
                else:
                    properties[key] = l_prop or r_prop
            left_required = set(left.get("required") or [])
            right_required = set(right.get("required") or [])
            return {
                "type": "object",
                "properties": properties,
                "required": sorted(left_required & right_required),
            }
        if left_type == right_type == "array":
            return {
                "type": "array",
                "items": self._merge_schemas(left.get("items") or {}, right.get("items") or {}),
            }

        types = []
        for candidate in (left_type, right_type):
            if isinstance(candidate, list):
                for t in candidate:
                    if t not in types:
                        types.append(t)
            elif candidate and candidate not in types:
                types.append(candidate)
        return {"type": types if len(types) > 1 else (types[0] if types else "string")}

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
