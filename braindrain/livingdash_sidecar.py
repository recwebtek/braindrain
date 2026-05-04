from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from braindrain.livingdash import DEFAULT_COMMANDS, DEFAULT_SERVICES, ensure_livingdash_runtime


SESSION_COOKIE = "livingdash_session"
CONTRACT_VERSION = "1.0"


class LoginPayload(BaseModel):
    username: str
    password: str


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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


def _runtime_paths(project_root: Path) -> Any:
    return ensure_livingdash_runtime(project_root)


def _read_snapshot(data_dir: Path) -> dict[str, Any]:
    return _load_json(data_dir / "snapshot.json", {})


def _read_status(data_dir: Path) -> dict[str, Any]:
    status = _load_json(data_dir / "status.json", {})
    last_refreshed_at = status.get("last_refreshed_at")
    if isinstance(last_refreshed_at, str) and last_refreshed_at:
        try:
            refreshed = datetime.fromisoformat(last_refreshed_at.replace("Z", "+00:00"))
            status["refresh_age_seconds"] = max(0, int((datetime.now(UTC) - refreshed).total_seconds()))
        except ValueError:
            status["refresh_age_seconds"] = int(status.get("refresh_age_seconds", 0) or 0)
    return status


def _read_history(paths: Any) -> dict[str, Any]:
    return _load_json(paths.command_history, {"schema_version": CONTRACT_VERSION, "entries": []})


def _write_history(paths: Any, payload: dict[str, Any]) -> None:
    _save_json(paths.command_history, payload)


def _read_process_state(paths: Any) -> dict[str, Any]:
    return _load_json(paths.process_state, {"schema_version": CONTRACT_VERSION, "services": {}})


def _write_process_state(paths: Any, payload: dict[str, Any]) -> None:
    _save_json(paths.process_state, payload)


def _read_telemetry_export(paths: Any) -> dict[str, Any]:
    return _load_json(paths.telemetry_export, {"schema_version": CONTRACT_VERSION, "exports": []})


def _write_telemetry_export(paths: Any, payload: dict[str, Any]) -> None:
    _save_json(paths.telemetry_export, payload)


def _read_commands(paths: Any) -> dict[str, Any]:
    payload = _load_json(paths.commands_config, DEFAULT_COMMANDS)
    commands = payload.get("commands")
    if not isinstance(commands, list):
        commands = DEFAULT_COMMANDS["commands"]
    valid = []
    for item in commands:
        if not isinstance(item, dict):
            continue
        command = item.get("command")
        if not isinstance(command, list) or not all(isinstance(part, str) and part for part in command):
            continue
        command_id = str(item.get("id", "")).strip()
        label = str(item.get("label", "")).strip()
        if not command_id or not label:
            continue
        valid.append(
            {
                "id": command_id,
                "label": label,
                "category": str(item.get("category", "general")),
                "description": str(item.get("description", "")),
                "command": command,
                "cwd": str(item.get("cwd", ".")),
                "timeout_seconds": int(item.get("timeout_seconds", 120)),
            }
        )
    return {"schema_version": str(payload.get("schema_version", CONTRACT_VERSION)), "commands": valid}


def _read_services(paths: Any) -> dict[str, Any]:
    payload = _load_json(paths.services_config, DEFAULT_SERVICES)
    services = payload.get("services")
    if not isinstance(services, list):
        services = DEFAULT_SERVICES["services"]
    valid = []
    for item in services:
        if not isinstance(item, dict):
            continue
        service_id = str(item.get("id", "")).strip()
        name = str(item.get("name", "")).strip()
        if not service_id or not name:
            continue
        start = item.get("start")
        if start is not None and (not isinstance(start, list) or not all(isinstance(part, str) and part for part in start)):
            start = None
        allowed_actions = item.get("allowed_actions") or []
        valid.append(
            {
                "id": service_id,
                "name": name,
                "description": str(item.get("description", "")),
                "cwd": str(item.get("cwd", ".")),
                "start": start,
                "open_target": item.get("open_target"),
                "healthcheck_url": item.get("healthcheck_url"),
                "allowed_actions": [str(action) for action in allowed_actions if isinstance(action, str)],
            }
        )
    return {"schema_version": str(payload.get("schema_version", CONTRACT_VERSION)), "services": valid}


