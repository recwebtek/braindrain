"""Token benchmark harness tests (P1c)."""

from __future__ import annotations

from pathlib import Path

import pytest

from braindrain.config import Config
from braindrain.token_benchmark import (
    assert_savings_floor,
    load_fixture,
    replay_fixture,
    run_benchmark,
    write_report,
)
from braindrain.tool_registry import ToolRegistry

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES_DIR = _REPO_ROOT / "tests" / "fixtures" / "token_benchmark"
_CONFIG_PATH = _REPO_ROOT / "config" / "hub_config.yaml"


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry(Config(_CONFIG_PATH).data)


@pytest.mark.token_benchmark
def test_fixtures_replay_with_positive_savings(registry: ToolRegistry) -> None:
    for fixture_path in sorted(_FIXTURES_DIR.glob("*.json")):
        fixture = load_fixture(fixture_path)
        metrics = replay_fixture(fixture, registry=registry)
        assert metrics.hub_on_tokens < metrics.hub_off_tokens, fixture_path.name
        assert metrics.saved_pct > 0, fixture_path.name


@pytest.mark.token_benchmark
def test_aggregate_benchmark_meets_default_floor() -> None:
    report = run_benchmark(fixtures_dir=_FIXTURES_DIR, config_path=_CONFIG_PATH)
    assert report.hub_off_tokens > report.hub_on_tokens
    assert report.saved_pct >= report.savings_floor_pct
    assert_savings_floor(report)


@pytest.mark.token_benchmark
def test_report_markdown_written(tmp_path: Path) -> None:
    report = run_benchmark(fixtures_dir=_FIXTURES_DIR, config_path=_CONFIG_PATH)
    out_path = write_report(report, tmp_path)
    assert out_path.exists()
    text = out_path.read_text(encoding="utf-8")
    assert "Token benchmark report" in text
    assert "grep_log_flood" in text or "Per-fixture breakdown" in text
    assert f"{report.saved_pct:.2f}%" in text
