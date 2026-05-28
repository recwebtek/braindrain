from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from braindrain.livingdash_collectors import (
    SNAPSHOT_SCHEMA_VERSION,
    collect_gitops_state,
    collect_mcp_catalog,
    collect_observer_logs,
    collect_scriptlib_summary,
    collect_sessions_summary,
    collect_workflows_summary,
    collect_workspace_agents,
    collect_workspace_bundle,
    collect_workspace_tests,
    collect_cursor_plans,
    load_livingdash_config,
)


@pytest.fixture()
def mini_workspace(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "hub_config.yaml").write_text(
        """
project_name: TestProject
livingdash:
  enabled: true
  host: 127.0.0.1
  port: 0
cost_tracking:
  log_file: costs/session.jsonl
observer:
  storage_path: events.db
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "config" / "templates" / "agents").mkdir(parents=True)
    (tmp_path / "config" / "templates" / "agents" / "gitops.md").write_text(
        "---\nmodel: composer-2\n---\nGitops agent.",
        encoding="utf-8",
    )
    cursor_root = tmp_path / "dotcursor"
    (cursor_root / "agents").mkdir(parents=True)
    (cursor_root / "agents" / "gitops.md").write_text(
        "---\nmodel: composer-2\n---\nInstalled gitops.",
        encoding="utf-8",
    )
    try:
        (tmp_path / ".cursor").symlink_to(cursor_root, target_is_directory=True)
    except OSError:
        import shutil

        shutil.copytree(cursor_root, tmp_path / ".cursor")
    (tmp_path / ".cursor" / "plans").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".cursor" / "plans" / "sample.plan.md").write_text(
        "---\nname: Sample\ndisposition: active\n---\n# Sample plan\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (tmp_path / ".braindrain").mkdir()
    (tmp_path / ".braindrain" / "primed.json").write_text(
        json.dumps({"primed_at": "2026-01-01T00:00:00Z", "bundle": "core"}),
        encoding="utf-8",
    )
    return tmp_path


def test_load_livingdash_config_reads_block(mini_workspace: Path) -> None:
    import yaml

    hub = yaml.safe_load((mini_workspace / "config" / "hub_config.yaml").read_text())
    cfg = load_livingdash_config(hub)
    assert cfg["host"] == "127.0.0.1"
    assert cfg["port"] == 0


def test_collect_workspace_agents_installed(mini_workspace: Path) -> None:
    payload = collect_workspace_agents(mini_workspace)
    names = {item["name"] for item in payload["items"]}
    assert "gitops" in names
    gitops = next(item for item in payload["items"] if item["name"] == "gitops")
    assert gitops["installed"] is True
    assert gitops["provider"] == "cursor"


def test_collect_workspace_tests_lists_python_files(mini_workspace: Path) -> None:
    payload = collect_workspace_tests(mini_workspace)
    assert payload["python_test_count"] == 1
    assert "tests/test_sample.py" in payload["python_tests"]


def test_collect_cursor_plans_lists_plan_files(mini_workspace: Path) -> None:
    plans = collect_cursor_plans(mini_workspace)
    assert len(plans) == 1
    assert plans[0]["name"] == "Sample"
    assert plans[0]["path"].endswith("sample.plan.md")


def test_collect_observer_logs_reads_metadata_column(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE brain_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            session_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            tool_name TEXT,
            files_touched TEXT NOT NULL,
            token_cost INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            metadata TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO brain_events (timestamp, session_id, event_type, tool_name, files_touched, metadata)
        VALUES (1.0, 'sess-1', 'tool_call', 'ping', '[]', '{"ok": true}')
        """
    )
    conn.commit()
    conn.close()

    payload = collect_observer_logs({"observer_db": db_path})
    assert payload["exists"] is True
    assert payload.get("error") is None
    assert len(payload["events"]) == 1
    assert payload["events"][0]["payload"] == {"ok": True}


def test_collect_workspace_bundle_schema(mini_workspace: Path) -> None:
    bundle = collect_workspace_bundle(mini_workspace)
    assert bundle["schema_version"] == SNAPSHOT_SCHEMA_VERSION
    assert "agents" in bundle
    assert "tests" in bundle
    assert "gitops" in bundle
    assert "workflows" in bundle
    assert "mcp_catalog" in bundle
    assert "sessions" in bundle
    assert "scriptlib" in bundle
    assert len(bundle["plans"]["cursor_plans"]) == 1


def test_collect_gitops_state_empty(mini_workspace: Path) -> None:
    payload = collect_gitops_state(mini_workspace)
    assert payload["queue_exists"] is False
    assert payload["memory_exists"] is False
    assert payload["queue_count"] == 0


def test_collect_workflows_summary_from_hub(mini_workspace: Path) -> None:
    import yaml

    config_path = mini_workspace / "config" / "hub_config.yaml"
    hub = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    hub["workflows"] = [
        {
            "name": "demo",
            "description": "demo flow",
            "steps": ["a", "b"],
            "executes_in": "sandbox",
            "model": "tier_local",
            "token_budget": 100,
            "plan_before_run": True,
        }
    ]
    payload = collect_workflows_summary(hub)
    assert payload["count"] == 1
    assert payload["items"][0]["name"] == "demo"
    assert payload["items"][0]["step_count"] == 2


def test_collect_mcp_catalog_and_scriptlib(mini_workspace: Path) -> None:
    catalog_tool = mini_workspace / ".braindrain" / "mcp-catalog" / "alpha" / "tools"
    catalog_tool.mkdir(parents=True)
    (mini_workspace / ".braindrain" / "mcp-catalog" / "README.md").write_text("# Catalog", encoding="utf-8")
    (catalog_tool / "ping.md").write_text("# ping", encoding="utf-8")
    scriptlib = mini_workspace / ".scriptlib"
    scriptlib.mkdir(parents=True)
    (scriptlib / "index.json").write_text(json.dumps({"entries": [{"name": "x"}]}), encoding="utf-8")
    (scriptlib / "catalog.md").write_text("# scripts", encoding="utf-8")

    payload = collect_mcp_catalog(mini_workspace, {"mcp_tools": [{"name": "context_mode", "hot": True}]})
    assert payload["exists"] is True
    assert payload["server_count"] == 1
    assert payload["servers"][0]["tool_count"] == 1

    script_payload = collect_scriptlib_summary(mini_workspace)
    assert script_payload["exists"] is True
    assert script_payload["index"]["entry_count"] == 1


def test_collect_sessions_summary_reads_sqlite(tmp_path: Path) -> None:
    db_path = tmp_path / "sessions.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE session_summaries (
            session_id TEXT PRIMARY KEY,
            start_time REAL,
            end_time REAL,
            events_count INTEGER,
            tools_used TEXT,
            files_modified TEXT,
            key_decisions TEXT,
            errors TEXT,
            open_todos TEXT,
            token_total INTEGER,
            updated_at REAL,
            context_index_handle TEXT,
            compact_package_json TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO session_summaries (
            session_id, start_time, end_time, events_count, files_modified,
            key_decisions, errors, open_todos, token_total, updated_at
        ) VALUES (
            'sess-1', 1.0, 2.0, 3, '["a.py"]', '["decide"]', '[]', '["todo"]', 10, 99.0
        )
        """
    )
    conn.commit()
    conn.close()
    payload = collect_sessions_summary({"sessions_db": db_path})
    assert payload["exists"] is True
    assert payload["count"] == 1
    assert payload["items"][0]["session_id"] == "sess-1"
