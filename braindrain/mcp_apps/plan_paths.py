"""Resolve plan file paths from repo-relative sources."""

from __future__ import annotations

from pathlib import Path


def resolve_plan_path(repo_root: Path, source: str) -> Path:
    """Return plan file path, trying IDE plan dirs when the direct path is missing."""
    rel = source.lstrip("/")
    root_abs = repo_root.resolve()

    def _is_safe(p: Path) -> bool:
        try:
            p.resolve().relative_to(root_abs)
            return True
        except ValueError:
            return False

    direct = repo_root / rel
    if direct.is_file() and _is_safe(direct):
        return direct

    name = Path(rel).name
    for folder in (".cursor/plans", ".codex/plans", "plans"):
        candidate = repo_root / folder / name
        if candidate.is_file() and _is_safe(candidate):
            return candidate

    # Security: Ensure we don't return an escaped path even as a fallback
    if not _is_safe(direct):
        return root_abs / name

    return direct
