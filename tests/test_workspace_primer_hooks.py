"""Tests for Cursor hook template deployment from ``config/templates/cursor``."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from braindrain.workspace_primer import (
    CURSOR_COMMANDS_TEMPLATES_DIR,
    CURSOR_HOOK_TEMPLATES_DIR,
    CURSOR_SKILL_TEMPLATES_DIR,
    MAX_ROLLBACK_SNAPSHOTS,
    _resolve_bundle_manifest,
    compact_prime_result_for_mcp,
    create_prime_snapshot,
    deploy_cursor_commands,
    deploy_cursor_hook_templates,
    deploy_cursor_skill_templates,
    deploy_operational_scripts,
    deploy_subagent_templates,
    prime,
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


def test_braindrain_hub_pr_skill_template_exists() -> None:
    skill = CURSOR_SKILL_TEMPLATES_DIR / "braindrain-hub-pr" / "SKILL.md"
    assert skill.is_file()
    assert "BRAIN_MCP_HUB" in skill.read_text(encoding="utf-8")


def test_deploy_cursor_skill_templates_writes_skill_dir(tmp_project_dir: Path) -> None:
    out = deploy_cursor_skill_templates(
        tmp_project_dir,
        ["braindrain-hub-pr"],
        sync_templates=False,
        dry_run=False,
    )
    dst = tmp_project_dir / ".cursor" / "skills" / "braindrain-hub-pr" / "SKILL.md"
    assert dst.is_file()
    assert out["skills/braindrain-hub-pr/SKILL.md"]["action"] == "created"


def test_cursor_hook_templates_exist_in_repo() -> None:
    assert (CURSOR_HOOK_TEMPLATES_DIR / "hooks.json").is_file()
    hooks = CURSOR_HOOK_TEMPLATES_DIR / "hooks"
    assert (hooks / "on-stop-daily-plan-audit.sh").is_file()
    assert (hooks / "on-stop-gitops.sh").is_file()
    assert (hooks / "on-stop-observe.sh").is_file()


def test_brainlog_command_template_exists() -> None:
    cmd = CURSOR_COMMANDS_TEMPLATES_DIR / "brainlog.md"
    assert cmd.is_file()
    text = cmd.read_text(encoding="utf-8")
    assert "touch_session" in text
    assert "end_session=true" in text
    assert "evaluate_memory_candidate" in text
    assert "run_dream" in text


def test_deploy_cursor_commands_writes_brainlog(tmp_project_dir: Path) -> None:
    out = deploy_cursor_commands(tmp_project_dir, sync_templates=False, dry_run=False)
    dst = tmp_project_dir / ".cursor" / "commands" / "brainlog.md"
    assert dst.is_file()
    assert out["commands/brainlog.md"]["action"] == "created"
    assert "brainlog" in dst.read_text(encoding="utf-8").lower()


def test_deploy_cursor_commands_skips_existing_without_sync(tmp_project_dir: Path) -> None:
    deploy_cursor_commands(tmp_project_dir, sync_templates=False, dry_run=False)
    out2 = deploy_cursor_commands(tmp_project_dir, sync_templates=False, dry_run=False)
    assert out2["commands/brainlog.md"]["action"] == "skipped_existing"


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


def test_deploy_subagent_templates_writes_codex_agents(tmp_project_dir: Path) -> None:
    out = deploy_subagent_templates(
        tmp_project_dir,
        sync_subagents=False,
        to_cursor=False,
        to_codex=True,
    )
    assert out
    codex_agents = tmp_project_dir / ".codex" / "agents"
    assert codex_agents.is_dir()
    assert (codex_agents / "coordinator.md").is_file()
    assert (codex_agents / "daily-plan-auditor.md").is_file()


def test_deploy_subagent_templates_preserves_customized(tmp_project_dir: Path) -> None:
    agents_dir = tmp_project_dir / ".cursor" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    custom_path = agents_dir / "coordinator.md"
    custom_text = "# My Custom Coordinator\n\nkeep me\n"
    custom_path.write_text(custom_text, encoding="utf-8")

    out = deploy_subagent_templates(
        tmp_project_dir,
        sync_subagents=True,
        to_cursor=True,
        to_codex=False,
    )
    assert out["coordinator.md"]["classification"] == "customized"
    assert out["coordinator.md"]["action"] == "skipped_existing"
    assert custom_path.read_text(encoding="utf-8") == custom_text


def test_deploy_subagent_templates_marks_default_current(tmp_project_dir: Path) -> None:
    out_first = deploy_subagent_templates(
        tmp_project_dir,
        sync_subagents=False,
        to_cursor=True,
        to_codex=False,
    )
    assert out_first["coordinator.md"]["action"] in {"created", "created_from_empty"}

    out_second = deploy_subagent_templates(
        tmp_project_dir,
        sync_subagents=True,
        to_cursor=True,
        to_codex=False,
    )
    assert out_second["coordinator.md"]["classification"] == "default_current"


def test_create_prime_snapshot_archives_cursor_and_manifest(tmp_project_dir: Path) -> None:
    (tmp_project_dir / ".cursor" / "agents").mkdir(parents=True, exist_ok=True)
    (tmp_project_dir / ".cursor" / "agents" / "x.md").write_text("x", encoding="utf-8")
    snapshot = create_prime_snapshot(
        tmp_project_dir,
        apply_agents=["cursor"],
        all_agents=False,
        dry_run=False,
    )
    assert snapshot["ok"] is True
    assert snapshot["archive_count"] >= 1
    manifest_path = Path(str(snapshot["manifest_path"]))
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert ".cursor" in manifest["ide_dirs"]
    archive_paths = [Path(a["path"]) for a in manifest["archives"]]
    assert any(p.name == "cursor.tar.gz" for p in archive_paths)
    tar_path = next(p for p in archive_paths if p.name == "cursor.tar.gz")
    with tarfile.open(tar_path, "r:gz") as tf:
        names = tf.getnames()
    assert any(name.endswith("agents/x.md") for name in names)


def test_create_prime_snapshot_prunes_to_max(tmp_project_dir: Path) -> None:
    rollback_root = tmp_project_dir / ".braindrain" / "rollback"
    for idx in range(MAX_ROLLBACK_SNAPSHOTS + 2):
        d = rollback_root / f"20260101-0000{idx:02d}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text("{}", encoding="utf-8")
    (tmp_project_dir / ".cursor").mkdir(parents=True, exist_ok=True)
    create_prime_snapshot(
        tmp_project_dir,
        apply_agents=["cursor"],
        all_agents=False,
        dry_run=False,
    )
    dirs = [p for p in rollback_root.iterdir() if p.is_dir()]
    assert len(dirs) == MAX_ROLLBACK_SNAPSHOTS


def test_prime_result_exposes_rollback_manifest(tmp_project_dir: Path) -> None:
    (tmp_project_dir / ".cursor").mkdir(parents=True, exist_ok=True)
    with (
        patch(
            "braindrain.workspace_primer.run_ruler_apply",
            return_value={"ok": True, "stdout": "", "stderr": "", "command": "x", "returncode": 0},
        ),
        patch(
            "braindrain.workspace_primer.initialize_project_memory",
            return_value={"ok": True, "dry_run": False, "artifacts": {}, "migration": {}},
        ),
        patch(
            "braindrain.workspace_primer.seed_if_enabled",
            return_value={"ok": True, "enabled": False},
        ),
        patch(
            "braindrain.workspace_primer.verify_prime_install",
            return_value={"ok": True, "checks": {"dry_run": False}},
        ),
    ):
        result = prime(path=str(tmp_project_dir), agents=["cursor"], local_only=True)
    assert result["rollback_manifest_path"]
    assert isinstance(result["rollback_archives"], list)


def test_prime_restores_cursor_agents_if_ruler_removes_directory(tmp_project_dir: Path) -> None:
    agents_dir = tmp_project_dir / ".cursor" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    custom = agents_dir / "custom.md"
    custom.write_text("# keep me\n", encoding="utf-8")

    def _ruler_side_effect(*args, **kwargs):
        shutil.rmtree(agents_dir, ignore_errors=True)
        return {"ok": True, "stdout": "", "stderr": "", "command": "x", "returncode": 0}

    with (
        patch("braindrain.workspace_primer.run_ruler_apply", side_effect=_ruler_side_effect),
        patch(
            "braindrain.workspace_primer.initialize_project_memory",
            return_value={"ok": True, "dry_run": False, "artifacts": {}, "migration": {}},
        ),
        patch(
            "braindrain.workspace_primer.seed_if_enabled",
            return_value={"ok": True, "enabled": False},
        ),
        patch(
            "braindrain.workspace_primer.verify_prime_install",
            return_value={"ok": True, "checks": {"dry_run": False}},
        ),
    ):
        result = prime(path=str(tmp_project_dir), agents=["cursor"], local_only=True)

    assert result["ok"] is True
    guard = result.get("cursor_agents_guard") or {}
    assert guard.get("attempted") is True
    assert guard.get("restored") is True
    assert custom.is_file()


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
    assert "braindrain_hub_root" in content
    assert "_resolve_audit_script" in content


def test_deploy_operational_scripts_and_skills(tmp_project_dir: Path) -> None:
    bundle = _resolve_bundle_manifest("cursor-orchestration")
    scripts = deploy_operational_scripts(
        tmp_project_dir, bundle, sync_templates=False, dry_run=False
    )
    assert (tmp_project_dir / "scripts" / "daily_plan_audit.py").is_file()
    assert (tmp_project_dir / "scripts" / "plan_branch_utils.py").is_file()
    assert (tmp_project_dir / "scripts" / "plan_build_guard.py").is_file()
    assert any(v.get("action") == "created" for v in scripts.values())
    audit_text = (tmp_project_dir / "scripts" / "daily_plan_audit.py").read_text(encoding="utf-8")
    assert "braindrain-script: daily_plan_audit.py sha256=" in audit_text


def test_deploy_operational_scripts_upgrades_hub_revision(tmp_project_dir: Path) -> None:
    from braindrain.workspace_primer import (
        _SCRIPT_MARKER_PREFIX,
        _stamp_script_marker,
        deploy_operational_scripts,
    )

    bundle = _resolve_bundle_manifest("cursor-orchestration")
    scripts_dir = tmp_project_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    rel = "plan_branch_utils.py"
    dst = scripts_dir / rel
    stale_body = "# stale consumer copy\n"
    stamped_stale = _stamp_script_marker(stale_body, rel)
    dst.write_text(stamped_stale, encoding="utf-8")

    result = deploy_operational_scripts(
        tmp_project_dir, bundle, sync_templates=False, dry_run=False
    )
    key = f"scripts/{rel}"
    assert result[key]["action"] == "updated"
    assert result[key].get("classification") == "hub_revision"
    deployed = dst.read_text(encoding="utf-8")
    assert _SCRIPT_MARKER_PREFIX in deployed
    assert "stale consumer copy" not in deployed
    skill_ids = [str(s) for s in bundle.get("skills", []) if str(s).strip()]
    skills = deploy_cursor_skill_templates(
        tmp_project_dir, skill_ids, sync_templates=False, dry_run=False
    )
    assert (tmp_project_dir / ".cursor" / "skills" / "gitops" / "SKILL.md").is_file()
    assert skills


def test_observe_hook_template_suppresses_known_stdout_sources() -> None:
    """Guard against regressions that break Cursor JSON hook parsing."""
    hook_path = CURSOR_HOOK_TEMPLATES_DIR / "hooks" / "on-stop-observe.sh"
    content = hook_path.read_text(encoding="utf-8")
    assert "PRAGMA journal_mode=WAL;" in content
    assert 'sqlite3 "${DB_PATH}" >/dev/null 2>/dev/null <<SQL' in content
    assert "[observe-hook] Recorded stop event" not in content


def test_observe_hook_runtime_stdout_is_empty(tmp_project_dir: Path) -> None:
    hook_path = _REPO_ROOT / ".cursor" / "hooks" / "on-stop-observe.sh"
    if not hook_path.is_file():
        pytest.skip("workspace observe hook not present")
    for dep in ("sqlite3", "jq", "git"):
        if shutil.which(dep) is None:
            pytest.skip(f"{dep} is required for observe hook runtime test")

    fake_home = tmp_project_dir / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "session_id": "hook-test-session",
            "hook_event_name": "stop",
            "workspace_roots": [str(_REPO_ROOT)],
        }
    )
    result = subprocess.run(
        [str(hook_path)],
        input=payload,
        text=True,
        capture_output=True,
        cwd=_REPO_ROOT,
        env={**os.environ, **{"HOME": str(fake_home)}},
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""
    assert result.stderr.strip() == ""


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
        "# Plan\n- [ ] owner: alice first task\n- [ ] blocked by policy with no marker\n",
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

    assert 'schema_version: "1.2"' in report
    assert "## Status Matrix (5-State)" in report
    assert "## Overlap Analysis" in report
    assert "## Gap Analysis" in report
    assert "## Memory Context Used" in report
    assert "## Recommended Next Actions" in report
