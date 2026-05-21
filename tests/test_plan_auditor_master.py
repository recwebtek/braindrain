"""Tests for plan archive relocation and master-list archive hints."""

from __future__ import annotations

import importlib.util
import os
import sys
import uuid
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_AUDIT_SCRIPT_PATH = _REPO_ROOT / "scripts" / "daily_plan_audit.py"


@pytest.fixture
def tmp_project_dir() -> Path:
    d = _REPO_ROOT / ".pytest_tmp" / f"audit-{uuid.uuid4().hex[:12]}"
    d.mkdir(parents=True, exist_ok=True)
    try:
        yield d
    finally:
        import shutil

        shutil.rmtree(d, ignore_errors=True)


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("daily_plan_audit", _AUDIT_SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_relocate_archived_plan_frontmatter(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    (plans / "stale.plan.md").write_text(
        "---\narchived: true\n---\n\n# Stale\n- [ ] done\n",
        encoding="utf-8",
    )
    moved = m.relocate_archived_plans(tmp_project_dir)
    assert moved
    assert any("stale.plan.md" in p for p in moved)
    assert not (plans / "stale.plan.md").is_file()
    assert (plans / ".plan.archives" / "stale.plan.md").is_file()


def test_relocate_archived_via_master_list(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    (plans / "gone.plan.md").write_text("# Gone\n- [ ] x\n", encoding="utf-8")
    (plans / "_master.plan.md").write_text(
        "---\n"
        "archived_plans:\n"
        "  - gone.plan.md\n"
        "---\n\n"
        "# Master\n",
        encoding="utf-8",
    )
    moved = m.relocate_archived_plans(tmp_project_dir)
    assert moved
    assert not (plans / "gone.plan.md").is_file()
    assert (plans / ".plan.archives" / "gone.plan.md").is_file()


def test_relocate_archived_via_master_scalar_archive_key(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    (plans / "solo.plan.md").write_text("# Solo\n", encoding="utf-8")
    (plans / "_master.plan.md").write_text(
        "---\narchive: solo.plan.md\n---\n\n# Master\n",
        encoding="utf-8",
    )
    moved = m.relocate_archived_plans(tmp_project_dir)
    assert moved
    assert not (plans / "solo.plan.md").is_file()
    assert (plans / ".plan.archives" / "solo.plan.md").is_file()


def test_plan_marked_archived_disposition() -> None:
    m = _load_audit_module()
    assert m.plan_marked_archived({"disposition": "archived"})
    assert m.plan_marked_archived({"status": "archived"})
    assert not m.plan_marked_archived({"disposition": "active"})


def test_report_includes_model_provenance_frontmatter(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    (tmp_project_dir / ".cursor" / "plans").mkdir(parents=True)
    (tmp_project_dir / ".cursor" / "plans" / "p.plan.md").write_text(
        "# Plan\n- [ ] owner: test item\n",
        encoding="utf-8",
    )
    trace_path = tmp_project_dir / ".braindrain" / "plan-reports" / "model-trace.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text(
        '{"model_name":"composer-2","actor":"coordinator"}\n'
        '{"model_name":"gpt-5.4-medium","actor":"research"}\n',
        encoding="utf-8",
    )

    argv = [
        "daily_plan_audit.py",
        "--repo-root",
        str(tmp_project_dir),
        "--report-date",
        "2026-06-02",
        "--model-name",
        "Codex 5.3",
        "--cursor-mode",
        "auto",
        "--trace-path",
        str(trace_path),
    ]
    from unittest.mock import patch

    with patch.object(sys, "argv", argv):
        assert m.main() == 0

    report = (
        tmp_project_dir
        / ".braindrain"
        / "plan-reports"
        / "plan-audit-2026-06-02.md"
    ).read_text(encoding="utf-8")
    assert 'created_by_model: "Codex 5.3"' in report
    assert 'cursor_mode: "auto"' in report
    assert 'subagent_models_used:' in report
    assert '    - "composer-2"' in report
    assert '    - "gpt-5.4-medium"' in report


def test_master_mirror_shows_frontmatter_branch(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    plan_path = plans / "alpha.plan.md"
    plan_path.write_text(
        "---\nbranch: feature/alpha\nowner: @ettienne\n---\n# Alpha\n- [ ] todo\n",
        encoding="utf-8",
    )
    item = m.PlanItem(
        item="todo",
        source=".cursor/plans/alpha.plan.md",
        status="Outstanding",
        confidence="high",
        evidence=[".cursor/plans/alpha.plan.md#item"],
        why="test",
        tokens={"todo"},
    )
    cards = m.build_cards_index(tmp_project_dir, [plan_path], [item], default_owner="@ettienne")
    mirror = m.render_master_mirror(list(cards.values()), {"frontmatter": {}, "children": []})
    assert "| Plan | Owner | Branch | PR | Priority |" in mirror
    assert "`feature/alpha`" in mirror


def test_branch_resolves_from_gitops_queue_when_frontmatter_missing(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    queue_file = tmp_project_dir / ".cursor" / ".gitops-queue.json"
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    queue_file.write_text(
        '[{"action":"branch-setup","branchName":"feature/admin-ops-tool-draft-flow","status":"pending"}]',
        encoding="utf-8",
    )
    plan_path = plans / "admin-ops-tool-draft-flow_d75bcec7.plan.md"
    plan_path.write_text("# Admin Ops Plan\n- [ ] todo\n", encoding="utf-8")
    item = m.PlanItem(
        item="todo",
        source=".cursor/plans/admin-ops-tool-draft-flow_d75bcec7.plan.md",
        status="Outstanding",
        confidence="high",
        evidence=[".cursor/plans/admin-ops-tool-draft-flow_d75bcec7.plan.md#item"],
        why="test",
        tokens={"todo"},
    )
    cards = m.build_cards_index(tmp_project_dir, [plan_path], [item], default_owner="@ettienne")
    card = cards[".cursor/plans/admin-ops-tool-draft-flow_d75bcec7.plan.md"]
    assert card.branch == "feature/admin-ops-tool-draft-flow"
    assert card.branch_source == "gitops_queue"


def test_branch_falls_back_to_dash_when_no_sources(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    plan_path = plans / "lonely.plan.md"
    plan_path.write_text("# Lonely Plan\n- [ ] todo\n", encoding="utf-8")
    item = m.PlanItem(
        item="todo",
        source=".cursor/plans/lonely.plan.md",
        status="Outstanding",
        confidence="high",
        evidence=[".cursor/plans/lonely.plan.md#item"],
        why="test",
        tokens={"todo"},
    )
    cards = m.build_cards_index(tmp_project_dir, [plan_path], [item], default_owner="@ettienne")
    card = cards[".cursor/plans/lonely.plan.md"]
    assert card.branch == "—"
    assert card.branch_source == "none"


def _git_init_with_branch(tmp_project_dir: Path, branch: str) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_project_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "checkout", "-b", branch],
        cwd=tmp_project_dir,
        check=True,
        capture_output=True,
    )
    readme = tmp_project_dir / "README.md"
    readme.write_text("test\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_project_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_project_dir,
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t.com", "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t.com"},
    )


def test_branch_resolves_from_local_git_when_slug_matches(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    _git_init_with_branch(tmp_project_dir, "feature/lonely-plan")
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    plan_path = plans / "lonely.plan.md"
    plan_path.write_text("# Lonely Plan\n- [ ] todo\n", encoding="utf-8")
    item = m.PlanItem(
        item="todo",
        source=".cursor/plans/lonely.plan.md",
        status="Outstanding",
        confidence="high",
        evidence=[".cursor/plans/lonely.plan.md#item"],
        why="test",
        tokens={"todo"},
    )
    cards = m.build_cards_index(tmp_project_dir, [plan_path], [item], default_owner="@ettienne")
    card = cards[".cursor/plans/lonely.plan.md"]
    assert card.branch == "feature/lonely-plan"
    assert card.branch_source == "git_local"


def test_queue_branch_matches_plan_source(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    queue_file = tmp_project_dir / ".cursor" / ".gitops-queue.json"
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    queue_file.write_text(
        '[{"action":"branch-setup","branchName":"feature/exact","planSource":".cursor/plans/exact.plan.md","status":"pending"}]',
        encoding="utf-8",
    )
    plan_path = plans / "exact.plan.md"
    plan_path.write_text("# Exact\n- [ ] todo\n", encoding="utf-8")
    item = m.PlanItem(
        item="todo",
        source=".cursor/plans/exact.plan.md",
        status="Outstanding",
        confidence="high",
        evidence=[".cursor/plans/exact.plan.md#item"],
        why="test",
        tokens={"todo"},
    )
    cards = m.build_cards_index(tmp_project_dir, [plan_path], [item], default_owner="@ettienne")
    card = cards[".cursor/plans/exact.plan.md"]
    assert card.branch == "feature/exact"
    assert card.branch_source == "gitops_queue"


def test_resolve_pr_for_branch_gh_mock(tmp_project_dir: Path) -> None:
    m = _load_audit_module()

    def fake_gh(_root: Path, branch: str) -> list[dict[str, object]] | None:
        if branch == "feature/x":
            return [{"number": 7, "state": "OPEN", "url": "https://github.com/o/r/pull/7"}]
        return []

    cell, source = m.resolve_pr_for_branch(
        tmp_project_dir, "feature/x", gh_runner=fake_gh
    )
    assert source == "gh"
    assert "[#7 open]" in cell
    assert "https://github.com/o/r/pull/7" in cell

    cell_none, src_none = m.resolve_pr_for_branch(
        tmp_project_dir, "feature/no-pr", gh_runner=fake_gh
    )
    assert cell_none == "none"
    assert src_none == "none"

    cell_dash, src_dash = m.resolve_pr_for_branch(tmp_project_dir, "—")
    assert cell_dash == "—"
    assert src_dash == "none"


def test_master_mirror_shows_pr_column(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    plan_path = plans / "alpha.plan.md"
    plan_path.write_text(
        "---\nbranch: feature/alpha\nowner: @ettienne\n---\n# Alpha\n- [ ] todo\n",
        encoding="utf-8",
    )
    item = m.PlanItem(
        item="todo",
        source=".cursor/plans/alpha.plan.md",
        status="Outstanding",
        confidence="high",
        evidence=[".cursor/plans/alpha.plan.md#item"],
        why="test",
        tokens={"todo"},
    )
    cards = m.build_cards_index(tmp_project_dir, [plan_path], [item], default_owner="@ettienne")

    def fake_gh(_root: Path, branch: str) -> list[dict[str, object]] | None:
        return [{"number": 1, "state": "MERGED", "url": "https://example.com/pr/1"}]

    m.apply_pr_resolution(cards, tmp_project_dir, gh_runner=fake_gh)
    mirror = m.render_master_mirror(list(cards.values()), {"frontmatter": {}, "children": []})
    assert "| PR |" in mirror
    assert "[#1 merged]" in mirror


def test_bootstrap_branches_writes_git_local_match(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    _git_init_with_branch(tmp_project_dir, "feature/boot-plan")
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    plan_path = plans / "boot.plan.md"
    plan_path.write_text(
        "---\ndisposition: active\nowner: @ettienne\n---\n# Boot Plan\n- [ ] todo\n",
        encoding="utf-8",
    )
    item = m.PlanItem(
        item="todo",
        source=".cursor/plans/boot.plan.md",
        status="Outstanding",
        confidence="high",
        evidence=[".cursor/plans/boot.plan.md#item"],
        why="test",
        tokens={"todo"},
    )
    cards = m.build_cards_index(tmp_project_dir, [plan_path], [item], default_owner="@ettienne")
    updated = m.bootstrap_plan_branches_from_git_local(tmp_project_dir, cards)
    assert updated == [".cursor/plans/boot.plan.md"]
    text = plan_path.read_text(encoding="utf-8")
    assert "branch: feature/boot-plan" in text
