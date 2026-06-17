"""Token-savings benchmark harness for hub-on vs hub-off replay.

Replays deterministic agent-transcript fixtures and measures estimated context
tokens using the same telemetry estimators as production MCP tools.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from braindrain.config import Config
from braindrain.instrumentation import record_tool_io
from braindrain.output_router import build_routed_output
from braindrain.session import SessionSummary
from braindrain.session_compaction import (
    build_compact_package,
    retrieval_hint,
    session_index_handle,
)
from braindrain.telemetry import TelemetrySession, estimate_tokens
from braindrain.tool_registry import ToolRegistry

DEFAULT_FIXTURES_DIR = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "token_benchmark"
)
DEFAULT_SAVINGS_FLOOR_PCT = float(os.environ.get("TOKEN_BENCHMARK_MIN_SAVINGS_PCT", "25"))


@dataclass
class StepMetrics:
    step_type: str
    hub_off_tokens: int
    hub_on_tokens: int

    @property
    def saved_tokens(self) -> int:
        return max(0, self.hub_off_tokens - self.hub_on_tokens)

    @property
    def saved_pct(self) -> float:
        if self.hub_off_tokens <= 0:
            return 0.0
        return (self.saved_tokens / self.hub_off_tokens) * 100.0


@dataclass
class FixtureMetrics:
    fixture_id: str
    description: str
    steps: list[StepMetrics] = field(default_factory=list)

    @property
    def hub_off_tokens(self) -> int:
        return sum(step.hub_off_tokens for step in self.steps)

    @property
    def hub_on_tokens(self) -> int:
        return sum(step.hub_on_tokens for step in self.steps)

    @property
    def saved_tokens(self) -> int:
        return max(0, self.hub_off_tokens - self.hub_on_tokens)

    @property
    def saved_pct(self) -> float:
        if self.hub_off_tokens <= 0:
            return 0.0
        return (self.saved_tokens / self.hub_off_tokens) * 100.0


@dataclass
class BenchmarkReport:
    generated_at: str
    savings_floor_pct: float
    fixtures: list[FixtureMetrics]
    hub_off_tokens: int
    hub_on_tokens: int
    saved_tokens: int
    saved_pct: float
    passed: bool

    def to_markdown(self) -> str:
        lines = [
            "# Token benchmark report",
            "",
            f"- **Generated**: {self.generated_at}",
            f"- **Savings floor**: {self.savings_floor_pct:.1f}%",
            f"- **Aggregate hub-off tokens (est.)**: {self.hub_off_tokens}",
            f"- **Aggregate hub-on tokens (est.)**: {self.hub_on_tokens}",
            f"- **Aggregate saved tokens (est.)**: {self.saved_tokens}",
            f"- **Aggregate savings**: {self.saved_pct:.2f}%",
            f"- **Result**: {'PASS' if self.passed else 'FAIL'}",
            "",
            "## Per-fixture breakdown",
            "",
            "| Fixture | Hub-off | Hub-on | Saved | Savings % |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for fixture in self.fixtures:
            lines.append(
                f"| {fixture.fixture_id} | {fixture.hub_off_tokens} | "
                f"{fixture.hub_on_tokens} | {fixture.saved_tokens} | "
                f"{fixture.saved_pct:.2f}% |"
            )
            if fixture.description:
                lines.append("")
                lines.append(f"_{fixture.description}_")
            lines.append("")
            lines.append("| Step | Hub-off | Hub-on | Saved % |")
            lines.append("| --- | ---: | ---: | ---: |")
            for step in fixture.steps:
                lines.append(
                    f"| {step.step_type} | {step.hub_off_tokens} | "
                    f"{step.hub_on_tokens} | {step.saved_pct:.2f}% |"
                )
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


def _expand_content(step: dict[str, Any]) -> str:
    if isinstance(step.get("content"), str):
        return step["content"]
    line = str(step.get("line", "benchmark transcript line with neutral placeholder text\n"))
    repeat = int(step.get("repeat", 1))
    return line * max(1, repeat)


def _serialize(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _bloated_tool_catalog(registry: ToolRegistry) -> str:
    """Naive hub-off baseline: inline deferred tool definitions with faux schemas."""
    chunks: list[str] = []
    for tool in registry._tools.values():
        schema_block = {
            "name": tool.name,
            "description": tool.description,
            "tags": tool.tags,
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace path"},
                    "query": {"type": "string", "description": "Search query"},
                    "token_budget": {"type": "integer", "description": "Max tokens"},
                },
            },
            "examples": tool.input_examples or [{"note": "full schema loaded into context"}],
        }
        chunks.append(_serialize(schema_block))
        chunks.append(tool.description.strip())
    return "\n\n".join(chunks)


def _cached_env_context_envelope() -> str:
    return _serialize(
        {
            "cached": True,
            "summary": {
                "identity": {"username": "bench-user", "hostname": "bench-host"},
                "os": {"type": "linux", "arch": "x86_64"},
                "agent_hints": ["prefer rg over grep", "call get_env_context first"],
            },
        }
    )


def _naive_env_probe_dump(step: dict[str, Any]) -> str:
    line = str(
        step.get(
            "line",
            "probe: installed package python3 version 3.12 path /opt/example/bin/python3\n",
        )
    )
    repeat = int(step.get("repeat", 120))
    return line * max(1, repeat)


def _large_session_dump(step: dict[str, Any]) -> dict[str, Any]:
    decisions = [
        f"Decision {idx}: investigated module behavior and chose approach {idx}"
        for idx in range(int(step.get("decision_count", 40)))
    ]
    files = [f"src/pkg/module_{idx}.py" for idx in range(int(step.get("file_count", 60)))]
    errors = [f"transient error in step {idx}: retry succeeded" for idx in range(8)]
    todos = [f"todo-{idx}: follow-up task for benchmark replay" for idx in range(20)]
    return {
        "session_id": step.get("session_id", "bench-session-001"),
        "transcript": _expand_content(step),
        "decisions": decisions,
        "files_modified": files,
        "errors": errors,
        "open_todos": todos,
        "tools_used": {f"tool_{idx}": idx + 1 for idx in range(25)},
        "events_count": int(step.get("events_count", 180)),
        "token_total": int(step.get("token_total", 12000)),
    }


def _replay_step(
    step: dict[str, Any],
    *,
    registry: ToolRegistry,
    telemetry: TelemetrySession | None = None,
) -> StepMetrics:
    step_type = str(step.get("type", "large_output"))
    estimator = telemetry.estimator if telemetry is not None else None

    if step_type == "large_output":
        content = _expand_content(step)
        source = str(step.get("source", "fixture:large_output"))
        routed, _md = build_routed_output(source=source, content=content, intent=step.get("intent"))
        hub_on_payload = {
            "routed": True,
            "source": source,
            "handle": routed.handle,
            "preview": routed.preview,
            "retrieval_hint": retrieval_hint(routed.handle),
            "suggested_queries": routed.suggested_queries[:3],
        }
        hub_on_text = _serialize(hub_on_payload)
        hub_off_tokens = estimate_tokens(content, estimator)
        hub_on_tokens = estimate_tokens(hub_on_text, estimator)
        if telemetry is not None:
            record_tool_io(
                telemetry,
                tool_name="route_output",
                raw_text=content,
                actual_text=hub_on_text,
                module="output_sandbox",
            )
        return StepMetrics(step_type, hub_off_tokens, hub_on_tokens)

    if step_type == "search_tools":
        query = str(step.get("query", "token dashboard"))
        top_k = int(step.get("top_k", 5))
        compact = _serialize(
            {
                "tools": registry.search(query, top_k=top_k),
                "total_available": registry.count(),
                "query": query,
            }
        )
        bloated = _bloated_tool_catalog(registry)
        hub_off_tokens = estimate_tokens(bloated, estimator)
        hub_on_tokens = estimate_tokens(compact, estimator)
        if telemetry is not None:
            record_tool_io(
                telemetry,
                tool_name="search_tools",
                raw_text=query,
                actual_text=compact,
                module="tool_gate",
            )
        return StepMetrics(step_type, hub_off_tokens, hub_on_tokens)

    if step_type == "env_context":
        hub_off_text = _naive_env_probe_dump(step)
        hub_on_text = _cached_env_context_envelope()
        hub_off_tokens = estimate_tokens(hub_off_text, estimator)
        hub_on_tokens = estimate_tokens(hub_on_text, estimator)
        if telemetry is not None:
            record_tool_io(
                telemetry,
                tool_name="get_env_context",
                raw_text=hub_off_text,
                actual_text=hub_on_text,
                module="tool_gate",
            )
        return StepMetrics(step_type, hub_off_tokens, hub_on_tokens)

    if step_type == "session_summary":
        dump = _large_session_dump(step)
        hub_off_text = _serialize(dump)
        summary = SessionSummary(session_id=str(dump["session_id"]), start_time=0.0)
        summary.key_decisions.extend(dump["decisions"])
        summary.files_modified.extend(dump["files_modified"])
        summary.errors.extend(dump["errors"])
        summary.open_todos.extend(dump["open_todos"])
        summary.tools_used.update(dump["tools_used"])
        summary.events_count = int(dump["events_count"])
        summary.token_total = int(dump["token_total"])
        compact = build_compact_package(summary)
        handle = session_index_handle(summary.session_id)
        hub_on_text = _serialize(
            {
                "session_id": summary.session_id,
                "handle": handle,
                "package": compact,
                "retrieval_hint": retrieval_hint(handle),
            }
        )
        hub_off_tokens = estimate_tokens(hub_off_text, estimator)
        hub_on_tokens = estimate_tokens(hub_on_text, estimator)
        if telemetry is not None:
            record_tool_io(
                telemetry,
                tool_name="touch_session",
                raw_text=hub_off_text,
                actual_text=hub_on_text,
                module="output_sandbox",
            )
        return StepMetrics(step_type, hub_off_tokens, hub_on_tokens)

    raise ValueError(f"unsupported fixture step type: {step_type}")


def load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def replay_fixture(
    fixture: dict[str, Any],
    *,
    registry: ToolRegistry,
    telemetry: TelemetrySession | None = None,
) -> FixtureMetrics:
    fixture_id = str(fixture.get("id") or fixture.get("fixture_id") or "fixture")
    description = str(fixture.get("description", ""))
    steps = fixture.get("steps") or []
    metrics = FixtureMetrics(fixture_id=fixture_id, description=description)
    for step in steps:
        if not isinstance(step, dict):
            continue
        metrics.steps.append(_replay_step(step, registry=registry, telemetry=telemetry))
    return metrics


def run_benchmark(
    *,
    fixtures_dir: Path | None = None,
    config_path: Path | None = None,
    savings_floor_pct: float | None = None,
    telemetry_log: Path | None = None,
) -> BenchmarkReport:
    fixtures_root = fixtures_dir or DEFAULT_FIXTURES_DIR
    cfg_path = config_path or Path(__file__).resolve().parents[1] / "config" / "hub_config.yaml"
    floor = DEFAULT_SAVINGS_FLOOR_PCT if savings_floor_pct is None else savings_floor_pct

    config = Config(cfg_path)
    registry = ToolRegistry(config.data)
    telemetry = TelemetrySession(log_file=telemetry_log or Path(os.devnull))

    fixture_paths = sorted(fixtures_root.glob("*.json"))
    if not fixture_paths:
        raise FileNotFoundError(f"No benchmark fixtures found in {fixtures_root}")

    fixture_metrics: list[FixtureMetrics] = []
    for fixture_path in fixture_paths:
        fixture = load_fixture(fixture_path)
        fixture_metrics.append(replay_fixture(fixture, registry=registry, telemetry=telemetry))

    hub_off_total = sum(item.hub_off_tokens for item in fixture_metrics)
    hub_on_total = sum(item.hub_on_tokens for item in fixture_metrics)
    saved_total = max(0, hub_off_total - hub_on_total)
    saved_pct = (saved_total / hub_off_total * 100.0) if hub_off_total > 0 else 0.0

    return BenchmarkReport(
        generated_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        savings_floor_pct=floor,
        fixtures=fixture_metrics,
        hub_off_tokens=hub_off_total,
        hub_on_tokens=hub_on_total,
        saved_tokens=saved_total,
        saved_pct=round(saved_pct, 2),
        passed=saved_pct >= floor,
    )


def write_report(report: BenchmarkReport, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    date_prefix = report.generated_at[:10]
    out_path = output_dir / f"token-benchmark-{date_prefix}.md"
    out_path.write_text(report.to_markdown(), encoding="utf-8")
    return out_path


def assert_savings_floor(report: BenchmarkReport) -> None:
    if not report.passed:
        raise AssertionError(
            "Token benchmark savings regression: "
            f"{report.saved_pct:.2f}% < floor {report.savings_floor_pct:.2f}%"
        )
