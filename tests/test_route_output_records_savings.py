"""P0.5: routed-output savings appear in telemetry snapshots."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from braindrain.instrumentation import record_tool_io
from braindrain.telemetry import TelemetrySession
from braindrain.tools.tokens import search_index_impl


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


def test_search_index_uses_local_fallback_when_context_mode_missing() -> None:
    fallback_calls: list[tuple[str, int]] = []

    def fallback_search(*, query: str, limit: int) -> list[dict]:
        fallback_calls.append((query, limit))
        return [{"title": "fallback result", "content": "hello"}]

    result = asyncio.run(
        search_index_impl(
            get_context_mode_client=lambda: None,
            config=SimpleNamespace(
                get=lambda key, default=None: default,
                data=SimpleNamespace(embeddings={}),
            ),
            query="hello",
            limit=3,
            fallback_search=fallback_search,
        )
    )

    assert result["fallback"] == "wiki_brain_fts"
    assert result["results"][0]["title"] == "fallback result"
    assert fallback_calls == [("hello", 3)]
