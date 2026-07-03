"""BRAINDRAIN MCP Server - FastMCP implementation"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Auto-add project root to path so braindrain can be imported without PYTHONPATH
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from dotenv import load_dotenv
from fastmcp import FastMCP

from braindrain.config import Config
from braindrain.config_schema import ConfigValidationError
from braindrain.context_mode_client import ContextModeClient
from braindrain.dream import DreamEngine
from braindrain.env_probe import get_env_context as _probe_env_context
from braindrain.exec_path import ensure_node_path_in_environ
from braindrain.instrumentation import make_observe_mcp_tool
from braindrain.mcp_apps import register_mcp_app_resources, register_mcp_app_tools
from braindrain.mcp_catalog import export_mcp_catalog_async
from braindrain.memory_learning import can_promote_memory, evaluate_lesson_candidate
from braindrain.observer import BrainEvent, ObserverStore
from braindrain.output_router import should_route
from braindrain.scriptlib import (
    apply_update as _scriptlib_apply_update,
)
from braindrain.scriptlib import (
    catalog_status as _scriptlib_catalog_status,
)
from braindrain.scriptlib import (
    describe as _scriptlib_describe,
)
from braindrain.scriptlib import (
    disable as _scriptlib_disable,
)
from braindrain.scriptlib import (
    enable as _scriptlib_enable,
)
from braindrain.scriptlib import (
    fork as _scriptlib_fork,
)
from braindrain.scriptlib import (
    global_scriptlib_root as _global_scriptlib_root,
)
from braindrain.scriptlib import (
    harvest_workspace as _scriptlib_harvest_workspace,
)
from braindrain.scriptlib import (
    is_enabled as _scriptlib_is_enabled,
)
from braindrain.scriptlib import (
    list_updates as _scriptlib_list_updates,
)
from braindrain.scriptlib import (
    project_scriptlib_root as _project_scriptlib_root,
)
from braindrain.scriptlib import (
    promote as _scriptlib_promote,
)
from braindrain.scriptlib import (
    record_result as _scriptlib_record_result,
)
from braindrain.scriptlib import (
    refresh_index as _scriptlib_refresh_index,
)
from braindrain.scriptlib import (
    run as _scriptlib_run,
)
from braindrain.scriptlib import (
    run_maintenance as _scriptlib_run_maintenance,
)
from braindrain.scriptlib import (
    search as _scriptlib_search,
)
from braindrain.session import SessionStore
from braindrain.session_compaction import (
    retrieval_hint,
)
from braindrain.task_manager import TaskManager
from braindrain.telemetry import telemetry_from_config
from braindrain.token_checkpoints import append_checkpoint as _append_token_checkpoint
from braindrain.tool_registry import ToolRegistry
from braindrain.tools import memory as memory_tools
from braindrain.tools import output_models
from braindrain.tools import scriptlib as scriptlib_tools
from braindrain.tools import tokens as token_tools
from braindrain.tools import workflows as workflow_tools
from braindrain.tools import workspace as workspace_tools
from braindrain.updater import UpdateError as _HubUpdateError
from braindrain.updater import apply_update as _apply_hub_update
from braindrain.updater import check_update as _check_hub_update
from braindrain.updater import load_update_state as _load_update_state
from braindrain.wiki_brain import WikiBrain
from braindrain.workflow_engine import WorkflowEngine
from braindrain.workspace_primer import compact_prime_result_for_mcp
from braindrain.workspace_primer import (
    initialize_project_memory as _initialize_project_memory,
)
from braindrain.workspace_primer import (
    list_prime_snapshots as _list_prime_snapshots,
)
from braindrain.workspace_primer import prime as _prime_workspace
from braindrain.workspace_primer import (
    restore_prime_snapshot as _restore_prime_snapshot,
)

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

ensure_node_path_in_environ()

try:
    config = Config(CONFIG_PATH)
except FileNotFoundError as exc:
    print(f"[braindrain] {exc}", file=sys.stderr)
    raise SystemExit(1) from exc
except ConfigValidationError as exc:
    print(f"[braindrain] Invalid hub_config.yaml: {exc}", file=sys.stderr)
    raise SystemExit(1) from exc
except Exception as exc:
    print(f"[braindrain] Failed to load config from {CONFIG_PATH}: {exc}", file=sys.stderr)
    raise SystemExit(1) from exc
registry = ToolRegistry(config.data)
telemetry = telemetry_from_config(config.get("cost_tracking", {}) or {})

_context_mode_client: ContextModeClient | None = None
_workflow_engine: WorkflowEngine | None = None
_observer_store: ObserverStore | None = None
_session_store: SessionStore | None = None
_wiki_brain: WikiBrain | None = None
_dream_engine: DreamEngine | None = None
_task_manager: TaskManager | None = None


def _provenance_settings() -> dict:
    defaults = {
        "enabled": True,
        "date_format": "%Y-%m-%d",
        "chat_footer": {"enabled": True, "scope": "all_agents"},
        "plan_metadata": {"enabled": True},
        "subagent_trace": {
            "enabled": True,
            "path": ".braindrain/plan-reports/model-trace.jsonl",
        },
    }
    configured = config.get("provenance", {}) or {}
    merged = dict(defaults)
    merged.update(configured)
    merged["chat_footer"] = {
        **defaults["chat_footer"],
        **(configured.get("chat_footer", {}) if isinstance(configured, dict) else {}),
    }
    merged["plan_metadata"] = {
        **defaults["plan_metadata"],
        **(configured.get("plan_metadata", {}) if isinstance(configured, dict) else {}),
    }
    merged["subagent_trace"] = {
        **defaults["subagent_trace"],
        **(configured.get("subagent_trace", {}) if isinstance(configured, dict) else {}),
    }
    return merged


def _effective_model_name(explicit_model: str | None = None) -> str:
    if explicit_model and explicit_model.strip():
        return explicit_model.strip()
    for env_key in (
        "BRAINDRAIN_ACTIVE_MODEL",
        "CURSOR_ACTIVE_MODEL",
        "CURSOR_MODEL",
        "MODEL_NAME",
    ):
        value = os.environ.get(env_key, "").strip()
        if value:
            return value
    return "auto"


def _effective_cursor_mode() -> str:
    mode = (
        (
            os.environ.get("CURSOR_MODEL_SELECTION", "")
            or os.environ.get("BRAINDRAIN_CURSOR_MODE", "")
        )
        .strip()
        .lower()
    )
    if mode in {"manual", "auto"}:
        return mode
    return "auto"


def _get_context_mode_client() -> ContextModeClient | None:
    global _context_mode_client
    if _context_mode_client is not None:
        return _context_mode_client

    tool = config.get_tool("context_mode")
    if not tool or not tool.command:
        return None

    _context_mode_client = ContextModeClient(tool.command)
    return _context_mode_client


def _get_workflow_engine() -> WorkflowEngine | None:
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
        consolidation_similarity=float(
            forgetting_cfg.get("consolidation_similarity", 0.92) or 0.92
        ),
    )
    return _wiki_brain


def _get_dream_engine() -> DreamEngine:
    global _dream_engine
    if _dream_engine is not None:
        return _dream_engine
    dreaming_cfg = config.get("dreaming", {}) or {}
    storage_cfg = dreaming_cfg.get("storage", {}) or {}
    triggers = (
        dreaming_cfg.get("triggers") if isinstance(dreaming_cfg.get("triggers"), dict) else {}
    )
    host_idle = (
        triggers.get("macos_host_idle") if isinstance(triggers.get("macos_host_idle"), dict) else {}
    )
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
        "bypass_session_quiet": bool(host_idle.get("bypass_session_quiet", True)),
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


def _get_task_manager() -> TaskManager:
    global _task_manager
    if _task_manager is not None:
        return _task_manager
    _task_manager = TaskManager()
    return _task_manager


def _search_index_fallback(query: str, limit: int) -> list[dict]:
    """Fallback search when context-mode is unavailable."""
    records = _get_wiki_brain().query_records(query=query, limit=limit, include_superseded=False)
    results: list[dict] = []
    for record in records:
        results.append(
            {
                "record_id": record.record_id,
                "title": record.title,
                "content": record.content,
                "record_class": record.record_class,
                "source": record.source,
                "updated_at": record.updated_at,
            }
        )
    return results


_DEFAULT_HOT_TOOLS = frozenset(
    {
        "route_output",
        "search_index",
        "search_tools",
        "get_env_context",
        "refresh_env_context",
        "touch_session",
        "get_session_summary",
        "record_episode",
        "list_episodes",
        "store_fact",
        "query_facts",
        "cognitive_recall",
        "get_memory_metrics",
    }
)


def _observer_enabled() -> bool:
    cfg = config.get("observer", {}) or {}
    return bool(cfg.get("enabled", True))


def _observer_hash_args() -> bool:
    cfg = config.get("observer", {}) or {}
    return bool(cfg.get("hash_args", True))


def _should_wrap_tool(tool_name: str) -> bool:
    cfg = config.get("observer", {}) or {}
    if not _observer_enabled():
        return False
    if bool(cfg.get("wrap_all_tools", True)):
        return True
    hot = cfg.get("hot_tools")
    if hot:
        return tool_name in set(hot)
    return tool_name in _DEFAULT_HOT_TOOLS


observe_mcp_tool = make_observe_mcp_tool(
    telemetry=telemetry,
    observer_enabled=_observer_enabled,
    observer_store_getter=_get_observer_store,
    hash_args_enabled=_observer_hash_args,
    wrap_tool=_should_wrap_tool,
    project_root_getter=lambda: str(_project_root),
)

_original_mcp_tool = mcp.tool


def _mcp_tool_with_observer(*args, **kwargs):
    def decorator(fn):
        wrapped = observe_mcp_tool(fn) if _should_wrap_tool(fn.__name__) else fn
        return _original_mcp_tool(*args, **kwargs)(wrapped)

    if args and callable(args[0]) and not kwargs:
        fn = args[0]
        wrapped = observe_mcp_tool(fn) if _should_wrap_tool(fn.__name__) else fn
        return _original_mcp_tool(wrapped)
    return decorator


mcp.tool = _mcp_tool_with_observer


def _cost_tracking_cfg() -> dict:
    return config.get("cost_tracking", {}) or {}


def _route_threshold_chars(min_chars: int) -> int:
    cfg = _cost_tracking_cfg()
    configured = cfg.get("route_threshold_chars")
    if configured is not None:
        return int(configured)
    return min_chars


def _should_route_output(text: str, *, min_chars: int, force_inline: bool) -> bool:
    if force_inline:
        return False
    threshold = _route_threshold_chars(min_chars)
    cfg = _cost_tracking_cfg()
    if bool(cfg.get("auto_route_output", False)):
        return len(text) >= threshold
    return should_route(text, min_chars=threshold)


session_stats = {"note": "deprecated: use telemetry snapshot"}  # kept for backwards compatibility

OUTPUT_SCHEMAS = {
    "search_tools": output_models.schema_for(output_models.SearchToolsOutput),
    "get_token_dashboard": output_models.schema_for(output_models.TokenDashboardOutput),
    "get_env_context": output_models.schema_for(output_models.EnvContextOutput),
    "get_session_summary": output_models.schema_for(output_models.SessionSummaryOutput),
    "list_workflows": output_models.schema_for(output_models.ListWorkflowsOutput),
    "get_token_stats": output_models.schema_for(output_models.TokenStatsOutput),
    "search_index": output_models.schema_for(output_models.SearchIndexOutput),
    "route_output": output_models.schema_for(output_models.RouteOutputModel),
    "get_available_tools": output_models.schema_for(output_models.GetAvailableToolsOutput),
    "prime_workspace": output_models.schema_for(output_models.PrimeWorkspaceOutput),
}


@mcp.tool(output_schema=OUTPUT_SCHEMAS["search_tools"])
async def search_tools(query: str = "", top_k: int = 5) -> dict:
    """
    Search available tools by capability. Call this FIRST before any task.
    Returns lightweight references (~300 tokens total), not full definitions.

    Args:
        query: Natural-language capability query (e.g. "codebase symbols", "git operations").
        top_k: Maximum number of matching tools to return. Default: 5.
    """
    return await token_tools.search_tools_impl(registry, query=query, top_k=top_k)


@mcp.tool(output_schema=OUTPUT_SCHEMAS["list_workflows"])
async def list_workflows() -> dict:
    """
    List available workflows with descriptions and token budgets.
    Use this to see what automated tasks BRAINDRAIN can perform.
    """
    return await workflow_tools.list_workflows_impl(config)


@mcp.tool()
async def run_workflow(name: str, args: dict = None, async_mode: bool = False) -> dict:
    """
    Execute a workflow in an isolated sandbox. Returns only final summary.
    Intermediate data NEVER enters your context window.

    Args:
        name: Workflow id from list_workflows() (e.g. ingest_codebase, refactor_prep).
        args: Workflow-specific argument dict (see hub_config workflows input_examples).
        async_mode: When True, queue background execution and return a task id.
    """
    if async_mode:
        manager = _get_task_manager()
        record = await manager.submit(
            task_type="run_workflow",
            runner=lambda: workflow_tools.run_workflow_impl(
                config=config,
                telemetry=telemetry,
                get_workflow_engine=_get_workflow_engine,
                init_project_memory_fn=init_project_memory,
                prime_workspace_fn=prime_workspace,
                name=name,
                args=args,
            ),
        )
        return {
            "status": "queued",
            "task_id": record.task_id,
            "task_type": record.task_type,
            "poll_tool": "get_task_status",
        }
    return await workflow_tools.run_workflow_impl(
        config=config,
        telemetry=telemetry,
        get_workflow_engine=_get_workflow_engine,
        init_project_memory_fn=init_project_memory,
        prime_workspace_fn=prime_workspace,
        name=name,
        args=args,
    )


@mcp.tool()
async def get_task_status(task_id: str) -> dict:
    """
    Poll status/result for an async task.

    Args:
        task_id: Task id returned by async_mode-enabled tools.
    """
    return await _get_task_manager().as_dict(task_id)


@mcp.tool()
async def plan_workflow(name: str, args: dict = None) -> dict:
    """
    Generate a review plan before running a destructive workflow.
    Use before: refactor_prep, ingest_codebase (large projects)

    Note: This feature requires crit (Phase 3). Currently returns stub.

    Args:
        name: Workflow id from list_workflows().
        args: Workflow-specific argument dict to include in the plan preview.
    """
    return await workflow_tools.plan_workflow_impl(
        config=config,
        get_workflow_engine=_get_workflow_engine,
        name=name,
        args=args,
    )


@mcp.tool(output_schema=OUTPUT_SCHEMAS["get_token_stats"])
async def get_token_stats() -> dict:
    """
    Session cost tracking: tokens saved, cost avoided, cache hits by module.
    Call anytime to see BRAINDRAIN's impact on your token usage.
    """
    return await token_tools.get_token_stats_impl(
        registry=registry, telemetry=telemetry, config=config
    )


@mcp.tool(output_schema=OUTPUT_SCHEMAS["get_available_tools"])
async def get_available_tools() -> dict:
    """
    Get list of all available MCP tools with their loading status.
    Shows which tools are HOT (always loaded) vs DEFERRED (loaded on demand).
    """
    return await token_tools.get_available_tools_impl(config=config)


@mcp.tool(output_schema=OUTPUT_SCHEMAS["route_output"])
async def route_output(
    text: str,
    source: str = "braindrain",
    intent: str | None = None,
    min_chars: int = 5000,
    force_index: bool = False,
    force_inline: bool = False,
) -> dict:
    """
    Route large text outputs through context-mode's FTS5 index to avoid dumping
    raw bytes into the model context window.

    Args:
        text: Content to route or return inline when below threshold.
        source: Source label stored with the index entry. Default: braindrain.
        intent: Optional intent tag for context-mode indexing.
        min_chars: Character threshold before routing (when auto-route is off). Default: 5000.
        force_index: When True, always index regardless of size.
        force_inline: When True, skip auto-routing and return inline text when allowed.
    """
    return await token_tools.route_output_impl(
        get_context_mode_client=_get_context_mode_client,
        should_route_output=_should_route_output,
        text=text,
        source=source,
        intent=intent,
        min_chars=min_chars,
        force_index=force_index,
        force_inline=force_inline,
    )


@mcp.tool(output_schema=OUTPUT_SCHEMAS["search_index"])
async def search_index(query: str, limit: int = 5, rerank: bool | None = None) -> dict:
    """
    Convenience wrapper for context-mode ctx_search.
    Use when you have a handle/source and want to retrieve only relevant chunks.

    Primary retrieval is context-mode FTS5 — no embedding API required.

    Args:
        query: Search query or handle (e.g. handle:abc123).
        limit: Maximum number of chunks to return. Default: 5.
        rerank: Override rerank_on_search from config. None uses hub_config default.
    """
    return await token_tools.search_index_impl(
        get_context_mode_client=_get_context_mode_client,
        config=config,
        query=query,
        limit=limit,
        rerank=rerank,
        fallback_search=_search_index_fallback,
    )


@mcp.tool(output_schema=OUTPUT_SCHEMAS["get_token_dashboard"])
async def get_token_dashboard() -> dict:
    """
    Compact token-savings JSON snapshot (estimated tokens, Claude-focused).

    For an inline visual dashboard in MCP Apps hosts (Cursor 2.6+), call
    ``show_token_dashboard`` instead — this tool returns JSON only.
    """
    return telemetry.snapshot()


@mcp.tool()
def record_token_checkpoint(
    phase: str,
    task: str,
    note: str = "",
    context_tags: list[str] | None = None,
    path: str = ".",
) -> dict:
    """
    Append a schema 1.0 token checkpoint to `.braindrain/token-metrics.jsonl`.

    Args:
        phase: Checkpoint phase — start | pre_high_cost | post_high_cost | milestone_close | end.
        task: Short task identifier for this checkpoint row.
        note: Optional human-readable summary of what triggered the checkpoint.
        context_tags: Optional tags (e.g. ["search", "subagent"]) for attribution.
        path: Project root directory (not the JSONL path). Default: current working directory.
              Checkpoints write to <path>/.braindrain/token-metrics.jsonl.
    """
    cost_cfg = config.get("cost_tracking", {}) or {}
    if not bool(cost_cfg.get("enabled", True)):
        return {"ok": False, "status": "disabled", "message": "cost_tracking.enabled is false"}
    return _append_token_checkpoint(
        phase=phase,
        task=task,
        note=note,
        context_tags=context_tags,
        telemetry=telemetry,
        project_root=Path(path).resolve(),
        tool="record_token_checkpoint",
    )


@mcp.tool()
async def export_mcp_catalog(path: str = ".", dry_run: bool = False) -> dict:
    """
    Export MCP tool catalog markdown for folder-discovery.

    Writes `.braindrain/mcp-catalog/<server>/tools/*.md` from hub_config external
    servers plus native braindrain MCP tools. Use `rg` on the catalog before loading
    heavy deferred servers.

    Args:
        path: Project root for `.braindrain/mcp-catalog/` output. Default: current directory.
        dry_run: When True, return planned paths without writing files.
    """
    return await export_mcp_catalog_async(
        config=config,
        mcp_server=mcp,
        project_root=Path(path).resolve(),
        dry_run=dry_run,
    )


@mcp.tool()
def check_hub_update() -> dict:
    """
    Check whether this braindrain clone is behind its tracked git branch.

    Fetches from origin, compares local vs remote version, and writes
    `.braindrain/update-state.json`. Notify-only — does not pull changes.
    """
    repo_root = _project_root
    result = _check_hub_update(repo_root)
    cached = _load_update_state(repo_root) or {}
    result["cached_state"] = {
        "last_check": cached.get("last_check"),
        "restart_required": bool(cached.get("restart_required")),
    }
    return result


@mcp.tool()
def apply_hub_update() -> dict:
    """
    Fast-forward pull braindrain when the clone is clean and behind origin.

    Syncs dependencies when lockfiles change and runs an MCP handshake smoke
    test. The running MCP process still serves the old code until you reconnect
    or restart the braindrain MCP connection in your IDE.
    """
    try:
        return _apply_hub_update(_project_root)
    except _HubUpdateError as exc:
        return {"ok": False, "error": str(exc), "restart_required": False}


@mcp.tool()
def get_provenance_settings() -> dict:
    """Return current model provenance settings and effective defaults."""
    return memory_tools.get_provenance_settings_impl(
        provenance_settings_fn=_provenance_settings,
        effective_model_name_fn=_effective_model_name,
        effective_cursor_mode_fn=_effective_cursor_mode,
    )


@mcp.tool()
def record_model_trace_event(
    actor: str,
    model_name: str = "",
    event: str = "run",
    source: str = "manual",
    metadata: dict | None = None,
) -> dict:
    """
    Append a machine-local model provenance event for audits and plan reports.

    Args:
        actor: Agent or subagent name (e.g. coordinator, architect).
        model_name: Model id override; empty uses effective model from host/config.
        event: Event type (e.g. run, plan, audit). Default: run.
        source: Provenance source label (e.g. manual, subagent). Default: manual.
        metadata: Optional extra fields attached to the trace row.
    """
    return memory_tools.record_model_trace_event_impl(
        provenance_settings_fn=_provenance_settings,
        effective_model_name_fn=_effective_model_name,
        effective_cursor_mode_fn=_effective_cursor_mode,
        telemetry=telemetry,
        actor=actor,
        model_name=model_name,
        event=event,
        source=source,
        metadata=metadata,
    )


@mcp.tool()
def evaluate_memory_candidate(candidate: str) -> dict:
    """
    Evaluate whether a memory candidate can be promoted safely.

    Args:
        candidate: Proposed memory text to score against promotion policy.
    """
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
    """
    Evaluate grounded episode content for lesson/playbook promotion.

    Args:
        problem: Problem or situation the episode addressed.
        action: Action taken to address the problem.
        outcome: Result of the action (success, failure, partial).
        local_critique: Optional critique of the specific action taken.
        global_reflection: Optional broader lesson learned.
        evidence_refs: Optional file paths, URLs, or handles supporting the episode.
    """
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
    """
    Record an observer event into the episodic ring buffer.

    Args:
        session_id: Session identifier linking events to a work session.
        event_type: Event category (e.g. tool_call, file_edit, error).
        tool_name: Optional MCP tool name when event_type is tool-related.
        files_touched: Optional list of file paths modified in this event.
        token_cost: Estimated tokens consumed. Default: 0.
        duration_ms: Event duration in milliseconds. Default: 0.
        metadata: Optional extra structured fields for the event.
        timestamp: Unix timestamp; default is current time.
    """
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
    """
    Get observer event counts and latest activity.

    Args:
        session_id: Filter stats to one session; None returns global stats.
    """
    return _get_observer_store().get_event_stats(session_id=session_id)


@mcp.tool()
async def touch_session(
    session_id: str,
    tool_name: str | None = None,
    files_modified: list[str] | None = None,
    key_decision: str | None = None,
    error: str | None = None,
    open_todos: list[str] | None = None,
    token_delta: int = 0,
    timestamp: float | None = None,
    end_session: bool = False,
    index_in_context_mode: bool = True,
) -> dict:
    """
    Update session summary telemetry.

    Set end_session=true to finalize and emit a ≤2 KB compact package.

    Args:
        session_id: Unique session identifier for this work session.
        tool_name: Optional last tool invoked in this touch.
        files_modified: Optional list of file paths changed this touch.
        key_decision: Optional short decision note to append.
        error: Optional error message if a failure occurred.
        open_todos: Optional list of remaining todo strings.
        token_delta: Token count delta to add to session total. Default: 0.
        timestamp: Unix timestamp override; default is current time.
        end_session: When True, finalize session and emit compact package.
        index_in_context_mode: When True and end_session, index package via context-mode.
    """
    return await memory_tools.touch_session_impl(
        get_session_store=_get_session_store,
        get_context_mode_client=_get_context_mode_client,
        get_observer_store=_get_observer_store,
        session_id=session_id,
        tool_name=tool_name,
        files_modified=files_modified,
        key_decision=key_decision,
        error=error,
        open_todos=open_todos,
        token_delta=token_delta,
        timestamp=timestamp,
        end_session=end_session,
        index_in_context_mode=index_in_context_mode,
    )


@mcp.tool(output_schema=OUTPUT_SCHEMAS["get_session_summary"])
def get_session_summary(session_id: str | None = None) -> dict:
    """
    Return latest session summary or a specific session.

    Args:
        session_id: Session to retrieve; None returns the most recent session.
    """
    summary = _get_session_store().get_session_summary(session_id=session_id)
    if not summary:
        return {"status": "not_found", "session_id": session_id}
    payload = summary.__dict__
    if summary.compact_package_json:
        try:
            payload["compact_package"] = json.loads(summary.compact_package_json)
        except json.JSONDecodeError:
            payload["compact_package"] = None
    if summary.context_index_handle:
        payload["retrieval_hint"] = retrieval_hint(summary.context_index_handle)
    return payload


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
    """
    Store a grounded episode candidate for future dream consolidation.

    Args:
        session_id: Session this episode belongs to.
        problem: Problem or situation encountered.
        context: Background context relevant to the problem.
        action: Action taken to address the problem.
        outcome: Result of the action.
        evidence_refs: Optional supporting file paths, URLs, or index handles.
        local_critique: Optional critique of the specific action.
        global_reflection: Optional broader lesson or pattern observed.
        confidence: Confidence score 0.0–1.0. Default: 0.5.
        tags: Optional categorization tags.
        episode_id: Optional explicit id; auto-generated when empty.
    """
    return memory_tools.record_episode_impl(
        get_session_store=_get_session_store,
        session_id=session_id,
        problem=problem,
        context=context,
        action=action,
        outcome=outcome,
        evidence_refs=evidence_refs,
        local_critique=local_critique,
        global_reflection=global_reflection,
        confidence=confidence,
        tags=tags,
        episode_id=episode_id,
    )


@mcp.tool()
def list_episodes(session_id: str | None = None, limit: int = 20) -> dict:
    """
    List recent episodes (optionally by session).

    Args:
        session_id: Filter to one session; None returns episodes across sessions.
        limit: Maximum episodes to return. Default: 20.
    """
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
    """
    Store a durable semantic/procedural/lesson record.

    Args:
        content: Durable fact or lesson body text to store.
        record_class: Record type — semantic | procedural | lesson. Default: semantic.
        title: Optional short title for the record.
        source: Provenance label (e.g. manual, dream, session). Default: manual.
        category: Grouping category. Default: general.
        importance: Importance score 0.0–1.0. Default: 0.5.
        confidence: Confidence score 0.0–1.0. Default: 0.5.
        tags: Optional list of categorization tags.
        evidence_refs: Optional file paths, URLs, or index handles supporting the record.
        metadata: Optional extra structured fields stored with the record.
    """
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
    """
    Query durable records from Wiki-Brain.

    Args:
        query: Text search query; empty returns recent records.
        record_class: Filter by semantic | procedural | lesson; None returns all classes.
        limit: Maximum records to return. Default: 10.
        include_superseded: When True, include records marked superseded. Default: False.
    """
    records = _get_wiki_brain().query_records(
        query=query,
        record_class=record_class,
        limit=limit,
        include_superseded=include_superseded,
    )
    return {"records": [record.__dict__ for record in records], "count": len(records)}


@mcp.tool()
def cognitive_recall(query: str, record_class: str | None = None, limit: int = 5) -> dict:
    """
    Score and rank durable recall candidates.

    Args:
        query: Natural-language recall query.
        record_class: Filter by semantic | procedural | lesson; None searches all.
        limit: Maximum ranked results. Default: 5.
    """
    return {
        "results": _get_wiki_brain().cognitive_recall(
            query=query,
            record_class=record_class,
            limit=limit,
        )
    }


@mcp.tool()
def review_playbook(query: str = "", limit: int = 10) -> dict:
    """
    Review active lesson/playbook records.

    Args:
        query: Optional text filter for lesson content.
        limit: Maximum records to return. Default: 10.
    """
    return {"records": _get_wiki_brain().review_playbook(query=query, limit=limit)}


@mcp.tool()
def record_memory_metric(
    metric_type: str,
    value: float = 1.0,
    source: str = "manual",
    metadata: dict | None = None,
) -> dict:
    """
    Record durable memory-system metric events.

    Args:
        metric_type: Metric name (e.g. recall_hit, promotion, dream_cycle).
        value: Numeric metric value. Default: 1.0.
        source: Provenance label. Default: manual.
        metadata: Optional extra fields attached to the metric event.
    """
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
async def run_dream(mode: str = "full", force: bool = False, async_mode: bool = False) -> dict:
    """
    Run Light/REM/Deep memory consolidation.

    Args:
        mode: Dream cycle mode — light | rem | deep | full. Default: full.
        force: When True, run even if interval guard would skip. Default: False.
        async_mode: When True, queue background execution and return a task id.
    """
    if async_mode:
        manager = _get_task_manager()
        record = await manager.submit(
            task_type="run_dream",
            runner=lambda: asyncio.to_thread(
                _get_dream_engine().run,
                mode=mode,
                force=force,
                trigger="mcp",
            ),
        )
        return {
            "status": "queued",
            "task_id": record.task_id,
            "task_type": record.task_type,
            "poll_tool": "get_task_status",
        }
    return await asyncio.to_thread(_get_dream_engine().run, mode=mode, force=force, trigger="mcp")


@mcp.tool()
def get_dream_status() -> dict:
    """Read latest dream consolidation status."""
    return _get_dream_engine().get_status()


@mcp.tool()
async def ping() -> dict:
    """Health check — verify BRAINDRAIN is running and whether MCP Apps tools are loaded."""
    result = await workspace_tools.ping_impl(config)
    tool_names = {t.name for t in await mcp.list_tools()}
    result["mcp_tool_count"] = len(tool_names)
    result["mcp_apps"] = {
        "enabled": "show_token_dashboard" in tool_names,
        "show_token_dashboard": "show_token_dashboard" in tool_names,
        "show_plan_board": "show_plan_board" in tool_names,
    }
    return result


@mcp.tool(output_schema=OUTPUT_SCHEMAS["get_env_context"])
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
    return workspace_tools.get_env_context_impl(_probe_env_context, refresh=refresh)


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
    return workspace_tools.refresh_env_context_impl(_probe_env_context)


@mcp.tool()
def scriptlib_enable(
    path: str = ".",
    scope: str = "project",
    harvest: bool = True,
    dry_run: bool = False,
) -> dict:
    """
    Enable scriptlib for the project or global scope. Project enable harvests scripts by default.

    Args:
        path: Project root directory. Default: current working directory.
        scope: Enable target — project | global. Default: project.
        harvest: When True, harvest workspace scripts on project enable. Default: True.
        dry_run: When True, preview without writing config. Default: False.
    """
    return _scriptlib_enable(path, scope=scope, harvest=harvest, dry_run=dry_run)


@mcp.tool()
def scriptlib_disable(
    path: str = ".",
    scope: str = "project",
    dry_run: bool = False,
) -> dict:
    """
    Disable scriptlib for the project or global scope without removing harvested files.

    Args:
        path: Project root directory. Default: current working directory.
        scope: Disable target — project | global. Default: project.
        dry_run: When True, preview without writing config. Default: False.
    """
    return _scriptlib_disable(path, scope=scope, dry_run=dry_run)


@mcp.tool()
def scriptlib_harvest_workspace(
    path: str = ".",
    dry_run: bool = False,
) -> dict:
    """
    Copy useful script-like files from the workspace into the local scriptlib catalog.

    Args:
        path: Project root to harvest from. Default: current working directory.
        dry_run: When True, report candidates without copying. Default: False.
    """
    return _scriptlib_harvest_workspace(project_path=path, dry_run=dry_run)


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
    """
    Search project and global scriptlib entries with lightweight lexical ranking.

    Args:
        query: Natural-language or keyword search query.
        path: Project root for project-scoped catalog. Default: current directory.
        capability: Optional filter by capability tag.
        language: Optional filter by language (e.g. python, bash).
        harness: Optional filter by test harness type.
        effect_tier: Optional filter by side-effect tier.
        limit: Maximum results. Default: 5.
    """
    return _scriptlib_search(
        query,
        project_path=path,
        capability=capability,
        language=language,
        harness=harness,
        effect_tier=effect_tier,
        limit=limit,
    )


@mcp.tool()
def scriptlib_describe(
    script_id: str,
    path: str = ".",
    variant: str | None = None,
) -> dict:
    """
    Return full metadata for a scriptlib entry.

    Args:
        script_id: Scriptlib entry id from search or catalog.
        path: Project root for project-scoped lookup. Default: current directory.
        variant: Optional variant/version id when multiple exist.
    """
    return _scriptlib_describe(script_id, project_path=path, variant=variant)


@mcp.tool()
def scriptlib_run(
    script_id: str,
    path: str = ".",
    variant: str | None = None,
    args: list[str] | None = None,
    dry_run: bool = False,
    timeout_seconds: int = 60,
) -> dict:
    """
    Run a scriptlib entry using native copy or restored source context.

    Args:
        script_id: Scriptlib entry id to execute.
        path: Project root for project-scoped lookup. Default: current directory.
        variant: Optional variant/version id to run.
        args: Optional CLI arguments passed to the script.
        dry_run: When True, return the command without executing. Default: False.
        timeout_seconds: Max execution time in seconds. Default: 60.
    """
    return _scriptlib_run(
        script_id,
        project_path=path,
        variant=variant,
        args=args,
        dry_run=dry_run,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def scriptlib_fork(
    script_id: str,
    new_variant_or_version: str,
    path: str = ".",
) -> dict:
    """
    Fork an existing scriptlib entry into a new version for safe modification.

    Args:
        script_id: Source scriptlib entry id to fork.
        new_variant_or_version: New variant or version label for the fork.
        path: Project root for project-scoped catalog. Default: current directory.
    """
    return _scriptlib_fork(
        script_id,
        project_path=path,
        new_variant_or_version=new_variant_or_version,
    )


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
    """
    Record a run result and update success score, mistakes, and validation state.

    Args:
        script_id: Scriptlib entry id that was run.
        outcome: Run outcome — success | failure | partial.
        path: Project root for project-scoped catalog. Default: current directory.
        variant: Optional variant/version id that was run.
        notes: Optional freeform notes about the run.
        duration_ms: Optional run duration in milliseconds.
        promote_status: Optional promotion status update.
        validate_native_copy: When True, validate the native copy artifact. Default: False.
    """
    return _scriptlib_record_result(
        script_id,
        project_path=path,
        variant=variant,
        outcome=outcome,
        notes=notes,
        duration_ms=duration_ms,
        promote_status=promote_status,
        validate_native_copy=validate_native_copy,
    )


@mcp.tool()
def scriptlib_promote(
    script_id: str,
    path: str = ".",
    variant: str | None = None,
    channel: str = "stable",
    approved: bool = False,
    dry_run: bool = False,
) -> dict:
    """
    Promote a validated project script into the shared personal scriptlib catalog.

    Args:
        script_id: Project scriptlib entry id to promote.
        path: Project root. Default: current working directory.
        variant: Optional variant/version id to promote.
        channel: Release channel (e.g. stable, beta). Default: stable.
        approved: When True, confirm promotion approval gate. Default: False.
        dry_run: When True, preview promotion without writing. Default: False.
    """
    return _scriptlib_promote(
        script_id,
        project_path=path,
        variant=variant,
        channel=channel,
        approved=approved,
        dry_run=dry_run,
    )


@mcp.tool()
def scriptlib_list_updates(
    path: str = ".",
) -> dict:
    """
    List pinned shared script artifacts with available updates for this workspace.

    Args:
        path: Project root. Default: current working directory.
    """
    return _scriptlib_list_updates(project_path=path)


@mcp.tool()
def scriptlib_apply_update(
    script_id: str,
    path: str = ".",
    channel: str | None = None,
    target_revision: int | None = None,
    approved: bool = False,
    dry_run: bool = False,
) -> dict:
    """
    Pin or upgrade a shared script artifact in the current workspace.

    Args:
        script_id: Shared scriptlib entry id to pin or upgrade.
        path: Project root. Default: current working directory.
        channel: Optional release channel to pin (e.g. stable).
        target_revision: Optional explicit revision number to pin.
        approved: When True, confirm update approval gate. Default: False.
        dry_run: When True, preview update without writing. Default: False.
    """
    return _scriptlib_apply_update(
        script_id,
        project_path=path,
        channel=channel,
        target_revision=target_revision,
        approved=approved,
        dry_run=dry_run,
    )


@mcp.tool()
def scriptlib_run_maintenance(
    path: str = ".",
    scope: str = "all",
    dry_run: bool = False,
    add_ignore_dirs: list[str] | None = None,
) -> dict:
    """
    Refresh indexes, surface duplicates and promotion candidates, and optionally persist ignore dirs.

    Args:
        path: Project root. Default: current working directory.
        scope: Maintenance scope — project | global | all. Default: all.
        dry_run: When True, report findings without writing. Default: False.
        add_ignore_dirs: Optional directory names to add to harvest ignore list.
    """
    return _scriptlib_run_maintenance(
        project_path=path,
        scope=scope,
        dry_run=dry_run,
        add_ignore_dirs=add_ignore_dirs,
    )


@mcp.tool()
def scriptlib_catalog_status(
    path: str = ".",
    include_entries: bool = False,
    limit: int = 20,
) -> dict:
    """
    Summarize local/shared scriptlib state, promotion candidates, pins, and updates.

    Args:
        path: Project root. Default: current working directory.
        include_entries: When True, include entry summaries in response. Default: False.
        limit: Max entries when include_entries is True. Default: 20.
    """
    return _scriptlib_catalog_status(
        project_path=path, include_entries=include_entries, limit=limit
    )


@mcp.tool()
def scriptlib_refresh_index(
    path: str = ".",
    scope: str = "project",
    dry_run: bool = False,
) -> dict:
    """
    Rebuild project, global, or combined scriptlib indexes and catalogs.

    Args:
        path: Project root for project scope. Default: current working directory.
        scope: Index scope — project | global | all. Default: project.
        dry_run: When True, preview rebuild without writing. Default: False.
    """
    return scriptlib_tools.scriptlib_refresh_index_impl(
        project_scriptlib_root=_project_scriptlib_root,
        global_scriptlib_root=_global_scriptlib_root,
        scriptlib_is_enabled=_scriptlib_is_enabled,
        scriptlib_refresh_index=_scriptlib_refresh_index,
        path=path,
        scope=scope,
        dry_run=dry_run,
    )


@mcp.tool(output_schema=OUTPUT_SCHEMAS["prime_workspace"])
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
    async_mode: bool = False,
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
        sync_subagents: Update existing ``.cursor/agents/*.md`` and ``.codex/agents/*.md``
            from ``config/templates/agents/`` with timestamped backups (create-only by default);
            when Codex is in scope, also updates the managed block in ``.codex/config.toml``.
        all_agents:     Deploy full template and apply all configured agents.
        local_only:     Pass --local-only to ruler apply (default True).
        patch_user_cursor_mcp: If True, also patch ~/.cursor/mcp.json with
            serverName entries (fixes Cursor allowlist warning for user-braindrain).
        codex_agent_targets: Optional relative target paths for codex subagent
            file deployment. Default: [".codex/agents"].
        compact_mcp_response: If True (default), return a smaller dict so the MCP
            client is less likely to hit ClosedResourceError on large tool results.
        bundle: Bundle manifest to use from config/bundles/<name>.yaml.
        async_mode: When True, queue background execution and return a task id.

    After priming:
    - Agents that support project-local MCP configs will have braindrain wired.
    - Agent rule files will reference the braindrain protocol.
    - When Cursor is in the resolved agent set, ``config/templates/cursor/`` is
      copied to ``.cursor/hooks.json`` and ``.cursor/hooks/*.sh`` (see result
      ``cursor_hooks``; use sync_templates to refresh existing hook files).
    - Project memory is initialized under .braindrain/ (gitignored).
    - Call get_env_context() to populate the live env block.
    """
    if async_mode:
        manager = _get_task_manager()
        record = await manager.submit(
            task_type="prime_workspace",
            runner=lambda: workspace_tools.prime_workspace_impl(
                prime_workspace_fn=_prime_workspace,
                compact_prime_result_for_mcp=compact_prime_result_for_mcp,
                telemetry=telemetry,
                path=path,
                agents=agents,
                dry_run=dry_run,
                sync_templates=sync_templates,
                sync_subagents=sync_subagents,
                all_agents=all_agents,
                local_only=local_only,
                patch_user_cursor_mcp=patch_user_cursor_mcp,
                codex_agent_targets=codex_agent_targets,
                compact_mcp_response=compact_mcp_response,
                bundle=bundle,
            ),
        )
        return {
            "status": "queued",
            "task_id": record.task_id,
            "task_type": record.task_type,
            "poll_tool": "get_task_status",
        }
    return await workspace_tools.prime_workspace_impl(
        prime_workspace_fn=_prime_workspace,
        compact_prime_result_for_mcp=compact_prime_result_for_mcp,
        telemetry=telemetry,
        path=path,
        agents=agents,
        dry_run=dry_run,
        sync_templates=sync_templates,
        sync_subagents=sync_subagents,
        all_agents=all_agents,
        local_only=local_only,
        patch_user_cursor_mcp=patch_user_cursor_mcp,
        codex_agent_targets=codex_agent_targets,
        compact_mcp_response=compact_mcp_response,
        bundle=bundle,
    )


