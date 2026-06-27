"""Tests for lightweight MCP Apps (`ui://`) dashboards."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from braindrain.mcp_apps.constants import PLAN_BOARD_URI, SIGINT_MAP_URI, TOKEN_DASHBOARD_URI
from braindrain.mcp_apps.data import (
    _group_plan_rows,
    _load_archived_plan_groups,
    _parse_master_plan_queue,
    _parse_plan_board_table,
    build_plan_board_payload,
    build_token_dashboard_payload,
    load_token_checkpoints,
)
from braindrain.mcp_apps.plan_enrich import (
    enrich_plan_groups,
    parse_master_disposition_tables,
)
from braindrain.mcp_apps.html import plan_board_html, sigint_map_html, token_dashboard_html
from braindrain.mcp_apps.sigint_data import build_sigint_map_payload
from braindrain.observer import BrainEvent, ObserverStore
from braindrain.server import mcp
from braindrain.telemetry import telemetry_from_config


def test_token_dashboard_html_is_self_contained():
    html = token_dashboard_html()
    assert TOKEN_DASHBOARD_URI.split("/")[-1] in html or "Token Dashboard" in html
    assert "ui/initialize" in html
    assert "ui/notifications/initialized" in html
    assert "ui/notifications/tool-result" in html
    assert "2026-01-26" in html
    assert "JSON.stringify" not in html
    assert "pendingRequests" in html
    assert "String(msg.id)" in html
    assert "https://" not in html


def test_plan_board_html_is_self_contained():
    html = plan_board_html()
    assert "Plan Board" in html
    assert "renderDashboard" in html
    assert "plan-card" in html
    assert "plan_groups" in html
    assert "<details" in html
    assert "todo_summary" in html
    assert "disp-filter" in html
    assert "expand-all" in html
    assert "collapse-all" in html
    assert "callTool" in html
    assert "plan-action" in html
    assert "https://" not in html


def test_build_token_dashboard_payload_shape():
    telemetry = telemetry_from_config({"enabled": True})
    payload = build_token_dashboard_payload(telemetry, path=".")
    assert "snapshot" in payload
    assert "tools" in payload
    assert "checkpoints" in payload
    assert "tokens_saved_est" in payload["snapshot"]


def test_load_token_checkpoints_reads_jsonl(tmp_path: Path):
    metrics = tmp_path / ".braindrain" / "token-metrics.jsonl"
    metrics.parent.mkdir(parents=True)
    row = {
        "schema_version": "1.0",
        "phase": "start",
        "task": "t",
        "totals": {"saved_tokens": 1},
        "context_tags": ["search"],
    }
    metrics.write_text(json.dumps(row) + "\n", encoding="utf-8")
    loaded = load_token_checkpoints(tmp_path, limit=5)
    assert len(loaded) == 1
    assert loaded[0]["phase"] == "start"


def test_parse_plan_board_table_from_markdown():
    md = """
| Seq | Plan | IDE | Status | Owner | Item | Source | Gaps |
|-----|------|-----|--------|-------|------|--------|------|
| 1 | Token eval | cursor | In Progress | @test | ship it | `a.plan.md` | — |
"""
    rows = _parse_plan_board_table(md)
    assert len(rows) == 1
    assert rows[0]["plan"] == "Token eval"
    assert rows[0]["status"] == "In Progress"
    assert rows[0]["item"] == "ship it"
    assert rows[0]["source"] == "a.plan.md"


def test_group_plan_rows_collapses_by_source():
    rows = [
        {
            "seq": 1,
            "plan": "P1b",
            "ide": "cursor",
            "status": "Outstanding",
            "owner": "@test",
            "item": "task a",
            "source": "a.plan.md",
            "gaps": "test",
        },
        {
            "seq": 1,
            "plan": "P1b",
            "ide": "cursor",
            "status": "Blocked",
            "owner": "@test",
            "item": "task b",
            "source": "a.plan.md",
            "gaps": "—",
        },
    ]
    master = {
        "a.plan.md": {
            "seq": 1,
            "plan": "P1b — Server modernization",
            "priority": "P2",
            "disposition": "active",
            "branch": "feat/x",
            "next_verb": "IMPLEMENT",
            "source": "a.plan.md",
        }
    }
    groups = _group_plan_rows(rows, master_by_source=master)
    assert len(groups) == 1
    assert groups[0]["plan"] == "P1b — Server modernization"
    assert groups[0]["branch"] == "feat/x"
    assert len(groups[0]["items"]) == 2
    assert groups[0]["status_counts"]["Blocked"] == 1
    assert groups[0]["status_counts"]["Outstanding"] == 1


def test_parse_master_plan_queue():
    md = """
