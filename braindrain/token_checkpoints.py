"""Machine-local token checkpoint JSONL (schema 1.0)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from braindrain.telemetry import TelemetrySession

SCHEMA_VERSION = "1.0"
VALID_PHASES = frozenset({"start", "pre_high_cost", "post_high_cost", "milestone_close", "end"})


def default_checkpoint_path(project_root: Path | str | None = None) -> Path:
    """Resolve `.braindrain/token-metrics.jsonl` under the workspace root.

    Prefer an explicit ``project_root`` (same semantics as ``export_mcp_catalog(path=...)``).
    When omitted, falls back to ``Path.cwd()`` for CLI callers.
    """
    if project_root is None:
        root = Path.cwd()
    else:
        root = Path(project_root).expanduser().resolve()
    return root / ".braindrain" / "token-metrics.jsonl"


def _totals_from_snapshot(snapshot: dict[str, Any]) -> dict[str, int]:
    return {
        "estimated_raw_tokens": int(snapshot.get("tokens_in_raw_est", 0) or 0),
        "actual_context_tokens": int(snapshot.get("tokens_in_actual_est", 0) or 0),
        "saved_tokens": int(snapshot.get("tokens_saved_est", 0) or 0),
    }


def append_checkpoint(
    *,
    phase: str,
    task: str,
    note: str = "",
    context_tags: list[str] | None = None,
    telemetry: TelemetrySession,
    path: Path | None = None,
    project_root: Path | str | None = None,
    tool: str = "get_token_dashboard",
) -> dict[str, Any]:
    """Append a schema 1.0 checkpoint row to `.braindrain/token-metrics.jsonl`.

    ``path`` overrides the output file directly. Otherwise ``project_root`` (or cwd)
    selects ``<root>/.braindrain/token-metrics.jsonl``.
    """
    phase_norm = phase.strip().lower()
    if phase_norm not in VALID_PHASES:
        return {
            "ok": False,
            "error": f"Invalid phase '{phase}'. Expected one of: {sorted(VALID_PHASES)}",
        }

    out_path = path or default_checkpoint_path(project_root)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    snapshot = telemetry.snapshot()
    row = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "task": task,
        "phase": phase_norm,
        "tool": tool,
        "totals": _totals_from_snapshot(snapshot),
        "context_tags": list(context_tags or []),
        "note": note,
    }

    # Ensure sensitive information in the checkpoint row is redacted before persistence
    sanitized_row = telemetry.sanitize(row)

    with open(out_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(sanitized_row, ensure_ascii=False) + "\n")

    return {"ok": True, "path": str(out_path), "checkpoint": sanitized_row}
