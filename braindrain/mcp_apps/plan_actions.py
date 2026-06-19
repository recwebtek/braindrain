"""Plan board action tools: audit, sync, merge-ready, archive, continue."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from braindrain.mcp_apps.plan_gates import compute_action_gates
from braindrain.mcp_apps.plan_paths import resolve_plan_path

_PATH_RE = re.compile(
    r"`([^`]+)`|"
    r'"([^"]+\.(?:py|md|yaml|yml|json|toml))"|'
    r"(?<![\w./])((?:tests|braindrain|scripts|config)/[\w./-]+)"
)
_FILE_EXT_RE = re.compile(r"\b((?:[\w.-]+/)+[\w.-]+\.(?:py|md|yaml|yml|json|toml))\b")
_CONFIDENCE_ORDER = {"high": 3, "medium": 2, "low": 1}


def _ensure_scripts_importable(repo_root: Path) -> None:
    root = str(repo_root.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)


def _extract_paths(content: str) -> list[str]:
    paths: list[str] = []
    try:
        from scripts.daily_plan_audit import extract_path_refs

        paths.extend(extract_path_refs(content))
    except ImportError:
        pass
    for match in _PATH_RE.finditer(content):
        path = next(g for g in match.groups() if g)
        path = path.strip().strip("'\"")
        if path and path not in paths:
            paths.append(path)
    for match in _FILE_EXT_RE.finditer(content):
        path = match.group(1).strip()
        if path and path not in paths:
            paths.append(path)
    return paths


def _keyword_path_hints(content: str, repo_root: Path) -> list[str]:
    """Map common todo phrases to known repo paths when files exist."""
    lowered = content.lower()
    hints: list[str] = []
    checks: list[tuple[tuple[str, ...], str]] = [
        (("snapshot", "schema"), "tests/fixtures/mcp_tool_schemas_snapshot.json"),
        (("mcp_tool_schemas",), "tests/fixtures/mcp_tool_schemas_snapshot.json"),
        (("config_schema",), "braindrain/config_schema.py"),
        (("token_benchmark",), "braindrain/token_benchmark.py"),
        (("plan_enrich",), "braindrain/mcp_apps/plan_enrich.py"),
        (("plan_actions",), "braindrain/mcp_apps/plan_actions.py"),
        (("streamable",), "braindrain/server.py"),
        (("primer",), "braindrain/primer/__init__.py"),
    ]
    for keywords, rel in checks:
        if all(k in lowered for k in keywords) and (repo_root / rel).is_file():
            hints.append(rel)
    return hints


def _todo_plan_snippet(plan_text: str, todo: dict[str, str]) -> str:
    """Collect plan body lines that mention this todo id (phase sections)."""
    todo_id = str(todo.get("id") or "").strip()
    if not todo_id or "---" not in plan_text:
        return ""
    body = plan_text.split("---", 2)[-1]
    block: list[str] = []
    capturing = False
    for line in body.splitlines():
        if todo_id in line:
            capturing = True
        if capturing:
            block.append(line)
            if len(block) >= 20:
                break
    return "\n".join(block)


def _branch_changed_files(repo_root: Path, branch: str) -> list[str]:
    branch = branch.strip()
    if not branch or branch in {"—", "-", "none", "n/a"}:
        return []
    for base_ref in ("main", "master", "origin/main", "origin/master"):
        try:
            verify = subprocess.run(
                ["git", "rev-parse", "--verify", base_ref],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if verify.returncode != 0:
                continue
            for diff_args in (
                ["git", "diff", "--name-only", f"{base_ref}...{branch}"],
                ["git", "diff", "--name-only", base_ref, branch],
            ):
                diff = subprocess.run(
                    diff_args,
                    cwd=repo_root,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if diff.returncode == 0 and diff.stdout.strip():
                    return [ln.strip() for ln in diff.stdout.splitlines() if ln.strip()]
        except (OSError, subprocess.TimeoutExpired):
            continue
    return []


def _todo_branch_evidence(todo: dict[str, str], branch_files: list[str]) -> list[str]:
    if not branch_files:
        return []
    haystack = f"{todo.get('id', '')} {todo.get('content', '')}".lower()
    tokens = {t for t in re.findall(r"[a-z][a-z0-9_/-]{3,}", haystack)}
    tokens -= {
        "phase",
        "server",
        "plan",
        "todo",
        "item",
        "with",
        "from",
        "that",
        "this",
        "merge",
        "update",
        "implement",
        "modernization",
        "baseline",
    }
    matched: list[str] = []
    for path in branch_files:
        normalized = path.lower().replace("/", " ").replace("-", " ").replace("_", " ")
        for tok in tokens:
            if tok in normalized or tok in path.lower():
                matched.append(path)
                break
    return matched


def _resolve_root(path: str) -> Path:
    return Path(path or ".").expanduser().resolve()


def _plan_path(repo_root: Path, source: str) -> Path:
    return resolve_plan_path(repo_root, source)


def _load_plan_text(repo_root: Path, source: str) -> tuple[Path, str]:
    plan_path = _plan_path(repo_root, source)
    if not plan_path.is_file():
        raise FileNotFoundError(f"Plan not found: {source}")
    return plan_path, plan_path.read_text(encoding="utf-8", errors="ignore")


def _resolve_pr_state(pr_url: str, *, timeout: float = 8.0) -> str:
    if not pr_url:
        return "none"
    try:
        proc = subprocess.run(
            ["gh", "pr", "view", pr_url, "--json", "state,mergedAt"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode != 0:
            return "open"
        data = json.loads(proc.stdout or "{}")
        state = str(data.get("state") or "").upper()
        if state == "MERGED" or data.get("mergedAt"):
            return "merged"
        if state == "OPEN":
            return "open"
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return "open"
    return "open"


def _todo_summary_from_todos(todos: list[dict[str, str]]) -> dict[str, int]:
    summary = {"total": len(todos), "completed": 0, "pending": 0, "in_progress": 0, "cancelled": 0}
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


def _audit_todo(
    repo_root: Path,
    todo: dict[str, str],
    *,
    plan_snippet: str = "",
    branch_files: list[str] | None = None,
) -> dict[str, Any] | None:
    status = str(todo.get("status") or "pending").lower()
    if status in {"completed", "cancelled"}:
        return None
    content = str(todo.get("content") or "")
    combined = "\n".join(part for part in (content, plan_snippet) if part)
    paths = _extract_paths(combined)
    paths.extend(_keyword_path_hints(combined, repo_root))
    paths = list(dict.fromkeys(paths))
    evidence: list[str] = []
    found = 0
    for rel in paths:
        candidate = repo_root / rel
        if candidate.is_file() or candidate.is_dir():
            found += 1
            evidence.append(f"exists: {rel}")
        else:
            evidence.append(f"missing: {rel}")
    if not paths:
        branch_hits = _todo_branch_evidence(todo, branch_files or [])
        existing_branch = [p for p in branch_hits if (repo_root / p).is_file()]
        if existing_branch:
            return {
                "todo_id": todo.get("id") or "",
                "content": content,
                "current_status": status,
                "suggested_status": "completed",
                "confidence": "medium",
                "evidence": [f"branch: {p}" for p in existing_branch[:5]],
            }
        if "snapshot" in content.lower() and "schema" in content.lower():
            fixture = repo_root / "tests/fixtures/mcp_tool_schemas_snapshot.json"
            if fixture.is_file():
                return {
                    "todo_id": todo.get("id") or "",
                    "content": content,
                    "current_status": status,
                    "suggested_status": "completed",
                    "confidence": "medium",
                    "evidence": [f"exists: {fixture.relative_to(repo_root).as_posix()}"],
                }
        return None
    if found == len(paths):
        confidence = "high" if found >= 1 else "medium"
        return {
            "todo_id": todo.get("id") or "",
            "content": content,
            "current_status": status,
            "suggested_status": "completed",
            "confidence": confidence,
            "evidence": evidence,
        }
    if found > 0:
        return {
            "todo_id": todo.get("id") or "",
            "content": content,
            "current_status": status,
            "suggested_status": status,
            "confidence": "low",
            "evidence": evidence,
        }
    return None


def audit_plan_implementation(
    *,
    path: str,
    source: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Compare plan todos against repo files; return sync proposals (read-only)."""
    repo_root = _resolve_root(path)
    _ensure_scripts_importable(repo_root)
    from scripts.plan_branch_utils import parse_frontmatter_todos, parse_plan_frontmatter

    plan_path, text = _load_plan_text(repo_root, source)
    fm = parse_plan_frontmatter(text)
    todos = parse_frontmatter_todos(text)
    rel_source = plan_path.relative_to(repo_root).as_posix()
    branch = str(fm.get("branch") or "").strip()
    branch_files = _branch_changed_files(repo_root, branch)

    proposals: list[dict[str, Any]] = []
    for todo in todos:
        snippet = _todo_plan_snippet(text, todo)
        proposal = _audit_todo(
            repo_root,
            todo,
            plan_snippet=snippet,
            branch_files=branch_files,
        )
        if proposal:
            proposals.append(proposal)

    pr_url = str(fm.get("pr") or "").strip()
    pr_state = _resolve_pr_state(pr_url) if pr_url else "none"
    pr = {"label": "PR", "url": pr_url, "state": pr_state} if pr_url else None

    group = {
        "source": rel_source,
        "disposition": str(fm.get("disposition") or "active"),
        "branch": str(fm.get("branch") or "—"),
        "pr": pr,
        "todo_summary": _todo_summary_from_todos(todos),
    }
    gates = compute_action_gates(group, repo_root=repo_root, pr_state=pr_state)
    if proposals:
        gates = dict(gates)
        gates["apply_sync"] = {"enabled": True, "reason": ""}

    summary = f"{len(proposals)} todo(s) may need sync" if proposals else "No drift detected"
    return {
        "source": rel_source,
        "disposition": group["disposition"],
        "branch": group["branch"],
        "pr": pr,
        "dry_run": dry_run,
        "proposals": proposals,
        "action_gates": gates,
        "summary": summary,
    }


