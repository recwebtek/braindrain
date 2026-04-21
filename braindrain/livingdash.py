from __future__ import annotations

import json
import os
import secrets
import socket
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    server: Path
    ui: Path
    data: Path
    snapshot: Path
    status: Path
    auth: Path
    pid: Path


SERVER_SHIM = """from braindrain.livingdash_sidecar import main\n\nif __name__ == "__main__":\n    main()\n"""


def _runtime_paths(project_root: Path) -> RuntimePaths:
    root = project_root / ".ldash"
    data = root / "data"
    return RuntimePaths(
        root=root,
        server=root / "server",
        ui=root / "ui",
        data=data,
        snapshot=data / "snapshot.json",
        status=data / "status.json",
        auth=data / "auth.json",
        pid=data / "livingdash.pid",
    )


def ensure_livingdash_runtime(project_root: str | Path) -> RuntimePaths:
    project_root = Path(project_root).expanduser().resolve()
    paths = _runtime_paths(project_root)
    for path in (paths.root, paths.server, paths.ui, paths.data):
        path.mkdir(parents=True, exist_ok=True)
    app_py = paths.server / "app.py"
    if not app_py.exists():
        app_py.write_text(SERVER_SHIM, encoding="utf-8")
    return paths


def _read_project_name(project_root: Path) -> str:
    config_path = project_root / "config" / "hub_config.yaml"
    if config_path.exists():
        try:
            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
        if isinstance(data, dict):
            name = data.get("project_name")
            if isinstance(name, str) and name.strip():
                normalized = name.strip().lower()
                if normalized == "braindrain":
                    return "BrainDrain MCP"
                return name.strip()
    if project_root.name.lower() == "brain_mcp_hub":
        return "BrainDrain MCP"
    return project_root.name


def _detect_env_files(project_root: Path) -> list[dict[str, str]]:
    names = [".env", ".env.dev", ".env.prod", ".env.local", ".env.example"]
    found: list[dict[str, str]] = []
    for name in names:
        path = project_root / name
        if path.exists():
            found.append({"name": name, "path": str(path)})
    return found


def _detect_agents(project_root: Path) -> dict[str, Any]:
    agent_dir = project_root / ".cursor" / "agents"
    agents = sorted(p.stem for p in agent_dir.glob("*.md")) if agent_dir.exists() else []
    return {"count": len(agents), "items": agents}


