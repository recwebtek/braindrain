"""Safe git-based self-update for repo-clone braindrain installs."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from braindrain import __version__

DEFAULT_BRANCH = "main"
DEFAULT_REMOTE = "origin"
FETCH_TIMEOUT_SECONDS = 60
CHECK_STALE_HOURS = 24
CHANGELOG_LIMIT = 15
DEPENDENCY_FILES = ("requirements.txt", "pyproject.toml", "uv.lock")

_HANDSHAKE = (
    '{"jsonrpc":"2.0","id":1,"method":"initialize",'
    '"params":{"protocolVersion":"2024-11-05","capabilities":{},'
    '"clientInfo":{"name":"update-test","version":"0"}}}'
)


class UpdateError(Exception):
    """Raised when update preconditions fail."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _utc_now()).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _braindrain_dir(repo_root: Path) -> Path:
    return repo_root / ".braindrain"


def _state_path(repo_root: Path) -> Path:
    return _braindrain_dir(repo_root) / "update-state.json"


def _logs_dir(repo_root: Path) -> Path:
    return _braindrain_dir(repo_root) / "update-logs"


def _run_git(
    args: list[str],
    *,
    cwd: Path,
    timeout: int = FETCH_TIMEOUT_SECONDS,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UpdateError(f"git {' '.join(args)} failed: {exc}") from exc
    if check and completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        raise UpdateError(f"git {' '.join(args)} failed: {stderr or completed.returncode}")
    return completed


def _read_version_from_pyproject_text(text: str) -> str | None:
    try:
        import tomllib
    except ModuleNotFoundError:
        match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        return match.group(1) if match else None
    parsed = tomllib.loads(text)
    version = parsed.get("project", {}).get("version")
    return str(version) if version else None


def _local_version(repo_root: Path) -> str:
    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        parsed = _read_version_from_pyproject_text(pyproject.read_text(encoding="utf-8"))
        if parsed:
            return parsed
    return __version__


def _remote_version(repo_root: Path, remote_ref: str) -> str | None:
    completed = _run_git(["show", f"{remote_ref}:pyproject.toml"], cwd=repo_root, check=False)
    if completed.returncode != 0:
        return None
    return _read_version_from_pyproject_text(completed.stdout)


def _resolve_track_branch(repo_root: Path) -> str:
    env_branch = os.environ.get("BRAINDRAIN_UPDATE_BRANCH", "").strip()
    if env_branch:
        return env_branch
    upstream = _run_git(
        ["rev-parse", "--abbrev-ref", "@{upstream}"],
        cwd=repo_root,
        check=False,
    )
    if upstream.returncode == 0:
        ref = upstream.stdout.strip()
        if ref.startswith(f"{DEFAULT_REMOTE}/"):
            return ref.split("/", 1)[1]
        if "/" in ref:
            return ref.split("/", 1)[1]
        return ref
    return DEFAULT_BRANCH


def _remote_ref(repo_root: Path, branch: str) -> str:
    return f"{DEFAULT_REMOTE}/{branch}"


def _ensure_git_repo(repo_root: Path) -> None:
    if not (repo_root / ".git").exists():
        raise UpdateError(f"Not a git repository: {repo_root}")


def _current_branch(repo_root: Path) -> str | None:
    completed = _run_git(["symbolic-ref", "--short", "HEAD"], cwd=repo_root, check=False)
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _is_dirty(repo_root: Path) -> bool:
    completed = _run_git(["status", "--porcelain"], cwd=repo_root)
    for line in completed.stdout.splitlines():
        path = line[3:].strip()
        if path == ".braindrain" or path.startswith(".braindrain/"):
            continue
        if path:
            return True
    return False


def _behind_count(repo_root: Path, remote_ref: str) -> int:
    completed = _run_git(
        ["rev-list", "--count", f"HEAD..{remote_ref}"],
        cwd=repo_root,
        check=False,
    )
    if completed.returncode != 0:
        return 0
    return int(completed.stdout.strip() or "0")


def _can_fast_forward(repo_root: Path, remote_ref: str) -> bool:
    completed = _run_git(
        ["merge-base", "--is-ancestor", "HEAD", remote_ref],
        cwd=repo_root,
        check=False,
    )
    return completed.returncode == 0


def _changelog(repo_root: Path, remote_ref: str, *, limit: int = CHANGELOG_LIMIT) -> list[str]:
    completed = _run_git(
        ["log", "--format=%s", f"HEAD..{remote_ref}"],
        cwd=repo_root,
        check=False,
    )
    if completed.returncode != 0:
        return []
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    return lines[:limit]


def _current_sha(repo_root: Path) -> str:
    return _run_git(["rev-parse", "HEAD"], cwd=repo_root).stdout.strip()


def _write_state(repo_root: Path, payload: dict[str, Any]) -> Path:
    braindir = _braindrain_dir(repo_root)
    braindir.mkdir(parents=True, exist_ok=True)
    path = _state_path(repo_root)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _append_log(repo_root: Path, event: str, payload: dict[str, Any]) -> None:
    logs = _logs_dir(repo_root)
    logs.mkdir(parents=True, exist_ok=True)
    stamp = _utc_now().strftime("%Y%m%d")
    log_path = logs / f"update-{stamp}.jsonl"
    row = {"timestamp": _iso(), "event": event, **payload}
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_update_state(repo_root: Path) -> dict[str, Any] | None:
    path = _state_path(repo_root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _state_is_stale(state: dict[str, Any] | None, *, hours: int = CHECK_STALE_HOURS) -> bool:
    if not state:
        return True
    last_check = state.get("last_check")
    if not isinstance(last_check, str) or not last_check:
        return True
    try:
        checked_at = datetime.fromisoformat(last_check.replace("Z", "+00:00"))
    except ValueError:
        return True
    return _utc_now() - checked_at > timedelta(hours=hours)


def _dependency_files_changed(repo_root: Path, from_sha: str, to_sha: str) -> bool:
    completed = _run_git(
        ["diff", "--name-only", from_sha, to_sha, "--", *DEPENDENCY_FILES],
        cwd=repo_root,
        check=False,
    )
    if completed.returncode != 0:
        return True
    return bool(completed.stdout.strip())


def _sync_dependencies(repo_root: Path) -> bool:
    venv_python = repo_root / ".venv" / "bin" / "python"
    if not venv_python.is_file():
        raise UpdateError("Missing .venv; run ./install.sh before applying updates.")
    if _command_exists("uv") and (repo_root / "pyproject.toml").is_file():
        completed = subprocess.run(
            ["uv", "sync"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or completed.stdout or "").strip()
            raise UpdateError(f"uv sync failed: {stderr or completed.returncode}")
        return True
    requirements = repo_root / "requirements.txt"
    if requirements.is_file():
        completed = subprocess.run(
            [str(venv_python), "-m", "pip", "install", "-r", str(requirements)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or completed.stdout or "").strip()
            raise UpdateError(f"pip install failed: {stderr or completed.returncode}")
        return True
    return False


def _command_exists(command: str) -> bool:
    from shutil import which

    return which(command) is not None


def _run_handshake(repo_root: Path) -> bool:
    launcher = os.environ.get(
        "BRAINDRAIN_LAUNCHER_PATH",
        str(repo_root / "config" / "braindrain"),
    )
    launcher_path = Path(launcher)
    if not launcher_path.is_file():
        return False
    try:
        completed = subprocess.run(
            [str(launcher_path)],
            input=_HANDSHAKE,
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return '"serverInfo"' in (completed.stdout or "")


def check_update(repo_root: Path | str | None = None, *, fetch: bool = True) -> dict[str, Any]:
    """Fetch (optional) and report whether the clone is behind its tracked branch."""
    root = Path(repo_root or ".").resolve()
    _ensure_git_repo(root)

    branch = _resolve_track_branch(root)
    remote_ref = _remote_ref(root, branch)
    current_branch = _current_branch(root)
    dirty = _is_dirty(root)

    error: str | None = None
    if fetch:
        try:
            _run_git(["fetch", DEFAULT_REMOTE, branch], cwd=root)
        except UpdateError as exc:
            error = str(exc)

    behind = _behind_count(root, remote_ref) if error is None else 0
    can_ff = _can_fast_forward(root, remote_ref) if error is None else False
    changelog = _changelog(root, remote_ref) if error is None and behind > 0 else []

    result: dict[str, Any] = {
        "ok": error is None,
        "repo_root": str(root),
        "track_branch": branch,
        "current_branch": current_branch,
        "remote_ref": remote_ref,
        "current_version": _local_version(root),
        "remote_version": _remote_version(root, remote_ref) if error is None else None,
        "behind": behind,
        "changelog": changelog,
        "dirty": dirty,
        "can_ff": can_ff,
        "update_available": behind > 0 and can_ff and not dirty,
        "restart_required": False,
        "error": error,
        "last_check": _iso(),
    }

    existing = load_update_state(root) or {}
    state = {
        **existing,
        "last_check": result["last_check"],
        "behind": behind,
        "remote_version": result["remote_version"],
        "current_version": result["current_version"],
        "track_branch": branch,
        "dirty": dirty,
        "can_ff": can_ff,
        "update_available": result["update_available"],
        "error": error,
    }
    _write_state(root, state)
    _append_log(root, "check", result)
    return result


def apply_update(repo_root: Path | str | None = None) -> dict[str, Any]:
    """Fast-forward pull when safe, sync deps if needed, and run handshake smoke test."""
    root = Path(repo_root or ".").resolve()
    _ensure_git_repo(root)

    check = check_update(root, fetch=True)
    if not check.get("ok"):
        raise UpdateError(check.get("error") or "update check failed")

    if check["behind"] == 0:
        result = {
            "ok": True,
            "updated": False,
            "message": "Already up to date.",
            "from_sha": _current_sha(root),
            "to_sha": _current_sha(root),
            "deps_synced": False,
            "handshake_ok": _run_handshake(root),
            "restart_required": False,
            **check,
        }
        _append_log(root, "apply", result)
        return result

    if check["dirty"]:
        raise UpdateError("Working tree has local changes; commit or stash before updating.")

    if not check["current_branch"]:
        raise UpdateError("Detached HEAD; checkout a branch before updating.")

    if not check["can_ff"]:
        raise UpdateError(
            "Cannot fast-forward; local history diverged from "
            f"{check['remote_ref']}. Resolve manually."
        )

    from_sha = _current_sha(root)
    branch = check["track_branch"]
    _run_git(["pull", "--ff-only", DEFAULT_REMOTE, branch], cwd=root)
    to_sha = _current_sha(root)

    deps_synced = False
    if _dependency_files_changed(root, from_sha, to_sha):
        deps_synced = _sync_dependencies(root)

    handshake_ok = _run_handshake(root)
    result: dict[str, Any] = {
        "ok": True,
        "updated": True,
        "message": (
            "Update applied on disk. Reconnect or restart the braindrain MCP connection "
            "so the host loads the new code and tool schemas."
        ),
        "from_sha": from_sha,
        "to_sha": to_sha,
        "deps_synced": deps_synced,
        "handshake_ok": handshake_ok,
        "restart_required": True,
        "current_version": _local_version(root),
        "remote_version": check.get("remote_version"),
        "behind": 0,
        "changelog": check.get("changelog", []),
    }

    state = {
        **(load_update_state(root) or {}),
        "last_update": _iso(),
        "last_check": _iso(),
        "behind": 0,
        "restart_required": True,
        "from_sha": from_sha,
        "to_sha": to_sha,
        "current_version": result["current_version"],
        "remote_version": result["remote_version"],
        "update_available": False,
    }
    _write_state(root, state)
    _append_log(root, "apply", result)
    return result


def maybe_background_check(repo_root: Path | str) -> bool:
    """Return True when a stale state warrants a background check (notify-only)."""
    root = Path(repo_root).resolve()
    state = load_update_state(root)
    return _state_is_stale(state)


def startup_notify_message(repo_root: Path | str) -> str | None:
    """Return a stderr notice when cached state shows updates are available."""
    state = load_update_state(Path(repo_root).resolve())
    if not state:
        return None
    behind = int(state.get("behind") or 0)
    if behind <= 0:
        return None
    return (
        f"[braindrain] Update available ({behind} commits behind). "
        "Run scripts/update_braindrain.sh apply or call apply_hub_update."
    )


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check or apply braindrain hub updates.")
    parser.add_argument(
        "mode",
        nargs="?",
        choices=("check", "apply"),
        default="check",
        help="check (default) or apply",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Path to braindrain clone (default: current directory)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress JSON stdout (still writes update-state.json)",
    )
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve()

    try:
        if args.mode == "check":
            result = check_update(root)
            if not args.quiet:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            if not result.get("ok"):
                return 1
            if result.get("behind", 0) > 0:
                return 10
            return 0
        result = apply_update(root)
        if not args.quiet:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result.get("ok") else 1
    except UpdateError as exc:
        payload = {"ok": False, "error": str(exc)}
        if not args.quiet:
            print(json.dumps(payload, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1


def main() -> None:
    raise SystemExit(_cli())


if __name__ == "__main__":
    main()
