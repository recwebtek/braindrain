"""P0.5: telemetry ↔ observer bridge for MCP tool instrumentation."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from braindrain.instrumentation import make_observe_mcp_tool, record_tool_io, record_tool_io_async
from braindrain.observer import ObserverStore
from braindrain.telemetry import TelemetrySession


@pytest.fixture
def telemetry(tmp_path: Path) -> TelemetrySession:
    return TelemetrySession(log_file=tmp_path / "session.jsonl")


@pytest.fixture
def observer(tmp_path: Path) -> ObserverStore:
    return ObserverStore(db_path=tmp_path / "events.db", max_events=100)


def test_record_tool_io_writes_telemetry_and_observer_tool_call(
    telemetry: TelemetrySession, observer: ObserverStore
) -> None:
    result = record_tool_io(
        telemetry,
        tool_name="search_tools",
        raw_text="x" * 8000,
        actual_text='{"matches": []}',
        module="tool_gate",
        observer_store=observer,
        session_id="test-session",
        hash_tool_args=False,
        project_root="/tmp/workspace",
    )

    assert result["saved_tokens"] > 0

    snapshot = telemetry.snapshot()
    assert snapshot["tokens_saved_est"] > 0
    assert "search_tools" in snapshot["tools"]

    stats = observer.get_event_stats(session_id="test-session")
    assert stats["total_events"] == 1
    assert stats["by_type"].get("tool_call") == 1
    events = observer.query_events(session_id="test-session", limit=1)
    assert events[0].metadata.get("project_root") == "/tmp/workspace"

    lines = (telemetry.log_file).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1
    row = json.loads(lines[-1])
    assert row["tool"] == "search_tools"
    assert row["tokens_saved_est"] > 0


def test_record_tool_io_async_persists_observer_off_event_loop(
    telemetry: TelemetrySession, observer: ObserverStore
) -> None:
    async def _run() -> None:
        with patch(
            "braindrain.instrumentation.asyncio.to_thread",
            side_effect=lambda func, *args, **kwargs: func(*args, **kwargs),
        ) as to_thread:
            await record_tool_io_async(
                telemetry,
                tool_name="route_output",
                raw_text="y" * 10_000,
                actual_text='{"routed": true, "preview": "small"}',
                module="output_sandbox",
                observer_store=observer,
                session_id="async-session",
                hash_tool_args=False,
            )
            to_thread.assert_awaited_once()

    asyncio.run(_run())
    stats = observer.get_event_stats(session_id="async-session")
    assert stats["total_events"] == 1


def test_observe_mcp_tool_async_wrapper_uses_async_observer_path(
    telemetry: TelemetrySession, observer: ObserverStore
) -> None:
    observe = make_observe_mcp_tool(
        telemetry=telemetry,
        observer_enabled=lambda: True,
        observer_store_getter=lambda: observer,
        hash_args_enabled=lambda: False,
        wrap_tool=lambda _name: True,
    )

    @observe
    async def sample_tool(text: str) -> dict:
        return {"echo": text[:32]}

    async def _run() -> None:
        with patch(
            "braindrain.instrumentation.record_tool_io_async",
            wraps=record_tool_io_async,
        ) as record_async:
            out = await sample_tool("z" * 5000)
            assert "echo" in out
            record_async.assert_awaited_once()

    asyncio.run(_run())


def test_observe_mcp_tool_emits_session_start_once(
    telemetry: TelemetrySession, observer: ObserverStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRAINDRAIN_SESSION_ID", "session-start-test")
    observe = make_observe_mcp_tool(
        telemetry=telemetry,
        observer_enabled=lambda: True,
        observer_store_getter=lambda: observer,
        hash_args_enabled=lambda: False,
        wrap_tool=lambda _name: True,
    )

    @observe
    def sample_tool(text: str) -> dict:
        return {"echo": text}

    sample_tool("first")
    sample_tool("second")

    events = observer.query_events(session_id="session-start-test", limit=10)
    session_start_count = sum(1 for event in events if event.event_type == "session_start")
    tool_call_count = sum(1 for event in events if event.event_type == "tool_call")
    assert session_start_count == 1
    assert tool_call_count == 2
