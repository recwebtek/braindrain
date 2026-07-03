#!/usr/bin/env python3
"""One-time backfill of plan-audit-history.jsonl from existing dated audit reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.daily_plan_audit import _ensure_braindrain_on_path  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill plan-audit-history.jsonl")
    parser.add_argument("--repo-root", default=".", help="Repository root")
    parser.add_argument(
        "--render",
        action="store_true",
        help="Also regenerate plan-audit-history.html after backfill",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    _ensure_braindrain_on_path(repo_root)
    from braindrain.plan_audit_history import backfill_history_jsonl

    result = backfill_history_jsonl(repo_root)
    print(json.dumps(result, indent=2))

    if args.render:
        from scripts.daily_plan_audit import render_plan_audit_history_dashboard

        render_plan_audit_history_dashboard(repo_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
