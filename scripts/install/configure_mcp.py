#!/usr/bin/env python3
"""
Interactive MCP config writer for BRAINDRAIN.

- Presents a numbered checklist of known IDE/agent config targets.
- Uses detected app configs from env_probe when available.
- Shows unified diffs for all selected changes.
- Applies only after explicit confirmation.
- Creates timestamped backups before every write.
"""

from __future__ import annotations

import argparse
import difflib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Target:
    key: str
    display: str
    path: Path
    style: str
    detected: bool


def _strip_jsonc_comments(text: str) -> str:
    import re

    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"(?<!:)//[^\n]*", "", text)
    return text


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8", errors="ignore")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = json.loads(_strip_jsonc_comments(raw))
    if not isinstance(parsed, dict):
        raise ValueError(f"Config at {path} is not a JSON object")
    return parsed


def _render_json(obj: dict[str, Any], style: str) -> str:
    # Keep JSONC-compatible files as plain JSON output for safety.
    _ = style
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def _set_nested(root: dict[str, Any], dotted_key: str, value: Any) -> None:
    parts = dotted_key.split(".")
    cur = root
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _get_nested(root: dict[str, Any], dotted_key: str) -> Any:
    cur: Any = root
    for part in dotted_key.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _ensure_server_entry(config: dict[str, Any], target: Target, launcher: str) -> dict[str, Any]:
    if target.style == "mcpServers":
        servers = _get_nested(config, "mcpServers")
        if not isinstance(servers, dict):
            servers = {}
            _set_nested(config, "mcpServers", servers)
        servers["braindrain"] = {"command": launcher, "args": [], "env": {}}
        return config

    if target.style == "context_servers":
        servers = _get_nested(config, "context_servers")
        if not isinstance(servers, dict):
            servers = {}
            _set_nested(config, "context_servers", servers)
        servers["braindrain"] = {"command": launcher, "args": [], "env": {}}
        return config

    if target.style == "mcp":
        block = _get_nested(config, "mcp")
        if not isinstance(block, dict):
            block = {}
            _set_nested(config, "mcp", block)
        block["braindrain"] = {"type": "local", "command": [launcher]}
        return config

    if target.style == "mcp.servers":
        block = _get_nested(config, "mcp.servers")
        if not isinstance(block, dict):
            block = {}
            _set_nested(config, "mcp.servers", block)
        block["braindrain"] = {"command": launcher, "args": [], "env": {}}
        return config

    raise ValueError(f"Unsupported style: {target.style}")


def _build_targets(detected_configs: dict[str, Any]) -> list[Target]:
    defaults: list[tuple[str, str, str, str]] = [
        ("cursor", "Cursor", "~/.cursor/mcp.json", "mcpServers"),
        ("windsurf", "Windsurf", "~/.codeium/windsurf/mcp_config.json", "mcpServers"),
        ("zed", "Zed", "~/.config/zed/settings.json", "context_servers"),
        ("opencode", "OpenCode", "~/.config/opencode/opencode.jsonc", "mcp"),
        ("antigravity", "Antigravity", "~/.gemini/antigravity/mcp_config.json", "mcpServers"),
        ("gemini_cli", "Gemini CLI", "~/.gemini/settings.json", "mcpServers"),
        ("codex_cli", "Codex CLI", "~/.codex/config.json", "mcpServers"),
        ("codex_openai", "Codex (OpenAI)", "~/.openai/mcp.json", "mcpServers"),
        (
            "claude_desktop",
            "Claude Desktop",
            "~/Library/Application Support/Claude/claude_desktop_config.json",
            "mcpServers",
        ),
        ("claude_cli", "Claude CLI", "~/.config/claude/claude_desktop_config.json", "mcpServers"),
        ("continue", "Continue", "~/.continue/config.json", "mcpServers"),
        ("vscode", "VS Code", "~/.vscode/settings.json", "mcp.servers"),
        ("void", "Void", "~/.void/mcp.json", "mcpServers"),
        ("aider", "Aider", "~/.aider/mcp.json", "mcpServers"),
    ]

    out: list[Target] = []
    for key, display, default_path, style in defaults:
        probe = detected_configs.get(key) if isinstance(detected_configs, dict) else None
        path = Path((probe or {}).get("config_path", default_path)).expanduser()
        detected = bool((probe or {}).get("exists", False))
        out.append(Target(key=key, display=display, path=path, style=style, detected=detected))
    return out


