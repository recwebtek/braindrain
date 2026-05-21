"""P0.5: routed-output savings appear in telemetry snapshots."""

from __future__ import annotations

import json
from pathlib import Path

from braindrain.instrumentation import record_tool_io
from braindrain.telemetry import TelemetrySession


def test_route_output_style_savings_in_dashboard_snapshot(tmp_path: Path) -> None:
    """Simulate route_output: large input text, compact handle response."""
    telemetry = TelemetrySession(log_file=tmp_path / "session.jsonl")
    large_input = "log line\n" * 1200
    compact_response = json.dumps(
        {
            "routed": True,
            "handle": "abc123",
            "preview": "log line\n" * 3,
            "retrieval_hint": "Call search_index with handle:abc123",
        }
    )

    record_tool_io(
        telemetry,
        tool_name="route_output",
        raw_text=large_input,
        actual_text=compact_response,
        module="output_sandbox",
    )

    snapshot = telemetry.snapshot()
    assert snapshot["tokens_saved_est"] > 0
    route_stats = snapshot["tools"]["route_output"]
    assert route_stats["calls"] == 1
    assert route_stats["tokens_saved_est"] > 0
    assert snapshot["module_attribution"]["output_sandbox"] > 0
