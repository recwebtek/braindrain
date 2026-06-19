"""Register MCP App resources and tools on the braindrain FastMCP server."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.apps import UI_MIME_TYPE, AppConfig, app_config_to_meta_dict
from fastmcp.resources.types import TextResource
from fastmcp.tools.base import ToolResult

from braindrain.mcp_apps.constants import (
    APPLY_PLAN_TODO_SYNC_TOOL,
    ARCHIVE_PLAN_TOOL,
    AUDIT_PLAN_IMPLEMENTATION_TOOL,
    ENQUEUE_PLAN_CONTINUE_TOOL,
    MARK_PLAN_MERGE_READY_TOOL,
    PLAN_BOARD_HANDOFF_TOOL,
    PLAN_BOARD_URI,
    POLL_PLAN_BOARD_TOOL,
    POLL_TOKEN_DASHBOARD_TOOL,
    TOKEN_DASHBOARD_URI,
)
from braindrain.mcp_apps.data import build_plan_board_payload, build_token_dashboard_payload
from braindrain.mcp_apps.html import plan_board_html, token_dashboard_html
from braindrain.mcp_apps.plan_actions import (
    apply_plan_todo_sync,
    archive_plan,
    audit_plan_implementation,
    enqueue_plan_continue,
    mark_plan_merge_ready,
    plan_board_handoff,
)
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
_ACTION_APP = AppConfig(resource_uri=PLAN_BOARD_URI, visibility=["app"])
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

    @tool_decorator(
        name=AUDIT_PLAN_IMPLEMENTATION_TOOL,
        app=_ACTION_APP,
        tags={"mcp-apps", "planning", "audit"},
    )
    async def audit_plan_implementation_tool(
        source: str,
        path: str = "",
        dry_run: bool = True,
    ) -> ToolResult:
        """
        App-only: compare plan todos against repo files (read-only audit).

        Args:
            source: Repo-relative plan path (e.g. `.cursor/plans/foo.plan.md`).
            path: Project root. Default: server project root.
            dry_run: Always true for audit; included for API symmetry.
        """
        result = audit_plan_implementation(
            path=path or default_path,
            source=source,
            dry_run=dry_run,
        )
        return ToolResult(structured_content=result)

    @tool_decorator(
        name=APPLY_PLAN_TODO_SYNC_TOOL,
        app=_ACTION_APP,
        tags={"mcp-apps", "planning", "write"},
    )
    async def apply_plan_todo_sync_tool(
        source: str,
        proposals: list[dict[str, object]],
        path: str = "",
        confirm: bool = False,
    ) -> ToolResult:
        """
        App-only: apply todo status updates from audit proposals.

        Args:
            source: Repo-relative plan path.
            proposals: Audit proposal objects with todo_id, suggested_status, confidence.
            path: Project root. Default: server project root.
            confirm: Must be true to write frontmatter.
        """
        result = apply_plan_todo_sync(
            path=path or default_path,
            source=source,
            proposals=proposals,
            confirm=confirm,
        )
        return ToolResult(structured_content=result)

    @tool_decorator(
        name=MARK_PLAN_MERGE_READY_TOOL,
        app=_ACTION_APP,
        tags={"mcp-apps", "planning", "write"},
    )
    async def mark_plan_merge_ready_tool(
        source: str,
        path: str = "",
        confirm: bool = False,
    ) -> ToolResult:
        """
        App-only: set plan disposition to merge-ready when gates pass.

        Args:
            source: Repo-relative plan path.
            path: Project root. Default: server project root.
            confirm: Must be true to write frontmatter.
        """
        result = mark_plan_merge_ready(
            path=path or default_path,
            source=source,
            confirm=confirm,
        )
        return ToolResult(structured_content=result)

    @tool_decorator(
        name=ARCHIVE_PLAN_TOOL,
        app=_ACTION_APP,
        tags={"mcp-apps", "planning", "write"},
    )
    async def archive_plan_tool(
        source: str,
        path: str = "",
        confirm: bool = False,
    ) -> ToolResult:
        """
        App-only: archive a plan to `.plan.archives/` when gates pass.

        Args:
            source: Repo-relative plan path.
            path: Project root. Default: server project root.
            confirm: Must be true to move the plan file.
        """
        result = archive_plan(path=path or default_path, source=source, confirm=confirm)
        return ToolResult(structured_content=result)

    @tool_decorator(
        name=ENQUEUE_PLAN_CONTINUE_TOOL,
        app=_ACTION_APP,
        tags={"mcp-apps", "planning", "gitops"},
    )
    async def enqueue_plan_continue_tool(
        source: str,
        path: str = "",
        confirm: bool = False,
    ) -> ToolResult:
        """
        App-only: queue branch-setup and return continue-build handoff text.

        Args:
            source: Repo-relative plan path.
            path: Project root. Default: server project root.
            confirm: Must be true to write gitops queue / branch frontmatter.
        """
        result = enqueue_plan_continue(
            path=path or default_path,
            source=source,
            confirm=confirm,
        )
        return ToolResult(structured_content=result)

    @tool_decorator(
        name=PLAN_BOARD_HANDOFF_TOOL,
        app=_ACTION_APP,
        tags={"mcp-apps", "planning", "handoff"},
    )
    async def plan_board_handoff_tool(
        action: str,
        source: str,
        branch: str = "",
    ) -> ToolResult:
        """
        App-only: build chat handoff message for research or continue actions.

        Args:
            action: Handoff kind (`research` or `continue`).
            source: Repo-relative plan path.
            branch: Optional branch name for continue handoffs.
        """
        result = plan_board_handoff(action=action, source=source, branch=branch)
        return ToolResult(structured_content=result)
