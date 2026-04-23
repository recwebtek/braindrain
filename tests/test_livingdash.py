from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from braindrain.livingdash import (
    LivingDashManager,
    build_dashboard_snapshot,
    ensure_livingdash_runtime,
)
from braindrain.livingdash_sidecar import create_app

_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def tmp_project_dir() -> Path:
    d = _REPO_ROOT / ".pytest_tmp" / f"ldash-{uuid.uuid4().hex[:12]}"
    d.mkdir(parents=True, exist_ok=True)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _make_sample_project(root: Path) -> Path:
    project = root / "sample-project"
    (project / "braindrain").mkdir(parents=True, exist_ok=True)
    (project / "config").mkdir(parents=True, exist_ok=True)
    (project / ".cursor" / "agents").mkdir(parents=True, exist_ok=True)

    (project / "README.md").write_text(
        "# braindrain\n\n"
        "An MCP server that keeps AI agents lean by caching environment context,\n"
        "deferring heavy tools, and routing large outputs.\n",
        encoding="utf-8",
    )
    (project / "config" / "hub_config.yaml").write_text(
        'project_name: "braindrain"\n'
        "mcp_tools:\n"
        "  - name: get_env_context\n"
        "    hot: true\n"
        "  - name: search_tools\n"
        "    hot: true\n",
        encoding="utf-8",
    )
    (project / "braindrain" / "server.py").write_text(
        "config = Config('config/hub_config.yaml')\n"
        "registry = ToolRegistry(config.data)\n"
        "telemetry = telemetry_from_config({})\n"
        "@mcp.tool()\n"
        "def search_tools():\n"
        "    return {}\n",
        encoding="utf-8",
    )
    (project / ".env.dev").write_text("OPENAI_API_KEY=test\n", encoding="utf-8")
    (project / ".cursor" / "agents" / "research.md").write_text("# research\n", encoding="utf-8")
    (project / ".cursor" / "agents" / "gitops.md").write_text("# gitops\n", encoding="utf-8")

    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=project,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return project


def test_ensure_livingdash_runtime_creates_isolated_layout(tmp_project_dir: Path) -> None:
    project = _make_sample_project(tmp_project_dir)

    runtime = ensure_livingdash_runtime(project)

    root = project / ".braindrain" / "ldash"
    scaffold = project / ".ldash"
    assert runtime.root == root
    assert runtime.scaffold_root == scaffold
    assert (scaffold / "server").is_dir()
    assert (scaffold / "ui").is_dir()
    assert (scaffold / "config" / "commands.json").is_file()
    assert (scaffold / "config" / "services.json").is_file()
    assert (root / "data").is_dir()
    assert (scaffold / "server" / "app.py").is_file()


def test_build_dashboard_snapshot_collects_workspace_signals(tmp_project_dir: Path) -> None:
    project = _make_sample_project(tmp_project_dir)

    snapshot = build_dashboard_snapshot(project)

    assert snapshot["workspace"]["name"] == "sample-project"
    assert snapshot["repo"]["project_name"] == "BrainDrain MCP"
    assert snapshot["workspace_signals"]["git"]["branch"] == "main"
    assert snapshot["workspace_signals"]["git"]["default_branch"] == "main"
    assert snapshot["workspace_signals"]["agents"]["count"] == 2
    env_names = {item["name"] for item in snapshot["workspace_signals"]["env_files"]}
    assert ".env.dev" in env_names
    hot_tools = {item["name"] for item in snapshot["workspace_signals"]["mcp_tools"]["active"]}
    assert {"get_env_context", "search_tools"} <= hot_tools


def test_build_dashboard_snapshot_derives_repo_brief_and_startup_flow(tmp_project_dir: Path) -> None:
    project = _make_sample_project(tmp_project_dir)

    snapshot = build_dashboard_snapshot(project)

    assert "keeps AI agents lean" in snapshot["narrative"]["repo_brief"]
    assert "Moving parts:" in snapshot["narrative"]["repo_brief"]
    assert "**Version:**" not in snapshot["narrative"]["repo_brief"]
    step_ids = [step["id"] for step in snapshot["narrative"]["startup_flow"]["steps"]]
    assert step_ids == ["load_config", "build_registry", "init_telemetry", "expose_mcp_tools"]


