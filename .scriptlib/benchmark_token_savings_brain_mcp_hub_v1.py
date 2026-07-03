#!/usr/bin/env python3
"""Run the token-savings benchmark harness (hub-on vs hub-off replay).

Machine-local report default:
  <repo-root>/.braindrain/plan-reports/token-benchmark-YYYY-MM-DD.md

Example:
  python3 scripts/benchmark_token_savings_brain_mcp_hub_v1.py --repo-root .
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _repo_root(value: str) -> Path:
    return Path(value).resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay token benchmark fixtures.")
    parser.add_argument("--repo-root", type=_repo_root, default=Path.cwd(), help="Workspace root")
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=None,
        help="Override fixtures directory (default: tests/fixtures/token_benchmark)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Override hub_config.yaml path",
    )
    parser.add_argument(
        "--savings-floor",
        type=float,
        default=None,
        help="Minimum aggregate savings percentage (default: env TOKEN_BENCHMARK_MIN_SAVINGS_PCT or 25)",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=None,
        help="Report output directory (default: <repo-root>/.braindrain/plan-reports)",
    )
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Exit non-zero when savings fall below the configured floor",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root
    sys.path.insert(0, str(repo_root))

    from braindrain.token_benchmark import (  # noqa: PLC0415
        assert_savings_floor,
        run_benchmark,
        write_report,
    )

    fixtures_dir = args.fixtures_dir or (repo_root / "tests" / "fixtures" / "token_benchmark")
    config_path = args.config or (repo_root / "config" / "hub_config.yaml")
    report_dir = args.report_dir or (repo_root / ".braindrain" / "plan-reports")

    report = run_benchmark(
        fixtures_dir=fixtures_dir,
        config_path=config_path,
        savings_floor_pct=args.savings_floor,
    )
    out_path = write_report(report, report_dir)
    print(f"Wrote {out_path}")
    print(
        f"Aggregate savings: {report.saved_pct:.2f}% "
        f"({report.saved_tokens} tokens saved of {report.hub_off_tokens} hub-off est.)"
    )

    if args.fail_on_regression:
        assert_savings_floor(report)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
