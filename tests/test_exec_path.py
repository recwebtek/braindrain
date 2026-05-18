"""Tests for Node/npx PATH resolution under minimal environments."""

from __future__ import annotations

import os

from braindrain.exec_path import (
    augmented_path,
    ensure_node_path_in_environ,
    resolve_command_argv,
    resolve_executable,
)


def test_augmented_path_prepends_homebrew():
    path = augmented_path()
    assert "/opt/homebrew/bin" in path.split(os.pathsep)


def test_resolve_executable_finds_npx():
    ensure_node_path_in_environ()
    npx = resolve_executable("npx")
    if npx is None:
        return  # CI without Node — skip
    assert os.path.isabs(npx)
    assert os.path.basename(npx) == "npx"


def test_resolve_command_argv_absolute_npx():
    ensure_node_path_in_environ()
    if resolve_executable("npx") is None:
        return
    argv = resolve_command_argv("npx -y context-mode")
    assert argv[0].endswith("npx") or argv[0].endswith("npx.cmd")
    assert os.path.isabs(argv[0]) or argv[0].startswith("/")
    assert argv[1:] == ["-y", "context-mode"]