def _refresh_plan_reports(repo_root: Path, *, trigger: str = "plan-board-sync") -> dict[str, Any]:
    script = repo_root / "scripts" / "daily_plan_audit.py"
    if not script.is_file():
        return {"ok": False, "reason": "daily_plan_audit.py not found"}
    python = "/usr/bin/python3"
    proc = subprocess.run(
        [
            python,
            str(script),
            "--repo-root",
            str(repo_root),
            "--trigger",
            trigger,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    ok = proc.returncode == 0
    return {
        "ok": ok,
        "summary": "Planning reports refreshed" if ok else "Masterplan run failed",
        "trigger": trigger,
        "stderr_tail": (proc.stderr or "")[-400:] if not ok else "",
    }


def run_masterplan_refresh(*, path: str) -> dict[str, Any]:
    """Regenerate .braindrain/plan-reports/ (same as /masterplan, read-only)."""
    repo_root = _resolve_root(path)
    return _refresh_plan_reports(repo_root, trigger="manual-masterplan-command")


def apply_plan_todo_sync(
    *,
    path: str,
    source: str,
    proposals: list[dict[str, Any]],
    confirm: bool = False,
) -> dict[str, Any]:
    """Apply todo status updates from audit proposals."""
    if not confirm:
        return {"ok": False, "reason": "confirm=True required"}
    repo_root = _resolve_root(path)
    _ensure_scripts_importable(repo_root)
    from scripts.plan_branch_utils import (
        parse_frontmatter_todos,
        render_frontmatter_todos,
        set_frontmatter_yaml_block,
    )

    plan_path, text = _load_plan_text(repo_root, source)
    todos = parse_frontmatter_todos(text)
    if not todos:
        return {"ok": False, "reason": "No todos in plan frontmatter"}

    applied: list[str] = []
    skipped: list[str] = []
    proposal_by_id = {
        str(p.get("todo_id") or ""): p
        for p in proposals
        if str(p.get("todo_id") or "")
    }
    for todo in todos:
        todo_id = str(todo.get("id") or "")
        proposal = proposal_by_id.get(todo_id)
        if not proposal:
            continue
        suggested = str(proposal.get("suggested_status") or "").lower()
        confidence = str(proposal.get("confidence") or "low").lower()
        if confidence not in {"high", "medium"}:
            skipped.append(todo_id)
            continue
        todo["status"] = suggested
        applied.append(todo_id)

    if not applied:
        return {"ok": False, "reason": "No proposals applied", "skipped": skipped}

    new_text = set_frontmatter_yaml_block(text, "todos", render_frontmatter_todos(todos))
    plan_path.write_text(new_text, encoding="utf-8")
    _refresh_plan_reports(repo_root)
    return {
        "ok": True,
        "applied": applied,
        "skipped": skipped,
        "refresh_hint": "Board refreshed; run /masterplan for full report sync",
    }


def mark_plan_merge_ready(*, path: str, source: str, confirm: bool = False) -> dict[str, Any]:
    """Set disposition merge-ready when PR exists and todos are complete."""
    if not confirm:
        return {"ok": False, "reason": "confirm=True required"}
    repo_root = _resolve_root(path)
    audit = audit_plan_implementation(path=str(repo_root), source=source, dry_run=True)
    gates = audit.get("action_gates") or {}
    if not gates.get("merge_ready", {}).get("enabled"):
        return {
            "ok": False,
            "reason": gates.get("merge_ready", {}).get("reason") or "merge-ready gate failed",
        }

    _ensure_scripts_importable(repo_root)
    from scripts.plan_branch_utils import set_frontmatter_key

    plan_path, text = _load_plan_text(repo_root, source)
    new_text = set_frontmatter_key(text, "disposition", "merge-ready")
    plan_path.write_text(new_text, encoding="utf-8")
    _refresh_plan_reports(repo_root)
    return {"ok": True, "disposition": "merge-ready", "source": source}


def set_plan_disposition(
    *,
    path: str,
    source: str,
    disposition: str,
    confirm: bool = False,
) -> dict[str, Any]:
    """Set plan frontmatter ``disposition`` to any auditor-valid value."""
    if not confirm:
        return {"ok": False, "reason": "confirm=True required"}
    repo_root = _resolve_root(path)
    _ensure_scripts_importable(repo_root)
    from scripts.daily_plan_audit import VALID_DISPOSITIONS
    from scripts.plan_branch_utils import set_frontmatter_key

    disp = str(disposition or "").strip().lower()
    if disp not in VALID_DISPOSITIONS:
        return {
            "ok": False,
            "reason": f"Invalid disposition: {disposition}. Valid: {', '.join(VALID_DISPOSITIONS)}",
        }

    plan_path, text = _load_plan_text(repo_root, source)
    new_text = set_frontmatter_key(text, "disposition", disp)
    plan_path.write_text(new_text, encoding="utf-8")
    _refresh_plan_reports(repo_root)
    return {
        "ok": True,
        "disposition": disp,
        "source": source,
        "refresh_hint": "Run /masterplan to sync master index and task board",
    }


def archive_plan(
    *,
    path: str,
    source: str,
    confirm: bool = False,
    force: bool = False,
    cancel_note: str = "",
) -> dict[str, Any]:
    """Archive a single plan file to .plan.archives/."""
    if not confirm:
        return {"ok": False, "reason": "confirm=True required"}
    repo_root = _resolve_root(path)
    if not force:
        audit = audit_plan_implementation(path=str(repo_root), source=source, dry_run=True)
        gates = audit.get("action_gates") or {}
        if not gates.get("archive", {}).get("enabled"):
            return {
                "ok": False,
                "reason": gates.get("archive", {}).get("reason") or "archive gate failed",
            }

    _ensure_scripts_importable(repo_root)
    from scripts.plan_branch_utils import (
        parse_frontmatter_todos,
        render_frontmatter_todos,
        set_frontmatter_key,
        set_frontmatter_yaml_block,
    )

    plan_path, text = _load_plan_text(repo_root, source)
    if force:
        note = (cancel_note or "").strip() or "Cancelled — outdated or superseded plan."
        todos = parse_frontmatter_todos(text)
        for todo in todos:
            status = str(todo.get("status") or "pending").lower()
            if status in {"pending", "in_progress"}:
                todo["status"] = "cancelled"
        text = set_frontmatter_yaml_block(text, "todos", render_frontmatter_todos(todos))
        text = set_frontmatter_key(text, "disposition", "scratched")
        text = set_frontmatter_key(text, "overview", note)
        updated = set_frontmatter_key(text, "archived", "true")
    else:
        updated = set_frontmatter_key(text, "disposition", "archived")
        updated = set_frontmatter_key(updated, "archived", "true")
    plan_path.write_text(updated, encoding="utf-8")

    archive_dir = plan_path.parent / ".plan.archives"
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = archive_dir / plan_path.name
    if dest.exists():
        ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        dest = archive_dir / f"{plan_path.stem}.bak.{ts}{plan_path.suffix}"
    shutil.move(str(plan_path), str(dest))
    new_rel = dest.relative_to(repo_root).as_posix()
    _refresh_plan_reports(repo_root)
    return {
        "ok": True,
        "archived_to": new_rel,
        "disposition": "scratched" if force else "archived",
        "cancel_note": cancel_note if force else "",
        "refresh_hint": "Run /masterplan to sync master index and links",
    }


def _upsert_gitops_queue(repo_root: Path, entry: dict[str, object]) -> None:
    queue_path = repo_root / ".cursor" / ".gitops-queue.json"
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []
    if queue_path.is_file():
        try:
            entries = json.loads(queue_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            entries = []
    if not isinstance(entries, list):
        entries = []
    plan_source = str(entry.get("planSource") or "").lstrip("/")
    filtered = [
        e
        for e in entries
        if str(e.get("planSource") or "").lstrip("/") != plan_source
    ]
    filtered.append(entry)
    queue_path.write_text(json.dumps(filtered, indent=2) + "\n", encoding="utf-8")


def enqueue_plan_continue(*, path: str, source: str, confirm: bool = False) -> dict[str, Any]:
    """Queue branch-setup / continue-build for a plan."""
    if not confirm:
        return {"ok": False, "reason": "confirm=True required"}
    repo_root = _resolve_root(path)
    audit = audit_plan_implementation(path=str(repo_root), source=source, dry_run=True)
    gates = audit.get("action_gates") or {}
    if not gates.get("continue", {}).get("enabled"):
        return {
            "ok": False,
            "reason": gates.get("continue", {}).get("reason") or "continue gate failed",
        }

    _ensure_scripts_importable(repo_root)
    from scripts.plan_branch_utils import (
        branch_name_for_plan,
        branch_ref_exists,
        create_branch_ref,
        parse_plan_frontmatter,
        resolve_base_branch,
        set_frontmatter_key,
    )

    plan_path = _plan_path(repo_root, source)
    text = plan_path.read_text(encoding="utf-8", errors="ignore")
    fm = parse_plan_frontmatter(text)
    branch = str(fm.get("branch") or "").strip()
    if not branch or branch in {"—", "-"}:
        branch = branch_name_for_plan(plan_path)
    base = resolve_base_branch(repo_root)
    created = False
    if not branch_ref_exists(repo_root, branch):
        ok, msg = create_branch_ref(repo_root, branch, base)
        if not ok:
            return {"ok": False, "reason": msg}
        created = True

    rel_source = plan_path.relative_to(repo_root).as_posix()
    if not re.search(r"(?m)^branch\s*:", text):
        plan_path.write_text(set_frontmatter_key(text, "branch", branch), encoding="utf-8")

    _upsert_gitops_queue(
        repo_root,
        {
            "action": "branch-setup",
            "branchName": branch,
            "baseBranch": base,
            "planSource": rel_source,
            "status": "pending",
            "source": "plan_board",
        },
    )
    handoff = (
        f"Continue Plan Build on branch `{branch}` for `{rel_source}`. "
        "Checkout the branch, verify plan todos, and run the next pending todo."
    )
    return {
        "ok": True,
        "branch": branch,
        "branch_created": created,
        "queue_status": "pending",
        "handoff_message": handoff,
    }


def plan_board_handoff(*, action: str, source: str, branch: str = "") -> dict[str, Any]:
    """Build chat handoff text for research or continue actions."""
    action = action.strip().lower()
    if action == "research":
        message = (
            f"Deep research for plan `{source}`: compare plan todos and body against the "
            "current codebase, list gaps, and propose frontmatter todo updates."
        )
    elif action == "continue":
        branch_part = f" on `{branch}`" if branch else ""
        message = (
            f"Continue implementation for `{source}`{branch_part}. Checkout the branch, "
            "read plan todos, and execute the next pending item."
        )
    else:
        message = f"Plan board action `{action}` for `{source}`."
    return {"message": message, "action": action, "source": source}


def dispatch_plan_board_action(
    *,
    path: str,
    action: str = "",
    source: str = "",
    confirm: bool = False,
    force: bool = False,
    cancel_note: str = "",
    dry_run: bool = True,
    proposals: list[dict[str, Any]] | None = None,
    branch: str = "",
    disposition: str = "",
) -> dict[str, Any]:
    """Route plan-board iframe actions through poll_plan_board (host-safe single tool)."""
    from braindrain.mcp_apps.data import build_plan_board_payload

    action_key = (action or "").strip().lower()
    if not action_key:
        return build_plan_board_payload(path=path)

    result: dict[str, Any]
    if action_key == "audit":
        result = audit_plan_implementation(path=path, source=source, dry_run=dry_run)
    elif action_key == "apply_sync":
        result = apply_plan_todo_sync(
            path=path,
            source=source,
            proposals=proposals or [],
            confirm=confirm,
        )
    elif action_key == "merge_ready":
        result = mark_plan_merge_ready(path=path, source=source, confirm=confirm)
    elif action_key == "archive":
        result = archive_plan(path=path, source=source, confirm=confirm, force=force)
    elif action_key in {"cancel_plan", "force_archive"}:
        result = archive_plan(
            path=path,
            source=source,
            confirm=confirm,
            force=True,
            cancel_note=cancel_note,
        )
    elif action_key == "continue":
        result = enqueue_plan_continue(path=path, source=source, confirm=confirm)
    elif action_key == "research":
        result = plan_board_handoff(action="research", source=source, branch=branch)
    elif action_key == "handoff_continue":
        result = plan_board_handoff(action="continue", source=source, branch=branch)
    elif action_key == "masterplan":
        result = run_masterplan_refresh(path=path)
    elif action_key in {"set_disposition", "disposition"}:
        result = set_plan_disposition(
            path=path,
            source=source,
            disposition=disposition,
            confirm=confirm,
        )
    else:
        result = {"ok": False, "reason": f"Unknown action: {action_key}"}

    payload = build_plan_board_payload(path=path)
    payload["action_result"] = result
    payload["action"] = action_key
    if source:
        payload["action_source"] = source
    return payload
