#!/usr/bin/env python3
"""Ensure plan branch exists and checkout before Cursor Plan Build implementation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from plan_branch_utils import (
    branch_ref_exists,
    checkout_plan_branch,
    create_branch_ref,
    current_branch,
    is_meta_plan,
    parse_plan_disposition,
    resolve_base_branch,
    resolve_plan_branch,
    slug_from_plan_path,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Plan Build branch guard (create + checkout).")
    p.add_argument("--plan", required=True, help="Repo-relative or absolute path to *.plan.md")
    p.add_argument("--repo-root", default=".", help="Git repository root")
    p.add_argument(
        "--create-only",
        action="store_true",
        help="Create branch if missing but do not checkout",
    )
    p.add_argument(
        "--no-stash",
        action="store_true",
        help="Refuse checkout when working tree is dirty (no stash)",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    repo_root = Path(args.repo_root).expanduser().resolve()
    plan_arg = Path(args.plan)
    plan_path = plan_arg if plan_arg.is_absolute() else (repo_root / plan_arg)
    if not plan_path.is_file():
        print(json.dumps({"ok": False, "error": f"plan not found: {plan_path}"}))
        return 2

    rel_plan = plan_path.relative_to(repo_root).as_posix()
    disposition = parse_plan_disposition(plan_path)

    if is_meta_plan(plan_path):
        out = {
            "ok": False,
            "error": "meta_plan_no_build",
            "guardReason": "meta_plan_no_build",
            "disposition": disposition,
            "planSource": rel_plan,
            "message": (
                "Meta plans are not buildable. Run /metaplan-closeout to create child "
                "plans, then Build on a child plan file."
            ),
        }
        print(json.dumps(out, indent=2))
        return 1

    branch = resolve_plan_branch(plan_path)
    base = resolve_base_branch(repo_root)
    slug = slug_from_plan_path(plan_path)

    out: dict[str, object] = {
        "ok": True,
        "planSource": rel_plan,
        "disposition": disposition,
        "branch": branch,
        "baseBranch": base,
        "branchCreated": False,
        "checkedOut": False,
        "previousBranch": current_branch(repo_root),
    }

    if not branch_ref_exists(repo_root, branch):
        ok, msg = create_branch_ref(repo_root, branch, base)
        out["branchCreated"] = ok and msg == "created"
        if not ok:
            out["ok"] = False
            out["error"] = msg
            print(json.dumps(out))
            return 1

    if args.create_only:
        print(json.dumps(out))
        return 0

    switch = checkout_plan_branch(
        repo_root,
        branch,
        plan_slug=slug,
        allow_stash=not args.no_stash,
    )
    out.update(switch)
    out["checkedOut"] = bool(switch.get("ok"))
    if not switch.get("ok"):
        out["ok"] = False
    print(json.dumps(out, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
