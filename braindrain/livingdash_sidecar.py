from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


SESSION_COOKIE = "livingdash_session"


class LoginPayload(BaseModel):
    username: str
    password: str


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _is_authenticated(request: Request, auth_config: dict[str, str]) -> bool:
    return request.cookies.get(SESSION_COOKIE) == auth_config.get("session_secret")


def _require_auth(request: Request, auth_config: dict[str, str]) -> None:
    if not _is_authenticated(request, auth_config):
        raise HTTPException(status_code=401, detail="Authentication required")


def _read_snapshot(data_dir: Path) -> dict[str, Any]:
    return _load_json(data_dir / "snapshot.json", {})


def _read_status(data_dir: Path) -> dict[str, Any]:
    return _load_json(data_dir / "status.json", {})


def _tone_from_state(value: Any, *, positive: set[str] | None = None, negative: set[str] | None = None) -> str:
    text = str(value or "").strip().lower()
    positive = positive or {"ok", "on", "hot", "clean", "active", "true"}
    negative = negative or {"error", "off", "failed", "dirty", "down", "false", "blocked"}
    if any(token in text for token in negative):
        return "rose"
    if any(token in text for token in positive):
        return "emerald"
    return "cyan"


def _to_ui_snapshot(raw: dict[str, Any]) -> dict[str, Any]:
    workspace = raw.get("workspace", {}) or {}
    repo = raw.get("repo", {}) or {}
    signals = raw.get("workspace_signals", {}) or {}
    narrative = raw.get("narrative", {}) or {}
    startup = (narrative.get("startup_flow", {}) or {}).get("steps", []) or []
    key_modules = narrative.get("key_modules", []) or []
    git = signals.get("git", {}) or {}
    mcp = signals.get("mcp_tools", {}) or {}
    agents = signals.get("agents", {}) or {}
    env_files = signals.get("env_files", []) or []
    insights = raw.get("insights", {}) or {}
    map_summary = raw.get("map_summary", {}) or {}

    branch = git.get("branch") or "unknown"
    dirty = git.get("dirty")
    git_state = "dirty" if dirty is True else ("clean" if dirty is False else "unknown")
    entrypoint = key_modules[0]["path"] if key_modules and isinstance(key_modules[0], dict) else "unknown"

    systems = [
        {
            "label": "Workspace",
            "value": workspace.get("name", "unknown"),
            "tone": "blue",
            "detail": f"Root: {workspace.get('root', 'unknown')}",
        },
        {
            "label": "MCP",
            "value": f"{mcp.get('count', 0)} active",
            "tone": "cyan",
            "detail": "Hot-loaded MCP tools available to the runtime.",
        },
        {
            "label": "Env",
            "value": f"{len(env_files)} files",
            "tone": "amber" if env_files else "rose",
            "detail": "Environment files detected in workspace root.",
        },
        {
            "label": "Git",
            "value": git_state,
            "tone": _tone_from_state(git_state, positive={"clean"}, negative={"dirty"}),
            "detail": f"Branch: {branch}",
        },
        {
            "label": "Agents",
            "value": str(agents.get("count", 0)),
            "tone": "violet",
            "detail": "Detected local Cursor agent definitions.",
        },
        {
            "label": "Risk",
            "value": "low" if int(insights.get("env_drift", 0) or 0) == 0 else "elevated",
            "tone": "emerald" if int(insights.get("env_drift", 0) or 0) == 0 else "rose",
            "detail": "Derived from env drift and workspace health indicators.",
        },
    ]

    return {
        "workspaceName": workspace.get("name", "workspace"),
        "projectName": repo.get("project_name", "LivingDash"),
        "branch": branch,
        "repoBrief": {
            "title": "What this repo does",
            "summary": narrative.get("repo_brief", "No repository brief available."),
            "entrypoint": entrypoint,
            "posture": "Snapshot-first with live workspace signals",
        },
        "facts": [
            {"label": "Workspace", "value": workspace.get("name", "unknown"), "tone": "blue"},
            {"label": "Project", "value": repo.get("project_name", "unknown"), "tone": "cyan"},
            {"label": "MCP", "value": f"{mcp.get('count', 0)} active", "tone": "emerald"},
            {"label": "Branch", "value": branch, "tone": "violet"},
            {"label": "Agents", "value": str(agents.get("count", 0)), "tone": "amber"},
            {"label": "Blockers", "value": "0", "tone": "rose"},
        ],
        "systems": systems,
        "startupFlow": [
            {
                "label": step.get("label", "step"),
                "detail": f"id: {step.get('id', 'unknown')}",
                "tone": "blue" if idx == 0 else "cyan",
            }
            for idx, step in enumerate(startup)
            if isinstance(step, dict)
        ],
        "actions": [
            {"label": action.get("label", "Action"), "detail": f"kind: {action.get('kind', 'view')}", "tone": "blue"}
            for action in (raw.get("actions", []) or [])
            if isinstance(action, dict)
        ],
        "mapAccess": {
            "label": "Bounded 2D systems map",
            "description": "Secondary map view for drilling into repo structure and hotspots.",
            "nodes": str(map_summary.get("nodes", 0)),
            "edges": str(max(0, int(map_summary.get("nodes", 0) or 0) - 1)),
            "hotspots": str(map_summary.get("hotspots", 0)),
            "cta": "OPEN SYSTEM MAP",
        },
    }


