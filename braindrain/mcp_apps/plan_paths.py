"""Resolve plan file paths from repo-relative sources."""

from __future__ import annotations

from pathlib import Path


def resolve_plan_path(repo_root: Path, source: str) -> Path:
    """Return plan file path, trying IDE plan dirs when the direct path is missing."""
    rel = source.lstrip("/")

    # Security: Prevent path traversal by ensuring the requested path stays within repo_root
    try:
        # Ensure both are absolute for reliable relative_to comparison
        abs_root = repo_root.resolve()
        resolved_requested = (abs_root / rel).resolve()
        resolved_requested.relative_to(abs_root)
        # If no error, we use the safe resolved path
        direct = resolved_requested
    except (ValueError, RuntimeError, OSError):
        # Path is outside repo_root or otherwise invalid; return a safe non-existent path
        return repo_root / ".invalid_plan_source"

    if direct.is_file():
        return direct
    name = Path(rel).name
    for folder in (".cursor/plans", ".codex/plans", "plans"):
        candidate = repo_root / folder / name
        if candidate.is_file():
            return candidate
    return direct
