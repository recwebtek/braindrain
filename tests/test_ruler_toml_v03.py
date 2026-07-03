"""Tests for Ruler v0.3+ ruler.toml template materialization."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from braindrain.workspace_primer import (
    TEMPLATES_DIR,
    _filter_ruler_toml_agents,
    _materialize_ruler_toml_text,
    deploy_templates,
)

SAMPLE_V03 = """\
# sample
default_agents = [
  "cursor",
  "codex",
  "claude",
]

[agents.cursor]
enabled = true

[agents.codex]
enabled = true

[mcp_servers.braindrain]
command = "BRAINDRAIN_LAUNCHER_PATH"
args = []
env = {}
"""

LEGACY_AGENTS_TABLE = """\
[agents]
cursor = { source = "RULES.md" }
codex = { source = "RULES.md" }
claude = { source = "RULES.md" }

[mcp_servers.braindrain]
command = "x"
"""


def test_filter_default_agents_to_single_agent() -> None:
    filtered = _filter_ruler_toml_agents(SAMPLE_V03, ["cursor"])
    assert '"cursor"' in filtered
    assert '"codex"' not in filtered
    assert '"claude"' not in filtered
    assert "[agents.codex]" not in filtered
    assert "[mcp_servers.braindrain]" in filtered


def test_filter_legacy_agents_table() -> None:
    filtered = _filter_ruler_toml_agents(LEGACY_AGENTS_TABLE, ["cursor"])
    assert "cursor = { source" in filtered
    assert "codex = { source" not in filtered
    assert "[mcp_servers.braindrain]" in filtered


def test_materialize_template_substitutes_launcher_path() -> None:
    content = _materialize_ruler_toml_text(
        "/tmp/braindrain-launcher",
        agents=None,
        all_agents=True,
    )
    assert "BRAINDRAIN_LAUNCHER_PATH" not in content
    assert "/tmp/braindrain-launcher" in content
    assert "default_agents" in content
    assert '[agents]\n' not in content
    assert "source = \"RULES.md\"" not in content


def test_deploy_templates_minimal_agents_filters_default_agents(tmp_path: Path) -> None:
    deploy_templates(tmp_path, "/bin/echo", agents=["cursor", "codex"], all_agents=False)
    ruler_toml = (tmp_path / ".ruler" / "ruler.toml").read_text(encoding="utf-8")
    assert '"cursor"' in ruler_toml
    assert '"codex"' in ruler_toml
    assert '"windsurf"' not in ruler_toml


@pytest.mark.skipif(shutil.which("npx") is None, reason="npx not available")
def test_ruler_template_applies_with_installed_ruler(tmp_path: Path) -> None:
    """Integration: materialized template must pass ``ruler apply`` validation."""
    ruler_dir = tmp_path / ".ruler"
    ruler_dir.mkdir(parents=True, exist_ok=True)
    src_agents = TEMPLATES_DIR / "AGENTS.md"
    if src_agents.is_file():
        shutil.copy2(src_agents, ruler_dir / "AGENTS.md")
    else:
        (ruler_dir / "AGENTS.md").write_text("# test\n", encoding="utf-8")

    ruler_content = _materialize_ruler_toml_text(
        "/bin/echo",
        agents=["cursor"],
        all_agents=False,
    )
    (ruler_dir / "ruler.toml").write_text(ruler_content, encoding="utf-8")

    result = subprocess.run(
        [
            "npx",
            "--yes",
            "@intellectronica/ruler",
            "apply",
            "--config",
            str(ruler_dir / "ruler.toml"),
            "--agents",
            "cursor",
            "--local-only",
            "--no-gitignore",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
