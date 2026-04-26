from __future__ import annotations

from pathlib import Path

from braindrain.plugin_host import PluginHost


def _setup(tmp_path: Path) -> PluginHost:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        """
allow_commands: [ls, echo, cd]
blocked_commands: [curl]
blocked_prefixes: ["rm -rf"]
""".strip(),
        encoding="utf-8",
    )
    plugin_path = Path(__file__).resolve().parent.parent / "bd-plugins" / "ai-shell"
    host = PluginHost()
    load = host.load_plugin(
        "ai_shell",
        plugin_path,
        {
            "repo_root": str(repo_root),
            "session_db_path": str(tmp_path / "sessions.db"),
            "policy_path": str(policy),
            "default_mode": "hybrid",
        },
    )
    assert load["status"] == "plugin_loaded"
    assert host.register_plugin_tools("ai_shell")["status"] == "ok"
    return host


def test_hybrid_allows_real_world_for_allowlisted(tmp_path: Path) -> None:
    host = _setup(tmp_path)
    result = host.invoke_tool(
        "ai_shell_run",
        session_id="s1",
        command="echo hello",
        cwd=str(tmp_path / "repo"),
        requested_mode="hybrid",
        project_id="proj",
    )
    assert result["safety"]["policy_decision"] == "allow_real_world"
    assert result["mode_used"] == "real_world"


def test_simulated_mode_for_unknown_command(tmp_path: Path) -> None:
    host = _setup(tmp_path)
    result = host.invoke_tool(
        "ai_shell_run",
        session_id="s2",
        command="unknowncmd arg1",
        cwd=str(tmp_path / "repo"),
        requested_mode="simulated",
        project_id="proj",
    )
    assert result["safety"]["policy_decision"] == "force_simulated"
    assert result["mode_used"] == "simulated"


def test_real_world_unknown_command_is_blocked(tmp_path: Path) -> None:
    host = _setup(tmp_path)
    result = host.invoke_tool(
        "ai_shell_run",
        session_id="s3",
        command="unknowncmd arg1",
        cwd=str(tmp_path / "repo"),
        requested_mode="real_world",
        project_id="proj",
    )
    assert result["safety"]["policy_decision"] == "block"
    assert result["safety"]["blocked_reason"] == "not_allowlisted"


def test_policy_ignores_non_string_prefix_entries(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        """
allow_commands: [pwd, cd]
blocked_commands: [curl]
blocked_prefixes:
  - rm -rf
  - {bad: value}
""".strip(),
        encoding="utf-8",
    )
    plugin_path = Path(__file__).resolve().parent.parent / "bd-plugins" / "ai-shell"
    host = PluginHost()
    load = host.load_plugin(
        "ai_shell",
        plugin_path,
        {
            "repo_root": str(repo_root),
            "session_db_path": str(tmp_path / "sessions.db"),
            "policy_path": str(policy),
            "default_mode": "hybrid",
        },
    )
    assert load["status"] == "plugin_loaded"
    assert host.register_plugin_tools("ai_shell")["status"] == "ok"
    result = host.invoke_tool(
        "ai_shell_run",
        session_id="s4",
        command="pwd",
        cwd=str(repo_root),
        requested_mode="hybrid",
        project_id="proj",
    )
    assert result["safety"]["policy_decision"] == "allow_real_world"


def test_git_write_subcommand_blocked_in_real_world(tmp_path: Path) -> None:
    host = _setup(tmp_path)
    result = host.invoke_tool(
        "ai_shell_run",
        session_id="s5",
        command="git push",
        cwd=str(tmp_path / "repo"),
        requested_mode="real_world",
        project_id="proj",
    )
    assert result["safety"]["policy_decision"] == "block"
    assert result["safety"]["blocked_reason"] == "not_allowlisted"
