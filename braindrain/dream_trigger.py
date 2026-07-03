"""Host-idle dream trigger evaluation (macOS HID idle, per-workspace state)."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from braindrain.config import Config
from braindrain.macos_host_idle import get_hid_idle_seconds, is_macos


def workspace_hash(repo_root: Path) -> str:
    return hashlib.sha256(str(repo_root.resolve()).encode("utf-8")).hexdigest()[:12]


def workspace_state_dir(repo_root: Path) -> Path:
    ws_hash = workspace_hash(repo_root)
    return Path("~/.braindrain/dreaming/workspaces").expanduser() / ws_hash


def launchd_label(repo_root: Path) -> str:
    return f"com.braindrain.dream-watch.{workspace_hash(repo_root)}"


def _trigger_config(dreaming_cfg: dict[str, Any]) -> dict[str, Any]:
    triggers = (
        dreaming_cfg.get("triggers") if isinstance(dreaming_cfg.get("triggers"), dict) else {}
    )
    cfg = (
        triggers.get("macos_host_idle") if isinstance(triggers.get("macos_host_idle"), dict) else {}
    )
    return cfg


def _load_state(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state_path: Path, state: dict[str, Any]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _try_acquire_lock(lock_path: Path) -> bool:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except FileExistsError:
        return False


def _release_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


def evaluate_host_idle_trigger(
    *,
    repo_root: Path,
    config_path: Path,
) -> dict[str, Any]:
    """
    One-shot host-idle evaluation for a workspace.

    Requires dreaming.triggers.macos_host_idle.enabled=true in that workspace config
    and a running launchd/manual watcher that invokes this function.
    """
    repo_root = repo_root.resolve()
    cfg = Config(config_path)
    dreaming = cfg.get("dreaming", {}) or {}
    trigger_cfg = _trigger_config(dreaming if isinstance(dreaming, dict) else {})

    if not trigger_cfg.get("enabled", False):
        return {
            "status": "disabled",
            "reason": "dreaming.triggers.macos_host_idle.enabled is false",
            "workspace": str(repo_root),
        }

    if not is_macos():
        return {
            "status": "unsupported_platform",
            "reason": "host idle trigger is macOS-only",
            "workspace": str(repo_root),
        }

    idle_seconds = get_hid_idle_seconds()
    if idle_seconds is None:
        return {
            "status": "idle_probe_failed",
            "workspace": str(repo_root),
        }

    threshold = float(trigger_cfg.get("idle_threshold_seconds", 300) or 300)
    cooldown_minutes = float(trigger_cfg.get("cooldown_minutes", 60) or 60)
    mode = str(trigger_cfg.get("mode", "full") or "full")
    bypass_quiet = bool(trigger_cfg.get("bypass_session_quiet", True))

    state_dir = workspace_state_dir(repo_root)
    state_path = state_dir / "host-idle-state.json"
    lock_path = state_dir / "host-idle.lock"
    now = time.time()

    state = _load_state(state_path)
    dreamed_this_streak = bool(state.get("dreamed_this_idle_streak", False))
    last_dream_at = float(state.get("last_dream_at", 0) or 0)

    base_result: dict[str, Any] = {
        "workspace": str(repo_root),
        "workspace_hash": workspace_hash(repo_root),
        "idle_seconds": round(idle_seconds, 3),
        "idle_threshold_seconds": threshold,
        "bypass_session_quiet": bypass_quiet,
        "mode": mode,
    }

    if idle_seconds < threshold:
        state.update(
            {
                "dreamed_this_idle_streak": False,
                "last_user_active_at": now,
                "last_idle_seconds": idle_seconds,
            }
        )
        _save_state(state_path, state)
        return {
            **base_result,
            "status": "skipped_not_idle",
            "dreamed_this_idle_streak": False,
        }

    cooldown_elapsed = (now - last_dream_at) >= cooldown_minutes * 60
    if dreamed_this_streak and not cooldown_elapsed:
        return {
            **base_result,
            "status": "skipped_cooldown",
            "dreamed_this_idle_streak": True,
            "cooldown_minutes": cooldown_minutes,
        }

    if not bypass_quiet:
        from braindrain.server import _get_session_store

        quiet_minutes = int(dreaming.get("quiet_minutes", 30) or 30)
        if not _get_session_store().should_dream(quiet_minutes=quiet_minutes):
            return {
                **base_result,
                "status": "skipped_active_session",
                "quiet_minutes": quiet_minutes,
            }

    if not _try_acquire_lock(lock_path):
        return {
            **base_result,
            "status": "skipped_lock_held",
        }

    try:
        from braindrain.server import _get_dream_engine

        dream_result = _get_dream_engine().run(
            mode=mode,
            force=False,
            trigger="host_idle",
        )
        state.update(
            {
                "dreamed_this_idle_streak": True,
                "last_dream_at": now,
                "last_idle_seconds": idle_seconds,
                "last_run_status": dream_result.get("status") or "completed",
            }
        )
        _save_state(state_path, state)
        return {
            **base_result,
            "status": "ran",
            "dream": dream_result,
        }
    finally:
        _release_lock(lock_path)
