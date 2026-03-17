"""Context-mode stdio client wrapper.

Uses the official `mcp` Python client to call context-mode tools like `ctx_index`
and `ctx_search` so BRAINDRAIN can keep large outputs out of the model context.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Any, Optional

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


class MCPProtocolError(RuntimeError):
    pass


@dataclass(frozen=True)
class MCPToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


class ContextModeClient:
    def __init__(self, command: str) -> None:
        argv = shlex.split(command)
        if not argv:
            raise ValueError("context-mode command is empty")
        self._cmd = argv[0]
        self._args = argv[1:]

    async def _with_session(self, fn):
        server = StdioServerParameters(command=self._cmd, args=self._args)
        async with stdio_client(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                tools: dict[str, MCPToolSpec] = {
                    t.name: MCPToolSpec(
                        name=t.name,
                        description=t.description or "",
                        input_schema=(t.inputSchema or {}),
                    )
                    for t in tools_result.tools
                }
                return await fn(session, tools)

    async def index_markdown(self, *, content_md: str, source: str, intent: Optional[str] = None) -> Any:
        async def _run(session: ClientSession, tools: dict[str, MCPToolSpec]):
            spec = tools.get("ctx_index")
            if spec is None:
                raise MCPProtocolError("context-mode does not expose ctx_index")

            props = (spec.input_schema or {}).get("properties", {}) if isinstance(spec.input_schema, dict) else {}
            args: dict[str, Any] = {}

            # Adapt to schema naming (content/markdown/text)
            if "content" in props:
                args["content"] = content_md
            elif "markdown" in props:
                args["markdown"] = content_md
            elif "text" in props:
                args["text"] = content_md
            else:
                args["content"] = content_md

            if "source" in props:
                args["source"] = source
            elif "title" in props:
                args["title"] = source

            if intent and ("intent" in props):
                args["intent"] = intent

            result = await session.call_tool("ctx_index", args)
            return result.model_dump(by_alias=True, exclude_none=True)

        return await self._with_session(_run)

    async def search(self, *, query: str, limit: int = 5) -> Any:
        async def _run(session: ClientSession, tools: dict[str, MCPToolSpec]):
            spec = tools.get("ctx_search")
            if spec is None:
                raise MCPProtocolError("context-mode does not expose ctx_search")

            props = (spec.input_schema or {}).get("properties", {}) if isinstance(spec.input_schema, dict) else {}
            args: dict[str, Any] = {}

            if "query" in props:
                args["query"] = query
            elif "queries" in props:
                args["queries"] = [query]
            else:
                args["query"] = query

            if "limit" in props:
                args["limit"] = limit
            elif "top_k" in props:
                args["top_k"] = limit
            elif "max_results" in props:
                args["max_results"] = limit

            result = await session.call_tool("ctx_search", args)
            return result.model_dump(by_alias=True, exclude_none=True)

        return await self._with_session(_run)