def _resolve_cwd(project_root: Path, relative_cwd: str) -> Path:
    candidate = (project_root / relative_cwd).resolve()
    try:
        candidate.relative_to(project_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Configured cwd escapes project root") from exc
    return candidate


def _safe_run(project_root: Path, command: list[str], *, cwd: str = ".", timeout_seconds: int = 120) -> dict[str, Any]:
    started = time.perf_counter()
    run_cwd = _resolve_cwd(project_root, cwd)
    try:
        result = subprocess.run(
            command,
            cwd=run_cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout[-5000:],
            "stderr": result.stderr[-3000:],
            "duration_ms": duration_ms,
        }
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        return {
            "ok": False,
            "returncode": -1,
            "stdout": (exc.stdout or "")[-5000:],
            "stderr": ((exc.stderr or "") + "\nCommand timed out.")[-3000:],
            "duration_ms": duration_ms,
        }


def _is_pid_running(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _check_url(url: str | None) -> bool:
    if not url:
        return False
    try:
        with urlopen(url, timeout=1.5) as response:
            return int(getattr(response, "status", 200)) < 500
    except (URLError, ValueError, TimeoutError):
        return False


def _open_target(target: str) -> tuple[bool, str]:
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, "Opened target"
    except Exception as exc:
        return False, f"Failed to open target: {exc}"


def _record_history(paths: Any, entry: dict[str, Any]) -> dict[str, Any]:
    history = _read_history(paths)
    entries = history.get("entries", [])
    if not isinstance(entries, list):
        entries = []
    entries.insert(0, entry)
    history["entries"] = entries[:25]
    history["updated_at"] = _now_iso()
    _write_history(paths, history)
    return history


def _git_summary(project_root: Path) -> dict[str, Any]:
    status = _safe_run(project_root, ["git", "status", "--porcelain=v1", "--branch"], cwd=".")
    lines = [line for line in status["stdout"].splitlines() if line.strip()]
    branch = "unknown"
    ahead = 0
    behind = 0
    staged = 0
    unstaged = 0
    untracked = 0

    if lines and lines[0].startswith("## "):
        branch_line = lines.pop(0)[3:]
        branch = branch_line.split("...", 1)[0].strip() or branch
        if "ahead " in branch_line:
            try:
                ahead = int(branch_line.split("ahead ", 1)[1].split("]", 1)[0].split(",", 1)[0])
            except Exception:
                ahead = 0
        if "behind " in branch_line:
            try:
                behind = int(branch_line.split("behind ", 1)[1].split("]", 1)[0].split(",", 1)[0])
            except Exception:
                behind = 0

    for line in lines:
        if line.startswith("??"):
            untracked += 1
            continue
        x = line[:1]
        y = line[1:2]
        if x and x != " ":
            staged += 1
        if y and y != " ":
            unstaged += 1

    commits_raw = _safe_run(
        project_root,
        ["git", "log", "--max-count=5", "--pretty=format:%h%x1f%s%x1f%cr"],
        cwd=".",
        timeout_seconds=30,
    )
    commits = []
    for line in commits_raw["stdout"].splitlines():
        parts = line.split("\x1f")
        if len(parts) == 3:
            commits.append({"hash": parts[0], "subject": parts[1], "age": parts[2]})

    return {
        "branch": branch,
        "dirty": staged > 0 or unstaged > 0 or untracked > 0,
        "ahead": ahead,
        "behind": behind,
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "recent_commits": commits,
        "last_checked_at": _now_iso(),
    }


def _telemetry_summary(snapshot: dict[str, Any], status: dict[str, Any], history: dict[str, Any]) -> dict[str, Any]:
    signals = snapshot.get("workspace_signals", {}) or {}
    mcp = signals.get("mcp_tools", {}) or {}
    agents = signals.get("agents", {}) or {}
    insights = snapshot.get("insights", {}) or {}
    entries = history.get("entries", []) if isinstance(history.get("entries"), list) else []
    recent_events = [
        {
            "kind": "command",
            "label": entry.get("label", "Command"),
            "status": entry.get("status", "unknown"),
            "detail": f"exit {entry.get('returncode', 'n/a')} in {entry.get('duration_ms', 0)}ms",
            "time": entry.get("finished_at", ""),
        }
        for entry in entries[:8]
    ]
    return {
        "version": CONTRACT_VERSION,
        "summary": {
            "active_tools": int(mcp.get("count", 0) or 0),
            "agents_online": int(agents.get("count", 0) or 0),
            "refresh_age_seconds": int(status.get("refresh_age_seconds", 0) or 0),
            "token_saving_active": bool(insights.get("token_saving_active", False)),
            "env_drift": int(insights.get("env_drift", 0) or 0),
            "recent_action_count": len(entries),
        },
        "events": recent_events,
        "updated_at": _now_iso(),
    }


def _service_state(paths: Any, service: dict[str, Any]) -> dict[str, Any]:
    state = _read_process_state(paths).get("services", {}).get(service["id"], {})
    pid = state.get("pid")
    running = _is_pid_running(pid)
    healthy = _check_url(service.get("healthcheck_url")) if running else False
    return {
        "id": service["id"],
        "name": service["name"],
        "description": service.get("description", ""),
        "cwd": service.get("cwd", "."),
        "allowed_actions": service.get("allowed_actions", []),
        "status": "running" if running else "stopped",
        "healthy": healthy if running else False,
        "pid": pid if running else None,
        "open_target": service.get("open_target"),
        "healthcheck_url": service.get("healthcheck_url"),
        "last_started_at": state.get("last_started_at"),
        "last_stopped_at": state.get("last_stopped_at"),
        "last_exit_code": state.get("last_exit_code"),
    }


def _list_services(paths: Any) -> dict[str, Any]:
    config = _read_services(paths)
    return {
        "version": CONTRACT_VERSION,
        "items": [_service_state(paths, service) for service in config["services"]],
        "updated_at": _now_iso(),
    }


def _find_command(paths: Any, command_id: str) -> dict[str, Any] | None:
    for command in _read_commands(paths)["commands"]:
        if command["id"] == command_id:
            return command
    return None


def _find_service(paths: Any, service_id: str) -> dict[str, Any] | None:
    for service in _read_services(paths)["services"]:
        if service["id"] == service_id:
            return service
    return None


def _build_overview(project_root: Path, paths: Any) -> dict[str, Any]:
    snapshot = _read_snapshot(paths.data)
    status = _read_status(paths.data)
    git = _git_summary(project_root)
    services = _list_services(paths)
    history = _read_history(paths)
    telemetry = _telemetry_summary(snapshot, status, history)
    workspace = snapshot.get("workspace", {}) or {}
    repo = snapshot.get("repo", {}) or {}
    narrative = snapshot.get("narrative", {}) or {}

    kpis = [
        {"label": "Commands run", "value": str(len(history.get("entries", []) or [])), "tone": "violet"},
        {"label": "Services running", "value": str(sum(1 for item in services["items"] if item["status"] == "running")), "tone": "cyan"},
        {"label": "Git changes", "value": str(git["staged"] + git["unstaged"] + git["untracked"]), "tone": "amber"},
        {"label": "Active MCP tools", "value": str(telemetry["summary"]["active_tools"]), "tone": "emerald"},
    ]
    recent_activity = [
        {
            "label": entry.get("label", "Command"),
            "detail": f"{entry.get('status', 'unknown')} · exit {entry.get('returncode', 'n/a')}",
            "tone": "emerald" if entry.get("ok") else "rose",
        }
        for entry in (history.get("entries", []) or [])[:4]
    ]
    shortcuts = [
        {"id": "commands", "label": "Open commands", "detail": "Run approved workspace commands.", "tone": "violet"},
        {"id": "git", "label": "Open git status", "detail": "Inspect branch drift and guarded sync actions.", "tone": "cyan"},
        {"id": "processes", "label": "Open processes", "detail": "Manage repo-scoped services only.", "tone": "amber"},
        {"id": "telemetry", "label": "Open telemetry", "detail": "Inspect recent runtime signals and exports.", "tone": "emerald"},
    ]

    return {
        "version": CONTRACT_VERSION,
        "workspace": {
            "name": workspace.get("name", project_root.name),
            "project_name": repo.get("project_name", project_root.name),
            "branch": git["branch"],
        },
        "repo_brief": {
            "title": "Workspace overview",
            "summary": narrative.get("repo_brief", "No repository brief available."),
            "entrypoint": (narrative.get("key_modules") or [{}])[0].get("path", "unknown"),
            "posture": "Operational shell with guarded local actions",
        },
        "facts": [
            {"label": "Workspace", "value": workspace.get("name", project_root.name), "tone": "violet"},
            {"label": "Project", "value": repo.get("project_name", project_root.name), "tone": "cyan"},
            {"label": "Branch", "value": git["branch"], "tone": "emerald"},
            {"label": "Dirty", "value": "Yes" if git["dirty"] else "No", "tone": "amber" if git["dirty"] else "emerald"},
            {"label": "Tools", "value": str(telemetry["summary"]["active_tools"]), "tone": "violet"},
        ],
        "systems": [
            {
                "label": "Git",
                "value": "dirty" if git["dirty"] else "clean",
                "tone": "amber" if git["dirty"] else "emerald",
                "detail": f"ahead {git['ahead']} · behind {git['behind']}",
            },
            {
                "label": "Processes",
                "value": str(sum(1 for item in services["items"] if item["status"] == "running")),
                "tone": "cyan",
                "detail": "Repo-scoped services available to the dashboard.",
            },
            {
                "label": "Telemetry",
                "value": "active" if telemetry["summary"]["token_saving_active"] else "idle",
                "tone": "violet",
                "detail": f"refresh age {telemetry['summary']['refresh_age_seconds']}s",
            },
        ],
        "startup_flow": [
            {"label": step.get("label", "step"), "detail": f"id: {step.get('id', 'unknown')}", "tone": "cyan"}
            for step in ((narrative.get("startup_flow", {}) or {}).get("steps", []) or [])
            if isinstance(step, dict)
        ],
        "kpis": kpis,
        "recent_activity": recent_activity,
        "shortcuts": shortcuts,
        "map_access": {
            "label": "Map access",
            "description": "The bounded systems map remains a secondary drill-down, not the primary workspace.",
            "cta": "OPEN SYSTEM MAP",
        },
        "updated_at": _now_iso(),
    }


def _commands_payload(paths: Any) -> dict[str, Any]:
    registry = _read_commands(paths)
    history = _read_history(paths)
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in registry["commands"]:
        groups.setdefault(item["category"], []).append(
            {
                "id": item["id"],
                "label": item["label"],
                "description": item["description"],
                "cwd": item["cwd"],
                "timeout_seconds": item["timeout_seconds"],
            }
        )
    return {
        "version": CONTRACT_VERSION,
        "groups": [{"id": category, "label": category.replace("_", " ").title(), "items": items} for category, items in groups.items()],
        "history": history.get("entries", []),
        "updated_at": _now_iso(),
    }


def _git_payload(project_root: Path) -> dict[str, Any]:
    git = _git_summary(project_root)
    return {
        "version": CONTRACT_VERSION,
        "summary": git,
        "actions": [
            {"id": "fetch", "label": "Fetch", "description": "Run git fetch --all --prune."},
            {"id": "pull", "label": "Pull", "description": "Run git pull --ff-only on the current branch."},
        ],
        "updated_at": _now_iso(),
    }


def _make_action_response(*, ok: bool, status: str, message: str, payload_key: str, payload: Any) -> dict[str, Any]:
    return {
        "ok": ok,
        "status": status,
        "message": message,
        "updated_at": _now_iso(),
        payload_key: payload,
    }


def _run_command(project_root: Path, paths: Any, command_id: str) -> dict[str, Any]:
    command = _find_command(paths, command_id)
    if not command:
        raise HTTPException(status_code=404, detail="Unknown command")

    result = _safe_run(
        project_root,
        command["command"],
        cwd=command["cwd"],
        timeout_seconds=command["timeout_seconds"],
    )
    entry = {
        "id": command["id"],
        "label": command["label"],
        "category": command["category"],
        "cwd": command["cwd"],
        "ok": result["ok"],
        "status": "success" if result["ok"] else "failed",
        "returncode": result["returncode"],
        "duration_ms": result["duration_ms"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "finished_at": _now_iso(),
    }
    _record_history(paths, entry)
    return _make_action_response(
        ok=result["ok"],
        status=entry["status"],
        message=f"{command['label']} completed" if result["ok"] else f"{command['label']} failed",
        payload_key="command_run",
        payload=entry,
    )


def _git_action(project_root: Path, action: str) -> dict[str, Any]:
    if action == "fetch":
        result = _safe_run(project_root, ["git", "fetch", "--all", "--prune"], cwd=".", timeout_seconds=120)
    elif action == "pull":
        branch = _git_summary(project_root)["branch"]
        result = _safe_run(project_root, ["git", "pull", "--ff-only", "origin", branch], cwd=".", timeout_seconds=120)
    else:
        raise HTTPException(status_code=400, detail="Unsupported git action")
    payload = {
        "action": action,
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "duration_ms": result["duration_ms"],
    }
    return _make_action_response(
        ok=result["ok"],
        status="success" if result["ok"] else "failed",
        message=f"git {action} completed" if result["ok"] else f"git {action} failed",
        payload_key="git_action",
        payload=payload,
    )


def _start_service(project_root: Path, paths: Any, service: dict[str, Any]) -> dict[str, Any]:
    if "start" not in service.get("allowed_actions", []):
        raise HTTPException(status_code=403, detail="Start is not allowed for this service")
    if not service.get("start"):
        raise HTTPException(status_code=400, detail="Service has no start command")
    state = _read_process_state(paths)
    services_state = state.get("services", {})
    current = services_state.get(service["id"], {})
    if _is_pid_running(current.get("pid")):
        return _make_action_response(
            ok=True,
            status="noop",
            message=f"{service['name']} is already running",
            payload_key="service",
            payload=_service_state(paths, service),
        )

    proc = subprocess.Popen(
        service["start"],
        cwd=_resolve_cwd(project_root, service["cwd"]),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    services_state[service["id"]] = {
        "pid": proc.pid,
        "last_started_at": _now_iso(),
        "last_exit_code": None,
    }
    state["schema_version"] = CONTRACT_VERSION
    state["services"] = services_state
    _write_process_state(paths, state)
    return _make_action_response(
        ok=True,
        status="success",
        message=f"{service['name']} started",
        payload_key="service",
        payload=_service_state(paths, service),
    )


def _stop_service(paths: Any, service: dict[str, Any]) -> dict[str, Any]:
    if "stop" not in service.get("allowed_actions", []):
        raise HTTPException(status_code=403, detail="Stop is not allowed for this service")
    state = _read_process_state(paths)
    services_state = state.get("services", {})
    current = services_state.get(service["id"], {})
    pid = current.get("pid")
    if not _is_pid_running(pid):
        current.update({"pid": None, "last_stopped_at": _now_iso()})
        services_state[service["id"]] = current
        state["services"] = services_state
        _write_process_state(paths, state)
        return _make_action_response(
            ok=True,
            status="noop",
            message=f"{service['name']} is already stopped",
            payload_key="service",
            payload=_service_state(paths, service),
        )

    try:
        os.kill(int(pid), 15)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to stop service: {exc}") from exc
    current.update({"pid": None, "last_stopped_at": _now_iso()})
    services_state[service["id"]] = current
    state["services"] = services_state
    _write_process_state(paths, state)
    return _make_action_response(
        ok=True,
        status="success",
        message=f"{service['name']} stopped",
        payload_key="service",
        payload=_service_state(paths, service),
    )


def _open_service(paths: Any, service: dict[str, Any]) -> dict[str, Any]:
    if "open" not in service.get("allowed_actions", []):
        raise HTTPException(status_code=403, detail="Open is not allowed for this service")
    target = service.get("open_target")
    if not isinstance(target, str) or not target:
        raise HTTPException(status_code=400, detail="Service has no open target")
    ok, message = _open_target(target)
    return _make_action_response(
        ok=ok,
        status="success" if ok else "failed",
        message=message,
        payload_key="service",
        payload=_service_state(paths, service),
    )


def create_app(
    *,
    project_root: Path,
    data_dir: Path,
    ui_dist: Path,
    auth_config: dict[str, str],
) -> FastAPI:
    paths = _runtime_paths(project_root)
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
        response = JSONResponse({"ok": True, "authenticated": True, "userName": auth_config.get("username")})
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

    @app.get("/api/overview")
    def overview(request: Request) -> dict[str, Any]:
        _require_auth(request, auth_config)
        return _build_overview(project_root, paths)

    @app.get("/api/commands")
    def commands(request: Request) -> dict[str, Any]:
        _require_auth(request, auth_config)
        return _commands_payload(paths)

    @app.get("/api/commands/history")
    def commands_history(request: Request) -> dict[str, Any]:
        _require_auth(request, auth_config)
        history = _read_history(paths)
        return {"version": CONTRACT_VERSION, "items": history.get("entries", []), "updated_at": _now_iso()}

    @app.post("/api/commands/run/{command_id}")
    def run_command(command_id: str, request: Request) -> dict[str, Any]:
        _require_auth(request, auth_config)
        return _run_command(project_root, paths, command_id)

    @app.get("/api/git")
    def git_status(request: Request) -> dict[str, Any]:
        _require_auth(request, auth_config)
        return _git_payload(project_root)

    @app.post("/api/git/fetch")
    def git_fetch(request: Request) -> dict[str, Any]:
        _require_auth(request, auth_config)
        return _git_action(project_root, "fetch")

    @app.post("/api/git/pull")
    def git_pull(request: Request) -> dict[str, Any]:
        _require_auth(request, auth_config)
        return _git_action(project_root, "pull")

    @app.get("/api/processes")
    def processes(request: Request) -> dict[str, Any]:
        _require_auth(request, auth_config)
        return _list_services(paths)

    @app.post("/api/processes/{service_id}/start")
    def start_process(service_id: str, request: Request) -> dict[str, Any]:
        _require_auth(request, auth_config)
        service = _find_service(paths, service_id)
        if not service:
            raise HTTPException(status_code=404, detail="Unknown service")
        return _start_service(project_root, paths, service)

    @app.post("/api/processes/{service_id}/stop")
    def stop_process(service_id: str, request: Request) -> dict[str, Any]:
        _require_auth(request, auth_config)
        service = _find_service(paths, service_id)
        if not service:
            raise HTTPException(status_code=404, detail="Unknown service")
        return _stop_service(paths, service)

    @app.post("/api/processes/{service_id}/open")
    def open_process(service_id: str, request: Request) -> dict[str, Any]:
        _require_auth(request, auth_config)
        service = _find_service(paths, service_id)
        if not service:
            raise HTTPException(status_code=404, detail="Unknown service")
        return _open_service(paths, service)

    @app.get("/api/telemetry")
    def telemetry(request: Request) -> dict[str, Any]:
        _require_auth(request, auth_config)
        snapshot = _read_snapshot(data_dir)
        status = _read_status(data_dir)
        history = _read_history(paths)
        return _telemetry_summary(snapshot, status, history)

    @app.get("/api/telemetry/export")
    def telemetry_export(request: Request) -> dict[str, Any]:
        _require_auth(request, auth_config)
        snapshot = _read_snapshot(data_dir)
        status = _read_status(data_dir)
        history = _read_history(paths)
        telemetry = _telemetry_summary(snapshot, status, history)
        cache = _read_telemetry_export(paths)
        exports = cache.get("exports", [])
        if not isinstance(exports, list):
            exports = []
        record = {"created_at": _now_iso(), "telemetry": telemetry}
        exports.insert(0, record)
        cache["schema_version"] = CONTRACT_VERSION
        cache["exports"] = exports[:10]
        _write_telemetry_export(paths, cache)
        return {
            "version": CONTRACT_VERSION,
            "export": record,
            "updated_at": _now_iso(),
        }

    @app.get("/api/snapshot")
    def snapshot(request: Request) -> dict[str, Any]:
        _require_auth(request, auth_config)
        overview_payload = _build_overview(project_root, paths)
        return {
            "workspaceName": overview_payload["workspace"]["name"],
            "projectName": overview_payload["workspace"]["project_name"],
            "branch": overview_payload["workspace"]["branch"],
            "repoBrief": overview_payload["repo_brief"],
            "facts": overview_payload["facts"],
            "systems": overview_payload["systems"],
            "startupFlow": overview_payload["startup_flow"],
            "actions": overview_payload["shortcuts"],
            "mapAccess": overview_payload["map_access"],
        }

    @app.get("/api/live")
    def live(request: Request) -> dict[str, Any]:
        _require_auth(request, auth_config)
        telemetry_payload = _telemetry_summary(_read_snapshot(data_dir), _read_status(data_dir), _read_history(paths))
        summary = telemetry_payload["summary"]
        events = telemetry_payload["events"]
        return {
            "refreshedAt": f"{summary['refresh_age_seconds']}s ago" if summary["refresh_age_seconds"] else "just now",
            "activeTools": f"{summary['active_tools']} active",
            "agentsOnline": f"{summary['agents_online']} online",
            "insights": [
                {
                    "label": "Token saving",
                    "value": "on" if summary["token_saving_active"] else "off",
                    "detail": "Token-saving telemetry from the latest snapshot.",
                    "tone": "emerald" if summary["token_saving_active"] else "rose",
                },
                {
                    "label": "Env drift",
                    "value": str(summary["env_drift"]),
                    "detail": "Configuration drift count from the snapshot insights.",
                    "tone": "emerald" if summary["env_drift"] == 0 else "amber",
                },
                {
                    "label": "Recent actions",
                    "value": str(summary["recent_action_count"]),
                    "detail": "Approved command runs captured by the dashboard.",
                    "tone": "violet",
                },
            ],
            "liveCounters": [
                {"label": "Tools", "value": str(summary["active_tools"]), "tone": "emerald"},
                {"label": "Agents", "value": str(summary["agents_online"]), "tone": "cyan"},
                {"label": "Actions", "value": str(summary["recent_action_count"]), "tone": "violet"},
                {"label": "Refresh", "value": f"{summary['refresh_age_seconds']}s", "tone": "amber"},
            ],
            "events": events,
        }

    @app.get("/api/actions")
    def actions(request: Request) -> dict[str, Any]:
        _require_auth(request, auth_config)
        return {"actions": _build_overview(project_root, paths)["shortcuts"]}

    @app.post("/api/actions/run/{action_id}")
    def run_action(action_id: str, request: Request) -> dict[str, Any]:
        _require_auth(request, auth_config)
        if action_id == "commands":
            return _make_action_response(ok=True, status="view_only", message="Open the Commands tab.", payload_key="action", payload={"id": action_id})
        return _make_action_response(ok=False, status="view_only", message="Legacy action is view-only in MVP.", payload_key="action", payload={"id": action_id})

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
        <html lang="en">
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>LivingDash | UI Pending</title>
            <style>
              :root {
                --bg: #120916;
                --card-bg: #1d1124;
                --text: #f6eeff;
                --text-dim: #b8a9c3;
                --accent: #d2a8ff;
                --border: #3c2a4d;
              }
              body {
                font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
                background: var(--bg);
                color: var(--text);
                margin: 0;
                display: flex;
                align-items: center;
                justify-content: center;
                min-height: 100vh;
                line-height: 1.6;
              }
              .card {
                background: var(--card-bg);
                border: 1px solid var(--border);
                border-radius: 12px;
                padding: 32px;
                max-width: 500px;
                width: 90%;
                box-shadow: 0 20px 40px rgba(0,0,0,0.4);
              }
              h1 {
                margin-top: 0;
                font-size: 24px;
                color: var(--accent);
                display: flex;
                align-items: center;
                gap: 12px;
              }
              p { color: var(--text-dim); margin-bottom: 24px; }
              code {
                background: #000;
                padding: 12px;
                border-radius: 6px;
                display: block;
                font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
                font-size: 13px;
                color: #e6edf3;
                overflow-x: auto;
                border: 1px solid var(--border);
              }
              .label {
                font-size: 11px;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                font-weight: 600;
                color: var(--accent);
                margin-bottom: 8px;
                display: block;
              }
            </style>
          </head>
          <body>
            <div class="card">
              <h1><span aria-hidden="true">🎨</span> LivingDash</h1>
              <p>The dashboard interface is ready to be built. Follow these steps to generate the UI bundle:</p>
              <span class="label">Required Actions</span>
              <code>cd .ldash/ui<br>pnpm install<br>pnpm run build</code>
              <p style="margin-top: 24px; font-size: 14px;">Once complete, refresh this page to access your workspace dashboard.</p>
            </div>
          </body>
        </html>
        """
        return HTMLResponse(fallback)

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7337)
    args = parser.parse_args()

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
