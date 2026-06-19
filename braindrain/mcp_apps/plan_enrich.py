"""Enrich plan board groups with frontmatter todos, PR links, and rollups."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from braindrain.mcp_apps.plan_gates import compute_action_gates

_MASTER_DISPOSITION_ROW_RE = re.compile(
    r"^\|\s*\[([^\]]+)\]\([^)]+\)\s*\|\s*([^|]+)\|\s*`?([^`|]+)`?\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*$",
    re.MULTILINE,
)
_PR_LINK_RE = re.compile(r"^\[(.+?)\]\((.+?)\)$")


def _clean_cell(value: str) -> str:
    text = value.strip()
    if text.startswith("`") and text.endswith("`"):
        text = text[1:-1].strip()
    return text


def _parse_pr_cell(cell: str) -> dict[str, str] | None:
    text = cell.strip()
    if not text or text in {"none", "—", "-"}:
        return None
    match = _PR_LINK_RE.match(text)
    if match:
        return {"label": match.group(1).strip(), "url": match.group(2).strip()}
    return {"label": text, "url": ""}


def _parse_todo_fraction(cell: str) -> dict[str, int] | None:
    text = _clean_cell(cell).strip()
    if text in {"—", "-", ""}:
        return None
    match = re.match(r"(\d+)/(\d+)", text)
    if not match:
        return None
    return {"done": int(match.group(1)), "total": int(match.group(2))}


def _parse_item_rollups(cell: str) -> dict[str, int] | None:
    text = cell.strip()
    parts = text.split("/")
    if len(parts) != 5:
        return None
    keys = ("implemented", "active", "blocked", "outstanding", "unknown")
    try:
        return {key: int(part.strip()) for key, part in zip(keys, parts, strict=True)}
    except ValueError:
        return None


def parse_master_disposition_tables(markdown: str) -> dict[str, dict[str, Any]]:
    """Map plan source path -> PR/todo/item metadata from master-plan disposition tables."""
    meta: dict[str, dict[str, Any]] = {}
    for match in _MASTER_DISPOSITION_ROW_RE.finditer(markdown):
        title = match.group(1).strip()
        if title.lower() == "plan":
            continue
        source = _clean_cell(match.group(8))
        meta[source] = {
            "plan": title,
            "owner": match.group(2).strip(),
            "branch": _clean_cell(match.group(3)),
            "pr": _parse_pr_cell(match.group(4)),
            "priority": match.group(5).strip(),
            "todo_fraction": _parse_todo_fraction(match.group(6)),
            "item_rollups": _parse_item_rollups(match.group(7)),
            "source": source,
        }
    return meta


def compute_todo_summary(todos: list[dict[str, str]]) -> dict[str, int]:
    summary = {
        "total": len(todos),
        "completed": 0,
        "pending": 0,
        "in_progress": 0,
        "cancelled": 0,
    }
    for todo in todos:
        status = str(todo.get("status") or "pending").lower()
        if status == "completed":
            summary["completed"] += 1
        elif status == "in_progress":
            summary["in_progress"] += 1
        elif status == "cancelled":
            summary["cancelled"] += 1
        else:
            summary["pending"] += 1
    return summary


def _ensure_scripts_importable(repo_root: Path) -> None:
    root = str(repo_root.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)


def load_plan_file_meta(repo_root: Path, source: str) -> dict[str, Any]:
    """Read plan frontmatter todos and scalar fields when the plan file exists."""
    rel = source.lstrip("/")
    plan_path = repo_root / rel
    if not plan_path.is_file():
        return {}

    _ensure_scripts_importable(repo_root)
    try:
        from scripts.plan_branch_utils import parse_frontmatter_todos, parse_plan_frontmatter
    except ImportError:
        return {}

    try:
        text = plan_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}

    fm = parse_plan_frontmatter(text)
    todos = parse_frontmatter_todos(text)
    out: dict[str, Any] = {}
    if todos:
        out["todos"] = [
            {
                "id": todo.get("id") or "",
                "content": todo.get("content") or "",
                "status": str(todo.get("status") or "pending").lower(),
            }
            for todo in todos
        ]
        out["todo_summary"] = compute_todo_summary(out["todos"])
    for key in ("overview", "parent", "pr", "branch", "name"):
        value = fm.get(key)
        if value:
            out[key] = str(value).strip()
    pr_url = str(fm.get("pr") or "").strip()
    if pr_url.startswith("http"):
        out["pr"] = {"label": "PR", "url": pr_url}
    return out


def enrich_plan_groups(
    groups: list[dict[str, Any]],
    *,
    repo_root: Path,
    master_md: str,
    include_pr_without_open_items: bool = True,
) -> list[dict[str, Any]]:
    """Merge master-plan disposition tables and plan frontmatter into plan groups."""
    disposition_by_source = parse_master_disposition_tables(master_md)
    enriched: list[dict[str, Any]] = []

    seen_sources: set[str] = set()
    for group in groups:
        source = str(group.get("source") or "")
        seen_sources.add(source)
        merged = dict(group)
        disp = disposition_by_source.get(source, {})
        file_meta = load_plan_file_meta(repo_root, source)

        if disp.get("branch") and disp["branch"] not in {"—", "-"}:
            merged["branch"] = disp["branch"]
        if disp.get("owner"):
            merged["owner"] = disp["owner"]
        if disp.get("priority"):
            merged["priority"] = disp["priority"]
        if disp.get("pr"):
            merged["pr"] = disp["pr"]
        if disp.get("item_rollups"):
            merged["item_rollups"] = disp["item_rollups"]

        todo_summary = file_meta.get("todo_summary")
        if todo_summary:
            merged["todo_summary"] = todo_summary
            merged["todos"] = file_meta.get("todos") or []
        elif disp.get("todo_fraction"):
            frac = disp["todo_fraction"]
            merged["todo_summary"] = {
                "total": frac["total"],
                "completed": frac["done"],
                "pending": max(0, frac["total"] - frac["done"]),
                "in_progress": 0,
                "cancelled": 0,
            }

        if file_meta.get("pr") and not merged.get("pr"):
            merged["pr"] = file_meta["pr"]
        if file_meta.get("overview"):
            merged["overview"] = file_meta["overview"]
        if file_meta.get("parent"):
            merged["parent"] = file_meta["parent"]

        merged["action_gates"] = compute_action_gates(merged, repo_root=repo_root)
        enriched.append(merged)

    if include_pr_without_open_items:
        for source, disp in disposition_by_source.items():
            if source in seen_sources:
                continue
            pr = disp.get("pr")
            if not pr:
                continue
            file_meta = load_plan_file_meta(repo_root, source)
            todo_summary = file_meta.get("todo_summary")
            if not todo_summary and disp.get("todo_fraction"):
                frac = disp["todo_fraction"]
                todo_summary = {
                    "total": frac["total"],
                    "completed": frac["done"],
                    "pending": max(0, frac["total"] - frac["done"]),
                    "in_progress": 0,
                    "cancelled": 0,
                }
            enriched.append(
                {
                    "seq": 999,
                    "plan": disp.get("plan") or file_meta.get("name") or source,
                    "ide": "cursor",
                    "owner": disp.get("owner") or "—",
                    "priority": disp.get("priority") or "—",
                    "disposition": "merge-ready",
                    "branch": disp.get("branch") or file_meta.get("branch") or "—",
                    "next_verb": "MERGE",
                    "source": source,
                    "items": [],
                    "status_counts": {"Blocked": 0, "In Progress": 0, "Outstanding": 0},
                    "pr": pr,
                    "todo_summary": todo_summary,
                    "todos": file_meta.get("todos") or [],
                    "overview": file_meta.get("overview"),
                    "parent": file_meta.get("parent"),
                    "item_rollups": disp.get("item_rollups"),
                    "synthetic_from_pr": True,
                }
            )
            enriched[-1]["action_gates"] = compute_action_gates(enriched[-1], repo_root=repo_root)
    return enriched