def test_manager_refresh_writes_snapshot_and_status_starts_stopped(tmp_project_dir: Path) -> None:
    project = _make_sample_project(tmp_project_dir)
    manager = LivingDashManager(project)

    status = manager.status()
    assert status["running"] is False
    assert status["url"] is None

    refreshed = manager.refresh()
    snapshot_path = project / ".braindrain" / "ldash" / "data" / "snapshot.json"

    assert refreshed["ok"] is True
    assert snapshot_path.is_file()
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert payload["workspace"]["name"] == "sample-project"


def test_sidecar_auth_and_snapshot_endpoints(tmp_project_dir: Path) -> None:
    project = _make_sample_project(tmp_project_dir)
    manager = LivingDashManager(project)
    auth = manager.ensure_auth()
    manager.refresh()

    app = create_app(
        project_root=project,
        data_dir=project / ".braindrain" / "ldash" / "data",
        ui_dist=project / ".ldash" / "ui" / "dist",
        auth_config=auth,
    )
    client = TestClient(app)

    session = client.get("/api/auth/session")
    assert session.status_code == 200
    assert session.json()["authenticated"] is False

    login = client.post("/api/auth/login", json={"username": "admin", "password": auth["password"]})
    assert login.status_code == 200

    session = client.get("/api/auth/session")
    assert session.json()["authenticated"] is True

    overview = client.get("/api/overview")
    assert overview.status_code == 200
    assert overview.json()["workspace"]["name"] == "sample-project"
    assert overview.json()["startup_flow"]

    commands = client.get("/api/commands")
    assert commands.status_code == 200
    assert commands.json()["groups"]

    git_status = client.get("/api/git")
    assert git_status.status_code == 200
    assert "summary" in git_status.json()

    processes = client.get("/api/processes")
    assert processes.status_code == 200
    assert processes.json()["items"]

    telemetry = client.get("/api/telemetry")
    assert telemetry.status_code == 200
    assert "summary" in telemetry.json()

    snapshot = client.get("/api/snapshot")
    assert snapshot.status_code == 200
    assert snapshot.json()["startupFlow"]

    live = client.get("/api/live")
    assert live.status_code == 200
    assert "events" in live.json()


def test_ensure_livingdash_runtime_migrates_legacy_ldash_data(tmp_project_dir: Path) -> None:
    project = _make_sample_project(tmp_project_dir)
    legacy_data = project / ".ldash" / "data"
    legacy_data.mkdir(parents=True, exist_ok=True)
    (legacy_data / "auth.json").write_text('{"username":"admin","password":"legacy"}', encoding="utf-8")
    (legacy_data / "status.json").write_text('{"running": false}', encoding="utf-8")

    runtime = ensure_livingdash_runtime(project)

    assert runtime.auth.exists()
    assert runtime.status.exists()
    assert json.loads(runtime.auth.read_text(encoding="utf-8"))["password"] == "legacy"


def test_sidecar_rejects_unknown_or_disallowed_actions(tmp_project_dir: Path) -> None:
    project = _make_sample_project(tmp_project_dir)
    manager = LivingDashManager(project)
    auth = manager.ensure_auth()
    manager.refresh()

    app = create_app(
        project_root=project,
        data_dir=project / ".braindrain" / "ldash" / "data",
        ui_dist=project / ".ldash" / "ui" / "dist",
        auth_config=auth,
    )
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"username": "admin", "password": auth["password"]})
    assert login.status_code == 200

    missing_command = client.post("/api/commands/run/does-not-exist")
    assert missing_command.status_code == 404

    unknown_service = client.post("/api/processes/missing/start")
    assert unknown_service.status_code == 404

    open_watcher = client.post("/api/processes/ui_tests_watch/open")
    assert open_watcher.status_code == 403
