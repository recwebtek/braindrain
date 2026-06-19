"""Tests for lightweight MCP Apps (`ui://`) dashboards."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from braindrain.mcp_apps.constants import PLAN_BOARD_URI, TOKEN_DASHBOARD_URI
from braindrain.mcp_apps.data import (
    _group_plan_rows,
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
from braindrain.mcp_apps.html import plan_board_html, token_dashboard_html
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
    assert "plan-action" in html
    assert "audit_plan_implementation" in html
    assert "action_gates" in html or "renderActionButtons" in html


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
