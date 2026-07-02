"""Scriptlib tool implementations extracted from server.py."""

from __future__ import annotations


def scriptlib_refresh_index_impl(
    project_scriptlib_root,
    global_scriptlib_root,
    scriptlib_is_enabled,
    scriptlib_refresh_index,
    path: str = ".",
    scope: str = "project",
    dry_run: bool = False,
) -> dict:
    if scope not in {"project", "global", "all"}:
        return {"ok": False, "error": f"Unsupported scope: {scope}"}
    roots = []
    if scope in {"project", "all"}:
        roots.append(project_scriptlib_root(path))
    if scope in {"global", "all"}:
        roots.append(global_scriptlib_root())
    results = []
    for root in roots:
        if not scriptlib_is_enabled(root):
            results.append({"ok": True, "root": str(root), "skipped": "scriptlib_disabled"})
            continue
        results.append(scriptlib_refresh_index(root, dry_run=dry_run))
    return {
        "ok": all(item.get("ok", False) for item in results),
        "scope": scope,
        "results": results,
    }
