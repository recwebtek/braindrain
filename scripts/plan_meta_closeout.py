#!/usr/bin/env python3
"""Split a meta plan into child plan skeletons and wire _master.plan.md."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from plan_branch_utils import (  # noqa: E402
    FRONTMATTER_BLOCK_RE,
    meta_slug_from_path,
    parse_frontmatter_children_spec,
    parse_frontmatter_todos,
    parse_plan_frontmatter,
    plan_body_after_frontmatter,
    render_frontmatter_todos,
    set_frontmatter_yaml_block,
    slice_body_section,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Meta-plan closeout: child skeletons + master links.")
    p.add_argument("--meta", required=True, help="Path to meta *.plan.md")
    p.add_argument("--repo-root", default=".", help="Git repository root")
    p.add_argument("--dry-run", action="store_true", help="Report actions without writing files")
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing child plan files",
    )
    p.add_argument(
        "--run-auditor",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Invoke daily_plan_audit.py after closeout (default: true)",
    )
    return p.parse_args()


def _validate_meta_plan(meta_path: Path) -> tuple[dict[str, object], list[dict[str, str]]]:
    fm = parse_plan_frontmatter(meta_path)
    if str(fm.get("disposition") or "").strip() != "meta":
        raise ValueError(f"plan disposition must be meta: {meta_path}")
    text = meta_path.read_text(encoding="utf-8", errors="ignore")
    specs = parse_frontmatter_children_spec(text)
    if not specs:
        raise ValueError(f"children_spec required in meta plan: {meta_path}")
    for spec in specs:
        if not spec.get("file") or not spec.get("id"):
            raise ValueError(f"each children_spec entry needs id and file: {spec}")
    return fm, specs


def _child_skeleton(
    spec: dict[str, str],
    *,
    parent_slug: str,
    meta_body: str,
) -> tuple[str, bool]:
    """Return (content, body_complete). body_complete=False when section stub only."""
    child_id = spec["id"]
    name = spec.get("name") or child_id
    branch = spec.get("branch") or ""
    section = spec.get("section") or ""
    body_slice = slice_body_section(meta_body, section) if section else ""
    body_complete = bool(body_slice.strip())
    if body_complete:
        body = body_slice
    else:
        anchor = section or f"## {name}"
        body = (
            f"<!-- body: extract from parent section {anchor} -->\n\n"
            f"# {name}\n\n"
            f"_Implementation details pending extraction from meta plan._\n"
        )
    lines = [
        "---",
        f"name: {name}",
        "disposition: active",
        f"parent: {parent_slug}",
    ]
    if branch:
        lines.append(f"branch: {branch}")
    branches = str(spec.get("branches") or "").strip()
    if branches:
        lines.append(f"branches: {branches}")
    lines.extend(
        [
            "todos:",
            f"  - id: impl-{child_id}",
            f'    content: "Implement {name}"',
            "    status: pending",
            "---",
            "",
            body.rstrip(),
            "",
        ]
    )
    return "\n".join(lines), body_complete


def _sync_meta_todos(text: str, specs: list[dict[str, str]], plans_dir: Path) -> str:
    todos = parse_frontmatter_todos(text)
    if not todos:
        return text
    created_ids = {spec["id"] for spec in specs if (plans_dir / str(spec.get("file"))).is_file()}
    updated = False
    for todo in todos:
        todo_id = todo.get("id", "")
        if not todo_id.startswith("split-"):
            continue
        child_id = todo_id[len("split-") :]
        if child_id in created_ids and todo.get("status") != "completed":
            todo["status"] = "completed"
            updated = True
    if not updated:
        return text
    return set_frontmatter_yaml_block(text, "todos", render_frontmatter_todos(todos))


def _append_master_active_links(
    master_path: Path,
    child_files: list[str],
    *,
    child_titles: dict[str, str],
) -> bool:
    if not master_path.is_file():
        return False
    text = master_path.read_text(encoding="utf-8", errors="ignore")
    fm_match = FRONTMATTER_BLOCK_RE.match(text)
    fm_block = fm_match.group(0) if fm_match else ""
    body = text[len(fm_block) :]
    existing_targets: set[str] = set()
    for _label, target in re.findall(r"\[([^\]]*)\]\(([^)]+)\)", body):
        existing_targets.add(target.split("/")[-1])
    new_bullets: list[str] = []
    for child_file in child_files:
        basename = Path(child_file).name
        if basename in existing_targets:
            continue
        title = child_titles.get(child_file, basename)
        new_bullets.append(f"- [{title}]({basename})")
    if not new_bullets:
        return False
    if "## active" in body.lower():
        lines = body.splitlines()
        insert_at = len(lines)
        for idx, line in enumerate(lines):
            if line.strip().lower() == "## active":
                for j in range(idx + 1, len(lines)):
                    if lines[j].startswith("## "):
                        insert_at = j
                        break
                else:
                    insert_at = len(lines)
                break
        lines[insert_at:insert_at] = new_bullets
        body = "\n".join(lines).rstrip() + "\n"
    else:
        body = body.rstrip() + "\n\n## active\n\n" + "\n".join(new_bullets) + "\n"
    master_path.write_text(fm_block + body, encoding="utf-8")
    return True


def run_closeout(
    meta_path: Path,
    repo_root: Path,
    *,
    dry_run: bool = False,
    force: bool = False,
    run_auditor: bool = True,
) -> dict[str, object]:
    meta_path = meta_path.resolve()
    rel_meta = meta_path.relative_to(repo_root).as_posix()
    if not str(rel_meta).startswith(".cursor/plans/"):
        raise ValueError("meta plan must live under .cursor/plans/ (not QA-Logs/)")

    fm, specs = _validate_meta_plan(meta_path)
    parent_slug = meta_slug_from_path(meta_path)
    plans_dir = meta_path.parent
    meta_text = meta_path.read_text(encoding="utf-8", errors="ignore")
    meta_body = plan_body_after_frontmatter(meta_text)

    created: list[str] = []
    skipped: list[str] = []
    body_pending: list[str] = []
    child_titles: dict[str, str] = {}

    for spec in specs:
        child_file = str(spec["file"]).strip()
        child_path = plans_dir / child_file
        child_titles[child_file] = str(spec.get("name") or spec.get("id") or child_file)
        if child_path.is_file() and not force:
            skipped.append(child_file)
            content, complete = _child_skeleton(spec, parent_slug=parent_slug, meta_body=meta_body)
            if not complete:
                body_pending.append(child_file)
            continue
        content, complete = _child_skeleton(spec, parent_slug=parent_slug, meta_body=meta_body)
        if not complete:
            body_pending.append(child_file)
        if dry_run:
            created.append(child_file)
            continue
        child_path.write_text(content, encoding="utf-8")
        created.append(child_file)

    children_list = [str(spec["file"]).strip() for spec in specs]
    if not dry_run:
        updated_meta = set_frontmatter_yaml_block(
            meta_text,
            "children",
            ["children:"] + [f"  - {name}" for name in children_list],
        )
        updated_meta = _sync_meta_todos(updated_meta, specs, plans_dir)
        meta_path.write_text(updated_meta, encoding="utf-8")

        master_path = plans_dir / "_master.plan.md"
        if master_path.is_file():
            _append_master_active_links(master_path, children_list, child_titles=child_titles)

        exec_order = fm.get("execution_order")
        if isinstance(exec_order, list) and exec_order and master_path.is_file():
            master_text = master_path.read_text(encoding="utf-8", errors="ignore")
            if "execution_order:" not in master_text:
                block = ["execution_order:"] + [
                    f"  - {entry}" for entry in exec_order if str(entry).strip()
                ]
                master_path.write_text(
                    set_frontmatter_yaml_block(master_text, "execution_order", block),
                    encoding="utf-8",
                )

    auditor_ran = False
    if run_auditor and not dry_run:
        audit_script = repo_root / "scripts" / "daily_plan_audit.py"
        if audit_script.is_file():
            subprocess.run(
                [
                    sys.executable,
                    str(audit_script),
                    "--repo-root",
                    str(repo_root),
                    "--trigger",
                    "meta-closeout",
                ],
                check=False,
            )
            auditor_ran = True

    return {
        "ok": True,
        "metaPlan": rel_meta,
        "dryRun": dry_run,
        "created": created,
        "skipped": skipped,
        "body_pending": body_pending,
        "children_spec_count": len(specs),
        "auditorRan": auditor_ran,
        "message": (
            "Run agent phase 2 for body_pending children, then /masterplan"
            if body_pending
            else "Child skeletons ready; run /masterplan"
        ),
    }


def main() -> int:
    args = _parse_args()
    repo_root = Path(args.repo_root).expanduser().resolve()
    meta_arg = Path(args.meta)
    meta_path = meta_arg if meta_arg.is_absolute() else (repo_root / meta_arg)
    try:
        result = run_closeout(
            meta_path,
            repo_root,
            dry_run=args.dry_run,
            force=args.force,
            run_auditor=args.run_auditor,
        )
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
