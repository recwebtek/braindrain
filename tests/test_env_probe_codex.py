"""Tests for Codex TOML detection and installer defaults."""

from __future__ import annotations

from pathlib import Path

from braindrain.env_probe import probe_app_configs
from scripts.install import configure_mcp

_ask_selection = configure_mcp._ask_selection
_build_targets = configure_mcp._build_targets


def test_probe_app_configs_reports_codex_cli_from_toml_and_preserves_json_apps(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    codex_dir = home / ".codex"
    cursor_dir = home / ".cursor"
    codex_dir.mkdir(parents=True)
    cursor_dir.mkdir(parents=True)

    (codex_dir / "config.toml").write_text(
        """
[mcp_servers.braindrain]
command = "/bin/true"
args = []
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (cursor_dir / "mcp.json").write_text(
        """{"mcpServers":{"braindrain":{"command":"/bin/true","args":[]}}}\n""",
        encoding="utf-8",
    )

    monkeypatch.setenv("HOME", str(home))

    configs = probe_app_configs()

    codex = configs["codex_cli"]
    assert codex["exists"] is True
    assert codex["config_path"] == str(codex_dir / "config.toml")
    assert codex["mcp_servers"] == ["braindrain"]

    cursor = configs["cursor"]
    assert cursor["exists"] is True
    assert cursor["config_path"] == str(cursor_dir / "mcp.json")
    assert cursor["mcp_servers"] == ["braindrain"]


def test_build_targets_collapses_codex_to_single_toml_target() -> None:
    targets = _build_targets(
        {
            "cursor": {
                "exists": True,
                "config_path": "/tmp/cursor.json",
            },
            "zed": {
                "exists": True,
                "config_path": "/tmp/zed.json",
            },
            "codex_cli": {
                "exists": True,
                "config_path": "/tmp/home/.codex/config.toml",
            },
        }
    )

    keys = [target.key for target in targets]
    assert "codex_cli" not in keys
    assert keys.count("codex_cli_toml") == 1

    codex = next(target for target in targets if target.key == "codex_cli_toml")
    assert codex.detected is True
    assert codex.style == "toml_mcp_servers"
    assert str(codex.path).endswith(".codex/config.toml")


def test_empty_installer_selection_defaults_to_cursor_zed_and_codex_toml(
    monkeypatch, capsys
) -> None:
    targets = _build_targets(
        {
            "cursor": {"exists": True, "config_path": "/tmp/cursor.json"},
            "zed": {"exists": True, "config_path": "/tmp/zed.json"},
            "codex_cli": {
                "exists": True,
                "config_path": "/tmp/home/.codex/config.toml",
            },
        }
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    selected = _ask_selection(targets)
    keys = [target.key for target in selected]

    assert keys == ["cursor", "zed", "codex_cli_toml"]

    out = capsys.readouterr().out
    assert "Cursor + Zed + Codex CLI (TOML)" in out
