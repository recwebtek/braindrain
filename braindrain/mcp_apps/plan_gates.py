"""Action-button gating for plan board MCP App cards."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_EMPTY_BRANCH = {"", "—", "-", "none", "n/a", "null"}


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


def _has_meaningful_branch(branch: str) -> bool:
    return branch.strip().lower() not in _EMPTY_BRANCH


def _group_has_pr(group: dict[str, Any]) -> bool:
    pr = group.get("pr")
    if not pr:
        return False
    url = str(pr.get("url") or "").strip()
    if url.startswith("http"):
        return True
    label = str(pr.get("label") or "").strip().lower()
    return label not in {"", "none", "—", "-", "n/a", "null"}


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
    pr_state = (pr_state or "none").lower()
    has_pr = _group_has_pr(group)
    if has_pr and pr_state == "none":
        pr_state = "open"

    summary = group.get("todo_summary") or {}
    all_done = _todo_summary_all_done(summary)
    branch = str(group.get("branch") or "").strip()
    has_branch = _has_meaningful_branch(branch)

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

    archive_ok = plan_exists and disposition not in {"archived", "scratched"}
    if not archive_ok:
        if not plan_exists:
            archive_reason = "Plan file missing"
        elif disposition in {"archived", "scratched"}:
            archive_reason = f"Already {disposition}"
        else:
            archive_reason = "Cannot archive this plan"
    elif has_branch or has_pr:
        archive_reason = ""
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

    # Cancel/scratch: any open plan (branch/PR allowed — branch is not deleted).
    cancel_ok = bool(source) and plan_exists and disposition not in {"archived", "scratched"}
    if not cancel_ok:
        if disposition in {"archived", "scratched"}:
            cancel_reason = f"Already {disposition}"
        elif not plan_exists:
            cancel_reason = "Plan file missing"
        elif not source:
            cancel_reason = "No plan source path"
        else:
            cancel_reason = "Cannot cancel this plan"
    else:
        cancel_reason = ""

    return {
        "audit": _gate(plan_exists, "Plan file missing"),
        "apply_sync": _gate(False, "Run audit first"),
        "research": _gate(bool(source), "Plan file missing"),
        "merge_ready": _gate(merge_ready, merge_reason),
        "archive": _gate(archive_ok, archive_reason),
        "cancel_plan": _gate(cancel_ok, cancel_reason),
        "continue": _gate(continue_ok, continue_reason),
    }
