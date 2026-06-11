"""Shared plan → git branch naming and git helpers for audit and Plan Build guard."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def plan_type_from_text(head: str) -> str:
    """Infer branch prefix from plan title/body head (mirrors on-stop-gitops-plans.sh)."""
    lower = head[:2000].lower()
    if re.search(r"\bbugfix\b|\bbug\b|\bfix\b", lower):
        return "bugfix"
    if re.search(r"\bhotfix\b|\bhot\b", lower):
        return "hotfix"
    if re.search(r"\bchore\b|\bmaintenance\b|\bdependenc", lower):
        return "chore"
    if re.search(r"\brefactor\b", lower):
        return "refactor"
    if re.search(r"\bdocs\b|\bdocumentation\b", lower):
        return "docs"
    return "feature"


def slug_from_plan_path(plan_path: Path) -> str:
    text = plan_path.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        if line.startswith("# "):
            raw = line[2:].strip()
            break
    else:
        raw = plan_path.stem.replace(".plan", "")
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    return (slug or "plan")[:40]


def branch_name_for_plan(plan_path: Path, *, plan_type: str | None = None) -> str:
    ptype = plan_type or plan_type_from_text(
        plan_path.read_text(encoding="utf-8", errors="ignore")[:2000]
    )
    slug = slug_from_plan_path(plan_path)
    return f"{ptype}/{slug}"


def resolve_base_branch(repo_root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "show-ref", "--verify", "--quiet", "refs/heads/main"],
            capture_output=True,
            check=False,
        )
        if proc.returncode == 0:
            return "main"
        proc2 = subprocess.run(
            ["git", "-C", str(repo_root), "symbolic-ref", "refs/remotes/origin/HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc2.returncode == 0 and proc2.stdout.strip():
            ref = proc2.stdout.strip()
            if ref.startswith("refs/remotes/origin/"):
                return ref[len("refs/remotes/origin/") :]
    except OSError:
        pass
    return "main"


def branch_ref_exists(repo_root: Path, branch: str) -> bool:
    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/heads/{branch}",
            ],
            capture_output=True,
            check=False,
        )
        return proc.returncode == 0
    except OSError:
        return False


def create_branch_ref(repo_root: Path, branch: str, base_branch: str) -> tuple[bool, str]:
    """Create local branch without checkout. Returns (ok, message)."""
    if branch_ref_exists(repo_root, branch):
        return True, "already_exists"
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "branch", branch, base_branch],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return False, str(exc)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        return False, err or f"git branch failed ({proc.returncode})"
    return True, "created"


def current_branch(repo_root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            return (proc.stdout or "").strip()
    except OSError:
        pass
    return ""


def working_tree_dirty(repo_root: Path) -> bool:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.returncode == 0 and bool((proc.stdout or "").strip())
    except OSError:
        return False


def checkout_plan_branch(
    repo_root: Path,
    branch: str,
    *,
    plan_slug: str = "plan",
    allow_stash: bool = True,
) -> dict[str, object]:
    """
    Switch to plan branch (plan-execution policy).
    Stashes dirty tree when allow_stash=True; does not pop stash (caller/agent continues work).
    """
    result: dict[str, object] = {
        "ok": False,
        "branch": branch,
        "previous_branch": current_branch(repo_root),
        "stashed": False,
        "stash_ref": "",
        "message": "",
    }
    if not branch_ref_exists(repo_root, branch):
        result["message"] = f"branch not found: {branch}"
        return result
    current = str(result["previous_branch"])
    if current == branch:
        result["ok"] = True
        result["message"] = "already_on_branch"
        return result
    if working_tree_dirty(repo_root) and allow_stash:
        msg = f"braindrain plan-execution {plan_slug}"
        try:
            proc = subprocess.run(
                ["git", "-C", str(repo_root), "stash", "push", "-u", "-m", msg],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode == 0:
                result["stashed"] = True
                result["stash_ref"] = "stash@{0}"
        except OSError as exc:
            result["message"] = f"stash failed: {exc}"
            return result
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "switch", branch],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        result["message"] = str(exc)
        return result
    if proc.returncode != 0:
        result["message"] = (proc.stderr or proc.stdout or "").strip()
        return result
    result["ok"] = True
    result["message"] = "switched"
    return result
