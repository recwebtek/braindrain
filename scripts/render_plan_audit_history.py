#!/usr/bin/env python3
"""Render self-contained plan audit history dashboard HTML."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.daily_plan_audit import _ensure_braindrain_on_path  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render plan audit history dashboard")
    parser.add_argument("--repo-root", default=".", help="Repository root")
    parser.add_argument(
        "--out",
        default="",
        help="Output HTML path (default: .braindrain/plan-reports/plan-audit-history.html)",
    )
    parser.add_argument("--window", type=int, default=None, help="Limit series to last N days")
    parser.add_argument(
        "--max-points",
        type=int,
        default=None,
        help="Downsample series to at most N points",
    )
    parser.add_argument("--open", action="store_true", help="Open the HTML file in a browser")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    _ensure_braindrain_on_path(repo_root)

    from braindrain.plan_audit_history import build_history_snapshot
    from braindrain.plan_audit_history_html import render_history_html

    snapshot = build_history_snapshot(
        repo_root,
        window_days=args.window,
        max_points=args.max_points,
    )
    out = Path(args.out) if args.out else repo_root / ".braindrain/plan-reports/plan-audit-history.html"
    if not out.is_absolute():
        out = repo_root / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_history_html(snapshot), encoding="utf-8")
    print(str(out))

    if args.open:
        webbrowser.open(out.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
