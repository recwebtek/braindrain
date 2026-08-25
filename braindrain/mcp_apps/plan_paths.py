"""Resolve plan file paths from repo-relative sources."""

from __future__ import annotations

from pathlib import Path


def resolve_plan_path(repo_root: Path, source: str) -> Path:
    """Return plan file path, trying IDE plan dirs when the direct path is missing."""
    repo_abs = repo_root.resolve()
    rel = source.lstrip("/")

    # Guard against path traversal by ensuring any resolved path is within repo_root
    try:
        # Check if the requested path is safe
        requested_path = (repo_root / rel).resolve()
        requested_path.relative_to(repo_abs)
        # If it didn't raise ValueError, it's inside repo_root
        if requested_path.is_file():
            return requested_path
    except (ValueError, RuntimeError):
        # Traversal attempted or outside repo_root; strip to just the filename
        rel = Path(rel).name

    # Not found at direct path or traversal attempted, try IDE folders
    name = Path(rel).name
    for folder in (".cursor/plans", ".codex/plans", "plans"):
        candidate = repo_root / folder / name
        try:
            # Re-verify candidate just in case, though folders are hardcoded
            candidate_abs = candidate.resolve()
            candidate_abs.relative_to(repo_abs)
            if candidate_abs.is_file():
                return candidate_abs
        except (ValueError, RuntimeError):
            continue

    return repo_root / rel