@mcp.tool()
def init_project_memory(path: str = ".", dry_run: bool = False) -> dict:
    """
    Initialize project memory artifacts used by continual-learning workflows.

    Creates (if missing):
    - .braindrain/AGENT_MEMORY.md  (migrated from .devdocs/ on first run if present)
    - .cursor/hooks/state/continual-learning-index.json

    Both paths are gitignored. This tool is idempotent and safe to re-run.

    Args:
        path: Project root directory. Default: current working directory.
        dry_run: When True, preview artifacts without creating files.
    """
    return workspace_tools.init_project_memory_impl(
        initialize_project_memory_fn=_initialize_project_memory,
        telemetry=telemetry,
        path=path,
        dry_run=dry_run,
    )


register_mcp_app_resources(mcp)
register_mcp_app_tools(
    mcp,
    telemetry=telemetry,
    tool_decorator=mcp.tool,
    default_project_root=_project_root,
)


@mcp.tool()
def list_prime_snapshots(path: str = ".") -> dict:
    """
    List available rollback snapshots created by prime_workspace.

    Args:
        path: Project root. Default: current working directory.
    """
    try:
        target = Path(path).expanduser().resolve()
        if not target.exists():
            return {"ok": False, "error": f"Path does not exist: {target}"}
        snapshots = _list_prime_snapshots(target)
        return {"ok": True, "snapshots": snapshots, "count": len(snapshots)}
    except Exception as e:
        telemetry.log_error(
            f"list_prime_snapshots exception: {e}",
            context={"path": path},
        )
        return {"ok": False, "error": str(e)}


