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
from braindrain.dream import DreamEngine
from braindrain.env_probe import get_env_context as _probe_env_context
from braindrain.memory_learning import can_promote_memory, evaluate_lesson_candidate
from braindrain.observer import BrainEvent, ObserverStore
from braindrain.output_router import build_routed_output, should_route
from braindrain.scriptlib import (
    describe as _scriptlib_describe,
    disable as _scriptlib_disable,
    enable as _scriptlib_enable,
    fork as _scriptlib_fork,
    global_scriptlib_root as _global_scriptlib_root,
    harvest_workspace as _scriptlib_harvest_workspace,
    is_enabled as _scriptlib_is_enabled,
    project_scriptlib_root as _project_scriptlib_root,
    record_result as _scriptlib_record_result,
    refresh_index as _scriptlib_refresh_index,
    run as _scriptlib_run,
    search as _scriptlib_search,
)
from braindrain.telemetry import telemetry_from_config
from braindrain.tool_registry import ToolRegistry
from braindrain.workflow_engine import WorkflowEngine
from braindrain.session import EpisodeRecord, SessionStore
from braindrain.wiki_brain import WikiBrain
from braindrain.workspace_primer import (
    initialize_project_memory as _initialize_project_memory,
)
from braindrain.workspace_primer import compact_prime_result_for_mcp
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
_observer_store: Optional[ObserverStore] = None
_session_store: Optional[SessionStore] = None
_wiki_brain: Optional[WikiBrain] = None
_dream_engine: Optional[DreamEngine] = None


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


def _resolve_path(path_value: str | None, fallback: str) -> Path:
    raw = path_value or fallback
    return Path(raw).expanduser()


def _get_observer_store() -> ObserverStore:
    global _observer_store
    if _observer_store is not None:
        return _observer_store
    observer_cfg = config.get("observer", {}) or {}
    db_path = _resolve_path(observer_cfg.get("storage_path"), "~/.braindrain/events.db")
    max_events = int(observer_cfg.get("ring_buffer_max", 10_000) or 10_000)
    _observer_store = ObserverStore(db_path=db_path, max_events=max_events)
    return _observer_store


def _get_session_store() -> SessionStore:
    global _session_store
    if _session_store is not None:
        return _session_store
    sessions_cfg = config.get("sessions", {}) or {}
    db_path = _resolve_path(sessions_cfg.get("storage_path"), "~/.braindrain/sessions.db")
    inactivity_timeout = int(sessions_cfg.get("inactivity_timeout_minutes", 30) or 30)
    _session_store = SessionStore(
        db_path=db_path,
        inactivity_timeout_minutes=inactivity_timeout,
    )
    return _session_store


def _get_wiki_brain() -> WikiBrain:
    global _wiki_brain
    if _wiki_brain is not None:
        return _wiki_brain
    wiki_cfg = config.get("wiki_brain", {}) or {}
    recall_cfg = wiki_cfg.get("recall", {}) or {}
    forgetting_cfg = wiki_cfg.get("forgetting", {}) or {}
    db_path = _resolve_path(wiki_cfg.get("storage_path"), "~/.braindrain/wiki-brain/brain.db")
    _wiki_brain = WikiBrain(
        db_path=db_path,
        similarity_weight=float(recall_cfg.get("similarity_weight", 0.5) or 0.5),
        recency_weight=float(recall_cfg.get("recency_weight", 0.3) or 0.3),
        importance_weight=float(recall_cfg.get("importance_weight", 0.2) or 0.2),
        recency_half_life_days=float(recall_cfg.get("recency_half_life_days", 30.0) or 30.0),
        decay_half_life_days=float(forgetting_cfg.get("decay_half_life_days", 90.0) or 90.0),
        prune_threshold=float(forgetting_cfg.get("prune_threshold", 0.05) or 0.05),
        consolidation_similarity=float(forgetting_cfg.get("consolidation_similarity", 0.92) or 0.92),
    )
    return _wiki_brain


