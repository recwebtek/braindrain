"""SIGINT map payload builder — operational topology from native observability."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from braindrain.mcp_apps.data import build_plan_board_payload
from braindrain.observer import BrainEvent, ObserverStore

_SESSION_WINDOW_HOURS = 2
_HUB_NODE_ID = "braindrain-hub"
_DEFAULT_OBSERVER_DB = "~/.braindrain/events.db"

_NODE_COLORS = {
    "session": "#3b82f6",
    "braindrain_hub": "#8b5cf6",
    "braindrain_tool": "#a78bfa",
    "external_mcp": "#64748b",
    "subagent": "#f59e0b",
    "plan": "#10b981",
    "hook": "#ef4444",
}


def _resolve_root(path: str | Path | None) -> Path:
    if not path:
        return Path.cwd()
    return Path(path).expanduser().resolve()


def _default_observer_db() -> Path:
    return Path(_DEFAULT_OBSERVER_DB).expanduser()


def _resolve_session_id(
    explicit: str | None,
    *,
    store: ObserverStore,
    project_root: Path,
) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    env_id = os.environ.get("BRAINDRAIN_SESSION_ID", "").strip()
    if env_id:
        return env_id
    since = (datetime.now(UTC) - timedelta(hours=_SESSION_WINDOW_HOURS)).timestamp()
    events = store.query_events(since=since, limit=500)
    repo_str = str(project_root)
    for event in events:
        meta = event.metadata or {}
        repo = str(meta.get("repo_root") or meta.get("project_root") or "")
        if repo and repo_str not in repo and repo not in repo_str:
            continue
        return event.session_id
    if events:
        return events[0].session_id
    return "mcp-default"


def _load_session_events(
    store: ObserverStore,
    session_id: str,
    *,
    limit: int,
) -> list[BrainEvent]:
    primary = store.query_events(session_id=session_id, limit=limit)
    if primary:
        return list(reversed(primary))

    since = (datetime.now(UTC) - timedelta(hours=_SESSION_WINDOW_HOURS)).timestamp()
    windowed = store.query_events(since=since, limit=limit)
    return list(reversed(windowed))


def _load_external_mcp_servers(project_root: Path) -> list[dict[str, str]]:
    servers: dict[str, str] = {}
    mcp_json = project_root / ".cursor" / "mcp.json"
    if mcp_json.is_file():
        try:
            data = json.loads(mcp_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        for key, entry in (data.get("mcpServers") or {}).items():
            if not isinstance(entry, dict):
                continue
            label = str(entry.get("serverName") or key).strip()
            if label and label.lower() not in {"braindrain", "user-braindrain"}:
                servers[label] = key

    catalog_dir = project_root / ".braindrain" / "mcp-catalog"
    if catalog_dir.is_dir():
        for child in sorted(catalog_dir.iterdir()):
            if not child.is_dir():
                continue
            name = child.name
            if name in {"braindrain"}:
                continue
            if name not in servers:
                servers[name] = name

    return [
        {"id": f"ext-mcp:{_slug_id(key)}", "key": key, "label": label}
        for label, key in sorted(servers.items())
    ]


def _slug_id(value: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in value.lower()).strip("-")


def _node(
    node_id: str,
    node_type: str,
    label: str,
    *,
    status: str = "active",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "label": label,
        "status": status,
        "color": _NODE_COLORS.get(node_type, "#94a3b8"),
        "meta": meta or {},
    }


def _edge(
    source: str,
    target: str,
    edge_type: str,
    *,
    weight: float = 1.0,
    ts: float | None = None,
    dashed: bool = False,
) -> dict[str, Any]:
    return {
        "source": source,
        "target": target,
        "type": edge_type,
        "weight": weight,
        "ts": ts,
        "dashed": dashed,
    }


def _active_plan_groups(project_root: Path) -> list[dict[str, Any]]:
    board = build_plan_board_payload(path=str(project_root))
    groups = board.get("plan_groups") or []
    return [g for g in groups if not g.get("is_archived")]


def _event_log_entry(event: BrainEvent) -> dict[str, Any]:
    return {
        "timestamp": event.timestamp,
        "event_type": event.event_type,
        "tool_name": event.tool_name,
        "session_id": event.session_id,
        "metadata": event.metadata,
    }


def build_sigint_map_payload(
    project_root: str | Path,
    *,
    session_id: str | None = None,
    limit: int = 500,
    observer_db: str | Path | None = None,
) -> dict[str, Any]:
    """
    Build operational topology graph for the SIGINT map MCP App.

    Combines observer events, configured external MCP servers, and active plans.
    """
    root = _resolve_root(project_root)
    db_path = Path(observer_db).expanduser() if observer_db else _default_observer_db()
    store = ObserverStore(db_path=db_path)
    resolved_session = _resolve_session_id(session_id, store=store, project_root=root)
    events = _load_session_events(store, resolved_session, limit=limit)

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    session_node_id = f"session:{_slug_id(resolved_session)}"

    nodes[session_node_id] = _node(
        session_node_id,
        "session",
        resolved_session[:24] + ("…" if len(resolved_session) > 24 else ""),
        meta={"session_id": resolved_session, "event_count": len(events)},
    )
    nodes[_HUB_NODE_ID] = _node(_HUB_NODE_ID, "braindrain_hub", "Braindrain MCP")
    edges.append(_edge(session_node_id, _HUB_NODE_ID, "session_hub", weight=2.0))

    tool_names: set[str] = set()
    hook_branches: set[str] = set()
    subagent_names: set[str] = set()

    for event in events:
        meta = event.metadata or {}
        if event.event_type == "tool_call" and event.tool_name:
            tool_names.add(event.tool_name)
            tool_id = f"tool:{_slug_id(event.tool_name)}"
            if tool_id not in nodes:
                nodes[tool_id] = _node(tool_id, "braindrain_tool", event.tool_name)
            edges.append(
                _edge(
                    _HUB_NODE_ID,
                    tool_id,
                    "tool_call",
                    weight=1.0,
                    ts=event.timestamp,
                )
            )
            edges.append(
                _edge(
                    session_node_id,
                    tool_id,
                    "tool_call",
                    weight=0.5,
                    ts=event.timestamp,
                )
            )

        if event.event_type == "session_end":
            hook_name = str(meta.get("hook") or "cursor_stop_hook")
            hook_id = f"hook:{_slug_id(hook_name)}"
            if hook_id not in nodes:
                nodes[hook_id] = _node(
                    hook_id,
                    "hook",
                    hook_name,
                    meta={"branch": meta.get("branch"), "repo_root": meta.get("repo_root")},
                )
            edges.append(
                _edge(
                    session_node_id,
                    hook_id,
                    "hook_fire",
                    weight=1.5,
                    ts=event.timestamp,
                )
            )
            branch = str(meta.get("branch") or "").strip()
            if branch:
                hook_branches.add(branch)

        subagent = str(meta.get("subagent") or meta.get("agent_type") or "").strip()
        if subagent:
            sub_id = f"subagent:{_slug_id(subagent)}"
            subagent_names.add(subagent)
            if sub_id not in nodes:
                nodes[sub_id] = _node(sub_id, "subagent", subagent)
            edges.append(
                _edge(
                    session_node_id,
                    sub_id,
                    "subagent_dispatch",
                    weight=1.2,
                    ts=event.timestamp,
                )
            )

    for ext in _load_external_mcp_servers(root):
        ext_id = ext["id"]
        if ext_id not in nodes:
            nodes[ext_id] = _node(
                ext_id,
                "external_mcp",
                ext["label"],
                status="configured",
                meta={"server_key": ext["key"]},
            )
        edges.append(
            _edge(
                _HUB_NODE_ID,
                ext_id,
                "downstream_mcp",
                weight=0.3,
                dashed=True,
            )
        )

    plan_count = 0
    for group in _active_plan_groups(root):
        source = str(group.get("source") or "").strip()
        if not source:
            continue
        plan_name = str(group.get("plan") or group.get("name") or source)
        plan_id = f"plan:{_slug_id(source)}"
        branch = str(group.get("branch") or "").strip()
        plan_count += 1
        nodes[plan_id] = _node(
            plan_id,
            "plan",
            plan_name,
            status=str(group.get("disposition") or "active"),
            meta={
                "source": source,
                "branch": branch,
                "disposition": group.get("disposition"),
            },
        )
        link_session = not hook_branches or (branch and branch in hook_branches)
        if link_session:
            edges.append(
                _edge(
                    session_node_id,
                    plan_id,
                    "plan_active",
                    weight=1.0,
                    dashed=not branch,
                )
            )

    log = [_event_log_entry(e) for e in events[-20:]]

    return {
        "session_id": resolved_session,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project_root": str(root),
        "stats": {
            "events": len(events),
            "tools": len(tool_names),
            "plans": plan_count,
            "external_mcps": sum(1 for n in nodes.values() if n["type"] == "external_mcp"),
            "subagents": len(subagent_names),
        },
        "nodes": list(nodes.values()),
        "edges": edges,
        "log": log,
        "legend": {
            "subagent_gap": "Subagent nodes appear only when metadata.subagent is recorded.",
            "external_mcp_edges": "Dashed edges = configured peers; live calls need phase-2 hooks.",
            "session_heuristic": f"Events unioned within {_SESSION_WINDOW_HOURS}h when session IDs diverge.",
        },
        "empty": len(events) == 0,
        "hint": (
            "No session events yet — run a braindrain tool or end a Cursor turn (stop hook)."
            if not events
            else ""
        ),
    }
