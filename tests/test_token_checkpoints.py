"""Token checkpoint path resolution (project root vs MCP cwd)."""

from __future__ import annotations

from pathlib import Path

from braindrain.telemetry import TelemetrySession
from braindrain.token_checkpoints import append_checkpoint, default_checkpoint_path


def test_default_checkpoint_path_uses_project_root(tmp_path: Path) -> None:
    workspace = tmp_path / "my-project"
    workspace.mkdir()
    assert default_checkpoint_path(workspace) == workspace / ".braindrain" / "token-metrics.jsonl"


def test_append_checkpoint_writes_under_project_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    telemetry = TelemetrySession(log_file=tmp_path / "session.jsonl")

    result = append_checkpoint(
        phase="start",
        task="unit-test",
        note="checkpoint path test",
        context_tags=["test"],
        telemetry=telemetry,
        project_root=workspace,
        tool="record_token_checkpoint",
    )

    assert result["ok"] is True
    out_path = Path(result["path"])
    assert out_path == workspace / ".braindrain" / "token-metrics.jsonl"
    assert out_path.exists()
    row = out_path.read_text(encoding="utf-8").strip().splitlines()[-1]
    assert '"schema_version": "1.0"' in row or '"schema_version":"1.0"' in row
    assert '"phase": "start"' in row or '"phase":"start"' in row