def _get_dream_engine() -> DreamEngine:
    global _dream_engine
    if _dream_engine is not None:
        return _dream_engine
    dreaming_cfg = config.get("dreaming", {}) or {}
    storage_cfg = dreaming_cfg.get("storage", {}) or {}
    engine_cfg = {
        "policy_version": dreaming_cfg.get("policy_version", "memory-lessons-v1"),
        "quiet_minutes": int(dreaming_cfg.get("quiet_minutes", 30) or 30),
        "lookback_hours": int(dreaming_cfg.get("lookback_hours", 72) or 72),
        "max_episode_scan": int(dreaming_cfg.get("max_episode_scan", 50) or 50),
        "max_event_scan": int(dreaming_cfg.get("max_event_scan", 250) or 250),
        "max_session_scan": int(dreaming_cfg.get("max_session_scan", 20) or 20),
        "weights": dreaming_cfg.get("weights", {}) or {},
        "deep": dreaming_cfg.get("deep", {}) or {},
        "storage_dir": storage_cfg.get("base_dir", "~/.braindrain/dreaming"),
    }
    provider_cfg = config.get("provider_context", {}) or {}
    _dream_engine = DreamEngine(
        observer_store=_get_observer_store(),
        session_store=_get_session_store(),
        wiki_brain=_get_wiki_brain(),
        config=engine_cfg,
        provider_context=provider_cfg,
    )
    return _dream_engine


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
                "Creates .braindrain/AGENT_MEMORY.md and .cursor/hooks/state/continual-learning-index.json when missing.",
                "Migrates .devdocs/AGENT_MEMORY.md to .braindrain/ if the legacy path exists.",
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
def evaluate_memory_candidate(candidate: str) -> dict:
    """Evaluate whether a memory candidate can be promoted safely."""
    policy = (config.get("memory_learning", {}) or {}).get("promotion", {}) or {}
    return can_promote_memory(candidate, policy)


@mcp.tool()
def evaluate_lesson_candidate_tool(
    problem: str,
    action: str,
    outcome: str,
    local_critique: str = "",
    global_reflection: str = "",
    evidence_refs: list[str] | None = None,
) -> dict:
    """Evaluate grounded episode content for lesson/playbook promotion."""
    lessons_cfg = (config.get("lessons", {}) or {}).get("promotion", {}) or {}
    return evaluate_lesson_candidate(
        problem=problem,
        action=action,
        outcome=outcome,
        local_critique=local_critique,
        global_reflection=global_reflection,
        evidence_refs=evidence_refs or [],
        policy=lessons_cfg,
    )


@mcp.tool()
def record_observer_event(
    session_id: str,
    event_type: str,
    tool_name: str | None = None,
    files_touched: list[str] | None = None,
    token_cost: int = 0,
    duration_ms: int = 0,
    metadata: dict | None = None,
    timestamp: float | None = None,
) -> dict:
    """Record an observer event into the episodic ring buffer."""
    event = BrainEvent(
        timestamp=float(timestamp or datetime.now().timestamp()),
        session_id=session_id,
        event_type=event_type,
        tool_name=tool_name,
        files_touched=files_touched or [],
        token_cost=token_cost,
        duration_ms=duration_ms,
        metadata=metadata or {},
    )
    return _get_observer_store().record_event(event)


@mcp.tool()
def get_event_stats(session_id: str | None = None) -> dict:
    """Get observer event counts and latest activity."""
    return _get_observer_store().get_event_stats(session_id=session_id)


@mcp.tool()
def touch_session(
    session_id: str,
    tool_name: str | None = None,
    files_modified: list[str] | None = None,
    key_decision: str | None = None,
    error: str | None = None,
    token_delta: int = 0,
    timestamp: float | None = None,
) -> dict:
    """Update session summary telemetry."""
    summary = _get_session_store().touch_session(
        session_id=session_id,
        tool_name=tool_name,
        files_modified=files_modified,
        key_decision=key_decision,
        error=error,
        token_delta=token_delta,
        timestamp=timestamp,
    )
    return summary.__dict__


