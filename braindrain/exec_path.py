"""Resolve Node.js CLI tools when MCP runs under a minimal PATH (e.g. Cursor GUI)."""

from __future__ import annotations

import os
import shlex
import shutil
from collections.abc import Iterable
from pathlib import Path

_NODE_CLI_NAMES = frozenset({"npx", "npm", "node", "pnpm", "yarn", "corepack"})


def _home() -> Path:
    return Path.home()


def node_bin_prefixes() -> list[str]:
    """Directories that commonly host ``npx`` when GUI apps omit them from PATH."""
    home = _home()
    prefixes: list[str] = []

    for fixed in (
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/opt/local/bin",
    ):
        prefixes.append(fixed)

    # fnm / volta / asdf shims
    for rel in (
        ".fnm/current/bin",
        ".volta/bin",
        ".asdf/shims",
        ".local/share/pnpm",
        ".npm-global/bin",
    ):
        prefixes.append(str(home / rel))

    nvm_dir = Path(os.environ.get("NVM_DIR", str(home / ".nvm")))
    nvm_current = nvm_dir / "alias" / "default"
    if nvm_current.is_file():
        try:
            version = nvm_current.read_text(encoding="utf-8").strip()
            if version:
                prefixes.append(str(nvm_dir / "versions" / "node" / version / "bin"))
        except OSError:
            pass
    nvm_versions = nvm_dir / "versions" / "node"
    if nvm_versions.is_dir():
        try:
            versions = sorted(p.name for p in nvm_versions.iterdir() if p.is_dir())
            if versions:
                prefixes.append(str(nvm_versions / versions[-1] / "bin"))
        except OSError:
            pass

    return prefixes


def augmented_path(*, extra_prefixes: Iterable[str] | None = None) -> str:
    """Build PATH with Node install dirs prepended (deduped, order preserved)."""
    parts: list[str] = []
    if extra_prefixes:
        parts.extend(str(p) for p in extra_prefixes if p)
    parts.extend(node_bin_prefixes())
    parts.extend(os.environ.get("PATH", "").split(os.pathsep))

    seen: set[str] = set()
    ordered: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.add(part)
            ordered.append(part)
    return os.pathsep.join(ordered)


def ensure_node_path_in_environ() -> str:
    """Patch ``os.environ['PATH']`` for this process; return the new PATH."""
    path = augmented_path()
    os.environ["PATH"] = path
    return path


def resolve_executable(name: str) -> str | None:
    """Return absolute path to ``name`` after PATH augmentation, or None."""
    ensure_node_path_in_environ()
    return shutil.which(name)


def resolve_command_argv(command: str) -> list[str]:
    """Split a shell command and resolve the executable to an absolute path when possible."""
    argv = shlex.split(command)
    if not argv:
        return argv
    head = argv[0]
    base = Path(head).name
    if base in _NODE_CLI_NAMES or "/" not in head:
        resolved = resolve_executable(base if base in _NODE_CLI_NAMES else head)
        if resolved:
            argv[0] = resolved
    return argv
