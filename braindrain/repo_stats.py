"""Lightweight repository statistics for workflow gating."""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".braindrain",
    ".cursor",
    "dist",
    "build",
    ".next",
    "target",
}

_DEFAULT_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".rb",
    ".php",
    ".cs",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".swift",
    ".scala",
    ".md",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
}


def count_repo_files(
    path: str | Path = ".",
    *,
    extensions: set[str] | None = None,
    skip_dirs: set[str] | None = None,
    max_files: int = 50_000,
) -> int:
    """
    Count source-like files under `path` (best-effort, bounded walk).

    Used by ingest_codebase to decide whether to run ai_distiller first.
    """
    root = Path(path).resolve()
    if not root.exists():
        return 0

    ext_set = extensions if extensions is not None else _DEFAULT_EXTENSIONS
    skip = skip_dirs if skip_dirs is not None else _DEFAULT_SKIP_DIRS
    count = 0

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext_set and ext not in ext_set:
                continue
            count += 1
            if count >= max_files:
                return count

    return count