def _to_ui_live(raw: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    signals = raw.get("workspace_signals", {}) or {}
    insights = raw.get("insights", {}) or {}
    mcp = signals.get("mcp_tools", {}) or {}
    agents = signals.get("agents", {}) or {}
    git = signals.get("git", {}) or {}
    refresh_age = status.get("refresh_age_seconds", 0)

    env_drift = int(insights.get("env_drift", 0) or 0)
    token_saving = bool(insights.get("token_saving_active", False))

    return {
        "refreshedAt": f"{refresh_age}s ago" if refresh_age else "just now",
        "activeTools": f"{mcp.get('count', 0)} active",
        "agentsOnline": f"{agents.get('count', 0)} online",
        "insights": [
            {
                "label": "Token saving",
                "value": "on" if token_saving else "off",
                "detail": "Telemetry indicates token-saving optimization status.",
                "tone": "emerald" if token_saving else "rose",
            },
            {
                "label": "Env drift",
                "value": str(env_drift),
                "detail": "Detected environment configuration drift count.",
                "tone": "emerald" if env_drift == 0 else "amber",
            },
            {
                "label": "Git state",
                "value": "dirty" if git.get("dirty") else "clean",
                "detail": f"Current branch: {git.get('branch') or 'unknown'}",
                "tone": "amber" if git.get("dirty") else "emerald",
            },
        ],
        "liveCounters": [
            {"label": "Tools", "value": str(mcp.get("count", 0)), "tone": "emerald"},
            {"label": "Agents", "value": str(agents.get("count", 0)), "tone": "cyan"},
            {"label": "Blocks", "value": "0", "tone": "rose"},
            {"label": "Refresh", "value": f"{refresh_age}s" if refresh_age else "0s", "tone": "violet"},
        ],
    }


def create_app(
    *,
    project_root: Path,
    data_dir: Path,
    ui_dist: Path,
    auth_config: dict[str, str],
) -> FastAPI:
    app = FastAPI(title="LivingDash Sidecar", docs_url=None, redoc_url=None)

    if ui_dist.exists():
        assets_dir = ui_dist / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/auth/session")
    def session(request: Request) -> dict[str, Any]:
        return {
            "authenticated": _is_authenticated(request, auth_config),
            "userName": auth_config.get("username"),
            "username": auth_config.get("username"),
        }

    @app.post("/api/auth/login")
    def login(payload: LoginPayload) -> JSONResponse:
        if payload.username != auth_config.get("username") or payload.password != auth_config.get("password"):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        response = JSONResponse({"ok": True})
        response.set_cookie(
            SESSION_COOKIE,
            auth_config.get("session_secret", ""),
            httponly=True,
            samesite="lax",
        )
        return response

    @app.post("/api/auth/logout")
    def logout() -> JSONResponse:
        response = JSONResponse({"ok": True})
        response.delete_cookie(SESSION_COOKIE)
        return response

    @app.get("/api/snapshot")
    def snapshot(request: Request) -> dict[str, Any]:
        _require_auth(request, auth_config)
        return _to_ui_snapshot(_read_snapshot(data_dir))

    @app.get("/api/live")
    def live(request: Request) -> dict[str, Any]:
        _require_auth(request, auth_config)
        snapshot = _read_snapshot(data_dir)
        status = _read_status(data_dir)
        return _to_ui_live(snapshot, status)

    @app.get("/api/actions")
    def actions(request: Request) -> dict[str, Any]:
        _require_auth(request, auth_config)
        snapshot = _read_snapshot(data_dir)
        return {"actions": snapshot.get("actions", [])}

    @app.post("/api/actions/run/{action_id}")
    def run_action(action_id: str, request: Request) -> dict[str, Any]:
        _require_auth(request, auth_config)
        if action_id != "run_tests":
            return {"ok": False, "action_id": action_id, "status": "view_only"}
        result = subprocess.run(
            ["./.venv/bin/python", "-m", "pytest", "tests/test_livingdash.py"],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        return {
            "ok": result.returncode == 0,
            "action_id": action_id,
            "stdout": result.stdout[-2000:],
            "stderr": result.stderr[-1000:],
            "returncode": result.returncode,
        }

    @app.get("/api/map")
    def map_data(request: Request) -> dict[str, Any]:
        _require_auth(request, auth_config)
        snapshot = _read_snapshot(data_dir)
        return snapshot.get("map_summary", {})

    @app.get("/{full_path:path}")
    def index(full_path: str):
        index_file = ui_dist / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        fallback = """
        <!doctype html>
        <html>
          <head><meta charset="utf-8"><title>LivingDash</title></head>
          <body style="font-family: ui-sans-serif, system-ui; background:#06101c; color:#eef5ff; padding:40px">
            <h1>LivingDash</h1>
            <p>The UI build has not been generated yet.</p>
          </body>
        </html>
        """
        return HTMLResponse(fallback)

    return app


def _env_path(name: str) -> Path:
    value = Path(Path.cwd()) if name == "LIVINGDASH_PROJECT_ROOT" else None
    raw = value or Path(__import__("os").environ[name])
    return Path(raw).expanduser().resolve()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7337)
    args = parser.parse_args()

    import os

    project_root = Path(os.environ["LIVINGDASH_PROJECT_ROOT"]).expanduser().resolve()
    data_dir = Path(os.environ["LIVINGDASH_DATA_DIR"]).expanduser().resolve()
    ui_dist = Path(os.environ["LIVINGDASH_UI_DIST"]).expanduser().resolve()
    auth_config = _load_json(data_dir / "auth.json", {})
    if "session_secret" not in auth_config:
        auth_config["session_secret"] = os.environ.get("LIVINGDASH_SESSION_SECRET", "")

    app = create_app(
        project_root=project_root,
        data_dir=data_dir,
        ui_dist=ui_dist,
        auth_config=auth_config,
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

