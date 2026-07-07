"""Tests for plan provenance stamping from Cursor hook payloads."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_STAMP_SCRIPT_PATH = _REPO_ROOT / "scripts" / "plan_provenance_stamp.py"
_BRANCH_UTILS_PATH = _REPO_ROOT / "scripts" / "plan_branch_utils.py"


@pytest.fixture
def tmp_project_dir() -> Path:
    d = _REPO_ROOT / ".pytest_tmp" / f"prov-{uuid.uuid4().hex[:12]}"
    d.mkdir(parents=True, exist_ok=True)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def stamp_module():
    spec = importlib.util.spec_from_file_location("plan_provenance_stamp", _STAMP_SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def branch_utils():
    spec = importlib.util.spec_from_file_location("plan_branch_utils", _BRANCH_UTILS_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_normalize_fable_with_low_effort(stamp_module) -> None:
    result = stamp_module.normalize_model_name(
        model="claude-fable-5-thinking-low",
        model_id="claude-fable-5-thinking-low",
        model_params=[{"id": "thinking", "value": "low"}],
    )
    assert result == "fable-5:low"


def test_normalize_auto_model(stamp_module) -> None:
    assert stamp_module.normalize_model_name(model="auto") == "auto"
    assert stamp_module.normalize_model_name(model_id="auto") == "auto"


def test_normalize_model_without_params(stamp_module) -> None:
    result = stamp_module.normalize_model_name(
        model="gpt-5.4-medium",
        model_id="gpt-5.4-medium",
    )
    assert result == "gpt-5.4-medium"


def test_stamp_plan_adds_frontmatter_when_missing(
    stamp_module,
    branch_utils,
    tmp_project_dir: Path,
) -> None:
    plan_path = tmp_project_dir / ".cursor" / "plans" / "alpha.plan.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("# Alpha\n\nBody\n", encoding="utf-8")

    info = {
        "model": "fable-5:low",
        "cursor_mode": "manual",
        "updated_at": "2026-07-03T10:00:00Z",
    }
    assert stamp_module.stamp_plan_frontmatter(plan_path, info) is True

    fm = branch_utils.parse_plan_frontmatter(plan_path)
    assert fm["created_by_model"] == "fable-5:low"
    assert fm["last_modified_by_model"] == "fable-5:low"
    assert fm["cursor_mode"] == "manual"


def test_stamp_plan_preserves_created_fields_on_resstamp(
    stamp_module,
    branch_utils,
    tmp_project_dir: Path,
) -> None:
    plan_path = tmp_project_dir / ".cursor" / "plans" / "beta.plan.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(
        "---\n"
        'created_by_model: "composer-2"\n'
        'created_at: "2026-07-01T08:00:00Z"\n'
        "name: Beta\n"
        "---\n\n# Beta\n",
        encoding="utf-8",
    )

    info = {
        "model": "fable-5:low",
        "cursor_mode": "manual",
        "updated_at": "2026-07-03T10:00:00Z",
    }
    stamp_module.stamp_plan_frontmatter(plan_path, info)

    fm = branch_utils.parse_plan_frontmatter(plan_path)
    assert fm["created_by_model"] == "composer-2"
    assert fm["created_at"] == "2026-07-01T08:00:00Z"
    assert fm["last_modified_by_model"] == "fable-5:low"
    assert fm["last_modified_at"] == "2026-07-03T10:00:00Z"


def test_write_and_load_active_model(stamp_module, tmp_project_dir: Path) -> None:
    now = stamp_module._iso_now()
    info = {
        "model": "fable-5:low",
        "model_id": "claude-fable-5-thinking-low",
        "cursor_mode": "manual",
        "conversation_id": "conv-1",
        "updated_at": now,
    }
    stamp_module.write_active_model(tmp_project_dir, info)
    loaded = stamp_module.load_active_model(
        tmp_project_dir,
        max_age=stamp_module.ACTIVE_MODEL_MAX_AGE,
    )
    assert loaded is not None
    assert loaded["model"] == "fable-5:low"


def test_hook_payload_end_to_end(
    stamp_module,
    branch_utils,
    tmp_project_dir: Path,
) -> None:
    plan_path = tmp_project_dir / ".cursor" / "plans" / "gamma.plan.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("# Gamma\n", encoding="utf-8")

    payload = {
        "model": "claude-fable-5-thinking-low",
        "model_id": "claude-fable-5-thinking-low",
        "model_params": [{"id": "thinking", "value": "low"}],
        "file_path": str(plan_path),
        "conversation_id": "conv-hook-1",
    }
    info = stamp_module.extract_model_from_payload(payload)
    stamp_module.write_active_model(tmp_project_dir, info)
    stamp_module.stamp_plan_frontmatter(plan_path, info)

    fm = branch_utils.parse_plan_frontmatter(plan_path)
    assert fm["created_by_model"] == "fable-5:low"
    assert fm["last_modified_by_model"] == "fable-5:low"
    assert (tmp_project_dir / ".braindrain" / "active-model.json").is_file()


def test_auditor_reads_active_model_fallback(tmp_project_dir: Path) -> None:
    audit_path = _REPO_ROOT / "scripts" / "daily_plan_audit.py"
    spec = importlib.util.spec_from_file_location("daily_plan_audit", audit_path)
    assert spec and spec.loader
    audit = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = audit
    spec.loader.exec_module(audit)

    # Use a fresh timestamp to satisfy ACTIVE_MODEL_MAX_AGE (24h)
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    state_dir = tmp_project_dir / ".braindrain"
    state_dir.mkdir(parents=True)
    (state_dir / "active-model.json").write_text(
        json.dumps(
            {
                "model": "fable-5:low",
                "cursor_mode": "manual",
                "updated_at": now,
            }
        ),
        encoding="utf-8",
    )

    assert audit.resolve_model_name(repo_root=tmp_project_dir) == "fable-5:low"
    assert audit.resolve_cursor_mode(repo_root=tmp_project_dir) == "manual"
