"""Export MCP tool catalog for folder-discovery (Cursor dynamic-context pattern)."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from braindrain.config import Config
from braindrain.tool_registry import ToolRegistry
from braindrain.types import ConfigData, MCPToolConfig

BRAINDRAIN_SERVER = "braindrain"
_NATIVE_TOKEN_WEIGHT: dict[str, str] = {
    "route_output": "low",
    "search_index": "low",
    "search_tools": "negligible",
    "get_env_context": "negligible",
    "refresh_env_context": "low",
    "get_token_dashboard": "negligible",
    "get_token_stats": "negligible",
    "record_token_checkpoint": "negligible",
    "prime_workspace": "medium",
    "run_workflow": "medium",
    "plan_workflow": "low",
}


@dataclass
class CatalogToolRow:
    name: str
    server: str
    description: str
    defer_loading: bool
    token_weight: str
    hot: bool = False
    tags: list[str] = field(default_factory=list)
    transport: str = ""
    command: str = ""
    roles: list[str] = field(default_factory=list)
    bundles: list[str] = field(default_factory=list)
    source: str = "hub_config"  # hub_config | native


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", name.strip()).strip("-").lower()
    return slug or "tool"


def _one_line(text: str, *, max_len: int = 240) -> str:
    line = " ".join((text or "").split())
    if len(line) <= max_len:
        return line
    return line[: max_len - 3] + "..."


def _row_from_hub_tool(tool: MCPToolConfig) -> CatalogToolRow:
    return CatalogToolRow(
        name=tool.name,
        server=tool.name,
        description=_one_line(tool.description),
        defer_loading=bool(tool.defer_loading),
        token_weight=str(tool.token_weight or "medium"),
        hot=bool(tool.hot),
        tags=list(tool.tags or []),
        transport=tool.transport or "",
        command=tool.command or "",
        roles=list(tool.roles or []),
        bundles=list(tool.bundles or []),
        source="hub_config",
    )


def _row_from_native_tool(tool: Any) -> CatalogToolRow:
    name = str(getattr(tool, "name", "") or "unknown")
    description = _one_line(str(getattr(tool, "description", "") or ""))
    tags = list(getattr(tool, "tags", None) or [])
    return CatalogToolRow(
        name=name,
        server=BRAINDRAIN_SERVER,
        description=description,
        defer_loading=False,
        token_weight=_NATIVE_TOKEN_WEIGHT.get(name, "medium"),
        hot=True,
        tags=tags,
        source="native",
    )


def render_tool_markdown(row: CatalogToolRow) -> str:
    tag_line = ", ".join(f"`{t}`" for t in row.tags) if row.tags else "—"
    roles = ", ".join(row.roles) if row.roles else "—"
    bundles = ", ".join(row.bundles) if row.bundles else "—"
    lines = [
        f"# {row.name}",
        "",
        f"- **server**: `{row.server}`",
        f"- **source**: `{row.source}`",
        f"- **defer_loading**: `{str(row.defer_loading).lower()}`",
        f"- **token_weight**: `{row.token_weight}`",
        f"- **hot**: `{str(row.hot).lower()}`",
        f"- **tags**: {tag_line}",
    ]
    if row.source == "hub_config":
        lines.extend(
            [
                f"- **transport**: `{row.transport or '—'}`",
                f"- **roles**: {roles}",
                f"- **bundles**: {bundles}",
            ]
        )
        if row.command:
            lines.append(f"- **command**: `{_one_line(row.command, max_len=120)}`")
    lines.extend(["", "## Description", "", row.description or "_No description._", ""])
    return "\n".join(lines)


def render_index_markdown(rows: list[CatalogToolRow], *, output_dir: Path) -> str:
    by_server: dict[str, list[CatalogToolRow]] = {}
    for row in rows:
        by_server.setdefault(row.server, []).append(row)

    lines = [
        "# MCP tool catalog",
        "",
        "Machine-local export for folder-discovery before loading heavy MCP servers.",
        "",
        f"- **output_dir**: `{output_dir}`",
        f"- **servers**: {len(by_server)}",
        f"- **tools**: {len(rows)}",
        "",
        "## Discover before load",
        "",
        "```bash",
        f"rg -l 'your capability' {output_dir}",
        "```",
        "",
        "Re-run `export_mcp_catalog()` after `hub_config.yaml` changes.",
        "",
        "## Servers",
        "",
    ]
    for server in sorted(by_server):
        tools = sorted(by_server[server], key=lambda r: r.name)
        lines.append(f"### `{server}` ({len(tools)} tools)")
        for row in tools:
            rel = f"{_slug(row.server)}/tools/{_slug(row.name)}.md"
            lines.append(f"- [{row.name}]({rel}) — {row.description}")
        lines.append("")
    return "\n".join(lines)


def collect_catalog_rows(
    config: ConfigData,
    native_tools: Optional[list[Any]] = None,
) -> list[CatalogToolRow]:
    rows = [_row_from_hub_tool(tool) for tool in config.mcp_tools]
    if native_tools:
        native_names = {r.name for r in rows}
        for tool in native_tools:
            row = _row_from_native_tool(tool)
            if row.name not in native_names:
                rows.append(row)
    return rows


def export_mcp_catalog(
    *,
    config: ConfigData,
    output_dir: Path,
    native_tools: Optional[list[Any]] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Write per-server markdown under `.braindrain/mcp-catalog/<server>/tools/*.md`."""
    rows = collect_catalog_rows(config, native_tools=native_tools)
    written: list[str] = []
    planned: list[str] = []

    for row in rows:
        rel = Path(_slug(row.server)) / "tools" / f"{_slug(row.name)}.md"
        path = output_dir / rel
        planned.append(str(rel))
        if dry_run:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_tool_markdown(row), encoding="utf-8")
        written.append(str(rel))

    index_rel = Path("README.md")
    index_path = output_dir / index_rel
    index_md = render_index_markdown(rows, output_dir=output_dir)
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        index_path.write_text(index_md, encoding="utf-8")
        written.append(str(index_rel))

    return {
        "ok": True,
        "dry_run": dry_run,
        "output_dir": str(output_dir),
        "servers": len({r.server for r in rows}),
        "tool_count": len(rows),
        "files_written": len(written),
        "files": written if not dry_run else planned,
    }


async def export_mcp_catalog_async(
    *,
    config: Config,
    mcp_server: Any,
    project_root: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = project_root or Path.cwd()
    output_dir = root / ".braindrain" / "mcp-catalog"
    native_tools = await mcp_server.list_tools()
    return export_mcp_catalog(
        config=config.data,
        output_dir=output_dir,
        native_tools=native_tools,
        dry_run=dry_run,
    )


def export_mcp_catalog_cli(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    from braindrain.server import CONFIG_PATH, config, mcp

    parser = argparse.ArgumentParser(description="Export BRAINDRAIN MCP tool catalog")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--path", default=".", help="Project root for .braindrain output")
    args = parser.parse_args(argv)

    result = asyncio.run(
        export_mcp_catalog_async(
            config=config,
            mcp_server=mcp,
            project_root=Path(args.path).resolve(),
            dry_run=bool(args.dry_run),
        )
    )
    print(result)
    return 0 if result.get("ok") else 1


def export_for_registry(config: ConfigData, registry: ToolRegistry) -> dict[str, Any]:
    """Export hub_config tools only (no native FastMCP introspection)."""
    _ = registry  # reserved for future registry-only metadata
    output_dir = Path.cwd() / ".braindrain" / "mcp-catalog"
    return export_mcp_catalog(config=config, output_dir=output_dir, native_tools=None, dry_run=False)
