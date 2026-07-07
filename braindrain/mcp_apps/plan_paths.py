"""Resolve plan file paths from repo-relative sources."""

from __future__ import annotations

from pathlib import Path


def resolve_plan_path(repo_root: Path, source: str) -> Path:
    """Return plan file path, trying IDE plan dirs when the direct path is missing."""
    # Ensure repo_root is absolute
    repo_root = repo_root.resolve()

    rel = source.lstrip("/")
    # Join and resolve to eliminate '..' and ensure we have an absolute path
    target = (repo_root / rel).resolve()

    # Path traversal check: must be within repo_root
    try:
        target.relative_to(repo_root)
    except ValueError:
        # If traversal detected, fallback to a safe default within repo (non-existent)
        # instead of allowing access to system files.
        return repo_root / "invalid_plan_path"

    if target.is_file():
        return target

    # Try IDE plan dirs for just the filename, still ensuring they are within repo_root
    name = Path(rel).name
    for folder in (".cursor/plans", ".codex/plans", "plans"):
        candidate = (repo_root / folder / name).resolve()
        try:
            candidate.relative_to(repo_root)
            if candidate.is_file():
                return candidate
        except ValueError:
            continue

    return target