@mcp.tool()
def get_session_summary(session_id: str | None = None) -> dict:
    """Return latest session summary or a specific session."""
    summary = _get_session_store().get_session_summary(session_id=session_id)
    return summary.__dict__ if summary else {"status": "not_found", "session_id": session_id}


@mcp.tool()
def record_episode(
    session_id: str,
    problem: str,
    context: str,
    action: str,
    outcome: str,
    evidence_refs: list[str] | None = None,
    local_critique: str = "",
    global_reflection: str = "",
    confidence: float = 0.5,
    tags: list[str] | None = None,
    episode_id: str = "",
) -> dict:
    """Store a grounded episode candidate for future dream consolidation."""
    episode = EpisodeRecord(
        episode_id=episode_id,
        session_id=session_id,
        problem=problem,
        context=context,
        action=action,
        outcome=outcome,
        evidence_refs=evidence_refs or [],
        local_critique=local_critique,
        global_reflection=global_reflection,
        confidence=confidence,
        tags=tags or [],
    )
    return _get_session_store().record_episode(episode)


@mcp.tool()
def list_episodes(session_id: str | None = None, limit: int = 20) -> dict:
    """List recent episodes (optionally by session)."""
    episodes = _get_session_store().list_episodes(session_id=session_id, limit=limit)
    return {"episodes": [episode.__dict__ for episode in episodes], "count": len(episodes)}


@mcp.tool()
def store_fact(
    content: str,
    record_class: str = "semantic",
    title: str | None = None,
    source: str = "manual",
    category: str = "general",
    importance: float = 0.5,
    confidence: float = 0.5,
    tags: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    metadata: dict | None = None,
) -> dict:
    """Store a durable semantic/procedural/lesson record."""
    return _get_wiki_brain().store_fact(
        content=content,
        record_class=record_class,
        title=title,
        source=source,
        category=category,
        importance=importance,
        confidence=confidence,
        tags=tags or [],
        evidence_refs=evidence_refs or [],
        metadata=metadata or {},
    )


@mcp.tool()
def query_facts(
    query: str = "",
    record_class: str | None = None,
    limit: int = 10,
    include_superseded: bool = False,
) -> dict:
    """Query durable records from Wiki-Brain."""
    records = _get_wiki_brain().query_records(
        query=query,
        record_class=record_class,
        limit=limit,
        include_superseded=include_superseded,
    )
    return {"records": [record.__dict__ for record in records], "count": len(records)}


@mcp.tool()
def cognitive_recall(query: str, record_class: str | None = None, limit: int = 5) -> dict:
    """Score and rank durable recall candidates."""
    return {
        "results": _get_wiki_brain().cognitive_recall(
            query=query,
            record_class=record_class,
            limit=limit,
        )
    }


@mcp.tool()
def review_playbook(query: str = "", limit: int = 10) -> dict:
    """Review active lesson/playbook records."""
    return {"records": _get_wiki_brain().review_playbook(query=query, limit=limit)}


@mcp.tool()
def record_memory_metric(
    metric_type: str,
    value: float = 1.0,
    source: str = "manual",
    metadata: dict | None = None,
) -> dict:
    """Record durable memory-system metric events."""
    return _get_wiki_brain().record_metric(
        metric_type,
        value=value,
        source=source,
        metadata=metadata or {},
    )


@mcp.tool()
def get_memory_metrics() -> dict:
    """Get memory metrics and durable record counts."""
    return _get_wiki_brain().get_metrics_snapshot()


@mcp.tool()
def get_provider_context_policy() -> dict:
    """Return provider boundary strategy for durable vs ephemeral context."""
    return config.get("provider_context", {}) or {"strategy": "provider-native-first"}


@mcp.tool()
def run_dream(mode: str = "full", force: bool = False) -> dict:
    """Run Light/REM/Deep memory consolidation."""
    return _get_dream_engine().run(mode=mode, force=force)


