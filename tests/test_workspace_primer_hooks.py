"""Tests for Cursor hook template deployment from ``config/templates/cursor``."""

from __future__ import annotations

import importlib.util
import json
import shutil
import stat
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from braindrain.workspace_primer import (
    CURSOR_HOOK_TEMPLATES_DIR,
    compact_prime_result_for_mcp,
    deploy_cursor_hook_templates,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_AUDIT_SCRIPT_PATH = _REPO_ROOT / "scripts" / "daily_plan_audit.py"


@pytest.fixture
def tmp_project_dir() -> Path:
    """Writable tree under the repo (system temp may be blocked in sandboxes)."""
    d = _REPO_ROOT / ".pytest_tmp" / f"ws-{uuid.uuid4().hex[:12]}"
    d.mkdir(parents=True, exist_ok=True)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("daily_plan_audit", _AUDIT_SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_cursor_hook_templates_exist_in_repo() -> None:
    assert (CURSOR_HOOK_TEMPLATES_DIR / "hooks.json").is_file()
    hooks = CURSOR_HOOK_TEMPLATES_DIR / "hooks"
    assert (hooks / "on-stop-daily-plan-audit.sh").is_file()
    assert (hooks / "on-stop-gitops.sh").is_file()
    assert (hooks / "on-stop-observe.sh").is_file()


def test_deploy_cursor_hook_templates_writes_expected_paths(tmp_project_dir: Path) -> None:
    src_json = (CURSOR_HOOK_TEMPLATES_DIR / "hooks.json").read_text(encoding="utf-8")
    out = deploy_cursor_hook_templates(tmp_project_dir, sync_templates=False, dry_run=False)

    hj = tmp_project_dir / ".cursor" / "hooks.json"
    assert hj.is_file()
    assert hj.read_text(encoding="utf-8") == src_json
    assert json.loads(hj.read_text(encoding="utf-8"))["version"] == 1

    d = tmp_project_dir / ".cursor" / "hooks" / "on-stop-daily-plan-audit.sh"
    g = tmp_project_dir / ".cursor" / "hooks" / "on-stop-gitops.sh"
    o = tmp_project_dir / ".cursor" / "hooks" / "on-stop-observe.sh"
    assert d.is_file() and g.is_file() and o.is_file()
    assert d.stat().st_mode & stat.S_IXUSR
    assert g.stat().st_mode & stat.S_IXUSR
    assert o.stat().st_mode & stat.S_IXUSR

    assert "hooks.json" in out
    assert out["hooks.json"]["action"] == "created"


def test_deploy_cursor_hook_templates_skips_existing_without_sync(tmp_project_dir: Path) -> None:
    deploy_cursor_hook_templates(tmp_project_dir, sync_templates=False, dry_run=False)
    out2 = deploy_cursor_hook_templates(tmp_project_dir, sync_templates=False, dry_run=False)
    assert all(v.get("action") == "skipped_existing" for v in out2.values())


def test_compact_prime_result_includes_cursor_hooks_summary() -> None:
    prime_like = {
        "ok": True,
        "cursor_hooks": {
            "source": str(CURSOR_HOOK_TEMPLATES_DIR),
            "skipped": False,
            "deployed": {
                "hooks.json": {"action": "created", "backup": ""},
                "hooks/on-stop-daily-plan-audit.sh": {"action": "created", "backup": ""},
                "hooks/on-stop-gitops.sh": {"action": "created", "backup": ""},
            },
            "new_files": 3,
            "updated_files": 0,
            "skipped_existing": 0,
        },
        "templates": {},
        "ruler": {},
        "memory_init": {},
    }
    compact = compact_prime_result_for_mcp(prime_like)
    assert compact.get("_mcp_response_compact") is True
    ch = compact.get("cursor_hooks")
    assert isinstance(ch, dict)
    assert ch.get("deployed_summary")
    assert any(x["file"] == "hooks.json" for x in ch["deployed_summary"])


def test_daily_plan_hook_contains_once_per_day_gate() -> None:
    hook_path = CURSOR_HOOK_TEMPLATES_DIR / "hooks" / "on-stop-daily-plan-audit.sh"
    content = hook_path.read_text(encoding="utf-8")
    assert "daily-plan-audit.json" in content
    assert "LAST_RUN_DATE" in content
    assert 'if [ "${LAST_RUN_DATE}" = "${TODAY}" ]; then' in content


def test_daily_plan_audit_prioritizes_cursor_plan_files(tmp_project_dir: Path) -> None:
    module = _load_audit_module()
    (tmp_project_dir / ".cursor" / "plans").mkdir(parents=True, exist_ok=True)
    (tmp_project_dir / ".devdocs").mkdir(parents=True, exist_ok=True)
    (tmp_project_dir / ".cursor" / "plans" / "x.plan.md").write_text(
        "# Plan\n- [ ] Outstanding item\n", encoding="utf-8"
    )
    (tmp_project_dir / "ROADMAP.md").write_text("# Roadmap\n- [ ] Next item\n", encoding="utf-8")
    (tmp_project_dir / "README.md").write_text("# Readme\nUnrelated docs\n", encoding="utf-8")
    (tmp_project_dir / ".devdocs" / "legacy.plan.md").write_text(
        "# Legacy Plan\n- [ ] stale task\n", encoding="utf-8"
    )

    primary, secondary = module.discover_sources(tmp_project_dir)
    assert [p.relative_to(tmp_project_dir).as_posix() for p in primary] == [
        ".cursor/plans/x.plan.md"
    ]
    assert "ROADMAP.md" in {p.relative_to(tmp_project_dir).as_posix() for p in secondary}
    assert "README.md" not in {p.relative_to(tmp_project_dir).as_posix() for p in secondary}
    assert ".devdocs/legacy.plan.md" not in {
        p.relative_to(tmp_project_dir).as_posix() for p in secondary
    }


def test_strict_owner_allowlist(tmp_project_dir: Path) -> None:
    _ = tmp_project_dir
    m = _load_audit_module()
    assert m.has_explicit_owner("@bob fix auth")
    assert m.has_explicit_owner("Ship owner: team-alpha")
    assert m.has_explicit_owner("x assignee: jane")
    assert m.has_explicit_owner("DRI: eng for rollout")
    assert not m.has_explicit_owner("the owner should review the blocked dependency")
    assert not m.has_explicit_owner("blocked command classes (policy)")


def test_daily_plan_audit_writes_task_board(tmp_project_dir: Path) -> None:
    m = _load_audit_module()
    (tmp_project_dir / ".cursor" / "plans").mkdir(parents=True, exist_ok=True)
    (tmp_project_dir / ".cursor" / "plans" / "board.plan.md").write_text(
        "# Plan\n"
        "- [ ] owner: alice first task\n"
        "- [ ] blocked by policy with no marker\n",
        encoding="utf-8",
    )
    argv = [
        "daily_plan_audit.py",
        "--repo-root",
        str(tmp_project_dir),
        "--report-date",
        "2026-06-01",
    ]
    with patch.object(sys, "argv", argv):
        assert m.main() == 0
    reports = tmp_project_dir / ".braindrain" / "plan-reports"
    assert (reports / "plan-task-board.md").is_file()
    board = (reports / "plan-task-board.md").read_text(encoding="utf-8")
    assert "# Plan task board" in board
    assert "alice" in board
    assert (reports / "plan-audit-2026-06-01.md").is_file()


def test_daily_plan_audit_report_contract(tmp_project_dir: Path) -> None:
    module = _load_audit_module()
    (tmp_project_dir / ".cursor" / "plans").mkdir(parents=True, exist_ok=True)
    plan_path = tmp_project_dir / ".cursor" / "plans" / "daily.plan.md"
    plan_path.write_text(
        "# Next\n- [ ] Add owner + tests for workflow item\n- [x] Ship core module\n",
        encoding="utf-8",
    )

    primary, secondary = module.discover_sources(tmp_project_dir)
    items = []
    for src in primary + secondary:
        items.extend(module.collect_items(src, tmp_project_dir))

    report = module.build_report(
        report_date="2026-04-26",
        trigger="cursor-stop-daily-gated",
        repo_root=tmp_project_dir,
        primary=primary,
        secondary=secondary,
        items=items,
    )

    assert 'schema_version: "1.1"' in report
    assert "## Status Matrix (5-State)" in report
    assert "## Overlap Analysis" in report
    assert "## Gap Analysis" in report
    assert "## Memory Context Used" in report
    assert "## Recommended Next Actions" in report
