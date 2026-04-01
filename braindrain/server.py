"""BRAINDRAIN MCP Server - FastMCP implementation"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Auto-add project root to path so braindrain can be imported without PYTHONPATH
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from dotenv import load_dotenv
from fastmcp import FastMCP

from braindrain.config import Config
from braindrain.context_mode_client import ContextModeClient, MCPProtocolError
from braindrain.env_probe import get_env_context as _probe_env_context
from braindrain.output_router import build_routed_output, should_route
from braindrain.telemetry import telemetry_from_config
from braindrain.tool_registry import ToolRegistry
from braindrain.workflow_engine import WorkflowEngine
from braindrain.workspace_primer import (
    initialize_project_memory as _initialize_project_memory,
)
from braindrain.workspace_primer import prime as _prime_workspace

mcp = FastMCP("braindrain")

CONFIG_PATH = os.environ.get(
    "BRAINDRAIN_CONFIG",
    str(Path(__file__).parent.parent / "config" / "hub_config.yaml"),
)

BRAINDRAIN_LAUNCHER_PATH = os.environ.get(
    "BRAINDRAIN_LAUNCHER_PATH",
    str(Path(__file__).parent.parent / "config" / "braindrain"),
)

# Load environment variables early (dev/prod).
# Precedence: existing env vars win; `.env.dev` preferred if present, else `.env.prod`, else `.env`.
_repo_root = Path(__file__).parent.parent
for _env_name in (".env.dev", ".env.prod", ".env"):
    _env_path = _repo_root / _env_name
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path, override=False)
        break

config = Config(CONFIG_PATH)
registry = ToolRegistry(config.data)
telemetry = telemetry_from_config(config.get("cost_tracking", {}) or {})

_context_mode_client: Optional[ContextModeClient] = None
_workflow_engine: Optional[WorkflowEngine] = None


def _get_context_mode_client() -> Optional[ContextModeClient]:
    global _context_mode_client
    if _context_mode_client is not None:
        return _context_mode_client

    tool = config.get_tool("context_mode")
    if not tool or not tool.command:
        return None

    _context_mode_client = ContextModeClient(tool.command)
    return _context_mode_client


def _get_workflow_engine() -> Optional[WorkflowEngine]:
    global _workflow_engine
    if _workflow_engine is not None:
        return _workflow_engine

    enabled = bool(config.get("modules.workflow_engine.enabled", False) or False)
    if not enabled:
        return None

    _workflow_engine = WorkflowEngine(
        config=config,
        telemetry=telemetry,
        context_mode_client_getter=_get_context_mode_client,
    )
    return _workflow_engine


session_stats = {
    "note": "deprecated: use telemetry snapshot"
}  # kept for backwards compatibility


@mcp.tool()
async def search_tools(query: str = "", top_k: int = 5) -> dict:
    """
    Search available tools by capability. Call this FIRST before any task.
    Returns lightweight references (~300 tokens total), not full definitions.

    Examples: "codebase symbols", "git operations", "compress context"
    """
    # Some clients/agents may accidentally call this tool with `{}`.
    # Make the parameter optional to avoid hard validation failures.
    results = await registry.search_async(query or "", top_k)

    return {
        "tools": results,
        "total_available": registry.count(),
        "query": query,
    }


@mcp.tool()
async def list_workflows() -> dict:
    """
    List available workflows with descriptions and token budgets.
    Use this to see what automated tasks BRAINDRAIN can perform.
    """
    return config.get_workflow_catalog()


@mcp.tool()
async def run_workflow(name: str, args: dict = None) -> dict:
    """
    Execute a workflow in an isolated sandbox. Returns only final summary.
    Intermediate data NEVER enters your context window.

    Available workflows: See list_workflows()
    """
    if args is None:
        args = {}

    if name == "init_project_memory":
        return init_project_memory(
            path=args.get("path", "."),
            dry_run=bool(args.get("dry_run", False)),
        )

    workflow = config.get_workflow(name)
    if not workflow:
        return {
            "error": f"Workflow '{name}' not found",
            "available": [wf.name for wf in config.workflows],
        }

    engine = _get_workflow_engine()
    if engine is None:
        return {
            "workflow": name,
            "status": "workflow_engine_disabled",
            "message": "Enable modules.workflow_engine.enabled in config/hub_config.yaml",
            "token_budget": workflow.token_budget,
        }

    try:
        return await engine.run(name=name, args=args)
    except Exception as e:
        telemetry.log_error(f"Workflow '{name}' failed: {e}", context={"name": name, "args": args})
        return {"error": str(e), "workflow": name}


@mcp.tool()
async def plan_workflow(name: str, args: dict = None) -> dict:
    """
    Generate a review plan before running a destructive workflow.
    Use before: refactor_prep, ingest_codebase (large projects)

    Note: This feature requires crit (Phase 3). Currently returns stub.
    """
    if args is None:
        args = {}

    if name == "init_project_memory":
        return {
            "workflow": name,
            "status": "plan_ready",
            "plan": {
                "workflow": name,
                "token_budget": 500,
                "steps": ["braindrain.init_project_memory"],
                "args": {
                    "path": args.get("path", "."),
                    "dry_run": bool(args.get("dry_run", False)),
                },
            },
            "notes": [
                "Idempotent memory bootstrap.",
                "Creates .devdocs/AGENT_MEMORY.md and .cursor/hooks/state/continual-learning-index.json when missing.",
            ],
        }

    workflow = config.get_workflow(name)
    if not workflow:
        return {
            "error": f"Workflow '{name}' not found",
            "available": [wf.name for wf in config.workflows],
        }

    engine = _get_workflow_engine()
    if engine is None:
        return {
            "workflow": name,
            "status": "workflow_engine_disabled",
            "message": "Enable modules.workflow_engine.enabled in config/hub_config.yaml to run workflows",
            "plan": {
                "workflow": name,
                "token_budget": workflow.token_budget,
                "steps": workflow.steps,
                "args": args,
            },
        }

    return engine.plan(name=name, args=args)


@mcp.tool()
async def get_token_stats() -> dict:
    """
    Session cost tracking: tokens saved, cost avoided, cache hits by module.
    Call anytime to see BRAINDRAIN's impact on your token usage.
    """
    stats = registry.get_stats()

    return {
        "session": telemetry.snapshot(),
        "registry": stats,
        "project": config.get("project_name"),
        "version": config.get("version"),
    }


@mcp.tool()
async def get_available_tools() -> dict:
    """
    Get list of all available MCP tools with their loading status.
    Shows which tools are HOT (always loaded) vs DEFERRED (loaded on demand).
    """
    hot_tools = []
    deferred_tools = []

    for tool in config.mcp_tools:
        tool_info = {
            "name": tool.name,
            "description": tool.description,
            "tags": tool.tags,
        }
        if tool.hot:
            hot_tools.append(tool_info)
        else:
            deferred_tools.append(tool_info)

    return {
        "hot_tools": hot_tools,
        "hot_count": len(hot_tools),
        "deferred_tools": deferred_tools,
        "deferred_count": len(deferred_tools),
    }


@mcp.tool()
async def route_output(
    text: str,
    source: str = "braindrain",
    intent: str | None = None,
    min_chars: int = 5000,
    force_index: bool = False,
) -> dict:
    """
    Route large text outputs through context-mode's FTS5 index to avoid dumping
    raw bytes into the model context window.

    - If content is small, returns it directly.
    - If large (or force_index), indexes into context-mode via ctx_index and returns a handle
      plus suggested ctx_search queries.
    """
    if not force_index and not should_route(text, min_chars=min_chars):
        resp = {
            "routed": False,
            "source": source,
            "bytes_raw": len(text.encode("utf-8", errors="ignore")),
            "text": text,
        }
        telemetry.record(
            tool_name="route_output",
            raw_text=text,
            actual_text=json.dumps(resp, ensure_ascii=False),
        )
        return resp

    client = _get_context_mode_client()
    if client is None:
        resp = {
            "routed": False,
            "error": "context_mode is not configured; cannot index",
            "source": source,
            "bytes_raw": len(text.encode("utf-8", errors="ignore")),
            "text_preview": text[:400],
        }
        telemetry.record(
            tool_name="route_output",
            raw_text=text,
            actual_text=json.dumps(resp, ensure_ascii=False),
        )
        return resp

    routed, md = build_routed_output(source=source, content=text, intent=intent)
    try:
        index_result = await client.index_markdown(
            content_md=md, source=source, intent=intent
        )
    except MCPProtocolError as e:
        resp = {
            "routed": False,
            "error": f"context-mode indexing failed: {e}",
            "source": source,
            "bytes_raw": routed.bytes_raw,
            "text_preview": routed.preview,
        }
        telemetry.record(
            tool_name="route_output",
            raw_text=text,
            actual_text=json.dumps(resp, ensure_ascii=False),
        )
        return resp

    resp = {
        "routed": True,
        "source": source,
        "handle": routed.handle,
        "bytes_raw": routed.bytes_raw,
        "preview": routed.preview,
        "suggested_queries": routed.suggested_queries,
        "context_mode": {
            "indexed_via": "ctx_index",
            "index_result": index_result,
        },
        "next_steps": {
            "use_ctx_search": True,
            "examples": [
                {"tool": "ctx_search", "query": q} for q in routed.suggested_queries[:3]
            ],
        },
    }
    telemetry.record(
        tool_name="route_output",
        raw_text=text,
        actual_text=json.dumps(resp, ensure_ascii=False),
        module="output_sandbox",
        meta={"handle": routed.handle, "source": source},
    )
    return resp


@mcp.tool()
async def search_index(query: str, limit: int = 5) -> dict:
    """
    Convenience wrapper for context-mode ctx_search.
    Use when you have a handle/source and want to retrieve only relevant chunks.
    """
    client = _get_context_mode_client()
    if client is None:
        resp = {"error": "context_mode is not configured; cannot search"}
        telemetry.record(
            tool_name="search_index",
            raw_text=query,
            actual_text=json.dumps(resp, ensure_ascii=False),
        )
        return resp
    try:
        results = await client.search(query=query, limit=limit)
        resp = {"query": query, "limit": limit, "results": results}
        telemetry.record(
            tool_name="search_index",
            raw_text=query,
            actual_text=json.dumps(resp, ensure_ascii=False),
        )
        return resp
    except MCPProtocolError as e:
        resp = {"error": f"context-mode search failed: {e}"}
        telemetry.record(
            tool_name="search_index",
            raw_text=query,
            actual_text=json.dumps(resp, ensure_ascii=False),
        )
        return resp


@mcp.tool()
async def get_token_dashboard() -> dict:
    """Compact token-savings dashboard (estimated tokens, Claude-focused)."""
    return telemetry.snapshot()


@mcp.tool()
async def ping() -> dict:
    """Health check - verify BRAINDRAIN is running"""
    return {
        "status": "ok",
        "service": "braindrain",
        "version": config.get("version", "1.0.1"),
        "timestamp": datetime.now().isoformat(),
    }


@mcp.tool()
def get_env_context(refresh: bool = False) -> dict:
    """
    Return a cached snapshot of the host OS environment: identity, network,
    shell, runtimes, editors, installed CLI tools, and agent behaviour hints.

    Returns a ready-to-paste AGENTS.md block plus full structured summary.

    Args:
        refresh: If True, re-run the OS probe and update the cache.
                 Default False returns the cached result instantly.

    Use this at the start of any session that involves shell commands, package
    installs, file operations, or tool invocations — so you know exactly what's
    available without discovery probing.
    """
    result = _probe_env_context(refresh=refresh)
    return {
        "cached": result["cached"],
        "probe_timestamp": result["probe_timestamp"],
        "agents_md_block": result["agents_md_block"],
        "summary": result["summary"],
    }


@mcp.tool()
def refresh_env_context() -> dict:
    """
    Re-run the full OS environment probe and update the cached snapshot.

    Run this when:
    - You've installed new tools or changed your shell config
    - You've switched machines or changed your network
    - The cached data feels stale

    Returns the fresh AGENTS.md block and structured summary.
    """
    result = _probe_env_context(refresh=True)
    return {
        "cached": False,
        "probe_timestamp": result["probe_timestamp"],
        "agents_md_block": result["agents_md_block"],
        "summary": result["summary"],
        "message": "Environment context refreshed and cached to ~/.braindrain/env_context.json",
    }


@mcp.tool()
async def prime_workspace(
    path: str = ".",
    agents: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Prime a project/workspace for AI agent use. Call this once when starting
    work in a new repo.

    Deploys braindrain Ruler templates into <path>/.ruler/ and runs
    `ruler apply` to distribute agent rule files and project-local MCP
    configs to all supported agents, then initializes project memory artifacts.

    Supported agents include: cursor, windsurf, claude, kiro, zed, codex,
    amp, goose, warp, roo, cline, continue, opencode, gemini, copilot, aider.

    Args:
        path:    Target project root. Default: current working directory.
        agents:  Specific agents to target. Default: all detected/enabled agents.
        dry_run: Preview changes without writing files.

    After priming:
    - Agents that support project-local MCP configs will have braindrain wired.
    - All agent rule files will reference the braindrain protocol.
    - Project memory files are initialized for continual-learning workflows.
    - Call get_env_context() to populate the live env block in AGENTS.md.
    """
    import asyncio
    try:
        result = await asyncio.to_thread(_prime_workspace, path, agents, dry_run)
        if not result.get("ok"):
            telemetry.log_error(f"prime_workspace failed: {result.get('error') or result.get('ruler', {}).get('stderr')}", context={"path": path, "agents": agents, "dry_run": dry_run})
        
        telemetry.record(
            tool_name="prime_workspace",
            raw_text=path,
            actual_text=str(result.get("templates", {}).get("new_files", 0)) + " files written",
            module="tool_gate",
            meta={"target": path, "dry_run": dry_run, "agents": agents},
        )
        return result
    except Exception as e:
        telemetry.log_error(f"prime_workspace exception: {e}", context={"path": path, "agents": agents, "dry_run": dry_run})
        return {"ok": False, "error": str(e)}


@mcp.tool()
def init_project_memory(path: str = ".", dry_run: bool = False) -> dict:
    """
    Initialize project memory artifacts used by continual-learning workflows.

    Creates (if missing):
    - .devdocs/AGENT_MEMORY.md
    - .cursor/hooks/state/continual-learning-index.json

    This tool is idempotent and safe to re-run.
    """
    try:
        target = Path(path).expanduser().resolve()
        if not target.exists():
            return {"ok": False, "error": f"Path does not exist: {target}"}

        result = _initialize_project_memory(target, dry_run=dry_run)
        telemetry.record(
            tool_name="init_project_memory",
            raw_text=path,
            actual_text=json.dumps(result, ensure_ascii=False),
            module="tool_gate",
            meta={"target": str(target), "dry_run": dry_run},
        )
        return result
    except Exception as e:
        telemetry.log_error(
            f"init_project_memory exception: {e}",
            context={"path": path, "dry_run": dry_run},
        )
        return {"ok": False, "error": str(e)}


def main():
    """Entry point for running the server"""
    import sys

    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"

    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="sse", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