def _detect_git_state(project_root: Path) -> dict[str, Any]:
    try:
        current_branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except Exception:
        current_branch = None

    default_branch = None
    try:
        remote_head = subprocess.run(
            ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if "/" in remote_head:
            default_branch = remote_head.split("/", 1)[1]
    except Exception:
        default_branch = None

    if not default_branch:
        try:
            has_main = subprocess.run(
                ["git", "show-ref", "--verify", "--quiet", "refs/heads/main"],
                cwd=project_root,
                check=False,
                capture_output=False,
            ).returncode == 0
            if has_main:
                default_branch = "main"
        except Exception:
            default_branch = None

    try:
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        is_dirty = bool(dirty)
    except Exception:
        is_dirty = None

    return {
        "branch": default_branch or current_branch,
        "current_branch": current_branch,
        "default_branch": default_branch,
        "dirty": is_dirty,
    }


def _detect_mcp_tools(project_root: Path) -> dict[str, Any]:
    config_path = project_root / "config" / "hub_config.yaml"
    active: list[dict[str, Any]] = []
    if config_path.exists():
        try:
            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
        for tool in (data.get("mcp_tools") or []):
            if not isinstance(tool, dict):
                continue
            name = str(tool.get("name", "")).strip()
            if not name:
                continue
            if bool(tool.get("hot", False)) or not bool(tool.get("defer_loading", True)):
                active.append({"name": name, "hot": bool(tool.get("hot", False))})
    return {"active": active, "count": len(active)}


def _read_repo_brief(project_root: Path) -> str:
    readme = project_root / "README.md"
    if readme.exists():
        lines = [line.strip() for line in readme.read_text(encoding="utf-8").splitlines()]
        prose: list[str] = []
        for line in lines:
            if not line:
                continue
            if line.startswith(("#", "|", "```", "---", "- ")):
                continue
            if line.startswith(("**Version:**", "**Last Updated:**")):
                continue
            if re.fullmatch(r"[*_`~\s-]+", line):
                continue
            prose.append(line)
        if prose:
            return " ".join(prose[:2]).strip()
    return f"{project_root.name} local dashboard snapshot."


def _compose_repo_brief(project_root: Path, mcp_tools: dict[str, Any], startup_flow: dict[str, Any]) -> str:
    readme_brief = _read_repo_brief(project_root)
    hot_tools = int(mcp_tools.get("count", 0) or 0)
    startup_steps = len((startup_flow.get("steps", []) or []))
    moving_parts = f"Moving parts: {hot_tools} active MCP tools, {startup_steps} startup stages, and signal-first telemetry."
    return f"{readme_brief} {moving_parts}"


def _detect_key_modules(project_root: Path) -> list[dict[str, str]]:
    candidates = [
        ("server", project_root / "braindrain" / "server.py"),
        ("config", project_root / "braindrain" / "config.py"),
        ("workflow_engine", project_root / "braindrain" / "workflow_engine.py"),
        ("telemetry", project_root / "braindrain" / "telemetry.py"),
    ]
    return [
        {"id": key, "path": str(path.relative_to(project_root))}
        for key, path in candidates
        if path.exists()
    ]


def _detect_startup_flow(project_root: Path) -> dict[str, Any]:
    server_file = project_root / "braindrain" / "server.py"
    text = server_file.read_text(encoding="utf-8") if server_file.exists() else ""
    step_defs = [
        ("load_config", "config = Config", "Load config"),
        ("build_registry", "registry = ToolRegistry", "Build registry"),
        ("init_telemetry", "telemetry = telemetry_from_config", "Init telemetry"),
        ("expose_mcp_tools", "@mcp.tool()", "Expose MCP tools"),
    ]
    steps = [
        {"id": step_id, "label": label}
        for step_id, marker, label in step_defs
        if marker in text
    ]
    return {"title": "Startup Flow", "steps": steps}


def _detect_map_summary(project_root: Path) -> dict[str, Any]:
    py_files = list(project_root.rglob("*.py"))
    return {
        "mode": "2d_systems_map",
        "nodes": len(py_files),
        "hotspots": min(7, len(py_files)),
        "key_modules": _detect_key_modules(project_root),
    }


def build_dashboard_snapshot(project_root: str | Path) -> dict[str, Any]:
    project_root = Path(project_root).expanduser().resolve()
    workspace_name = project_root.name
    project_name = _read_project_name(project_root)
    git = _detect_git_state(project_root)
    env_files = _detect_env_files(project_root)
    agents = _detect_agents(project_root)
    mcp_tools = _detect_mcp_tools(project_root)
    startup_flow = _detect_startup_flow(project_root)
    repo_brief = _compose_repo_brief(project_root, mcp_tools, startup_flow)

    return {
        "workspace": {"name": workspace_name, "root": str(project_root)},
        "repo": {"project_name": project_name, "path": str(project_root)},
        "workspace_signals": {
            "env_files": env_files,
            "agents": agents,
            "git": git,
            "mcp_tools": mcp_tools,
        },
        "narrative": {
            "repo_brief": repo_brief,
            "startup_flow": startup_flow,
            "key_modules": _detect_key_modules(project_root),
        },
        "insights": {
            "token_saving_active": True,
            "env_drift": 0,
            "primary_entrypoint_count": 1 if startup_flow["steps"] else 0,
        },
        "map_summary": _detect_map_summary(project_root),
        "actions": [
            {"id": "run_tests", "label": "Run tests", "kind": "command"},
            {"id": "inspect_env", "label": "Inspect env", "kind": "view"},
            {"id": "show_branches", "label": "Show branches", "kind": "view"},
            {"id": "active_tools", "label": "Active MCP tools", "kind": "view"},
        ],
    }


def _pick_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class LivingDashManager:
    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).expanduser().resolve()
        self.paths = ensure_livingdash_runtime(self.project_root)

    def _load_json(self, path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def _save_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def ensure_auth(self) -> dict[str, str]:
        auth = self._load_json(self.paths.auth, {})
        if auth.get("password"):
            return auth
        auth = {
            "username": "admin",
            "password": secrets.token_urlsafe(12),
            "session_secret": secrets.token_urlsafe(24),
        }
        self._save_json(self.paths.auth, auth)
        return auth

    def refresh(self) -> dict[str, Any]:
        snapshot = build_dashboard_snapshot(self.project_root)
        self._save_json(self.paths.snapshot, snapshot)
        status = self._load_json(self.paths.status, {})
        status.update(
            {
                "snapshot_path": str(self.paths.snapshot),
                "project_root": str(self.project_root),
                "running": bool(status.get("running", False)),
            }
        )
        self._save_json(self.paths.status, status)
        return {"ok": True, "snapshot_path": str(self.paths.snapshot)}

    def status(self) -> dict[str, Any]:
        status = self._load_json(self.paths.status, {})
        pid = status.get("pid")
        running = bool(status.get("running", False))
        if pid:
            try:
                os.kill(int(pid), 0)
            except OSError:
                running = False
        else:
            running = False
        return {
            "running": running,
            "pid": pid,
            "url": status.get("url"),
            "paths": asdict(self.paths),
        }

    def start(self) -> dict[str, Any]:
        auth = self.ensure_auth()
        self.refresh()
        port = _pick_port()
        env = os.environ.copy()
        env["LIVINGDASH_PROJECT_ROOT"] = str(self.project_root)
        env["LIVINGDASH_DATA_DIR"] = str(self.paths.data)
        env["LIVINGDASH_UI_DIST"] = str(self.paths.ui / "dist")
        env["LIVINGDASH_SESSION_SECRET"] = auth["session_secret"]
        proc = subprocess.Popen(
            [sys.executable, "-m", "braindrain.livingdash_sidecar", "--port", str(port)],
            cwd=self.project_root,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        status = {
            "running": True,
            "pid": proc.pid,
            "url": f"http://127.0.0.1:{port}",
            "project_root": str(self.project_root),
            "snapshot_path": str(self.paths.snapshot),
        }
        self.paths.pid.write_text(str(proc.pid), encoding="utf-8")
        self._save_json(self.paths.status, status)
        return {"ok": True, "url": status["url"], "pid": proc.pid, "credentials": auth}

    def stop(self) -> dict[str, Any]:
        status = self._load_json(self.paths.status, {})
        pid = status.get("pid")
        if pid:
            try:
                os.kill(int(pid), 15)
            except OSError:
                pass
        status.update({"running": False, "pid": None})
        self._save_json(self.paths.status, status)
        if self.paths.pid.exists():
            self.paths.pid.unlink()
        return {"ok": True, "stopped": True}
