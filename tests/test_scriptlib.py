from pathlib import Path

from braindrain import scriptlib
from braindrain import workspace_primer


def _make_workspace(tmp_path: Path) -> Path:
    (tmp_path / "tests").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "config").mkdir()

    (tmp_path / "config" / "marker.txt").write_text("marker-value\n", encoding="utf-8")
    (tmp_path / "tests" / "test_marker.py").write_text(
        "from pathlib import Path\n"
        "print(Path('config/marker.txt').read_text().strip())\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "echo_helper.sh").write_text(
        "#!/usr/bin/env bash\n"
        "echo helper-ok\n",
        encoding="utf-8",
    )
    return tmp_path


def test_scriptlib_harvest_search_run_and_fork(tmp_path):
    workspace = _make_workspace(tmp_path)

    enabled = scriptlib.enable(str(workspace), harvest=False)
    assert enabled["ok"] is True

    harvest = scriptlib.harvest_workspace(str(workspace))
    assert harvest["ok"] is True
    assert harvest["files_scanned"] == 2
    assert harvest["files_copied"] == 2
    assert harvest["entries_requiring_wrapper"] >= 1

    search = scriptlib.search("marker", project_path=str(workspace))
    assert search["ok"] is True
    assert search["results"]

    marker_entry = next(item for item in search["results"] if item["canonical_id"] == "tests--test_marker")
    run_result = scriptlib.run(marker_entry["script_id"], project_path=str(workspace))
    assert run_result["ok"] is True
    assert "marker-value" in run_result["stdout"]
    assert run_result["execution_mode"] in {"wrapped", "source_context"}

    recorded = scriptlib.record_result(
        marker_entry["script_id"],
        project_path=str(workspace),
        outcome="success",
        promote_status="validated",
        validate_native_copy=True,
    )
    assert recorded["ok"] is True
    described = scriptlib.describe(marker_entry["script_id"], project_path=str(workspace))
    assert described["script"]["status"] == "validated"
    assert described["script"]["execution_mode"] == "native_copy"

    forked = scriptlib.fork(
        marker_entry["script_id"],
        project_path=str(workspace),
        new_variant_or_version="v2",
    )
    assert forked["ok"] is True
    assert forked["script_id"].endswith(":v2")


def test_deploy_templates_includes_guidance_only_when_enabled(tmp_path):
    launcher = "/tmp/braindrain"

    disabled_workspace = tmp_path / "disabled"
    disabled_workspace.mkdir()
    workspace_primer.deploy_templates(disabled_workspace, launcher)
    disabled_rules = (disabled_workspace / ".ruler" / "RULES.md").read_text(encoding="utf-8")
    assert "scriptlib before writing a new task script" not in disabled_rules

    enabled_workspace = tmp_path / "enabled"
    enabled_workspace.mkdir()
    scriptlib.enable(str(enabled_workspace), harvest=False)
    workspace_primer.deploy_templates(enabled_workspace, launcher)
    enabled_rules = (enabled_workspace / ".ruler" / "RULES.md").read_text(encoding="utf-8")
    enabled_agents = (enabled_workspace / ".ruler" / "AGENTS.md").read_text(encoding="utf-8")
    assert "scriptlib before writing a new task script" in enabled_rules
    assert "scriptlib before writing a new task script" in enabled_agents


def test_prime_keeps_working_when_scriptlib_seed_fails(tmp_path, monkeypatch):
    workspace = _make_workspace(tmp_path)

    monkeypatch.setattr(
        workspace_primer,
        "run_ruler_apply",
        lambda *args, **kwargs: {
            "ok": True,
            "stdout": "",
            "stderr": "",
            "command": "ruler apply",
            "returncode": 0,
        },
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("seed failed")

    monkeypatch.setattr(workspace_primer, "seed_if_enabled", _boom)

    result = workspace_primer.prime(path=str(workspace))
    assert result["ok"] is True
    assert result["scriptlib"]["ok"] is False
    assert "seed failed" in result["scriptlib"]["error"]