def _ask_selection(targets: list[Target]) -> list[Target]:
    print("\nSelect MCP targets to configure (interactive checklist):")
    print("Enter comma-separated numbers, 'all', or press Enter for detected-only.")
    for idx, target in enumerate(targets, start=1):
        marker = "detected" if target.detected else "not-detected"
        exists = "exists" if target.path.exists() else "new-file"
        print(f"  {idx:>2}) {target.display:<16} [{marker} | {exists}] {target.path}")

    choice = input("\nSelection: ").strip().lower()
    if not choice:
        selected = [t for t in targets if t.detected]
        if selected:
            return selected
        print("No detected configs found; defaulting to Cursor + Zed + Codex CLI.")
        preferred = {"cursor", "zed", "codex_cli"}
        return [t for t in targets if t.key in preferred]

    if choice == "all":
        return targets

    picks: list[Target] = []
    seen: set[int] = set()
    for token in choice.split(","):
        token = token.strip()
        if not token.isdigit():
            continue
        i = int(token)
        if i < 1 or i > len(targets) or i in seen:
            continue
        seen.add(i)
        picks.append(targets[i - 1])

    if not picks:
        raise SystemExit("No valid selections provided.")
    return picks


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure MCP client config files for BRAINDRAIN.")
    parser.add_argument("--launcher", required=True, help="Absolute path to config/braindrain launcher")
    parser.add_argument("--detected-configs", default="", help="JSON object from env_probe summary.app_configs")
    args = parser.parse_args()

    launcher = str(Path(args.launcher).expanduser().resolve())
    detected_configs = {}
    if args.detected_configs:
        try:
            detected_configs = json.loads(args.detected_configs)
        except Exception:
            detected_configs = {}

    targets = _build_targets(detected_configs)
    selected = _ask_selection(targets)

    planned: list[tuple[Target, str, str]] = []
    for target in selected:
        try:
            before_obj = _load_json(target.path)
        except Exception as e:
            print(f"\nSkipping {target.display}: could not parse {target.path} ({e})")
            continue
        before_text = target.path.read_text(encoding="utf-8", errors="ignore") if target.path.exists() else ""
        after_obj = _ensure_server_entry(before_obj, target, launcher)
        after_text = _render_json(after_obj, target.style)
        planned.append((target, before_text, after_text))

    if not planned:
        print("\nNo writable config changes planned.")
        return 0

    print("\nPlanned MCP config changes:")
    for target, before, after in planned:
        diff = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"{target.path} (before)",
                tofile=f"{target.path} (after)",
            )
        )
        print(f"\n--- {target.display} ---")
        print(diff if diff.strip() else "(no textual change)")

    confirm = input("\nApply these changes? [y/N]: ").strip().lower()
    if confirm not in {"y", "yes"}:
        print("No files changed.")
        return 0

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    applied = 0
    for target, before, after in planned:
        if before == after:
            continue
        target.path.parent.mkdir(parents=True, exist_ok=True)
        if target.path.exists():
            backup = target.path.with_suffix(target.path.suffix + f".bak.{timestamp}")
            backup.write_text(before, encoding="utf-8")
            print(f"BACKUP: {backup}")
        target.path.write_text(after, encoding="utf-8")
        print(f"APPLIED: {target.path}")
        applied += 1

    print(f"\nApplied {applied} config update(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

