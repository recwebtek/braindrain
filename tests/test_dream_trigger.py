"""Tests for host-idle dream trigger policy."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

import braindrain.server
from braindrain.dream_trigger import evaluate_host_idle_trigger, workspace_hash


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "config").mkdir()
    config = {
        "version": "1.0.3",
        "dreaming": {
            "quiet_minutes": 30,
            "triggers": {
                "macos_host_idle": {
                    "enabled": True,
                    "idle_threshold_seconds": 60,
                    "cooldown_minutes": 0,
                    "bypass_session_quiet": True,
                    "mode": "light",
                }
            },
        },
    }
    (repo / "config" / "hub_config.yaml").write_text(yaml.dump(config), encoding="utf-8")
    return repo


def test_evaluate_disabled_when_config_off(workspace: Path):
    cfg_path = workspace / "config" / "hub_config.yaml"
    raw = yaml.safe_load(cfg_path.read_text())
    raw["dreaming"]["triggers"]["macos_host_idle"]["enabled"] = False
    cfg_path.write_text(yaml.dump(raw), encoding="utf-8")
    result = evaluate_host_idle_trigger(repo_root=workspace, config_path=cfg_path)
    assert result["status"] == "disabled"


def test_evaluate_runs_dream_when_idle(workspace: Path, tmp_path: Path):
    cfg_path = workspace / "config" / "hub_config.yaml"
    state_dir = tmp_path / "state"
    engine = MagicMock()
    engine.run.return_value = {"plan": {"mode": "light"}}

    def _state_dir(repo_root: Path) -> Path:
        return state_dir

    with patch("braindrain.dream_trigger.is_macos", return_value=True):
        with patch("braindrain.dream_trigger.get_hid_idle_seconds", return_value=120.0):
            with patch("braindrain.dream_trigger.workspace_state_dir", _state_dir):
                with patch("braindrain.dream_trigger._get_dream_engine", create=True) as get_engine:
                    with patch("braindrain.server._get_dream_engine", return_value=engine):
                        result = evaluate_host_idle_trigger(
                            repo_root=workspace,
                            config_path=cfg_path,
                        )

    assert result["status"] == "ran"
    engine.run.assert_called_once_with(mode="light", force=False, trigger="host_idle")


def test_workspace_hash_stable(workspace: Path):
    assert workspace_hash(workspace) == workspace_hash(workspace.resolve())


def test_host_idle_bypasses_session_quiet_gate():
    from braindrain.dream import DreamEngine
    from unittest.mock import MagicMock
    from pathlib import Path

    session_store = MagicMock()
    session_store.should_dream.return_value = False
    session_store.list_episodes.return_value = []
    session_store.list_recent_sessions.return_value = []
    observer = MagicMock()
    observer.query_events.return_value = []

    engine = DreamEngine(
        observer_store=observer,
        session_store=session_store,
        wiki_brain=MagicMock(),
        config={
            "quiet_minutes": 30,
            "bypass_session_quiet": True,
            "storage_dir": str(Path("/tmp/braindrain-dream-trigger-test")),
            "max_episode_scan": 1,
            "max_event_scan": 1,
            "max_session_scan": 1,
            "lookback_hours": 1,
        },
        provider_context={},
    )
    result = engine.run(mode="full", force=False, trigger="host_idle")
    assert result.get("status") != "skipped_active_session"
    session_store.should_dream.assert_not_called()
