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


def test_stale_frontmatter_loses_to_git_local_branch_with_pr(
    tmp_project_dir: Path,
) -> None:
    m = _load_audit_module()
    _git_init_with_branch(tmp_project_dir, "memory-config-wiring")
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    plan_path = plans / "memory_config_wiring_8d447816.plan.md"
    plan_path.write_text(
        "---\n"
        "branch: feature/memory-config-wiring-replaces-memory-les\n"
        "disposition: active\n"
        "owner: @ettienne\n"
        "---\n"
        "# Memory Config Wiring\n"
        "- [ ] todo\n",
        encoding="utf-8",
    )
    item = m.PlanItem(
        item="todo",
        source=".cursor/plans/memory_config_wiring_8d447816.plan.md",
        status="Outstanding",
        confidence="high",
        evidence=[".cursor/plans/memory_config_wiring_8d447816.plan.md#item"],
        why="test",
        tokens={"todo"},
    )
    cards = m.build_cards_index(tmp_project_dir, [plan_path], [item], default_owner="@ettienne")

    def fake_gh(_root: Path, branch: str) -> list[dict[str, object]] | None:
        if branch == "memory-config-wiring":
            return [{"number": 102, "state": "OPEN", "url": "https://github.com/o/r/pull/102"}]
        return []

    m.apply_pr_resolution(cards, tmp_project_dir, gh_runner=fake_gh)
    card = cards[".cursor/plans/memory_config_wiring_8d447816.plan.md"]
    assert card.branch == "memory-config-wiring"
    assert card.branch_source == "git_local"
    assert "[#102 open]" in card.pr


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
    m.apply_pr_resolution(cards, tmp_project_dir, gh_runner=lambda _r, _b: [])
    updated = m.bootstrap_plan_branches_from_git_local(tmp_project_dir, cards)
    assert updated == [".cursor/plans/boot.plan.md"]
    text = plan_path.read_text(encoding="utf-8")
    assert "branch: feature/boot-plan" in text


