"""Tests for plan_meta_closeout.py."""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CLOSEOUT_SCRIPT = _REPO_ROOT / "scripts" / "plan_meta_closeout.py"


def _load_closeout():
    spec = importlib.util.spec_from_file_location("plan_meta_closeout", _CLOSEOUT_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def tmp_project_dir() -> Path:
    d = _REPO_ROOT / ".pytest_tmp" / f"closeout-{uuid.uuid4().hex[:12]}"
    d.mkdir(parents=True, exist_ok=True)
    try:
        yield d
    finally:
        import shutil

        shutil.rmtree(d, ignore_errors=True)


def test_closeout_dry_run_creates_four_children(tmp_project_dir: Path) -> None:
    m = _load_closeout()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    meta = plans / "sc-multiplan-test.plan.md"
    meta.write_text(
        "---\n"
        "name: StackCraft UX Features\n"
        "disposition: meta\n"
        "children_spec:\n"
        "  - id: sidebar-ux\n"
        "    file: stackcraft-sidebar-ux.plan.md\n"
        '    name: "Sidebar UX"\n'
        "    branch: feature/sidebar-tags-styling\n"
        '    section: "## 2+3. Sidebar"\n'
        "  - id: genai-ldmode\n"
        "    file: stackcraft-genai-ldmode.plan.md\n"
        '    name: "GenAI L/D toggle"\n'
        "    branch: features/genai-ldmode-option-toggle\n"
        '    section: "## 1. Generated-output"\n'
        "  - id: loader\n"
        "    file: stackcraft-loader.plan.md\n"
        '    name: "AI loader"\n'
        "    branch: feature/aigen-loader-revamp\n"
        '    section: "## 4. AI generation"\n'
        "  - id: context-budget\n"
        "    file: stackcraft-context-budget.plan.md\n"
        '    name: "Context budget"\n'
        "    branch: feature/context-budget-breakdown\n"
        '    section: "## 5. Context budget"\n'
        "todos:\n"
        "  - id: split-sidebar-ux\n"
        '    content: "Child stackcraft-sidebar-ux.plan.md exists"\n'
        "    status: pending\n"
        "---\n\n"
        "# StackCraft UX\n\n"
        "## 1. Generated-output\n\n"
        "LD mode details.\n\n"
        "## 2+3. Sidebar\n\n"
        "Sidebar details.\n",
        encoding="utf-8",
    )
    result = m.run_closeout(meta, tmp_project_dir, dry_run=True, run_auditor=False)
    assert result["ok"] is True
    assert result["children_spec_count"] == 4
    assert len(result["created"]) == 4
    assert not (plans / "stackcraft-sidebar-ux.plan.md").exists()


def test_closeout_writes_children_and_master_links(tmp_project_dir: Path) -> None:
    m = _load_closeout()
    plans = tmp_project_dir / ".cursor" / "plans"
    plans.mkdir(parents=True)
    (plans / "_master.plan.md").write_text(
        "---\n---\n\n# Master\n\n## active\n\n",
        encoding="utf-8",
    )
    meta = plans / "meta.plan.md"
    meta.write_text(
        "---\n"
        "disposition: meta\n"
        "children_spec:\n"
        "  - id: a\n"
        "    file: child-a.plan.md\n"
        '    name: "Child A"\n'
        "    branch: feature/a\n"
        "todos:\n"
        "  - id: split-a\n"
        '    content: "Child child-a.plan.md exists"\n'
        "    status: pending\n"
        "---\n\n"
        "# Meta\n",
        encoding="utf-8",
    )
    result = m.run_closeout(meta, tmp_project_dir, dry_run=False, run_auditor=False)
    assert (plans / "child-a.plan.md").is_file()
    assert "status: completed" in meta.read_text(encoding="utf-8")
    master = (plans / "_master.plan.md").read_text(encoding="utf-8")
    assert "child-a.plan.md" in master
    assert result["created"] == ["child-a.plan.md"]