@mcp.tool()
def get_dream_status() -> dict:
    """Read latest dream consolidation status."""
    return _get_dream_engine().get_status()


@mcp.tool()
async def ping() -> dict:
    """Health check - verify BRAINDRAIN is running"""
    return {
        "status": "ok",
        "service": "braindrain",
        "version": config.get("version", "1.0.3"),
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
def scriptlib_enable(
    path: str = ".",
    scope: str = "project",
    harvest: bool = True,
    dry_run: bool = False,
) -> dict:
    """Enable scriptlib for the project or global scope. Project enable harvests scripts by default."""
    result = _scriptlib_enable(path, scope=scope, harvest=harvest, dry_run=dry_run)
    telemetry.record(
        tool_name="scriptlib_enable",
        raw_text=path,
        actual_text=json.dumps(result, ensure_ascii=False),
        module="tool_gate",
        meta={"scope": scope, "harvest": harvest, "dry_run": dry_run},
    )
    return result


@mcp.tool()
def scriptlib_disable(
    path: str = ".",
    scope: str = "project",
    dry_run: bool = False,
) -> dict:
    """Disable scriptlib for the project or global scope without removing harvested files."""
    result = _scriptlib_disable(path, scope=scope, dry_run=dry_run)
    telemetry.record(
        tool_name="scriptlib_disable",
        raw_text=path,
        actual_text=json.dumps(result, ensure_ascii=False),
        module="tool_gate",
        meta={"scope": scope, "dry_run": dry_run},
    )
    return result


@mcp.tool()
def scriptlib_harvest_workspace(
    path: str = ".",
    dry_run: bool = False,
) -> dict:
    """Copy useful script-like files from the workspace into the local scriptlib catalog."""
    result = _scriptlib_harvest_workspace(project_path=path, dry_run=dry_run)
    telemetry.record(
        tool_name="scriptlib_harvest_workspace",
        raw_text=path,
        actual_text=json.dumps(result, ensure_ascii=False),
        module="tool_gate",
        meta={"dry_run": dry_run},
    )
    return result


@mcp.tool()
def scriptlib_search(
    query: str,
    path: str = ".",
    capability: str | None = None,
    language: str | None = None,
    harness: str | None = None,
    effect_tier: str | None = None,
    limit: int = 5,
) -> dict:
    """Search project and global scriptlib entries with lightweight lexical ranking."""
    result = _scriptlib_search(
        query,
        project_path=path,
        capability=capability,
        language=language,
        harness=harness,
        effect_tier=effect_tier,
        limit=limit,
    )
    telemetry.record(
        tool_name="scriptlib_search",
        raw_text=query,
        actual_text=json.dumps(result, ensure_ascii=False),
        module="tool_gate",
        meta={"path": path, "language": language, "harness": harness, "limit": limit},
    )
    return result


@mcp.tool()
def scriptlib_describe(
    script_id: str,
    path: str = ".",
    variant: str | None = None,
) -> dict:
    """Return full metadata for a scriptlib entry."""
    result = _scriptlib_describe(script_id, project_path=path, variant=variant)
    telemetry.record(
        tool_name="scriptlib_describe",
        raw_text=script_id,
        actual_text=json.dumps(result, ensure_ascii=False),
        module="tool_gate",
        meta={"path": path, "variant": variant},
    )
    return result


@mcp.tool()
def scriptlib_run(
    script_id: str,
    path: str = ".",
    variant: str | None = None,
    args: list[str] | None = None,
    dry_run: bool = False,
    timeout_seconds: int = 60,
) -> dict:
    """Run a scriptlib entry using native copy or restored source context."""
    result = _scriptlib_run(
        script_id,
        project_path=path,
        variant=variant,
        args=args,
        dry_run=dry_run,
        timeout_seconds=timeout_seconds,
    )
    telemetry.record(
        tool_name="scriptlib_run",
        raw_text=script_id,
        actual_text=json.dumps(
            {
                "ok": result.get("ok"),
                "script_id": result.get("script_id"),
                "execution_mode": result.get("execution_mode"),
                "returncode": result.get("returncode"),
                "error": result.get("error"),
            },
            ensure_ascii=False,
        ),
        module="tool_gate",
        meta={"path": path, "variant": variant, "dry_run": dry_run},
    )
    return result


@mcp.tool()
def scriptlib_fork(
    script_id: str,
    new_variant_or_version: str,
    path: str = ".",
) -> dict:
    """Fork an existing scriptlib entry into a new version for safe modification."""
    result = _scriptlib_fork(
        script_id,
        project_path=path,
        new_variant_or_version=new_variant_or_version,
    )
    telemetry.record(
        tool_name="scriptlib_fork",
        raw_text=script_id,
        actual_text=json.dumps(result, ensure_ascii=False),
        module="tool_gate",
        meta={"path": path, "new_variant_or_version": new_variant_or_version},
    )
    return result


@mcp.tool()
def scriptlib_record_result(
    script_id: str,
    outcome: str,
    path: str = ".",
    variant: str | None = None,
    notes: str | None = None,
    duration_ms: int | None = None,
    promote_status: str | None = None,
    validate_native_copy: bool = False,
) -> dict:
    """Record a run result and update success score, mistakes, and validation state."""
    result = _scriptlib_record_result(
        script_id,
        project_path=path,
        variant=variant,
        outcome=outcome,
        notes=notes,
        duration_ms=duration_ms,
        promote_status=promote_status,
        validate_native_copy=validate_native_copy,
    )
    telemetry.record(
        tool_name="scriptlib_record_result",
        raw_text=script_id,
        actual_text=json.dumps(result, ensure_ascii=False),
        module="tool_gate",
        meta={
            "path": path,
            "variant": variant,
            "outcome": outcome,
            "promote_status": promote_status,
            "validate_native_copy": validate_native_copy,
        },
    )
    return result


@mcp.tool()
def scriptlib_refresh_index(
    path: str = ".",
    scope: str = "project",
    dry_run: bool = False,
) -> dict:
    """Rebuild project, global, or combined scriptlib indexes and catalogs."""
    if scope not in {"project", "global", "all"}:
        return {"ok": False, "error": f"Unsupported scope: {scope}"}
    roots = []
    if scope in {"project", "all"}:
        roots.append(_project_scriptlib_root(path))
    if scope in {"global", "all"}:
        roots.append(_global_scriptlib_root())

    results = []
    for root in roots:
        if not _scriptlib_is_enabled(root):
            results.append({"ok": True, "root": str(root), "skipped": "scriptlib_disabled"})
            continue
        results.append(_scriptlib_refresh_index(root, dry_run=dry_run))

    payload = {"ok": all(item.get("ok", False) for item in results), "scope": scope, "results": results}
    telemetry.record(
        tool_name="scriptlib_refresh_index",
        raw_text=path,
        actual_text=json.dumps(payload, ensure_ascii=False),
        module="tool_gate",
        meta={"scope": scope, "dry_run": dry_run},
    )
    return payload


@mcp.tool()
async def prime_workspace(
    path: str = ".",
    agents: list[str] | None = None,
    dry_run: bool = False,
    sync_templates: bool = False,
    sync_subagents: bool = False,
    all_agents: bool = False,
    local_only: bool = True,
    patch_user_cursor_mcp: bool = False,
    codex_agent_targets: list[str] | None = None,
    compact_mcp_response: bool = True,
    bundle: str = "core",
) -> dict:
    """
    Prime a project/workspace for AI agent use.

    First run: detects current IDE/CLI, deploys minimal Ruler templates, writes
    .braindrain/primed.json, initializes project memory under .braindrain/.
    Subsequent runs: updates templates (if sync_templates=True), optionally syncs
    subagent files (if sync_subagents=True), and re-applies.

    Agent resolution order:
      1. agents list (explicit override).
      2. all_agents=True → full template, no --agents filter (all local entries).
      3. Default: auto-detect from env vars / dotfolders → single best-fit agent.

    Args:
        path:           Target project root. Default: current working directory.
        agents:         Explicit agent ids (e.g. ["cursor", "claude"]).
        dry_run:        Preview changes without writing files.
        sync_templates: Update existing .ruler files with timestamped backups.
        sync_subagents: Update existing .cursor/agents/*.md from
            config/templates/agents with timestamped backups (create-only by default);
            when Codex is in scope, also updates the managed block in .codex/config.toml.
        all_agents:     Deploy full template and apply all configured agents.
        local_only:     Pass --local-only to ruler apply (default True).
        patch_user_cursor_mcp: If True, also patch ~/.cursor/mcp.json with
            serverName entries (fixes Cursor allowlist warning for user-braindrain).
        codex_agent_targets: Optional relative target paths for codex subagent
            file deployment. Default: [".codex/agents"].
        compact_mcp_response: If True (default), return a smaller dict so the MCP
            client is less likely to hit ClosedResourceError on large tool results.
        bundle: Bundle manifest to use from config/bundles/<name>.yaml.

    After priming:
    - Agents that support project-local MCP configs will have braindrain wired.
    - Agent rule files will reference the braindrain protocol.
    - When Cursor is in the resolved agent set, ``config/templates/cursor/`` is
      copied to ``.cursor/hooks.json`` and ``.cursor/hooks/*.sh`` (see result
      ``cursor_hooks``; use sync_templates to refresh existing hook files).
    - Project memory is initialized under .braindrain/ (gitignored).
    - Call get_env_context() to populate the live env block.
    """
    import asyncio
    try:
        result = await asyncio.to_thread(
            _prime_workspace,
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

        telemetry.record(
            tool_name="prime_workspace",
            raw_text=path,
            actual_text=json.dumps(
                {
                    "new_files": result.get("templates", {}).get("new_files", 0),
                    "updated_files": result.get("templates", {}).get("updated_files", 0),
                },
                ensure_ascii=False,
            ),
            module="tool_gate",
            meta={
                "target": path,
                "dry_run": dry_run,
                "sync_templates": sync_templates,
                "sync_subagents": sync_subagents,
                "all_agents": all_agents,
                "local_only": local_only,
                "resolved_agents": result.get("resolved_agents"),
                "detect_method": result.get("detect_method"),
                "cursor_rules": result.get("cursor_rules"),
                "gitignore_protocol": result.get("gitignore_protocol"),
                "cursor_mcp_json": result.get("cursor_mcp_json"),
                "subagents": result.get("subagents"),
                "codex_subagent_config": result.get("codex_subagent_config"),
                "patch_user_cursor_mcp": patch_user_cursor_mcp,
                "compact_mcp_response": compact_mcp_response,
                "bundle": bundle,
            },
        )
        return result
    except Exception as e:
        telemetry.log_error(
            f"prime_workspace exception: {e}",
            context={
                "path": path,
                "agents": agents,
                "dry_run": dry_run,
                "sync_templates": sync_templates,
                "sync_subagents": sync_subagents,
                "all_agents": all_agents,
                "patch_user_cursor_mcp": patch_user_cursor_mcp,
                "codex_agent_targets": codex_agent_targets,
                "bundle": bundle,
            },
        )
        return {"ok": False, "error": str(e)}


@mcp.tool()
def init_project_memory(path: str = ".", dry_run: bool = False) -> dict:
    """
    Initialize project memory artifacts used by continual-learning workflows.

    Creates (if missing):
    - .braindrain/AGENT_MEMORY.md  (migrated from .devdocs/ on first run if present)
    - .cursor/hooks/state/continual-learning-index.json

    Both paths are gitignored. This tool is idempotent and safe to re-run.
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
        # No banner: FastMCP prints ASCII + update notice to stderr; Cursor MCP logs stderr as [error].
        mcp.run(transport="stdio", show_banner=False)
    else:
        mcp.run(transport="sse", port=int(os.environ.get("PORT", "8000")), show_banner=False)


if __name__ == "__main__":
    main()
