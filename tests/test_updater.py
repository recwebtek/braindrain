"""Tests for repo-clone hub self-update helpers."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from braindrain.updater import (
    UpdateError,
    _state_path,
    apply_update,
    check_update,
    load_update_state,
    maybe_background_check,
    startup_notify_message,
)

PYPROJECT_V1 = '[project]\nname = "braindrain"\nversion = "1.0.0"\n'
PYPROJECT_V2 = '[project]\nname = "braindrain"\nversion = "1.0.1"\n'


def _run_git(cwd: Path, *args: str) -> None:
    env = os.environ.copy()
    env.setdefault("GIT_CONFIG_GLOBAL", "/dev/null")
    env.setdefault("GIT_CONFIG_SYSTEM", "/dev/null")
    subprocess.run(
        ["git", "-c", "init.templateDir=", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def _seed_repo(path: Path, *, version_text: str = PYPROJECT_V1) -> None:
    _run_git(path, "init")
    _run_git(path, "config", "user.email", "updater-test@example.com")
    _run_git(path, "config", "user.name", "Updater Test")
    (path / "pyproject.toml").write_text(version_text, encoding="utf-8")
    _run_git(path, "add", ".")
    _run_git(path, "commit", "-m", "init")
    _run_git(path, "branch", "-M", "main")


@pytest.fixture()
def git_pair(tmp_path: Path) -> dict[str, Path]:
    bare = tmp_path / "origin.git"
    _run_git(tmp_path, "init", "--bare", str(bare))

    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _seed_repo(upstream)
    _run_git(upstream, "remote", "add", "origin", str(bare))
    _run_git(upstream, "push", "-u", "origin", "main")

    clone = tmp_path / "clone"
    _run_git(tmp_path, "clone", str(bare), str(clone))

    return {"bare": bare, "upstream": upstream, "clone": clone}


def _push_upstream_commit(upstream: Path, *, message: str, version_text: str | None = None) -> None:
    if version_text is not None:
        (upstream / "pyproject.toml").write_text(version_text, encoding="utf-8")
        _run_git(upstream, "add", "pyproject.toml")
    else:
        (upstream / "notes.txt").write_text(f"{message}\n", encoding="utf-8")
        _run_git(upstream, "add", "notes.txt")
    _run_git(upstream, "commit", "-m", message)
    _run_git(upstream, "push", "origin", "main")


def test_check_update_detects_behind_and_writes_state(git_pair: dict[str, Path]) -> None:
    clone = git_pair["clone"]
    upstream = git_pair["upstream"]

    first = check_update(clone, fetch=True)
    assert first["ok"] is True
    assert first["behind"] == 0
    assert first["current_version"] == "1.0.0"

    _push_upstream_commit(upstream, message="release 1.0.1", version_text=PYPROJECT_V2)
    second = check_update(clone, fetch=True)
    assert second["behind"] == 1
    assert second["remote_version"] == "1.0.1"
    assert second["update_available"] is True
    assert "release 1.0.1" in second["changelog"]

    state = load_update_state(clone)
    assert state is not None
    assert state["behind"] == 1
    assert _state_path(clone).is_file()


def test_apply_update_refuses_dirty_tree(git_pair: dict[str, Path]) -> None:
    clone = git_pair["clone"]
    upstream = git_pair["upstream"]
    _push_upstream_commit(upstream, message="ahead", version_text=PYPROJECT_V2)

    (clone / "local-edit.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(UpdateError, match="local changes"):
        apply_update(clone)


def test_apply_update_refuses_non_fast_forward(git_pair: dict[str, Path]) -> None:
    clone = git_pair["clone"]
    upstream = git_pair["upstream"]

    _run_git(clone, "commit", "--allow-empty", "-m", "local-only")
    _push_upstream_commit(upstream, message="remote-only")

    result = check_update(clone, fetch=True)
    assert result["behind"] >= 1
    assert result["can_ff"] is False

    with pytest.raises(UpdateError, match="fast-forward"):
        apply_update(clone)


def test_apply_update_fast_forwards_clean_clone(git_pair: dict[str, Path]) -> None:
    clone = git_pair["clone"]
    upstream = git_pair["upstream"]
    _push_upstream_commit(upstream, message="ship docs")

    result = apply_update(clone)
    assert result["updated"] is True
    assert result["restart_required"] is True
    assert result["behind"] == 0
    assert result["deps_synced"] is False

    state = load_update_state(clone)
    assert state is not None
    assert state["behind"] == 0
    assert state["restart_required"] is True


def test_startup_notify_message_when_behind(git_pair: dict[str, Path]) -> None:
    clone = git_pair["clone"]
    check_update(clone, fetch=False)
    state = load_update_state(clone) or {}
    state["behind"] = 2
    _state_path(clone).write_text(json.dumps(state) + "\n", encoding="utf-8")

    message = startup_notify_message(clone)
    assert message is not None
    assert "2 commits behind" in message


def test_maybe_background_check_stale_when_missing_state(git_pair: dict[str, Path]) -> None:
    clone = git_pair["clone"]
    assert maybe_background_check(clone) is True

    check_update(clone, fetch=False)
    assert maybe_background_check(clone) is False
