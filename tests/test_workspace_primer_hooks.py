"""Tests for Cursor hook template deployment from ``config/templates/cursor``."""

from __future__ import annotations

import json
import shutil
import stat
import uuid
from pathlib import Path

import pytest

from braindrain.workspace_primer import (
    CURSOR_HOOK_TEMPLATES_DIR,
    compact_prime_result_for_mcp,
    deploy_cursor_hook_templates,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def tmp_project_dir() -> Path:
    """Writable tree under the repo (system temp may be blocked in sandboxes)."""
    d = _REPO_ROOT / ".pytest_tmp" / f"ws-{uuid.uuid4().hex[:12]}"
    d.mkdir(parents=True, exist_ok=True)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_cursor_hook_templates_exist_in_repo() -> None:
    assert (CURSOR_HOOK_TEMPLATES_DIR / "hooks.json").is_file()
    hooks = CURSOR_HOOK_TEMPLATES_DIR / "hooks"
    assert (hooks / "on-stop-gitops.sh").is_file()
    assert (hooks / "on-stop-observe.sh").is_file()


def test_deploy_cursor_hook_templates_writes_expected_paths(tmp_project_dir: Path) -> None:
    src_json = (CURSOR_HOOK_TEMPLATES_DIR / "hooks.json").read_text(encoding="utf-8")
    out = deploy_cursor_hook_templates(tmp_project_dir, sync_templates=False, dry_run=False)

    hj = tmp_project_dir / ".cursor" / "hooks.json"
    assert hj.is_file()
    assert hj.read_text(encoding="utf-8") == src_json
    assert json.loads(hj.read_text(encoding="utf-8"))["version"] == 1

    g = tmp_project_dir / ".cursor" / "hooks" / "on-stop-gitops.sh"
    o = tmp_project_dir / ".cursor" / "hooks" / "on-stop-observe.sh"
    assert g.is_file() and o.is_file()
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
                "hooks/on-stop-gitops.sh": {"action": "created", "backup": ""},
            },
            "new_files": 2,
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
