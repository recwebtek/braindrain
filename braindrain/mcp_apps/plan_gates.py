"""Action-button gating for plan board MCP App cards."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _gate(enabled: bool, reason: str = "") -> dict[str, Any]:
    return {"enabled": enabled, "reason": reason if not enabled else ""}


def _todo_summary_all_done(summary: dict[str, Any] | None) -> bool:
    if not summary:
        return False
    total = int(summary.get("total") or 0)
    if total <= 0:
        return False
    done = int(summary.get("completed") or 0) + int(summary.get("cancelled") or 0)
    return done >= total


def compute_action_gates(
    group: dict[str, Any],
    *,
    repo_root: Path,
    pr_state: str = "none",
) -> dict[str, dict[str, Any]]:
    """Return per-action enable flags and disabled reasons for a plan group."""
    source = str(group.get("source") or "").lstrip("/")
    plan_path = repo_root / source if source else None
    plan_exists = bool(plan_path and plan_path.is_file())

    disposition = str(group.get("disposition") or "active").strip().lower()
    pr = group.get("pr") or {}
    pr_url = str(pr.get("url") or "").strip()
    has_pr = bool(pr_url)
    pr_state = (pr_state or "none").lower()
    if has_pr and pr_state == "none":
        pr_state = "open"

    summary = group.get("todo_summary") or {}
    all_done = _todo_summary_all_done(summary)
    branch = str(group.get("branch") or "").strip()
    has_branch = branch not in {"", "—", "-"}

    merge_ready = (
        plan_exists
        and disposition == "active"
        and all_done
        and has_pr
        and pr_state in {"open", "merged"}
    )
    if not merge_ready:
        if not plan_exists:
            merge_reason = "Plan file missing"
        elif disposition != "active":
            merge_reason = f"Disposition is {disposition}, not active"
        elif not all_done:
            merge_reason = "Not all todos completed"
        elif not has_pr:
            merge_reason = "No PR linked yet"
        else:
            merge_reason = "PR state unknown"
    else:
        merge_reason = ""

    archive_ok = plan_exists and (
        disposition in {"merge-ready", "implemented"}
        or (pr_state == "merged" and all_done)
    )
    if not archive_ok:
        if not plan_exists:
            archive_reason = "Plan file missing"
        elif disposition in {"archived", "scratched"}:
            archive_reason = f"Already {disposition}"
        else:
            archive_reason = "Requires merge-ready/implemented or merged PR with todos done"
    else:
        archive_reason = ""

    continue_ok = plan_exists and disposition in {"active", "merge-ready"}
    if not continue_ok:
        continue_reason = (
            "Plan file missing"
            if not plan_exists
            else f"Disposition {disposition} not in build queue"
        )
    else:
        continue_reason = "" if has_branch else "Branch will be created on continue"

    return {
        "audit": _gate(plan_exists, "Plan file missing"),
        "apply_sync": _gate(False, "Run audit first"),
        "research": _gate(plan_exists, "Plan file missing"),
        "merge_ready": _gate(merge_ready, merge_reason),
        "archive": _gate(archive_ok, archive_reason),
        "continue": _gate(continue_ok, continue_reason),
    }
