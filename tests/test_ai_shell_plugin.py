from __future__ import annotations

from pathlib import Path

from braindrain.plugin_host import PluginHost
from braindrain.session import SessionStore


def _plugin_context(tmp_path: Path) -> dict:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    policy = tmp_path / "ai_shell_policy.yaml"
    policy.write_text(
        """
allow_commands: [ls, pwd, echo, cd]
blocked_commands: [rm, curl]
blocked_prefixes: ["rm -rf"]
""".strip(),
        encoding="utf-8",
    )
    return {
        "repo_root": str(repo_root),
        "session_db_path": str(tmp_path / "sessions.db"),
        "policy_path": str(policy),
        "default_mode": "hybrid",
    }


def _host_with_plugin(tmp_path: Path) -> PluginHost:
    host = PluginHost()
    plugin_path = Path(__file__).resolve().parent.parent / "bd-plugins" / "ai-shell"
    loaded = host.load_plugin("ai_shell", plugin_path, _plugin_context(tmp_path))
    assert loaded["status"] == "plugin_loaded"
    registered = host.register_plugin_tools("ai_shell")
    assert registered["status"] == "ok"
    return host


def test_ai_shell_cd_is_token_minimal_and_stateful(tmp_path: Path) -> None:
    host = _host_with_plugin(tmp_path)
    project_root = tmp_path / "repo"
    work_dir = project_root / "src"
    work_dir.mkdir(parents=True, exist_ok=True)

    response = host.invoke_tool(
        "ai_shell_run",
        session_id="s1",
        command="cd src",
        cwd=str(project_root),
        requested_mode="hybrid",
        project_id="p1",
    )
    assert response["output_text"] == f"__CD__:{work_dir}"
    assert response["signals"]["cd"] == str(work_dir)
    assert response["cwd_after"] == str(work_dir)

    sync = host.invoke_tool("ai_shell_state_sync", session_id="s1", project_id="p1")
    assert sync["cwd_after"] == str(work_dir)


def test_ai_shell_blocks_destructive_command(tmp_path: Path) -> None:
    host = _host_with_plugin(tmp_path)
    response = host.invoke_tool(
        "ai_shell_run",
        session_id="s2",
        command="rm -rf .",
        cwd=str(tmp_path / "repo"),
        requested_mode="real_world",
        project_id="p2",
    )
    assert response["safety"]["policy_decision"] == "block"
    assert response["safety"]["blocked_reason"] == "destructive_command"


def test_ai_shell_records_efficiency_metrics(tmp_path: Path) -> None:
    host = _host_with_plugin(tmp_path)
    repo_root = tmp_path / "repo"
    host.invoke_tool(
        "ai_shell_run",
        session_id="s3",
        command="pwd",
        cwd=str(repo_root),
        requested_mode="hybrid",
        project_id="p3",
    )
    db_path = tmp_path / "sessions.db"
    metrics = SessionStore(db_path).get_ai_shell_metrics(project_id="p3", session_id="s3")
    assert metrics["command_count"] == 1
    assert metrics["total_request_bytes"] > 0
    assert metrics["total_response_bytes"] > 0
    assert metrics["total_estimated_tokens"] > 0
