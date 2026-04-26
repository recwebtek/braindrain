"""Unix-socket bridge helpers for AI Shell macOS terminal integration."""

from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass
class BridgeState:
    session_id: str
    cwd: str
    stale_prompt: bool = False
    mismatch_count: int = 0


class MacOSTerminalBridge:
    """Client-side envelope sync logic for unix-socket AI shell bridge."""

    def __init__(self, socket_path: str, mismatch_threshold: int = 3, payload_limit: int = 64 * 1024) -> None:
        self.socket_path = Path(socket_path)
        self.mismatch_threshold = mismatch_threshold
        self.payload_limit = payload_limit

    def build_request(
        self,
        *,
        request_id: str,
        session_id: str,
        command: str,
        cwd_hint: str,
        requested_mode: str | None = None,
    ) -> dict[str, Any]:
        return {
            "request_id": request_id,
            "session_id": session_id,
            "command": command,
            "cwd_hint": cwd_hint,
            "requested_mode": requested_mode,
            "client_ts": time.time(),
        }

    def apply_response(self, state: BridgeState, response: dict[str, Any]) -> BridgeState:
        cwd_after = response.get("cwd_after")
        signals = response.get("signals") or {}
        cd_signal = signals.get("cd")
        if cd_signal and cwd_after and cd_signal != cwd_after:
            state.mismatch_count += 1
            state.stale_prompt = True
            return state

        if cwd_after:
            state.cwd = cwd_after
            state.stale_prompt = False
            state.mismatch_count = 0
        else:
            state.stale_prompt = True
        return state

    def needs_resync(self, state: BridgeState) -> bool:
        return state.mismatch_count >= self.mismatch_threshold or state.stale_prompt

    def send_envelope(self, envelope: dict[str, Any]) -> dict[str, Any]:
        raw = json.dumps(envelope).encode("utf-8")
        if len(raw) > self.payload_limit:
            raise ValueError("payload too large")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(self.socket_path))
            client.sendall(raw + b"\n")
            data = client.recv(self.payload_limit)
        return json.loads(data.decode("utf-8"))

    def run_command_flow(
        self,
        *,
        state: BridgeState,
        request_id: str,
        command: str,
        sync_state: Callable[..., dict[str, Any]],
        requested_mode: str | None = None,
        run_transport: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> tuple[BridgeState, dict[str, Any]]:
        """Canonical state_sync -> run -> apply -> optional resync flow."""
        if self.needs_resync(state):
            sync_resp = sync_state(session_id=state.session_id)
            cwd_after = sync_resp.get("cwd_after")
            if isinstance(cwd_after, str) and cwd_after:
                state.cwd = cwd_after
                state.stale_prompt = False
                state.mismatch_count = 0

        envelope = self.build_request(
            request_id=request_id,
            session_id=state.session_id,
            command=command,
            cwd_hint=state.cwd,
            requested_mode=requested_mode,
        )
        runner = run_transport or self.send_envelope
        response = runner(envelope)
        updated_state = self.apply_response(state, response)

        if self.needs_resync(updated_state):
            sync_resp = sync_state(session_id=updated_state.session_id)
            cwd_after = sync_resp.get("cwd_after")
            if isinstance(cwd_after, str) and cwd_after:
                updated_state.cwd = cwd_after
                updated_state.stale_prompt = False
                updated_state.mismatch_count = 0

        return updated_state, response
