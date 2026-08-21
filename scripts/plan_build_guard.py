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
    is_git_repo,
    is_meta_plan,
    parse_plan_disposition,
    plan_is_inside_repo,
    plan_lookup_roots,
    relative_plan_source,
    resolve_plan_base_branch,
    resolve_plan_branch,
    resolve_plan_path,
    slug_from_plan_path,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Plan Build branch guard (create + checkout).")
    p.add_argument(
        "--plan", required=True, help="Absolute, repo-relative, or workspace-relative *.plan.md"
    )
    p.add_argument(
        "--repo-root", default=".", help="Git repository root (where the branch is created)"
    )
    p.add_argument(
        "--plans-root",
        default=None,
        help="Directory to resolve --plan against when plans live outside the code repo",
    )
    p.add_argument(
        "--base-branch",
        default=None,
        help="Base branch for a new plan branch (overrides plan frontmatter and repo default)",
    )
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
    plans_root = Path(args.plans_root).expanduser().resolve() if args.plans_root else None

    if not is_git_repo(repo_root):
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "not_a_git_repo",
                    "repoRoot": repo_root.as_posix(),
                    "message": "--repo-root must point at a git repository (the code repo).",
                }
            )
        )
        return 2

    plan_path = resolve_plan_path(args.plan, repo_root, plans_root)
    if not plan_path.is_file():
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"plan not found: {plan_path}",
                    "searchedRoots": [
                        root.as_posix() for root in plan_lookup_roots(repo_root, plans_root)
                    ],
                    "message": "Pass --plans-root when plans live outside the code repo.",
                }
            )
        )
        return 2

    rel_plan = relative_plan_source(plan_path, repo_root)
    disposition = parse_plan_disposition(plan_path)

    if is_meta_plan(plan_path):
        out = {
            "ok": False,
            "error": "meta_plan_no_build",
            "guardReason": "meta_plan_no_build",
            "disposition": disposition,
            "planSource": rel_plan,
            "planPath": plan_path.as_posix(),
            "message": (
                "Meta plans are not buildable. Run /metaplan-closeout to create child "
                "plans, then Build on a child plan file."
            ),
        }
        print(json.dumps(out, indent=2))
        return 1

    branch = resolve_plan_branch(plan_path)
    base = resolve_plan_base_branch(plan_path, repo_root, args.base_branch)
    slug = slug_from_plan_path(plan_path)

    out: dict[str, object] = {
        "ok": True,
        "planSource": rel_plan,
        "planPath": plan_path.as_posix(),
        "repoRoot": repo_root.as_posix(),
        "planOutsideRepo": not plan_is_inside_repo(plan_path, repo_root),
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
