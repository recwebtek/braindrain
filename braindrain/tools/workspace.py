"""Workspace tool implementations extracted from server.py."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def get_env_context_impl(probe_env_context, refresh: bool = False) -> dict:
    result = probe_env_context(refresh=refresh)
    return {
        "cached": result["cached"],
        "probe_timestamp": result["probe_timestamp"],
        "agents_md_block": result["agents_md_block"],
        "summary": result["summary"],
    }


def refresh_env_context_impl(probe_env_context) -> dict:
    result = probe_env_context(refresh=True)
    return {
        "cached": False,
        "probe_timestamp": result["probe_timestamp"],
        "agents_md_block": result["agents_md_block"],
        "summary": result["summary"],
        "message": "Environment context refreshed and cached to ~/.braindrain/env_context.json",
    }


async def prime_workspace_impl(prime_workspace_fn, compact_prime_result_for_mcp, telemetry, path: str = ".", agents: list[str] | None = None, dry_run: bool = False, sync_templates: bool = False, sync_subagents: bool = False, all_agents: bool = False, local_only: bool = True, patch_user_cursor_mcp: bool = False, codex_agent_targets: list[str] | None = None, compact_mcp_response: bool = True, bundle: str = "core") -> dict:
    import asyncio
    try:
        result = await asyncio.to_thread(
            prime_workspace_fn,
            path,
            agents,
            dry_run,
            sync_templates,
            sync_subagents,
            all_agents,
            local_only,
            patch_user_cursor_mcp,
            bundle,
            codex_agent_targets,
        )
        if compact_mcp_response and isinstance(result, dict):
            result = compact_prime_result_for_mcp(result)
        if not result.get("ok"):
            telemetry.log_error(
                f"prime_workspace failed: {result.get('error') or result.get('ruler', {}).get('stderr')}",
                context={"path": path, "agents": agents, "dry_run": dry_run},
            )
        return result
    except Exception as e:
        telemetry.log_error(
            f"prime_workspace exception: {e}",
            context={"path": path, "agents": agents, "dry_run": dry_run, "sync_templates": sync_templates, "sync_subagents": sync_subagents, "all_agents": all_agents, "patch_user_cursor_mcp": patch_user_cursor_mcp, "codex_agent_targets": codex_agent_targets, "bundle": bundle},
        )
        return {"ok": False, "error": str(e)}


def init_project_memory_impl(initialize_project_memory_fn, telemetry, path: str = ".", dry_run: bool = False) -> dict:
    try:
        target = Path(path).expanduser().resolve()
        if not target.exists():
            return {"ok": False, "error": f"Path does not exist: {target}"}
        return initialize_project_memory_fn(target, dry_run=dry_run)
    except Exception as e:
        telemetry.log_error(f"init_project_memory exception: {e}", context={"path": path, "dry_run": dry_run})
        return {"ok": False, "error": str(e)}


async def ping_impl(config) -> dict:
    return {"status": "ok", "service": "braindrain", "version": config.get("version", "1.0.3"), "timestamp": datetime.now().isoformat()}

