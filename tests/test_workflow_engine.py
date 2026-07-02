import asyncio
import os
import sys
from pathlib import Path

from braindrain.config import Config
from braindrain.task_manager import TaskManager
from braindrain.telemetry import telemetry_from_config
from braindrain.workflow_engine import WorkflowEngine


def _make_test_config(tmp_path: Path) -> Config:
    # Copy base config, but override tool commands to use the fake test server
    base = Path("config/hub_config.yaml").read_text(encoding="utf-8")

    fake_cmd = f"{sys.executable} {Path('tests/fake_mcp_tool_server.py').resolve()}"

    # Minimal YAML override via string replacement (keeps test self-contained)
    # Replace repo_mapper command line
    base = base.replace(
        'command: "python3 /usr/local/bin/repomap_server.py"', f'command: "{fake_cmd}"'
    )
    # Replace jcodemunch command line
    base = base.replace('command: "uvx jcodemunch-mcp==1.108.53"', f'command: "{fake_cmd}"')

    cfg_path = tmp_path / "hub_config.yaml"
    cfg_path.write_text(base, encoding="utf-8")
    return Config(cfg_path)


def test_workflow_catalog_present(tmp_path):
    cfg = _make_test_config(tmp_path)
    catalog = cfg.get_workflow_catalog()
    assert catalog["count"] >= 2
    names = {w["name"] for w in catalog["workflows"]}
    assert "ingest_codebase" in names
    assert "refactor_prep" in names
    assert "refactor_prep_token_light" in names


def test_run_workflow_executes_steps_and_routes(tmp_path):
    cfg = _make_test_config(tmp_path)
    telemetry = telemetry_from_config({"log_file": str(tmp_path / "telemetry.jsonl")})

    # No context-mode configured in this test config; routing should fall back to preview+error
    os.environ["BRAINDRAIN_DISABLE_DOCKER_SANDBOX"] = "1"
    engine = WorkflowEngine(
        config=cfg, telemetry=telemetry, context_mode_client_getter=lambda: None
    )

    result = asyncio.run(
        engine.run(name="ingest_codebase", args={"path": "./src", "mode": "new_project"})
    )
    assert result["workflow"] == "ingest_codebase"
    assert "result" in result

    # ingest_codebase: optional distiller + generate + index
    summary = result["result"]
    assert "steps" in summary
    assert len(summary["steps"]) == 3

    # Last step (index) returns a large payload -> should be routed (or attempted)
    index_step = summary["steps"][-1]
    assert index_step["step"] == "jcodemunch.index"
    assert index_step["routed"] is True


def test_task_manager_tracks_completion() -> None:
    manager = TaskManager()

    async def _run() -> None:
        record = await manager.submit(
            task_type="unit", runner=lambda: asyncio.sleep(0, result={"ok": True})
        )
        assert record.status in {"queued", "running"}
        await asyncio.sleep(0.01)
        state = await manager.as_dict(record.task_id)
        assert state["status"] == "completed"
        assert state["result"] == {"ok": True}

    asyncio.run(_run())
