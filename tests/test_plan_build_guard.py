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
    repo = _init_git_repo(tmp_path / "repo")
    (repo / ".cursor" / "plans").mkdir(parents=True)
    return repo


def _init_git_repo(repo: Path) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
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
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


def _run_guard(
    repo: Path,
    plan_rel: str,
    *,
    create_only: bool = False,
    plans_root: Path | None = None,
    base_branch: str | None = None,
    cwd: Path | None = None,
) -> dict:
    cmd = [
        sys.executable,
        str(_GUARD_SCRIPT),
        "--plan",
        plan_rel,
        "--repo-root",
        str(repo),
    ]
    if plans_root is not None:
        cmd += ["--plans-root", str(plans_root)]
    if base_branch is not None:
        cmd += ["--base-branch", base_branch]
    if create_only:
        cmd.append("--create-only")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=cwd)
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


def test_plan_outside_repo_root_is_resolved(tmp_path: Path) -> None:
    """Workspace keeps plans at its root; code lives in a nested repo."""
    workspace = tmp_path / "workspace"
    plans = workspace / ".cursor" / "plans"
    plans.mkdir(parents=True)
    repo = _init_git_repo(workspace / "PROSPECTOR")
    plan = plans / "prospector-intake.plan.md"
    plan.write_text(
        "---\ndisposition: active\nbranch: feature/prospector-intake\n---\n\n# Intake\n",
        encoding="utf-8",
    )

    out = _run_guard(
        repo,
        ".cursor/plans/prospector-intake.plan.md",
        create_only=True,
        plans_root=workspace,
    )
    assert out["ok"] is True
    assert out["branch"] == "feature/prospector-intake"
    assert out["planOutsideRepo"] is True
    assert out["planSource"].endswith(".cursor/plans/prospector-intake.plan.md")
    assert out["planPath"] == plan.resolve().as_posix()


def test_plan_outside_repo_root_found_via_cwd(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    plans = workspace / ".cursor" / "plans"
    plans.mkdir(parents=True)
    repo = _init_git_repo(workspace / "PROSPECTOR")
    (plans / "cwd.plan.md").write_text(
        "---\ndisposition: active\nbranch: feature/cwd-plan\n---\n\n# CWD plan\n",
        encoding="utf-8",
    )

    out = _run_guard(repo, ".cursor/plans/cwd.plan.md", create_only=True, cwd=workspace)
    assert out["ok"] is True
    assert out["branch"] == "feature/cwd-plan"


def test_missing_plan_reports_searched_roots(tmp_git_repo: Path) -> None:
    out = _run_guard(tmp_git_repo, ".cursor/plans/nope.plan.md", create_only=True)
    assert out["ok"] is False
    assert "plan not found" in out["error"]
    assert out["searchedRoots"]


def test_repo_root_must_be_git_repo(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    plans = workspace / ".cursor" / "plans"
    plans.mkdir(parents=True)
    (plans / "p.plan.md").write_text("---\ndisposition: active\n---\n\n# Plan\n", encoding="utf-8")
    out = _run_guard(workspace, ".cursor/plans/p.plan.md", create_only=True)
    assert out["ok"] is False
    assert out["error"] == "not_a_git_repo"


def _branch_head(repo: Path, branch: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", branch],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _add_branch_with_commit(repo: Path, branch: str) -> None:
    subprocess.run(["git", "-C", str(repo), "branch", branch], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "switch", branch], check=True, capture_output=True)
    (repo / f"{branch.replace('/', '-')}.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", f"on {branch}"],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "-C", str(repo), "switch", "main"], check=True, capture_output=True)


def test_base_branch_flag_overrides_default(tmp_git_repo: Path) -> None:
    _add_branch_with_commit(tmp_git_repo, "develop")
    plan = tmp_git_repo / ".cursor" / "plans" / "flagged.plan.md"
    plan.write_text(
        "---\ndisposition: active\nbranch: feature/from-develop\n---\n\n# Flagged\n",
        encoding="utf-8",
    )
    out = _run_guard(
        tmp_git_repo,
        ".cursor/plans/flagged.plan.md",
        create_only=True,
        base_branch="develop",
    )
    assert out["ok"] is True
    assert out["baseBranch"] == "develop"
    assert _branch_head(tmp_git_repo, "feature/from-develop") == _branch_head(
        tmp_git_repo, "develop"
    )


def test_base_branch_from_plan_frontmatter(tmp_git_repo: Path) -> None:
    _add_branch_with_commit(tmp_git_repo, "develop")
    plan = tmp_git_repo / ".cursor" / "plans" / "fm-base.plan.md"
    plan.write_text(
        "---\n"
        "disposition: active\n"
        "branch: feature/fm-base\n"
        "base_branch: develop\n"
        "---\n\n"
        "# Frontmatter base\n",
        encoding="utf-8",
    )
    out = _run_guard(tmp_git_repo, ".cursor/plans/fm-base.plan.md", create_only=True)
    assert out["baseBranch"] == "develop"
    assert _branch_head(tmp_git_repo, "feature/fm-base") == _branch_head(tmp_git_repo, "develop")


def test_base_branch_falls_back_to_existing_default(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("plan_branch_utils", _UTILS_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    repo = tmp_path / "master-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "master"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True
    )
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    assert mod.resolve_base_branch(repo) == "master"
    assert mod.resolve_base_branch(repo, "custom-base") == "custom-base"


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
