"""Data loaders for MCP App dashboards (no sidecar / no Node stack)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from braindrain.mcp_apps.plan_enrich import enrich_plan_groups
from braindrain.telemetry import TelemetrySession
from braindrain.token_checkpoints import default_checkpoint_path

_TABLE_ROW_RE = re.compile(
    r"^\|\s*(\d+)\s*\|\s*([^|]+)\|\s*([^|]*)\|\s*([^|]*)\|\s*([^|]*)\|\s*([^|]*)\|\s*([^|]*)\|\s*([^|]*)\|\s*$",
    re.MULTILINE,
)
_MASTER_QUEUE_RE = re.compile(
    r"^\|\s*(\d+)\s*\|\s*\[([^\]]+)\]\([^)]+\)\s*\|\s*([^|]+)\|\s*`?([^`|]+)`?\s*\|\s*`?([^`|]+)`?\s*\|\s*([^|]+)\|\s*([^|]+)\|",
    re.MULTILINE,
)


def _clean_cell(value: str) -> str:
    text = value.strip()
    if text.startswith("`") and text.endswith("`"):
        text = text[1:-1].strip()
    return text


def _parse_plan_board_table(markdown: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for match in _TABLE_ROW_RE.finditer(markdown):
        plan = match.group(2).strip()
        if plan.lower() == "plan":
            continue
        seq_raw = match.group(1).strip()
        try:
            seq = int(seq_raw)
        except ValueError:
            continue
        rows.append(
            {
                "seq": seq,
                "plan": plan,
                "ide": match.group(3).strip(),
                "status": match.group(4).strip(),
                "owner": match.group(5).strip(),
                "item": _clean_cell(match.group(6)),
                "source": _clean_cell(match.group(7)),
                "gaps": _clean_cell(match.group(8)),
            }
        )
    return rows


def _parse_master_plan_queue(markdown: str) -> dict[str, dict[str, Any]]:
    """Map plan source path -> queue metadata from master-plan.md."""
    meta: dict[str, dict[str, Any]] = {}
    for match in _MASTER_QUEUE_RE.finditer(markdown):
        title = match.group(2).strip()
        if title.lower() == "plan":
            continue
        source = _clean_cell(match.group(7))
        meta[source] = {
            "seq": int(match.group(1)),
            "plan": title,
            "priority": match.group(3).strip(),
            "disposition": _clean_cell(match.group(4)),
            "branch": _clean_cell(match.group(5)),
            "next_verb": match.group(6).strip(),
            "source": source,
        }
    return meta


def _group_plan_rows(
    rows: list[dict[str, Any]],
    *,
    master_by_source: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Collapse task-board rows into one card per plan with nested todo items."""
    master_by_source = master_by_source or {}
    groups: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for row in rows:
        source = row.get("source") or f"{row.get('seq')}:{row.get('plan')}"
        if source not in groups:
            master = master_by_source.get(source, {})
            groups[source] = {
                "seq": master.get("seq", row.get("seq")),
                "plan": master.get("plan") or row.get("plan"),
                "ide": row.get("ide") or "—",
                "owner": row.get("owner") or "—",
                "priority": master.get("priority", "—"),
                "disposition": master.get("disposition", "—"),
                "branch": master.get("branch", "—"),
                "next_verb": master.get("next_verb", "—"),
                "source": source,
                "items": [],
                "status_counts": {"Blocked": 0, "In Progress": 0, "Outstanding": 0},
            }
            order.append(source)
        group = groups[source]
        status = row.get("status") or "Outstanding"
        if status in group["status_counts"]:
            group["status_counts"][status] += 1
        group["items"].append(
            {
                "status": status,
                "item": row.get("item") or "—",
                "gaps": row.get("gaps") or "—",
            }
        )

    grouped = [groups[key] for key in order]
    grouped.sort(key=lambda g: (int(g.get("seq") or 9999), g.get("plan") or ""))
    return grouped


def _load_next_actions_preview(path: Path, *, limit: int = 8) -> list[str]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    preview: list[str] = []
    for line in lines:
        text = line.strip()
        if not text.startswith("- "):
            continue
        preview.append(text[2:].strip())
        if len(preview) >= limit:
            break
    return preview


