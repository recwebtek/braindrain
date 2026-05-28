from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from braindrain.livingdash import build_dashboard_snapshot, ensure_livingdash_runtime
from braindrain.livingdash_sidecar import create_app


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "hub_config.yaml").write_text("project_name: SidecarTest\nlivingdash:\n  enabled: true\n", encoding="utf-8")
    cursor_root = tmp_path / "dotcursor"
    (cursor_root / "agents").mkdir(parents=True)
    (cursor_root / "agents" / "coordinator.md").write_text("---\nmodel: composer-2\n---\nCoordinator.", encoding="utf-8")
    try:
        (tmp_path / ".cursor").symlink_to(cursor_root, target_is_directory=True)
    except OSError:
        import shutil

        shutil.copytree(cursor_root, tmp_path / ".cursor")
    paths = ensure_livingdash_runtime(tmp_path)
    auth = {"username": "admin", "password": "secret", "session_secret": "test-secret"}
    paths.auth.write_text(json.dumps(auth), encoding="utf-8")
    snapshot = build_dashboard_snapshot(tmp_path)
    paths.snapshot.write_text(json.dumps(snapshot), encoding="utf-8")
    paths.status.write_text(
        json.dumps({"running": True, "last_refreshed_at": "2026-01-01T00:00:00Z", "refresh_age_seconds": 0}),
        encoding="utf-8",
    )
    ui_dist = tmp_path / "ui_dist"
    ui_dist.mkdir()
    (ui_dist / "index.html").write_text("<html></html>", encoding="utf-8")
    app = create_app(project_root=tmp_path, data_dir=paths.data, ui_dist=ui_dist, auth_config=auth)
    test_client = TestClient(app)
    test_client.post("/api/auth/login", json={"username": "admin", "password": "secret"})
    return test_client


def test_health_unauthenticated(client: TestClient) -> None:
    anon = TestClient(client.app)
    response = anon.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_agents_requires_auth(tmp_path: Path) -> None:
    paths = ensure_livingdash_runtime(tmp_path)
    auth = {"username": "admin", "password": "x", "session_secret": "s"}
    app = create_app(project_root=tmp_path, data_dir=paths.data, ui_dist=tmp_path, auth_config=auth)
    anon = TestClient(app)
    assert anon.get("/api/agents").status_code == 401


def test_agents_and_tests_authenticated(client: TestClient) -> None:
    agents = client.get("/api/agents")
    assert agents.status_code == 200
    assert "items" in agents.json()
    assert agents.json()["count"] >= 1

    tests = client.get("/api/tests")
    assert tests.status_code == 200
    assert "python_tests" in tests.json()
    for endpoint in ("/api/gitops", "/api/workflows", "/api/mcp-catalog", "/api/sessions", "/api/scriptlib"):
        resp = client.get(endpoint)
        assert resp.status_code == 200
        assert resp.json().get("version") == "2.1"

    config_page = client.get("/api/config")
    assert config_page.status_code == 200
    assert config_page.json().get("read_only") is True


def test_new_context_endpoints_empty_by_default(client: TestClient) -> None:
    gitops = client.get("/api/gitops").json()
    assert gitops["version"] == "2.1"
    assert gitops.get("queue_exists") is False

    sessions = client.get("/api/sessions").json()
    assert sessions["version"] == "2.1"
    assert isinstance(sessions.get("exists"), bool)
    assert isinstance(sessions.get("items"), list)

    scriptlib = client.get("/api/scriptlib").json()
    assert scriptlib["version"] == "2.1"
    assert scriptlib.get("exists") is False


def test_new_context_endpoints_populated(client: TestClient, tmp_path: Path) -> None:
    (tmp_path / ".cursor").mkdir(exist_ok=True)
    (tmp_path / ".cursor" / ".gitops-queue.json").write_text(
        json.dumps([{"action": "branch-setup", "status": "pending"}]),
        encoding="utf-8",
    )
    (tmp_path / ".cursor" / ".gitops-memory.jsonl").write_text(
        json.dumps({"operation": "merge-all", "resolution": "retry"}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / ".scriptlib").mkdir(exist_ok=True)
    (tmp_path / ".scriptlib" / "index.json").write_text(
        json.dumps({"entries": [{"name": "lint"}]}),
        encoding="utf-8",
    )
    (tmp_path / ".scriptlib" / "catalog.md").write_text("# catalog", encoding="utf-8")
    (tmp_path / ".braindrain" / "mcp-catalog" / "alpha" / "tools").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".braindrain" / "mcp-catalog" / "README.md").write_text("# mcp", encoding="utf-8")
    (tmp_path / ".braindrain" / "mcp-catalog" / "alpha" / "tools" / "ping.md").write_text(
        "# ping",
        encoding="utf-8",
    )

    client.post("/api/workspace/refresh")

    gitops = client.get("/api/gitops").json()
    assert gitops["queue_count"] == 1
    assert gitops["memory_count"] == 1

    scriptlib = client.get("/api/scriptlib").json()
    assert scriptlib["exists"] is True
    assert scriptlib["index"]["entry_count"] == 1

    catalog = client.get("/api/mcp-catalog").json()
    assert catalog["exists"] is True
    assert catalog["server_count"] >= 1


def test_agents_live_fallback_when_snapshot_bundle_empty(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "hub_config.yaml").write_text("project_name: SidecarTest\n", encoding="utf-8")
    cursor_root = tmp_path / "dotcursor"
    (cursor_root / "agents").mkdir(parents=True)
    (cursor_root / "agents" / "gitops.md").write_text("---\nmodel: fast\n---\nGitops.", encoding="utf-8")
    try:
        (tmp_path / ".cursor").symlink_to(cursor_root, target_is_directory=True)
    except OSError:
        import shutil

        shutil.copytree(cursor_root, tmp_path / ".cursor")
    paths = ensure_livingdash_runtime(tmp_path)
    auth = {"username": "admin", "password": "secret", "session_secret": "test-secret"}
    paths.auth.write_text(json.dumps(auth), encoding="utf-8")
    paths.snapshot.write_text(json.dumps({"schema_version": "1.0", "workspace_bundle": {}}), encoding="utf-8")
    ui_dist = tmp_path / "ui_dist"
    ui_dist.mkdir()
    (ui_dist / "index.html").write_text("<html></html>", encoding="utf-8")
    app = create_app(project_root=tmp_path, data_dir=paths.data, ui_dist=ui_dist, auth_config=auth)
    test_client = TestClient(app)
    test_client.post("/api/auth/login", json={"username": "admin", "password": "secret"})
    agents = test_client.get("/api/agents")
    assert agents.status_code == 200
    assert agents.json()["count"] >= 1


def test_plans_includes_cursor_plans(client: TestClient, tmp_path: Path) -> None:
    (tmp_path / ".cursor" / "plans").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".cursor" / "plans" / "alpha.plan.md").write_text(
        "---\nname: Alpha\ndisposition: active\n---\n# Alpha\n",
        encoding="utf-8",
    )
    client.post("/api/workspace/refresh")
    plans = client.get("/api/plans")
    assert plans.status_code == 200
    body = plans.json()
    assert "cursor_plans" in body
    assert any(p.get("name") == "Alpha" for p in body["cursor_plans"])


def test_workspace_refresh(client: TestClient) -> None:
    response = client.post("/api/workspace/refresh")
    assert response.status_code == 200
    assert response.json().get("ok") is True