@mcp.tool()
def restore_prime_snapshot(
    path: str = ".",
    snapshot_id: str | None = None,
    restore_memory: bool = True,
    restore_cursor: bool = True,
    restore_codex: bool = False,
    dry_run: bool = False,
) -> dict:
    """
    Restore memory files and selected IDE state from a rollback snapshot.

    Args:
        path: Project root. Default: current working directory.
        snapshot_id: Rollback directory name (e.g. 20260703-093000). Default: newest snapshot.
        restore_memory: Restore protected `.braindrain/*.md` backups. Default: True.
        restore_cursor: Extract `cursor.tar.gz` from the snapshot. Default: True.
        restore_codex: Extract `codex.tar.gz` from the snapshot. Default: False.
        dry_run: Preview restore actions without writing files. Default: False.
    """
    try:
        target = Path(path).expanduser().resolve()
        if not target.exists():
            return {"ok": False, "error": f"Path does not exist: {target}"}
        return _restore_prime_snapshot(
            target,
            snapshot_id=snapshot_id,
            restore_memory=restore_memory,
            restore_cursor=restore_cursor,
            restore_codex=restore_codex,
            dry_run=dry_run,
        )
    except Exception as e:
        telemetry.log_error(
            f"restore_prime_snapshot exception: {e}",
            context={
                "path": path,
                "snapshot_id": snapshot_id,
                "restore_memory": restore_memory,
                "restore_cursor": restore_cursor,
                "restore_codex": restore_codex,
                "dry_run": dry_run,
            },
        )
        return {"ok": False, "error": str(e)}


def main():
    """Entry point for running the server"""
    import sys

    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"

    if transport == "stdio":
        # No banner: FastMCP prints ASCII + update notice to stderr; Cursor MCP logs stderr as [error].
        # log_level=warning avoids the "Starting MCP server" INFO line being surfaced as an MCP error.
        mcp.run(transport="stdio", show_banner=False, log_level="warning")
    else:
        # Remote mode uses Streamable HTTP with stateless semantics (SSE removed).
        # FastMCP handles protocol header validation for MCP requests, including
        # MCP-Protocol-Version negotiation and required MCP method/name headers.
        mcp.run(
            transport="streamable-http",
            port=int(os.environ.get("PORT", "8000")),
            show_banner=False,
            stateless_http=True,
        )


if __name__ == "__main__":
    main()