def test_bootstrap_corrects_stale_frontmatter_branch(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    _git_init_with_branch(tmp_project_dir, "memory-config-wiring")
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    plan_path = plans / "memory_config_wiring_8d447816.plan.md"
    plan_path.write_text(
        "---\n"
        "branch: feature/memory-config-wiring-replaces-memory-les\n"
        "disposition: active\n"
        "owner: @ettienne\n"
        "---\n"
        "# Memory Config Wiring\n",
        encoding="utf-8",
    )
    item = m.PlanItem(
        item="x",
        source=".cursor/plans/memory_config_wiring_8d447816.plan.md",
        status="Outstanding",
        confidence="high",
        evidence=[".cursor/plans/memory_config_wiring_8d447816.plan.md#item"],
        why="test",
        tokens={"x"},
    )
    cards = m.build_cards_index(tmp_project_dir, [plan_path], [item], default_owner="@ettienne")

    def fake_gh(_root: Path, branch: str) -> list[dict[str, object]] | None:
        if branch == "memory-config-wiring":
            return [{"number": 102, "state": "OPEN", "url": "https://example.com/pr/102"}]
        return []

    m.apply_pr_resolution(cards, tmp_project_dir, gh_runner=fake_gh)
    updated = m.bootstrap_plan_branches_from_git_local(tmp_project_dir, cards)
    assert updated == [".cursor/plans/memory_config_wiring_8d447816.plan.md"]
    assert "branch: memory-config-wiring" in plan_path.read_text(encoding="utf-8")


def test_ensure_plan_branches_creates_ref_and_frontmatter(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    _git_init_with_branch(tmp_project_dir, "main")
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    plan_path = plans / "new_feature.plan.md"
    plan_path.write_text(
        "---\ndisposition: active\nowner: @ettienne\n---\n# New Feature\n- [ ] todo\n",
        encoding="utf-8",
    )
    item = m.PlanItem(
        item="todo",
        source=".cursor/plans/new_feature.plan.md",
        status="Outstanding",
        confidence="high",
        evidence=[".cursor/plans/new_feature.plan.md#item"],
        why="test",
        tokens={"todo"},
    )
    cards = m.build_cards_index(tmp_project_dir, [plan_path], [item], default_owner="@ettienne")
    card = cards[".cursor/plans/new_feature.plan.md"]
    assert card.branch == "—"
    created = m.ensure_plan_branches(tmp_project_dir, cards)
    assert ".cursor/plans/new_feature.plan.md" in created
    assert "branch: feature/new-feature" in plan_path.read_text(encoding="utf-8")
    assert card.branch == "feature/new-feature"
    assert card.branch_source == "audit_created"


def test_todo_counts_ignore_open_body_checklist(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    plan_path = plans / "done.plan.md"
    plan_path.write_text(
        "---\n"
        "disposition: active\n"
        "owner: @test\n"
        "todos:\n"
        "  - id: a\n"
        "    content: First task\n"
        "    status: completed\n"
        "  - id: b\n"
        "    content: Second task\n"
        "    status: completed\n"
        "---\n"
        "# Done plan\n"
        "- [ ] still open in body but ignored for counts\n",
        encoding="utf-8",
    )
    items = m.collect_plan_items(plan_path, tmp_project_dir)
    cards = m.build_cards_index(tmp_project_dir, [plan_path], items, default_owner="@test")
    card = cards[".cursor/plans/done.plan.md"]
    assert card.count_source == "todos"
    assert card.counts.get("Implemented", 0) == 2
    assert card.counts.get("Outstanding", 0) == 0
    assert card.todo_summary == {
        "total": 2,
        "completed": 2,
        "pending": 0,
        "in_progress": 0,
        "cancelled": 0,
    }
    assert card.stale_narrative is True


def test_active_plan_all_todos_done_skips_implement_verb(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    plan_path = plans / "ready.plan.md"
    plan_path.write_text(
        "---\n"
        "disposition: active\n"
        "owner: @test\n"
        "todos:\n"
        "  - id: only\n"
        "    content: Ship it\n"
        "    status: completed\n"
        "---\n"
        "# Ready\n",
        encoding="utf-8",
    )
    items = m.collect_plan_items(plan_path, tmp_project_dir)
    cards = m.build_cards_index(tmp_project_dir, [plan_path], items, default_owner="@test")
    actions = m.detect_actions(list(cards.values()))
    assert not any(a.plan_slug == "ready" and a.verb == "IMPLEMENT" for a in actions)


def test_legacy_plan_without_todos_uses_body_counts(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    plan_path = plans / "legacy.plan.md"
    plan_path.write_text("# Legacy\n- [ ] open item\n", encoding="utf-8")
    items = m.collect_plan_items(plan_path, tmp_project_dir)
    cards = m.build_cards_index(tmp_project_dir, [plan_path], items, default_owner="@test")
    card = cards[".cursor/plans/legacy.plan.md"]
    assert card.count_source == "body"
    assert card.todo_summary is None
    assert card.counts.get("Outstanding", 0) == 1


def test_ready_to_archive_in_next_actions_and_audit(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    plan_path = plans / "archive_me.plan.md"
    plan_path.write_text(
        "---\n"
        "disposition: active\n"
        "owner: @test\n"
        "todos:\n"
        "  - id: done\n"
        "    content: Finished\n"
        "    status: completed\n"
        "---\n"
        "# Archive me\n",
        encoding="utf-8",
    )
    items = m.collect_plan_items(plan_path, tmp_project_dir)
    cards = m.build_cards_index(tmp_project_dir, [plan_path], items, default_owner="@test")
    ready = m.detect_ready_to_archive(list(cards.values()))
    assert len(ready) == 1
    assert ready[0].plan_slug == "archive_me"
    next_md = m.render_next_actions([], ready_to_archive=ready, report_date="2026-06-03")
    assert "## READY_TO_ARCHIVE (confirm with user)" in next_md
    assert ":archive_me]" in next_md
    report = m.build_report(
        "2026-06-03",
        "test",
        tmp_project_dir,
        [plan_path],
        [],
        items,
        cards_by_source=cards,
        ready_to_archive=ready,
    )
    assert "READY_TO_ARCHIVE: 1 plan(s)" in report
    assert "## READY_TO_ARCHIVE (confirm with user)" in report


def test_apply_disposition_sync_only_when_flag_set(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    plan_path = plans / "sync_me.plan.md"
    plan_path.write_text(
        "---\n"
        "disposition: active\n"
        "owner: @test\n"
        "todos:\n"
        "  - id: x\n"
        "    content: Done\n"
        "    status: completed\n"
        "---\n"
        "# Sync\n",
        encoding="utf-8",
    )
    items = m.collect_plan_items(plan_path, tmp_project_dir)
    cards = m.build_cards_index(tmp_project_dir, [plan_path], items, default_owner="@test")
    assert "disposition: implemented" not in plan_path.read_text(encoding="utf-8")
    updated = m.apply_disposition_sync(tmp_project_dir, cards)
    assert updated == [".cursor/plans/sync_me.plan.md"]
    assert "disposition: implemented" in plan_path.read_text(encoding="utf-8")


def test_master_drift_ignores_metadata_only_archived_plan(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    (plans / "_master.plan.md").write_text(
        "---\n"
        "archived_plans:\n"
        "  - deleted_superseded.plan.md\n"
        "---\n\n"
        "# Master\n\n"
        "## archived\n\n"
        "- [Deleted](deleted_superseded.plan.md) — DRI: @test\n",
        encoding="utf-8",
    )
    master_path = plans / "_master.plan.md"
    master_doc = m.parse_master_plan(master_path, tmp_project_dir)
    mirror = m.render_master_mirror(
        [],
        master_doc,
        repo_root=tmp_project_dir,
        report_date="2026-06-03",
    )
    assert "### In curated master but missing from disk:" not in mirror
    assert "No drift" in mirror or "metadata" not in mirror.lower()


def test_apply_archive_moves_plan_and_updates_master(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    master_path = plans / "_master.plan.md"
    master_path.write_text(
        "---\narchived_plans: []\n---\n\n# Master\n\n## active\n\n"
        "- [Done](done.plan.md) — DRI: @test\n",
        encoding="utf-8",
    )
    plan_path = plans / "done.plan.md"
    plan_path.write_text(
        "---\n"
        "disposition: active\n"
        "owner: @test\n"
        "dri: @test\n"
        "todos:\n"
        "  - id: x\n"
        "    content: All done\n"
        "    status: completed\n"
        "---\n"
        "# Done\n",
        encoding="utf-8",
    )
    items = m.collect_plan_items(plan_path, tmp_project_dir)
    cards = m.build_cards_index(tmp_project_dir, [plan_path], items, default_owner="@test")
    ready = m.detect_ready_to_archive(list(cards.values()))
    archived = m.apply_archive_plans(
        tmp_project_dir,
        ready,
        cards,
        master_path=master_path,
        report_paths=[],
    )
    assert archived
    assert not plan_path.is_file()
    archive_path = plans / ".plan.archives" / "done.plan.md"
    assert archive_path.is_file()
    master_text = master_path.read_text(encoding="utf-8")
    assert ".plan.archives/done.plan.md" in master_text
    assert "disposition: archived" in archive_path.read_text(encoding="utf-8")


def test_apply_archive_after_disposition_sync_in_same_run(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    master_path = plans / "_master.plan.md"
    master_path.write_text(
        "---\narchived_plans: []\n---\n\n# Master\n\n## active\n\n"
        "- [Done](done.plan.md) — DRI: @test\n",
        encoding="utf-8",
    )
    plan_path = plans / "done.plan.md"
    plan_path.write_text(
        "---\n"
        "disposition: active\n"
        "owner: @test\n"
        "dri: @test\n"
        "todos:\n"
        "  - id: x\n"
        "    content: All done\n"
        "    status: completed\n"
        "---\n"
        "# Done\n",
        encoding="utf-8",
    )
    items = m.collect_plan_items(plan_path, tmp_project_dir)
    cards = m.build_cards_index(tmp_project_dir, [plan_path], items, default_owner="@test")
    m.apply_disposition_sync(tmp_project_dir, cards)
    targets = m.detect_ready_to_archive(list(cards.values()), include_implemented=True)
    assert targets
    archived = m.apply_archive_plans(
        tmp_project_dir, targets, cards, master_path=master_path, report_paths=[]
    )
    assert archived
    assert (plans / ".plan.archives" / "done.plan.md").is_file()


def test_master_mirror_excludes_plan_archives_from_drift(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    archive_dir = plans / ".plan.archives"
    archive_dir.mkdir(parents=True)
    (archive_dir / "old.plan.md").write_text(
        "---\ndisposition: archived\n---\n# Old\n",
        encoding="utf-8",
    )
    (plans / "active.plan.md").write_text(
        "---\ndisposition: active\n---\n# Active\n- [ ] todo\n",
        encoding="utf-8",
    )
    (plans / "_master.plan.md").write_text(
        "---\narchived_plans:\n  - old.plan.md\n---\n\n"
        "# Master\n\n## active\n\n- [Active](active.plan.md)\n",
        encoding="utf-8",
    )
    plan_path = plans / "active.plan.md"
    items = m.collect_plan_items(plan_path, tmp_project_dir)
    cards = m.build_cards_index(tmp_project_dir, [plan_path], items, default_owner="@test")
    master_doc = m.parse_master_plan(plans / "_master.plan.md", tmp_project_dir)
    mirror = m.render_master_mirror(
        list(cards.values()), master_doc, repo_root=tmp_project_dir
    )
    assert "### On disk but missing from curated master:" not in mirror
    assert "archived plan(s) under `.plan.archives/`" in mirror


def test_sync_master_archived_batch_writes_pr_fields(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    archive_dir = plans / ".plan.archives"
    archive_dir.mkdir(parents=True)
    (archive_dir / "shipped.plan.md").write_text(
        "---\n"
        "disposition: archived\n"
        "branch: feature/shipped\n"
        "overview: Shipped the widget pipeline.\n"
        "owner: @test\n"
        "dri: @test\n"
        "---\n"
        "# Shipped\n",
        encoding="utf-8",
    )
    master_path = plans / "_master.plan.md"
    master_path.write_text("---\narchived_plans: []\n---\n\n# Master\n\n## archived\n\n", encoding="utf-8")

    def fake_gh(_root: Path, branch: str) -> list[dict[str, object]] | None:
        if branch == "feature/shipped":
            return [
                {
                    "number": 9,
                    "state": "MERGED",
                    "url": "https://github.com/o/r/pull/9",
                    "title": "Ship widgets",
                    "body": "Merged after CI green.",
                }
            ]
        return []

    # apply_pr_resolution uses gh_runner; patch at fetch in sync uses _fetch_pr_details
    import daily_plan_audit as mod

    original = mod._fetch_pr_details

    def fake_details(repo_root: Path, branch: str):
        if branch == "feature/shipped":
            return {
                "number": "9",
                "state": "merged",
                "url": "https://github.com/o/r/pull/9",
                "title": "Ship widgets",
                "body": "Merged after CI green.",
            }
        return original(repo_root, branch)

    mod._fetch_pr_details = fake_details
    try:
        synced = m.sync_master_archived_batch(tmp_project_dir, master_path, default_owner="@test")
    finally:
        mod._fetch_pr_details = original

    assert synced == ["shipped.plan.md"]
    text = master_path.read_text(encoding="utf-8")
    assert "Branch: `feature/shipped`" in text
    assert "[#9 merged]" in text
    assert "Ship widgets" in text
    assert "Plan summary: Shipped the widget pipeline." in text
    assert "archived_plans:" in text
    assert "  - shipped.plan.md" in text


def test_parse_master_plan_active_children_section(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    (plans / "first.plan.md").write_text("---\ndisposition: active\n---\n# First\n", encoding="utf-8")
    (plans / "second.plan.md").write_text("---\ndisposition: active\n---\n# Second\n", encoding="utf-8")
    master_path = plans / "_master.plan.md"
    master_path.write_text(
        "---\n---\n\n# Master\n\n## active\n\n"
        "- [First](first.plan.md)\n"
        "- [Second](second.plan.md)\n",
        encoding="utf-8",
    )
    doc = m.parse_master_plan(master_path, tmp_project_dir)
    assert doc["active_children"] == [
        ".cursor/plans/first.plan.md",
        ".cursor/plans/second.plan.md",
    ]


def test_compute_plan_ranks_follows_master_active_order(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    for slug, title in (("plan_a.plan.md", "Plan A"), ("plan_b.plan.md", "Plan B")):
        (plans / slug).write_text(
            f"---\ndisposition: active\npriority: P1\n---\n# {title}\n- [ ] work item here\n",
            encoding="utf-8",
        )
    master_path = plans / "_master.plan.md"
    master_path.write_text(
        "---\n---\n\n# Master\n\n## active\n\n"
        "- [A](plan_a.plan.md)\n"
        "- [B](plan_b.plan.md)\n",
        encoding="utf-8",
    )
    items: list[m.PlanItem] = []
    cards: dict[str, m.PlanCard] = {}
    for slug in ("plan_a.plan.md", "plan_b.plan.md"):
        path = plans / slug
        items.extend(m.collect_plan_items(path, tmp_project_dir))
        card = m.build_plan_card(path, tmp_project_dir, items, default_owner="@test")
        cards[card.source] = card
    master_doc = m.parse_master_plan(master_path, tmp_project_dir)
    ranks, rank_source = m.compute_plan_ranks(
        master_doc, cards, repo_root=tmp_project_dir, master_path=master_path
    )
    assert rank_source == "master_body"
    assert ranks[".cursor/plans/plan_a.plan.md"] == 1
    assert ranks[".cursor/plans/plan_b.plan.md"] == 2


def test_execution_order_frontmatter_overrides_body(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    for slug in ("plan_a.plan.md", "plan_b.plan.md"):
        (plans / slug).write_text(
            "---\ndisposition: active\n---\n# X\n- [ ] work item here\n",
            encoding="utf-8",
        )
    master_path = plans / "_master.plan.md"
    master_path.write_text(
        "---\n"
        "execution_order:\n"
        "  - plan_b.plan.md\n"
        "  - plan_a.plan.md\n"
        "---\n\n# Master\n\n## active\n\n"
        "- [A](plan_a.plan.md)\n"
        "- [B](plan_b.plan.md)\n",
        encoding="utf-8",
    )
    items: list[m.PlanItem] = []
    cards: dict[str, m.PlanCard] = {}
    for slug in ("plan_a.plan.md", "plan_b.plan.md"):
        path = plans / slug
        items.extend(m.collect_plan_items(path, tmp_project_dir))
        card = m.build_plan_card(path, tmp_project_dir, items, default_owner="@test")
        cards[card.source] = card
    master_doc = m.parse_master_plan(master_path, tmp_project_dir)
    ranks, rank_source = m.compute_plan_ranks(
        master_doc, cards, repo_root=tmp_project_dir, master_path=master_path
    )
    assert rank_source == "master_frontmatter"
    assert ranks[".cursor/plans/plan_b.plan.md"] == 1
    assert ranks[".cursor/plans/plan_a.plan.md"] == 2


def test_task_board_and_mirror_implementation_sequence(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    (plans / "early.plan.md").write_text(
        "---\ndisposition: active\npriority: P0\n---\n# Early\n- [ ] ship early milestone\n",
        encoding="utf-8",
    )
    (plans / "late.plan.md").write_text(
        "---\ndisposition: active\npriority: P0\n---\n# Late\n- [ ] ship late milestone\n",
        encoding="utf-8",
    )
    master_path = plans / "_master.plan.md"
    master_path.write_text(
        "---\n---\n\n# Master\n\n## active\n\n"
        "- [Early](early.plan.md)\n"
        "- [Late](late.plan.md)\n",
        encoding="utf-8",
    )
    items: list[m.PlanItem] = []
    cards: dict[str, m.PlanCard] = {}
    for slug in ("early.plan.md", "late.plan.md"):
        path = plans / slug
        items.extend(m.collect_plan_items(path, tmp_project_dir))
        card = m.build_plan_card(path, tmp_project_dir, items, default_owner="@test")
        cards[card.source] = card
    master_doc = m.parse_master_plan(master_path, tmp_project_dir)
    ranks, rank_source = m.compute_plan_ranks(
        master_doc, cards, repo_root=tmp_project_dir, master_path=master_path
    )
    actions = m.detect_actions(list(cards.values()))
    board = m.render_task_board_markdown(
        "2026-06-04", items, cards_by_source=cards, plan_ranks=ranks
    )
    assert "| Seq | Plan |" in board
    assert "| 1 |" in board and "| 2 |" in board
    assert board.index("early.plan.md") < board.index("late.plan.md")
    assert board.index("| 1 |") < board.index("| 2 |")
    mirror = m.render_master_mirror(
        list(cards.values()),
        master_doc,
        repo_root=tmp_project_dir,
        plan_ranks=ranks,
        rank_source=rank_source,
        actions=actions,
    )
    assert "## Implementation sequence (build queue)" in mirror
    seq_early = mirror.find("| 1 ")
    seq_late = mirror.find("| 2 ")
    assert seq_early != -1 and seq_late != -1 and seq_early < seq_late


def test_compute_plan_ranks_heuristic_without_master(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    (plans / "z_backlog.plan.md").write_text(
        "---\ndisposition: backlogged\npriority: P2\n---\n# Z\n",
        encoding="utf-8",
    )
    (plans / "a_active.plan.md").write_text(
        "---\ndisposition: active\npriority: P1\n---\n# A\n- [ ] work item here\n",
        encoding="utf-8",
    )
    items: list[m.PlanItem] = []
    cards: dict[str, m.PlanCard] = {}
    for slug in ("z_backlog.plan.md", "a_active.plan.md"):
        path = plans / slug
        items.extend(m.collect_plan_items(path, tmp_project_dir))
        card = m.build_plan_card(path, tmp_project_dir, items, default_owner="@test")
        cards[card.source] = card
    ranks, rank_source = m.compute_plan_ranks(None, cards, repo_root=tmp_project_dir)
    assert rank_source == "heuristic"
    assert ranks[".cursor/plans/a_active.plan.md"] == 1
    assert ranks[".cursor/plans/z_backlog.plan.md"] == 2


def test_detect_plan_overlaps_shared_path(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    shared = "braindrain/server.py"
    (plans / "alpha.plan.md").write_text(
        f"---\ndisposition: active\n---\n# Alpha\n- [ ] update `{shared}` handler\n",
        encoding="utf-8",
    )
    (plans / "beta.plan.md").write_text(
        f"---\ndisposition: active\n---\n# Beta\n- [ ] refactor `{shared}` startup\n",
        encoding="utf-8",
    )
    items: list[m.PlanItem] = []
    cards: dict[str, m.PlanCard] = {}
    for slug in ("alpha.plan.md", "beta.plan.md"):
        path = plans / slug
        plan_items = m.collect_plan_items(path, tmp_project_dir)
        items.extend(plan_items)
        card = m.build_plan_card(path, tmp_project_dir, plan_items, default_owner="@test")
        cards[card.source] = card
    edges, clusters = m.detect_plan_overlaps(
        cards, items, repo_root=tmp_project_dir
    )
    path_edges = [edge for edge in edges if edge.signal == "path"]
    assert path_edges
    assert path_edges[0].severity == "high"
    assert len(clusters) == 1
    assert len(clusters[0]) == 2


def test_apply_overlap_relations_appends_relates_to(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    shared = "braindrain/server.py"
    (plans / "alpha.plan.md").write_text(
        f"---\ndisposition: active\n---\n# Alpha\n- [ ] update `{shared}` handler\n",
        encoding="utf-8",
    )
    (plans / "beta.plan.md").write_text(
        f"---\ndisposition: active\n---\n# Beta\n- [ ] refactor `{shared}` startup\n",
        encoding="utf-8",
    )
    items: list[m.PlanItem] = []
    cards: dict[str, m.PlanCard] = {}
    for slug in ("alpha.plan.md", "beta.plan.md"):
        path = plans / slug
        plan_items = m.collect_plan_items(path, tmp_project_dir)
        items.extend(plan_items)
        card = m.build_plan_card(path, tmp_project_dir, plan_items, default_owner="@test")
        cards[card.source] = card
    edges, _clusters = m.detect_plan_overlaps(
        cards, items, repo_root=tmp_project_dir
    )
    updated = m.apply_overlap_relations(tmp_project_dir, cards, edges)
    assert len(updated) == 2
    alpha_text = (plans / "alpha.plan.md").read_text(encoding="utf-8")
    beta_text = (plans / "beta.plan.md").read_text(encoding="utf-8")
    assert "relates_to:" in alpha_text
    assert "beta.plan.md" in alpha_text
    assert "relates_to:" in beta_text
    assert "alpha.plan.md" in beta_text


def test_load_goal_context_and_alignment_scores(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    cursor_dir = tmp_project_dir / ".cursor"
    plans = cursor_dir / "plans"
    plans.mkdir(parents=True)
    (cursor_dir / "PRD.md").write_text(
        "# PRD\n\n## Goals\n\n- Ship memory layers tunable via hub_config\n",
        encoding="utf-8",
    )
    (plans / "aligned.plan.md").write_text(
        "---\ndisposition: active\n---\n"
        "# Memory config wiring\n"
        "- [ ] tune memory layers via hub_config without behavior change\n",
        encoding="utf-8",
    )
    (plans / "unrelated.plan.md").write_text(
        "---\ndisposition: active\n---\n"
        "# LivingDash theme polish\n"
        "- [ ] adjust dashboard color tokens only\n",
        encoding="utf-8",
    )
    items: list[m.PlanItem] = []
    cards: dict[str, m.PlanCard] = {}
    for slug in ("aligned.plan.md", "unrelated.plan.md"):
        path = plans / slug
        plan_items = m.collect_plan_items(path, tmp_project_dir)
        items.extend(plan_items)
        card = m.build_plan_card(path, tmp_project_dir, plan_items, default_owner="@test")
        cards[card.source] = card
    goal_context = m.load_goal_context(tmp_project_dir, master_doc=None)
    assert ".cursor/PRD.md" in goal_context["sources"]
    alignments = m.compute_goal_alignments(cards, goal_context)
    by_source = {row.source: row for row in alignments}
    aligned = by_source[".cursor/plans/aligned.plan.md"]
    unrelated = by_source[".cursor/plans/unrelated.plan.md"]
    assert aligned.alignment_score > unrelated.alignment_score
    assert aligned.alignment_score >= 40
    mirror = m.render_master_mirror(
        list(cards.values()),
        None,
        repo_root=tmp_project_dir,
        goal_alignments=alignments,
        goal_context=goal_context,
    )
    assert "## Goal alignment" in mirror
    mem = m.memory_context(tmp_project_dir)
    assert mem.get("goal_count", 0) >= 1
    assert ".cursor/PRD.md" in mem["sources"]


def test_parse_frontmatter_phase_branches() -> None:
    m = _load_audit_module()
    text = (
        "---\n"
        "branch: feat-phase2\n"
        "branches:\n"
        "  - feat-phase0\n"
        "  - feat-phase1\n"
        "phase_branches:\n"
        "  - branch: feat-phase0\n"
        "    phase: \"0\"\n"
        "    pr: https://github.com/org/repo/pull/1\n"
        "  - branch: feat-phase1\n"
        "    phase: \"1\"\n"
        "    pr: https://github.com/org/repo/pull/2\n"
        "    pr_state: OPEN\n"
        "---\n\n"
        "# Plan\n"
    )
    rows = m.parse_frontmatter_phase_branches(text)
    assert len(rows) == 2
    assert rows[0]["branch"] == "feat-phase0"
    assert rows[0]["pr"].endswith("/pull/1")
    assert rows[1]["pr_state"] == "OPEN"


def test_sync_plan_phase_branches_writes_registry(
    tmp_project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    plan_path = plans / "overseer.plan.md"
    plan_path.write_text(
        "---\n"
        "disposition: active\n"
        "branch: overseer-phase2-3\n"
        "branches:\n"
        "  - overseer-phase0\n"
        "  - overseer-phase1\n"
        "  - overseer-phase2-3\n"
        "---\n\n"
        "# Overseer\n"
        "- [ ] work item for phase branch registry\n",
        encoding="utf-8",
    )

    def fake_fetch(
        repo_root: Path,
        branch: str,
        *,
        state: str = "open",
    ) -> dict[str, str] | None:
        if branch == "overseer-phase1":
            return {
                "number": "109",
                "url": "https://github.com/recwebtek/braindrain/pull/109",
                "state": "OPEN",
                "title": "phase1",
                "body": "",
            }
        if branch == "overseer-phase2-3":
            return {
                "number": "110",
                "url": "https://github.com/recwebtek/braindrain/pull/110",
                "state": "OPEN",
                "title": "phase23",
                "body": "",
            }
        return None

    monkeypatch.setattr(m, "_fetch_pr_details", fake_fetch)
    items = m.collect_plan_items(plan_path, tmp_project_dir)
    card = m.build_plan_card(plan_path, tmp_project_dir, items, default_owner="@test")
    cards = {card.source: card}
    updated = m.sync_plan_phase_branches(tmp_project_dir, cards)
    assert updated == [card.source]
    text = plan_path.read_text(encoding="utf-8")
    assert "phase_branches:" in text
    assert "pull/109" in text
    assert "pull/110" in text
    assert "overseer-phase0" in text
    assert "inherited" in text.lower() or "pull/109" in text
    assert "pr: https://" not in text.split("phase_branches:")[0]
    assert cards[card.source].pr == "#109, #110"


def test_format_plan_pr_summary_aggregates() -> None:
    m = _load_audit_module()
    card = m.PlanCard(
        slug="x",
        title="X",
        source=".cursor/plans/x.plan.md",
        ide="cursor",
        owner="@test",
        dri="@test",
        disposition="active",
        priority="P2",
        parent="_master",
        delegated_to=[],
        is_master=False,
        phase_branches=[
            {"branch": "a", "pr": "https://github.com/o/r/pull/109"},
            {"branch": "b", "pr": "https://github.com/o/r/pull/110"},
        ],
    )
    assert m.format_plan_pr_summary(card) == "#109, #110"


def test_load_planning_auditor_config_defaults(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    cfg = m.load_planning_auditor_config(tmp_project_dir)
    assert cfg["overlap_jaccard_threshold"] == m.DEFAULT_OVERLAP_JACCARD_THRESHOLD
    assert cfg["apply_overlap_relations"] is False
    assert cfg["apply_goal_tags"] is False
    assert cfg["goal_alignment_min_score"] == m.DEFAULT_GOAL_ALIGNMENT_MIN_SCORE


def test_load_planning_auditor_config_from_hub_yaml(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    config_dir = tmp_project_dir / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "hub_config.yaml").write_text(
        "planning_auditor:\n"
        "  overlap_jaccard_threshold: 0.42\n"
        "  apply_overlap_relations: true\n"
        "  apply_goal_tags: true\n"
        "  goal_alignment_min_score: 25\n",
        encoding="utf-8",
    )
    cfg = m.load_planning_auditor_config(tmp_project_dir)
    assert cfg["overlap_jaccard_threshold"] == 0.42
    assert cfg["apply_overlap_relations"] is True
    assert cfg["apply_goal_tags"] is True
    assert cfg["goal_alignment_min_score"] == 25


def test_resolve_planning_auditor_cli_overrides_yaml(tmp_project_dir: Path) -> None:
    import argparse

    m = _load_audit_module()
    config_dir = tmp_project_dir / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "hub_config.yaml").write_text(
        "planning_auditor:\n  apply_overlap_relations: true\n",
        encoding="utf-8",
    )
    args = argparse.Namespace(
        repo_root=str(tmp_project_dir),
        apply_overlap_relations=False,
        apply_goal_tags=False,
        overlap_jaccard_threshold=None,
        goal_alignment_min_score=None,
    )
    runtime = m.resolve_planning_auditor_runtime(args, tmp_project_dir)
    assert runtime["apply_overlap_relations"] is True
    args.overlap_jaccard_threshold = 0.33
    args.goal_alignment_min_score = 55
    runtime = m.resolve_planning_auditor_runtime(args, tmp_project_dir)
    assert runtime["overlap_jaccard_threshold"] == 0.33
    assert runtime["goal_alignment_min_score"] == 55


def test_meta_plan_excluded_from_build_queue(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    (plans / "meta.plan.md").write_text(
        "---\n"
        "disposition: meta\n"
        "children_spec:\n"
        "  - id: child-a\n"
        "    file: child-a.plan.md\n"
        "    branch: feature/child-a\n"
        "---\n\n"
        "# Meta umbrella\n",
        encoding="utf-8",
    )
    (plans / "child-a.plan.md").write_text(
        "---\ndisposition: active\nbranch: feature/child-a\n---\n# Child\n- [ ] work\n",
        encoding="utf-8",
    )
    items: list[m.PlanItem] = []
    cards: dict[str, m.PlanCard] = {}
    for slug in ("meta.plan.md", "child-a.plan.md"):
        path = plans / slug
        plan_items = m.collect_plan_items(path, tmp_project_dir)
        items.extend(plan_items)
        card = m.build_plan_card(path, tmp_project_dir, plan_items, default_owner="@test")
        cards[card.source] = card
    ranks, _rank_source = m.compute_plan_ranks(None, cards, repo_root=tmp_project_dir)
    assert ".cursor/plans/meta.plan.md" not in ranks
    assert ".cursor/plans/child-a.plan.md" in ranks


def test_meta_plan_split_verb_when_children_missing(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    (plans / "meta.plan.md").write_text(
        "---\n"
        "disposition: meta\n"
        "children_spec:\n"
        "  - id: child-a\n"
        "    file: missing-child.plan.md\n"
        "    branch: feature/child-a\n"
        "todos:\n"
        "  - id: split-child-a\n"
        '    content: "Child plan missing-child.plan.md exists"\n'
        "    status: pending\n"
        "---\n\n"
        "# Meta umbrella\n",
        encoding="utf-8",
    )
    path = plans / "meta.plan.md"
    items = m.collect_plan_items(path, tmp_project_dir)
    card = m.build_plan_card(path, tmp_project_dir, items, default_owner="@test")
    actions = m.detect_actions([card], repo_root=tmp_project_dir)
    assert actions
    assert actions[0].verb == "SPLIT"
    assert "metaplan-closeout" in actions[0].hint.lower()


def test_roadmap_version_alignment_warns_on_drift(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    (tmp_project_dir / "pyproject.toml").write_text(
        'version = "9.9.9"\n',
        encoding="utf-8",
    )
    (tmp_project_dir / "ROADMAP.md").write_text(
        "# Roadmap\n\nLast aligned with **v1.0.3** (2026-01-01).\n",
        encoding="utf-8",
    )
    warnings = m.check_roadmap_version_alignment(tmp_project_dir)
    assert warnings
    assert "Version drift" in warnings[0]
    assert "9.9.9" in warnings[0]


def test_roadmap_version_alignment_passes_when_matched(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    (tmp_project_dir / "pyproject.toml").write_text(
        '[project]\nversion = "1.0.3"\n',
        encoding="utf-8",
    )
    (tmp_project_dir / "ROADMAP.md").write_text(
        "# Roadmap\n\nLast aligned with **v1.0.3** (2026-04-10).\n",
        encoding="utf-8",
    )
    assert m.check_roadmap_version_alignment(tmp_project_dir) == []
