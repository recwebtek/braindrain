import asyncio
import os
from pathlib import Path

from braindrain.config import Config
from braindrain.telemetry import telemetry_from_config
from braindrain.workflow_engine import WorkflowEngine


def _make_test_config(tmp_path: Path) -> Config:
    # Copy base config, but override tool commands to use the fake test server
    base = Path("config/hub_config.yaml").read_text(encoding="utf-8")

    fake_cmd = f"python3 {Path('tests/fake_mcp_tool_server.py').resolve()}"

    # Minimal YAML override via string replacement (keeps test self-contained)
    # Replace repo_mapper command line
    base = base.replace("command: \"python3 /usr/local/bin/repomap_server.py\"", f"command: \"{fake_cmd}\"")
    # Replace jcodemunch command line
    base = base.replace("command: \"uvx jcodemunch-mcp\"", f"command: \"{fake_cmd}\"")

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


def test_run_workflow_executes_steps_and_routes(tmp_path):
    cfg = _make_test_config(tmp_path)
    telemetry = telemetry_from_config({"log_file": str(tmp_path / "telemetry.jsonl")})

    # No context-mode configured in this test config; routing should fall back to preview+error
    os.environ["BRAINDRAIN_DISABLE_DOCKER_SANDBOX"] = "1"
    engine = WorkflowEngine(config=cfg, telemetry=telemetry, context_mode_client_getter=lambda: None)

    result = asyncio.run(engine.run(name="ingest_codebase", args={"path": "./src", "mode": "new_project"}))
    assert result["workflow"] == "ingest_codebase"
    assert "result" in result

    # Ensure summary includes both steps (generate + index)
    summary = result["result"]
    assert "steps" in summary
    assert len(summary["steps"]) == 2

    # Second step (index) returns a large payload -> should be routed (or attempted)
    step2 = summary["steps"][1]
    assert step2["step"] == "jcodemunch.index"
    assert step2["routed"] is True

