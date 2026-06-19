"""Resolve plan file paths from repo-relative sources."""

from __future__ import annotations

from pathlib import Path


def resolve_plan_path(repo_root: Path, source: str) -> Path:
    """Return plan file path, trying IDE plan dirs when the direct path is missing."""
    rel = source.lstrip("/")
    direct = repo_root / rel
    if direct.is_file():
        return direct
    name = Path(rel).name
    for folder in (".cursor/plans", ".codex/plans", "plans"):
        candidate = repo_root / folder / name
        if candidate.is_file():
            return candidate
    return direct
