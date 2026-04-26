from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_bridge_module():
    bridge_path = Path(__file__).resolve().parent.parent / "bd-plugins" / "ai-shell" / "bridge.py"
    spec = importlib.util.spec_from_file_location("ai_shell_bridge", bridge_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_bridge_prompt_updates_from_cwd_after() -> None:
    bridge_mod = _load_bridge_module()
    bridge = bridge_mod.MacOSTerminalBridge("/tmp/not-used.sock")
    state = bridge_mod.BridgeState(session_id="s1", cwd="/repo")
    response = {"cwd_after": "/repo/src", "signals": {"cd": "/repo/src"}}
    next_state = bridge.apply_response(state, response)
    assert next_state.cwd == "/repo/src"
    assert next_state.stale_prompt is False


def test_bridge_marks_stale_on_signal_mismatch_and_requests_resync() -> None:
    bridge_mod = _load_bridge_module()
    bridge = bridge_mod.MacOSTerminalBridge("/tmp/not-used.sock", mismatch_threshold=1)
    state = bridge_mod.BridgeState(session_id="s1", cwd="/repo")
    response = {"cwd_after": "/repo/src", "signals": {"cd": "/repo/other"}}
    next_state = bridge.apply_response(state, response)
    assert next_state.stale_prompt is True
    assert bridge.needs_resync(next_state) is True


def test_bridge_run_command_flow_resyncs_before_and_after() -> None:
    bridge_mod = _load_bridge_module()
    bridge = bridge_mod.MacOSTerminalBridge("/tmp/not-used.sock", mismatch_threshold=1)
    state = bridge_mod.BridgeState(session_id="s1", cwd="/repo", stale_prompt=True, mismatch_count=1)

    def sync_state(*, session_id: str):
        assert session_id == "s1"
        return {"cwd_after": "/repo/src"}

    def run_transport(_envelope: dict):
        return {"cwd_after": "/repo/src", "signals": {"cd": "/repo/other"}}

    updated_state, response = bridge.run_command_flow(
        state=state,
        request_id="req1",
        command="pwd",
        sync_state=sync_state,
        run_transport=run_transport,
        requested_mode="hybrid",
    )
    assert response["cwd_after"] == "/repo/src"
    assert updated_state.cwd == "/repo/src"
    assert updated_state.stale_prompt is False
    assert updated_state.mismatch_count == 0
