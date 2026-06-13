"""Tests for plan_build_guard meta blocking and branch resolution."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GUARD_SCRIPT = _REPO_ROOT / "scripts" / "plan_build_guard.py"
_UTILS_SCRIPT = _REPO_ROOT / "scripts" / "plan_branch_utils.py"


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("# test\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    plans = repo / ".cursor" / "plans"
    plans.mkdir(parents=True)
    return repo


def _run_guard(repo: Path, plan_rel: str, *, create_only: bool = False) -> dict:
    cmd = [
        sys.executable,
        str(_GUARD_SCRIPT),
        "--plan",
        plan_rel,
        "--repo-root",
        str(repo),
    ]
    if create_only:
        cmd.append("--create-only")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return json.loads(proc.stdout or "{}")


def test_meta_plan_blocked(tmp_git_repo: Path) -> None:
    plan = tmp_git_repo / ".cursor" / "plans" / "umbrella.plan.md"
    plan.write_text(
        "---\n"
        "disposition: meta\n"
        "children_spec:\n"
        "  - id: child-a\n"
        "    file: child-a.plan.md\n"
        "    branch: feature/child-a\n"
        "---\n\n"
        "# Umbrella\n",
        encoding="utf-8",
    )
    out = _run_guard(tmp_git_repo, ".cursor/plans/umbrella.plan.md", create_only=True)
    assert out["ok"] is False
    assert out["error"] == "meta_plan_no_build"
    assert out["guardReason"] == "meta_plan_no_build"
    assert out["disposition"] == "meta"


def test_explicit_branch_honored(tmp_git_repo: Path) -> None:
    branch = "features/genai-ldmode-option-toggle"
    plan = tmp_git_repo / ".cursor" / "plans" / "genai.plan.md"
    plan.write_text(
        f"---\ndisposition: active\nbranch: {branch}\n---\n\n# GenAI toggle\n",
        encoding="utf-8",
    )
    out = _run_guard(tmp_git_repo, ".cursor/plans/genai.plan.md", create_only=True)
    assert out["ok"] is True
    assert out["branch"] == branch


def test_resolve_plan_branch_prefers_frontmatter(tmp_git_repo: Path) -> None:
    spec = importlib.util.spec_from_file_location("plan_branch_utils", _UTILS_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    plan = tmp_git_repo / ".cursor" / "plans" / "named.plan.md"
    plan.write_text(
        "---\ndisposition: active\nbranch: feature/custom-branch\n---\n\n# Custom Branch Plan\n",
        encoding="utf-8",
    )
    assert mod.resolve_plan_branch(plan) == "feature/custom-branch"
    inferred = mod.branch_name_for_plan(plan)
    assert inferred != "feature/custom-branch"
