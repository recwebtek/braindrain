"""Tests for plan archive relocation and master-list archive hints."""

from __future__ import annotations

import importlib.util
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
    assert "| Plan | Owner | Branch | Priority |" in mirror
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