| # | Plan | Priority | Disposition | Branch | Next verb | Source |
|---|------|----------|-------------|--------|-----------|--------|
| 1 | [P1b](.cursor/plans/p1.plan.md) | P2 | `active` | `feat/x` | IMPLEMENT | `.cursor/plans/p1.plan.md` |
"""
    meta = _parse_master_plan_queue(md)
    assert ".cursor/plans/p1.plan.md" in meta
    assert meta[".cursor/plans/p1.plan.md"]["branch"] == "feat/x"
    assert meta[".cursor/plans/p1.plan.md"]["disposition"] == "active"


def test_build_plan_board_payload_groups(tmp_path: Path):
    reports = tmp_path / ".braindrain" / "plan-reports"
    reports.mkdir(parents=True)
    board = """
| Seq | Plan | IDE | Status | Owner | Item | Source | Gaps |
|-----|------|-----|--------|-------|------|--------|------|
| 1 | Short title | cursor | Outstanding | @test | do thing | `p.plan.md` | — |
| 1 | Short title | cursor | Outstanding | @test | do other | `p.plan.md` | test |
"""
    master = """
| # | Plan | Priority | Disposition | Branch | Next verb | Source |
|---|------|----------|-------------|--------|-----------|--------|
| 1 | [Full title](p.plan.md) | P2 | `active` | `feat/y` | IMPLEMENT | `p.plan.md` |
"""
    (reports / "plan-task-board.md").write_text(board, encoding="utf-8")
    (reports / "master-plan.md").write_text(master, encoding="utf-8")
    (reports / "next-actions.md").write_text("- Ship plan board UI\n", encoding="utf-8")

    payload = build_plan_board_payload(path=str(tmp_path))
    assert payload["summary"]["plan_count"] == 1
    assert payload["summary"]["item_count"] == 2
    assert len(payload["plan_groups"]) == 1
    assert len(payload["plan_groups"][0]["items"]) == 2
    assert payload["plan_groups"][0]["branch"] == "feat/y"
    assert payload["next_actions"] == ["Ship plan board UI"]


def test_parse_master_disposition_tables():
    md = """
