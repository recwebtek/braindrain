"""Generic stdio MCP client wrapper.

This mirrors the pattern used by `ContextModeClient`, but is tool-agnostic so
the workflow engine can call any configured downstream MCP server by command.
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


class StdioMCPClient:
    def __init__(self, command: str) -> None:
        argv = shlex.split(command)
        if not argv:
            raise ValueError("MCP tool command is empty")
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

    async def list_tools(self) -> dict[str, MCPToolSpec]:
        async def _run(_session: ClientSession, tools: dict[str, MCPToolSpec]):
            return tools

        return await self._with_session(_run)

    async def call_tool(self, tool_name: str, args: Optional[dict[str, Any]] = None) -> Any:
        if args is None:
            args = {}

        async def _run(session: ClientSession, tools: dict[str, MCPToolSpec]):
            if tool_name not in tools:
                raise MCPProtocolError(f"Tool '{tool_name}' not exposed by server")
            spec = tools[tool_name]

            filtered_args = args
            if isinstance(spec.input_schema, dict):
                props = spec.input_schema.get("properties")
                if isinstance(props, dict) and props:
                    filtered_args = {k: v for k, v in args.items() if k in props}

            result = await session.call_tool(tool_name, filtered_args)
            return result.model_dump(by_alias=True, exclude_none=True)

        return await self._with_session(_run)

