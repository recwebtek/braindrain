"""Tests for lightweight MCP Apps (`ui://`) dashboards."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from braindrain.mcp_apps.constants import PLAN_BOARD_URI, TOKEN_DASHBOARD_URI
from braindrain.mcp_apps.data import (
    build_token_dashboard_payload,
    load_token_checkpoints,
)
from braindrain.mcp_apps.html import plan_board_html, token_dashboard_html
from braindrain.server import mcp
from braindrain.telemetry import telemetry_from_config


def test_token_dashboard_html_is_self_contained():
    html = token_dashboard_html()
    assert TOKEN_DASHBOARD_URI.split("/")[-1] in html or "Token Dashboard" in html
    assert "ui/initialize" in html
    assert "ui/notifications/tool-result" in html
    assert "https://" not in html


def test_plan_board_html_is_self_contained():
    html = plan_board_html()
    assert "Plan Board" in html
    assert "renderDashboard" in html
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
    from braindrain.mcp_apps.data import _parse_plan_board_table

    rows = _parse_plan_board_table(md)
    assert len(rows) == 1
    assert rows[0]["plan"] == "Token eval"
    assert rows[0]["status"] == "In Progress"


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


def test_mcp_app_resources_registered():
    resources = asyncio.run(mcp.list_resources())
    uris = {str(r.uri) for r in resources}
    assert TOKEN_DASHBOARD_URI in uris
    assert PLAN_BOARD_URI in uris