| Plan | Owner | Branch | PR | Priority | Todos (done/total) | Items (Impl/Active/Blocked/Out/Unk) | Source |
|------|-------|--------|----|----------|--------------------|--------------------------------------|--------|
| [P1a](.cursor/plans/p1.plan.md) | @test | `feat/x` | [#143 open](https://github.com/org/repo/pull/143) | P1 | 6/6 | 6/0/0/0/0 | `.cursor/plans/p1.plan.md` |
"""
    meta = parse_master_disposition_tables(md)
    source = ".cursor/plans/p1.plan.md"
    assert source in meta
    assert meta[source]["branch"] == "feat/x"
    assert meta[source]["todo_fraction"] == {"done": 6, "total": 6}
    assert meta[source]["pr"]["label"] == "#143 open"
    assert meta[source]["item_rollups"]["implemented"] == 6


def test_enrich_plan_groups_adds_todos_and_pr(tmp_path: Path):
    plan_dir = tmp_path / ".cursor" / "plans"
    plan_dir.mkdir(parents=True)
    plan_path = plan_dir / "demo.plan.md"
    plan_path.write_text(
        """---
name: Demo plan
overview: Ship the demo feature end to end.
parent: _master
branch: feat/demo
todos:
  - id: t1
    content: Build UI
    status: completed
  - id: t2
    content: Add tests
    status: pending
---
# Demo
""",
        encoding="utf-8",
    )
    groups = [
        {
            "seq": 1,
            "plan": "Demo plan",
            "source": ".cursor/plans/demo.plan.md",
            "owner": "@test",
            "branch": "—",
            "items": [],
            "status_counts": {"Blocked": 0, "In Progress": 0, "Outstanding": 1},
        }
    ]
    master = """
| Plan | Owner | Branch | PR | Priority | Todos (done/total) | Items | Source |
|------|-------|--------|----|----------|--------------------|-------|--------|
| [Demo plan](.cursor/plans/demo.plan.md) | @test | `feat/demo` | none | P2 | 1/2 | 0/0/0/1/0 | `.cursor/plans/demo.plan.md` |
"""
    enriched = enrich_plan_groups(groups, repo_root=tmp_path, master_md=master)
    assert len(enriched) == 1
    assert enriched[0]["branch"] == "feat/demo"
    assert enriched[0]["todo_summary"]["completed"] == 1
    assert enriched[0]["todo_summary"]["total"] == 2
    assert len(enriched[0]["todos"]) == 2
    assert enriched[0]["overview"].startswith("Ship the demo")
    assert "action_gates" in enriched[0]
    assert "audit" in enriched[0]["action_gates"]


def test_enrich_plan_groups_adds_pr_only_plan(tmp_path: Path):
    master = """
| Plan | Owner | Branch | PR | Priority | Todos (done/total) | Items (Impl/Active/Blocked/Out/Unk) | Source |
|------|-------|--------|----|----------|--------------------|--------------------------------------|--------|
| [P1a](.cursor/plans/p1a.plan.md) | @test | `feat/p1a` | [#143 open](https://github.com/org/repo/pull/143) | P1 | 6/6 | 6/0/0/0/0 | `.cursor/plans/p1a.plan.md` |
"""
    enriched = enrich_plan_groups([], repo_root=tmp_path, master_md=master)
    assert len(enriched) == 1
    assert enriched[0]["plan"] == "P1a"
    assert enriched[0]["pr"]["label"] == "#143 open"
    assert enriched[0]["synthetic_from_pr"] is True


def test_mcp_app_tools_registered_with_ui_meta():
    tools = asyncio.run(mcp.list_tools())
    by_name = {t.name: t for t in tools}
    assert "show_token_dashboard" in by_name
    assert "show_plan_board" in by_name
    token_tool = by_name["show_token_dashboard"]
    meta = getattr(token_tool, "meta", None) or {}
    ui = meta.get("ui") or meta.get("_meta", {}).get("ui")
    if ui is None:
        # FastMCP may expose meta on model_dump
        dumped = token_tool.model_dump() if hasattr(token_tool, "model_dump") else {}
        ui = (dumped.get("meta") or {}).get("ui")
    assert ui is not None
    resource_uri = ui.get("resourceUri") or ui.get("resource_uri")
    assert resource_uri == TOKEN_DASHBOARD_URI
    visibility = ui.get("visibility") or []
    assert "model" in visibility and "app" in visibility


def test_show_token_dashboard_tool_result_shape():
    from fastmcp import Client

    async def _run():
        async with Client(mcp) as client:
            return await client.call_tool("show_token_dashboard", {})

    result = asyncio.run(_run())
    assert result.content
    text = getattr(result.content[0], "text", "")
    assert text == "Token dashboard ready."
    assert "snapshot" in (result.structured_content or {})


def test_mcp_app_resources_registered():
    resources = asyncio.run(mcp.list_resources())
    uris = {str(r.uri) for r in resources}
    assert TOKEN_DASHBOARD_URI in uris
    assert PLAN_BOARD_URI in uris


def test_plan_board_html_has_action_bridge():
    html = plan_board_html()
    assert "callTool" in html
    assert "pollPlanAction" in html
    assert "plan-action" in html
    assert "cancel_plan" in html
    assert "run-masterplan" in html
    assert "show-archived" in html
    assert "session.showArchived = false" in html
    assert "ts-tag" in html
    assert "renderTimestampTags" in html
    assert "date-filter" in html
    assert "ts-current-month" in html
    assert "matchesDateFilter" in html
    assert "open-cursor" in html
    assert "openPlanInEditor" in html
    assert "showPlanOpenDialog" in html
    assert "copyTextFallback" in html
    assert "ui/open-link" in html
    assert "editorFileUriVariants" in html
    assert "plan-disposition" in html
    assert "renderDispositionSelect" in html
    assert "set_disposition" in html
    assert "__planBoardSession" in html
    assert "planDialogCancelPlan" in html
    assert "plan-modal" in html
    assert "window.confirm" not in html
    assert "action_gates" in html or "renderActionButtons" in html


def test_dispatch_plan_board_action_audit(tmp_path: Path):
    from braindrain.mcp_apps.plan_actions import dispatch_plan_board_action

    target = tmp_path / "braindrain" / "demo.py"
    target.parent.mkdir(parents=True)
    target.write_text("# demo\n", encoding="utf-8")
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir(parents=True)
    (plan_dir / "demo.plan.md").write_text(
        """---
todos:
  - id: t1
    content: "Add `braindrain/demo.py`"
    status: pending
---
# Demo
""",
        encoding="utf-8",
    )
    payload = dispatch_plan_board_action(
        path=str(tmp_path),
        action="audit",
        source="plans/demo.plan.md",
    )
    assert payload.get("plan_groups") is not None
    assert payload["action_result"]["proposals"]


def test_audit_detects_pathish_without_backticks(tmp_path: Path):
    from braindrain.mcp_apps.plan_actions import audit_plan_implementation

    target = tmp_path / "braindrain" / "config_schema.py"
    target.parent.mkdir(parents=True)
    target.write_text("# schema\n", encoding="utf-8")
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir(parents=True)
    (plan_dir / "demo.plan.md").write_text(
        """---
todos:
  - id: t1
    content: "Ship braindrain/config_schema.py validation"
    status: pending
---
# Demo
""",
        encoding="utf-8",
    )
    audit = audit_plan_implementation(path=str(tmp_path), source="plans/demo.plan.md")
    assert len(audit["proposals"]) >= 1
    assert audit["proposals"][0]["suggested_status"] == "completed"


def test_audit_uses_plan_body_snippet(tmp_path: Path):
    from braindrain.mcp_apps.plan_actions import audit_plan_implementation

    target = tmp_path / "braindrain" / "demo.py"
    target.parent.mkdir(parents=True)
    target.write_text("# demo\n", encoding="utf-8")
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir(parents=True)
    (plan_dir / "demo.plan.md").write_text(
        """---
todos:
  - id: phase-a-demo
    content: "Implement demo module"
    status: pending
---
# Demo

## phase-a-demo
Add `braindrain/demo.py` for the demo module.
""",
        encoding="utf-8",
    )
    audit = audit_plan_implementation(path=str(tmp_path), source="plans/demo.plan.md")
    assert audit["proposals"]
    assert audit["proposals"][0]["todo_id"] == "phase-a-demo"


def test_force_cancel_archive_plan(tmp_path: Path):
    from braindrain.mcp_apps.plan_actions import archive_plan

    plan_dir = tmp_path / "plans"
    plan_dir.mkdir(parents=True)
    plan_path = plan_dir / "old.plan.md"
    plan_path.write_text(
        """---
todos:
  - id: t1
    content: "Do thing"
    status: pending
disposition: replan-needed
overview: Old idea
---
# Old
""",
        encoding="utf-8",
    )
    result = archive_plan(
        path=str(tmp_path),
        source="plans/old.plan.md",
        confirm=True,
        force=True,
        cancel_note="Superseded by new approach",
    )
    assert result["ok"] is True
    assert result["disposition"] == "scratched"
    archived = plan_dir / ".plan.archives" / "old.plan.md"
    assert archived.is_file()
    text = archived.read_text(encoding="utf-8")
    assert "disposition: scratched" in text
    assert "Superseded by new approach" in text
    assert "status: cancelled" in text


def test_compute_action_gates_enables_cancel_without_branch_or_pr(tmp_path: Path):
    from braindrain.mcp_apps.plan_gates import compute_action_gates

    plan_path = tmp_path / "plans" / "ai-shell.plan.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("---\ndisposition: replan-needed\n---\n# AI Shell\n", encoding="utf-8")
    group = {
        "source": "plans/ai-shell.plan.md",
        "disposition": "replan-needed",
        "branch": "—",
        "todo_summary": {"total": 9, "completed": 0, "cancelled": 0},
    }
    gates = compute_action_gates(group, repo_root=tmp_path)
    assert gates["cancel_plan"]["enabled"] is True


def test_compute_action_gates_enables_cancel_with_branch(tmp_path: Path):
    from braindrain.mcp_apps.plan_gates import compute_action_gates

    plan_path = tmp_path / "plans" / "demo.plan.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("---\ndisposition: active\n---\n# Demo\n", encoding="utf-8")
    group = {
        "source": "plans/demo.plan.md",
        "disposition": "active",
        "branch": "feat/demo",
        "todo_summary": {"total": 2, "completed": 0, "cancelled": 0},
    }
    gates = compute_action_gates(group, repo_root=tmp_path)
    assert gates["cancel_plan"]["enabled"] is True
    assert gates["archive"]["enabled"] is True


def test_compute_action_gates_enables_archive_for_active_plan(tmp_path: Path):
    from braindrain.mcp_apps.plan_gates import compute_action_gates

    plan_path = tmp_path / "plans" / "demo.plan.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("---\ndisposition: active\n---\n# Demo\n", encoding="utf-8")
    group = {
        "source": "plans/demo.plan.md",
        "disposition": "active",
        "branch": "docs/hermes-gap",
        "todo_summary": {"total": 2, "completed": 0, "cancelled": 0},
    }
    gates = compute_action_gates(group, repo_root=tmp_path)
    assert gates["archive"]["enabled"] is True


def test_archive_active_plan_with_branch(tmp_path: Path):
    from braindrain.mcp_apps.plan_actions import archive_plan

    plan_dir = tmp_path / "plans"
    plan_dir.mkdir(parents=True)
    plan_path = plan_dir / "hermes.plan.md"
    plan_path.write_text(
        """---
disposition: active
branch: docs/hermes-gap
---
# Hermes gap
""",
        encoding="utf-8",
    )
    result = archive_plan(
        path=str(tmp_path),
        source="plans/hermes.plan.md",
        confirm=True,
        force=False,
    )
    assert result["ok"] is True
    assert result["disposition"] == "archived"
    assert (plan_dir / ".plan.archives" / "hermes.plan.md").is_file()


def test_compute_action_gates_disables_merge_ready_without_pr(tmp_path: Path):
    from braindrain.mcp_apps.plan_gates import compute_action_gates

    plan_path = tmp_path / "plans" / "demo.plan.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("---\ndisposition: active\n---\n# Demo\n", encoding="utf-8")
    group = {
        "source": "plans/demo.plan.md",
        "disposition": "active",
        "branch": "feat/demo",
        "todo_summary": {"total": 2, "completed": 2, "cancelled": 0},
    }
    gates = compute_action_gates(group, repo_root=tmp_path)
    assert gates["merge_ready"]["enabled"] is False
    assert "PR" in gates["merge_ready"]["reason"]


def test_audit_plan_implementation_detects_existing_file(tmp_path: Path):
    from braindrain.mcp_apps.plan_actions import audit_plan_implementation

    target = tmp_path / "braindrain" / "demo.py"
    target.parent.mkdir(parents=True)
    target.write_text("# demo\n", encoding="utf-8")
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir(parents=True)
    plan_path = plan_dir / "demo.plan.md"
    plan_path.write_text(
        """---
todos:
  - id: t1
    content: "Add `braindrain/demo.py` module"
    status: pending
disposition: active
---
# Demo
""",
        encoding="utf-8",
    )
    result = audit_plan_implementation(
        path=str(tmp_path),
        source="plans/demo.plan.md",
        dry_run=True,
    )
    assert result["proposals"]
    assert result["proposals"][0]["suggested_status"] == "completed"
    assert result["action_gates"]["apply_sync"]["enabled"] is True


def test_apply_plan_todo_sync_requires_confirm(tmp_path: Path):
    from braindrain.mcp_apps.plan_actions import apply_plan_todo_sync

    plan_dir = tmp_path / "plans"
    plan_dir.mkdir(parents=True)
    plan_path = plan_dir / "demo.plan.md"
    plan_path.write_text(
        """---
todos:
  - id: t1
    content: "Ship it"
    status: pending
---
# Demo
""",
        encoding="utf-8",
    )
    proposals = [
        {
            "todo_id": "t1",
            "suggested_status": "completed",
            "confidence": "high",
        }
    ]
    blocked = apply_plan_todo_sync(
        path=str(tmp_path),
        source="plans/demo.plan.md",
        proposals=proposals,
        confirm=False,
    )
    assert blocked["ok"] is False
    applied = apply_plan_todo_sync(
        path=str(tmp_path),
        source="plans/demo.plan.md",
        proposals=proposals,
        confirm=True,
    )
    assert applied["ok"] is True
    text = plan_path.read_text(encoding="utf-8")
    assert "status: completed" in text


def test_load_archived_plan_groups(tmp_path: Path):
    archive_dir = tmp_path / ".cursor" / "plans" / ".plan.archives"
    archive_dir.mkdir(parents=True)
    (archive_dir / "old.plan.md").write_text(
        """---
disposition: scratched
overview: Cancelled test
name: Old Plan
---
# Old
""",
        encoding="utf-8",
    )
    groups = _load_archived_plan_groups(tmp_path, existing_sources=set())
    assert len(groups) == 1
    assert groups[0]["is_archived"] is True
    assert groups[0]["disposition"] == "scratched"


def test_build_plan_board_includes_archived(tmp_path: Path):
    reports = tmp_path / ".braindrain" / "plan-reports"
    reports.mkdir(parents=True)
    (reports / "plan-task-board.md").write_text(
        "| Seq | Plan | IDE | Status | Owner | Item | Source | Gaps |\n|-----|------|-----|--------|-------|------|--------|------|\n",
        encoding="utf-8",
    )
    (reports / "master-plan.md").write_text("# Master\n", encoding="utf-8")
    archive_dir = tmp_path / ".cursor" / "plans" / ".plan.archives"
    archive_dir.mkdir(parents=True)
    (archive_dir / "gone.plan.md").write_text(
        "---\ndisposition: scratched\nname: Gone\n---\n# Gone\n",
        encoding="utf-8",
    )
    payload = build_plan_board_payload(path=str(tmp_path))
    assert payload["summary"]["archived_count"] >= 1
    assert any(g.get("is_archived") for g in payload["plan_groups"])


def test_load_plan_file_meta_timestamps(tmp_path: Path):
    from braindrain.mcp_apps.plan_enrich import load_plan_file_meta

    plan_dir = tmp_path / "plans"
    plan_dir.mkdir(parents=True)
    (plan_dir / "dated.plan.md").write_text(
        """---
name: Dated plan
created_at: 2026-06-01T10:00:00Z
last_modified_at: 2026-06-19T14:30:00Z
last_modified_by_model: auto
---
# Dated
""",
        encoding="utf-8",
    )
    meta = load_plan_file_meta(tmp_path, "plans/dated.plan.md")
    assert meta["updated_at"] == "2026-06-19T14:30:00Z"
    assert meta["created_at"] == "2026-06-01T10:00:00Z"
    tags = meta.get("timestamp_tags") or []
    assert any("updated" in t for t in tags)
    assert any("created 2026-06-01" in t for t in tags)
    assert any("model auto" in t for t in tags)


def test_build_plan_board_timestamp_tags_on_archived(tmp_path: Path):
    reports = tmp_path / ".braindrain" / "plan-reports"
    reports.mkdir(parents=True)
    (reports / "plan-task-board.md").write_text(
        "| Seq | Plan | IDE | Status | Owner | Item | Source | Gaps |\n|-----|------|-----|--------|-------|------|--------|------|\n",
        encoding="utf-8",
    )
    (reports / "master-plan.md").write_text("# Master\n", encoding="utf-8")
    archive_dir = tmp_path / ".cursor" / "plans" / ".plan.archives"
    archive_dir.mkdir(parents=True)
    (archive_dir / "gone.plan.md").write_text(
        """---
disposition: scratched
name: Gone
last_modified_at: 2026-06-18T09:15:00Z
---
# Gone
""",
        encoding="utf-8",
    )
    payload = build_plan_board_payload(path=str(tmp_path))
    archived = [g for g in payload["plan_groups"] if g.get("is_archived")]
    assert len(archived) == 1
    assert archived[0].get("timestamp_tags")
    assert archived[0].get("updated_at") == "2026-06-18T09:15:00Z"


def test_set_plan_disposition(tmp_path: Path):
    from braindrain.mcp_apps.plan_actions import set_plan_disposition

    plan_dir = tmp_path / "plans"
    plan_dir.mkdir(parents=True)
    plan_path = plan_dir / "demo.plan.md"
    plan_path.write_text("---\ndisposition: active\n---\n# Demo\n", encoding="utf-8")
    result = set_plan_disposition(
        path=str(tmp_path),
        source="plans/demo.plan.md",
        disposition="backlogged",
        confirm=True,
    )
    assert result["ok"] is True
    assert "disposition: backlogged" in plan_path.read_text(encoding="utf-8")


def test_build_plan_board_includes_disposition_options(tmp_path: Path):
    reports = tmp_path / ".braindrain" / "plan-reports"
    reports.mkdir(parents=True)
    (reports / "plan-task-board.md").write_text(
        "| Seq | Plan | IDE | Status | Owner | Item | Source | Gaps |\n|-----|------|-----|--------|-------|------|--------|------|\n",
        encoding="utf-8",
    )
    (reports / "master-plan.md").write_text("# Master\n", encoding="utf-8")
    payload = build_plan_board_payload(path=str(tmp_path))
    assert "backlogged" in payload["disposition_options"]
    assert "active" in payload["disposition_options"]


def test_plan_board_action_tools_registered():
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    for tool_name in (
        "audit_plan_implementation",
        "apply_plan_todo_sync",
        "mark_plan_merge_ready",
        "archive_plan",
        "enqueue_plan_continue",
        "plan_board_handoff",
    ):
        assert tool_name in names


def test_sigint_map_html_is_self_contained():
    html = sigint_map_html()
    assert "SIGINT Map" in html
    assert "renderDashboard" in html
    assert "poll_sigint_map" in html
    assert "sigint-svg" in html
    assert "ui/initialize" in html
    assert "https://" not in html


def test_build_sigint_map_payload_with_fixture_events(tmp_path: Path):
    db_path = tmp_path / "events.db"
    store = ObserverStore(db_path=db_path)
    store.record_event(
        BrainEvent(
            timestamp=1_700_000_000.0,
            session_id="sigint-test",
            event_type="tool_call",
            tool_name="get_token_dashboard",
            metadata={"project_root": str(tmp_path)},
        )
    )
    store.record_event(
        BrainEvent(
            timestamp=1_700_000_100.0,
            session_id="sigint-test",
            event_type="session_end",
            metadata={"hook": "stop", "branch": "feat/sigint", "repo_root": str(tmp_path)},
        )
    )
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "user-braindrain": {"serverName": "braindrain"},
                    "cursor-ide-browser": {"serverName": "cursor-ide-browser"},
                }
            }
        ),
        encoding="utf-8",
    )
    payload = build_sigint_map_payload(tmp_path, session_id="sigint-test", observer_db=db_path)
    assert payload["session_id"] == "sigint-test"
    assert payload["stats"]["events"] == 2
    assert payload["stats"]["tools"] == 1
    types = {n["type"] for n in payload["nodes"]}
    assert "session" in types
    assert "braindrain_hub" in types
    assert "braindrain_tool" in types
    assert "hook" in types
    assert "external_mcp" in types
    assert any(e["type"] == "tool_call" for e in payload["edges"])
    assert len(payload["log"]) == 2


def test_mcp_sigint_tools_registered_with_ui_meta():
    tools = asyncio.run(mcp.list_tools())
    by_name = {t.name: t for t in tools}
    assert "show_sigint_map" in by_name
    sigint_tool = by_name["show_sigint_map"]
    meta = getattr(sigint_tool, "meta", None) or {}
    ui = meta.get("ui") or meta.get("_meta", {}).get("ui")
    if ui is None:
        dumped = sigint_tool.model_dump() if hasattr(sigint_tool, "model_dump") else {}
        ui = (dumped.get("meta") or {}).get("ui")
    assert ui is not None
    resource_uri = ui.get("resourceUri") or ui.get("resource_uri")
    assert resource_uri == SIGINT_MAP_URI


def test_show_sigint_map_tool_result_shape():
    from fastmcp import Client

    async def _run():
        async with Client(mcp) as client:
            return await client.call_tool("show_sigint_map", {})

    result = asyncio.run(_run())
    assert result.content
    text = getattr(result.content[0], "text", "")
    assert text == "SIGINT map ready."
    structured = result.structured_content or {}
    assert "nodes" in structured
    assert "edges" in structured
    assert "stats" in structured


def test_mcp_sigint_resource_registered():
    resources = asyncio.run(mcp.list_resources())
    uris = {str(r.uri) for r in resources}
    assert SIGINT_MAP_URI in uris