def _resolve_root(path: str | None) -> Path:
    if not path:
        return Path.cwd()
    return Path(path).expanduser().resolve()


def load_token_checkpoints(project_root: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    path = default_checkpoint_path(project_root)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(rows) >= limit:
            break
    rows.reverse()
    return rows


def build_token_dashboard_payload(
    telemetry: TelemetrySession,
    *,
    path: str | None = None,
    checkpoint_limit: int = 20,
) -> dict[str, Any]:
    """Structured payload for the token dashboard MCP App."""
    root = _resolve_root(path)
    snapshot = telemetry.snapshot()
    tools = snapshot.get("tools") or {}
    tool_rows = [
        {
            "name": name,
            "calls": int(vals.get("calls", 0) or 0),
            "raw_tokens": int(vals.get("tokens_in_raw_est", 0) or 0),
            "actual_tokens": int(vals.get("tokens_in_actual_est", 0) or 0),
            "saved_tokens": int(vals.get("tokens_saved_est", 0) or 0),
            "saved_pct": float(vals.get("saved_pct_est", 0) or 0),
        }
        for name, vals in sorted(
            tools.items(),
            key=lambda item: -(int(item[1].get("tokens_saved_est", 0) or 0)),
        )
    ]
    checkpoints = load_token_checkpoints(root, limit=checkpoint_limit)
    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project_root": str(root),
        "snapshot": {
            "uptime_seconds": int(snapshot.get("uptime_seconds", 0) or 0),
            "tokens_in_raw_est": int(snapshot.get("tokens_in_raw_est", 0) or 0),
            "tokens_in_actual_est": int(snapshot.get("tokens_in_actual_est", 0) or 0),
            "tokens_saved_est": int(snapshot.get("tokens_saved_est", 0) or 0),
            "saved_pct_est": float(snapshot.get("saved_pct_est", 0) or 0),
            "cost_avoided_usd": float(snapshot.get("cost_avoided_usd", 0) or 0),
            "cache_hits": int(snapshot.get("cache_hits", 0) or 0),
            "module_attribution": dict(snapshot.get("module_attribution") or {}),
        },
        "tools": tool_rows,
        "checkpoints": checkpoints,
        "checkpoint_path": str(default_checkpoint_path(root)),
        "session_log": str(telemetry.log_file),
    }


def build_plan_board_payload(*, path: str | None = None) -> dict[str, Any]:
    """Structured payload for the plan board MCP App."""
    root = _resolve_root(path)
    reports = root / ".braindrain" / "plan-reports"
    board_path = reports / "plan-task-board.md"
    master_path = reports / "master-plan.md"
    next_actions_path = reports / "next-actions.md"

    board_md = ""
    if board_path.is_file():
        try:
            board_md = board_path.read_text(encoding="utf-8")
        except OSError:
            board_md = ""

    master_md = ""
    if master_path.is_file():
        try:
            master_md = master_path.read_text(encoding="utf-8")
        except OSError:
            master_md = ""

    board_rows = _parse_plan_board_table(board_md)
    master_by_source = _parse_master_plan_queue(master_md)
    plan_groups = _group_plan_rows(board_rows, master_by_source=master_by_source)
    plan_groups = enrich_plan_groups(plan_groups, repo_root=root, master_md=master_md)
    blocked_items = sum(g["status_counts"].get("Blocked", 0) for g in plan_groups)
    outstanding_items = sum(g["status_counts"].get("Outstanding", 0) for g in plan_groups)

    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project_root": str(root),
        "reports_dir": str(reports),
        "board_path": str(board_path),
        "board_rows": board_rows,
        "plan_groups": plan_groups,
        "summary": {
            "plan_count": len(plan_groups),
            "item_count": len(board_rows),
            "blocked_items": blocked_items,
            "outstanding_items": outstanding_items,
        },
        "next_actions": _load_next_actions_preview(next_actions_path),
        "has_master_plan": master_path.is_file(),
        "has_next_actions": next_actions_path.is_file(),
        "hint": (
            "Run /masterplan or python3 scripts/daily_plan_audit.py to refresh "
            ".braindrain/plan-reports/ when the board is empty."
        ),
    }
