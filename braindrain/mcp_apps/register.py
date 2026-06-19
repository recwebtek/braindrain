"""Register MCP App resources and tools on the braindrain FastMCP server."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.apps import UI_MIME_TYPE, AppConfig, app_config_to_meta_dict
from fastmcp.resources.types import TextResource
from fastmcp.tools.base import ToolResult

from braindrain.mcp_apps.constants import (
    PLAN_BOARD_URI,
    POLL_PLAN_BOARD_TOOL,
    POLL_TOKEN_DASHBOARD_TOOL,
    TOKEN_DASHBOARD_URI,
)
from braindrain.mcp_apps.data import build_plan_board_payload, build_token_dashboard_payload
from braindrain.mcp_apps.html import plan_board_html, token_dashboard_html
from braindrain.telemetry import TelemetrySession

_TOKEN_APP = AppConfig(
    resource_uri=TOKEN_DASHBOARD_URI,
    prefers_border=True,
    visibility=["model", "app"],
)
_PLAN_APP = AppConfig(
    resource_uri=PLAN_BOARD_URI,
    prefers_border=True,
    visibility=["model", "app"],
)
_POLL_APP = AppConfig(resource_uri=TOKEN_DASHBOARD_URI, visibility=["app"])
_POLL_PLAN_APP = AppConfig(resource_uri=PLAN_BOARD_URI, visibility=["app"])
_RESOURCE_UI = AppConfig(prefers_border=True, domain="ui://braindrain")


def register_mcp_app_resources(mcp: FastMCP) -> None:
    """Register static `ui://` HTML resources (idempotent)."""
    ui_meta = {"ui": app_config_to_meta_dict(_RESOURCE_UI)}
    mcp.add_resource(
        TextResource(
            uri=TOKEN_DASHBOARD_URI,  # type: ignore[arg-type]
            name="Braindrain Token Dashboard",
            description="Inline token savings dashboard for MCP Apps hosts (Cursor, Claude, …).",
            text=token_dashboard_html(),
            mime_type=UI_MIME_TYPE,
            meta=ui_meta,
        )
    )
    mcp.add_resource(
        TextResource(
            uri=PLAN_BOARD_URI,  # type: ignore[arg-type]
            name="Braindrain Plan Board",
            description="Inline plan task board from .braindrain/plan-reports/.",
            text=plan_board_html(),
            mime_type=UI_MIME_TYPE,
            meta=ui_meta,
        )
    )


def register_mcp_app_tools(
    mcp: FastMCP,
    *,
    telemetry: TelemetrySession,
    tool_decorator: Any,
    default_project_root: Path | None = None,
) -> None:
    """Register MCP App tools that return structured dashboard payloads."""
    default_path = str(default_project_root or Path.cwd())

    @tool_decorator(
        app=_TOKEN_APP,
        tags={"mcp-apps", "tokens", "dashboard"},
    )
    async def show_token_dashboard(path: str = "") -> ToolResult:
        """
        Open an interactive token-savings dashboard inline in the chat (MCP App).

        Shows session totals, per-tool savings, and recent `.braindrain/token-metrics.jsonl`
        checkpoints. Use when the user wants a visual token dashboard, not just JSON.

        Args:
            path: Project root for checkpoint file resolution. Default: current directory.
        """
        payload = build_token_dashboard_payload(telemetry, path=path or default_path)
        return ToolResult(
            content="Token dashboard ready.",
            structured_content=payload,
        )

    @tool_decorator(
        name=POLL_TOKEN_DASHBOARD_TOOL,
        app=_POLL_APP,
        tags={"mcp-apps", "tokens", "dashboard"},
    )
    async def poll_token_dashboard(path: str = "") -> ToolResult:
        """
        App-only refresh for the token dashboard iframe (not for the model).

        Args:
            path: Project root for checkpoint file resolution. Default: current directory.
        """
        payload = build_token_dashboard_payload(telemetry, path=path or default_path)
        return ToolResult(structured_content=payload)

    @tool_decorator(
        app=_PLAN_APP,
        tags={"mcp-apps", "planning", "dashboard"},
    )
    async def show_plan_board(path: str = "") -> ToolResult:
        """
        Open an interactive plan task board inline in the chat (MCP App).

        Reads `.braindrain/plan-reports/plan-task-board.md` when present (from `/masterplan`
        or `daily_plan_audit.py`). Use for visual plan status, not raw markdown dumps.

        Args:
            path: Project root containing `.braindrain/plan-reports/`. Default: cwd.
        """
        payload = build_plan_board_payload(path=path or default_path)
        return ToolResult(
            content="Plan board ready.",
            structured_content=payload,
        )

    @tool_decorator(
        name=POLL_PLAN_BOARD_TOOL,
        app=_POLL_APP,
        tags={"mcp-apps", "planning", "dashboard"},
    )
    async def poll_plan_board(path: str = "") -> ToolResult:
        """
        App-only refresh for the plan board iframe (not for the model).

        Args:
            path: Project root containing `.braindrain/plan-reports/`. Default: cwd.
        """
        payload = build_plan_board_payload(path=path or default_path)
        return ToolResult(structured_content=payload)
