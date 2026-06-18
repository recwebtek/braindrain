"""Data loaders for MCP App dashboards (no sidecar / no Node stack)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from braindrain.telemetry import TelemetrySession
from braindrain.token_checkpoints import default_checkpoint_path

_TABLE_ROW_RE = re.compile(
    r"^\|\s*(\d+)\s*\|\s*([^|]+)\|([^|]*)\|([^|]*)\|([^|]*)\|",
    re.MULTILINE,
)


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
            }
        )
    return rows


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

    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project_root": str(root),
        "reports_dir": str(reports),
        "board_path": str(board_path),
        "board_markdown": board_md,
        "board_rows": _parse_plan_board_table(board_md),
        "has_master_plan": master_path.is_file(),
        "has_next_actions": next_actions_path.is_file(),
        "hint": (
            "Run /masterplan or python3 scripts/daily_plan_audit.py to refresh "
            ".braindrain/plan-reports/ when the board is empty."
        ),
    }
