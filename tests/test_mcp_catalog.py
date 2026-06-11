"""MCP catalog export tests (P1.2)."""

from __future__ import annotations

from pathlib import Path

from braindrain.config import Config
from braindrain.mcp_catalog import collect_catalog_rows, export_mcp_catalog, render_tool_markdown


def _sample_config(tmp_path: Path) -> Config:
    cfg_path = tmp_path / "hub_config.yaml"
    cfg_path.write_text(
        """
version: "1.0"
project_name: test
mcp_tools:
  - name: github
    command: npx github-mcp
    defer_loading: true
    hot: false
    tags: [git, pr]
    description: GitHub operations for PRs and issues.
    token_weight: high
""",
        encoding="utf-8",
    )
    return Config(cfg_path)


def test_render_tool_markdown_includes_metadata(tmp_path: Path) -> None:
    row = collect_catalog_rows(
        _sample_config(tmp_path).data,
    )[0]
    md = render_tool_markdown(row)
    assert "defer_loading" in md
    assert "token_weight" in md
    assert "github" in md


def test_export_writes_per_server_tree(tmp_path: Path) -> None:
    config = _sample_config(tmp_path)
    out = tmp_path / "catalog"
    result = export_mcp_catalog(
        config=config.data,
        output_dir=out,
        native_tools=None,
        dry_run=False,
    )
    assert result["ok"] is True
    assert result["tool_count"] == 1
    tool_file = out / "github" / "tools" / "github.md"
    assert tool_file.exists()
    assert (out / "README.md").exists()
    assert "GitHub operations" in tool_file.read_text(encoding="utf-8")


def test_export_dry_run_plans_files_without_write(tmp_path: Path) -> None:
    config = _sample_config(tmp_path)
    out = tmp_path / "catalog"
    result = export_mcp_catalog(
        config=config.data,
        output_dir=out,
        dry_run=True,
    )
    assert result["dry_run"] is True
    assert not out.exists()


def test_collect_merges_native_tools(tmp_path: Path) -> None:
    config = _sample_config(tmp_path)

    class _Tool:
        name = "route_output"
        description = "Route large outputs through context-mode."
        tags = ["output"]
        parameters = {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Content to route or return inline when below threshold.",
                }
            },
        }

    rows = collect_catalog_rows(config.data, native_tools=[_Tool()])
    names = {r.name for r in rows}
    assert "github" in names
    assert "route_output" in names
    native = next(r for r in rows if r.name == "route_output")
    assert native.server == "braindrain"
    assert native.source == "native"
    md = render_tool_markdown(native)
    assert "## Parameters" in md
    assert "text" in md


def test_render_hub_tool_parameters_from_input_examples(tmp_path: Path) -> None:
    cfg_path = tmp_path / "hub_config.yaml"
    cfg_path.write_text(
        """
version: "1.0"
project_name: test
mcp_tools:
  - name: repo_mapper
    command: npx repo-mapper
    description: Map repository structure.
    input_examples:
      - path: .
        max_depth: 3
""",
        encoding="utf-8",
    )
    row = collect_catalog_rows(Config(cfg_path).data)[0]
    md = render_tool_markdown(row)
    assert "## Parameters" in md
    assert "path" in md
    assert "external MCP server" in md
