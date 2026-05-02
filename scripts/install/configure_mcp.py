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
import shlex
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# ANSI color codes
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"


@dataclass(frozen=True)
class Target:
    key: str
    display: str
    path: Path
    style: str
    detected: bool


@dataclass(frozen=True)
class CliCommandTarget:
    key: str
    display: str
    command_template: str  # e.g. "claude mcp add braindrain -- {launcher}"
    detected: bool
    style: str = "cli_command"

    @property
    def path(self) -> Path:
        return Path("/dev/null")  # sentinel — no config file


def _strip_jsonc_comments(text: str) -> str:
    import re

    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"(?<!:)//[^\n]*", "", text)
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    return text


def _load_config(path: Path, style: str) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8", errors="ignore")
    if style == "goose_yaml":
        import yaml
        return yaml.safe_load(raw) or {}
    if style == "toml_mcp_servers":
        try:
            import tomllib  # type: ignore # Python 3.11+ stdlib
        except ImportError:
            import tomli as tomllib  # type: ignore # fallback
        return tomllib.loads(raw)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = json.loads(_strip_jsonc_comments(raw))
    if not isinstance(parsed, dict):
        raise ValueError(f"Config at {path} is not a object/dict")
    return parsed


def _render_output(obj: dict[str, Any], style: str) -> str:
    if style == "goose_yaml":
        import yaml
        return yaml.dump(obj, default_flow_style=False, allow_unicode=True)
    if style == "toml_mcp_servers":
        import tomli_w
        return tomli_w.dumps(obj)
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


def _braindrain_stdio_entry(launcher: str, *, server_name: str = "braindrain") -> dict[str, Any]:
    """Cursor and other IDEs expect ``serverName`` on each MCP server object (avoids adapter warnings)."""
    return {
        "command": launcher,
        "args": [],
        "env": {},
        "serverName": server_name,
    }


def _ensure_server_entry(config: dict[str, Any], target: Target, launcher: str) -> dict[str, Any]:
    if target.style == "mcpServers":
        servers = _get_nested(config, "mcpServers")
        if not isinstance(servers, dict):
            servers = {}
            _set_nested(config, "mcpServers", servers)
        servers["braindrain"] = _braindrain_stdio_entry(launcher)
        return config

    if target.style == "context_servers":
        servers = _get_nested(config, "context_servers")
        if not isinstance(servers, dict):
            servers = {}
            _set_nested(config, "context_servers", servers)
        servers["braindrain"] = _braindrain_stdio_entry(launcher)
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
        block["braindrain"] = _braindrain_stdio_entry(launcher)
        return config

    if target.style == "goose_yaml":
        import yaml  # already a dep
        block = _get_nested(config, "mcp_servers")
        if not isinstance(block, dict):
            block = {}
            _set_nested(config, "mcp_servers", block)
        block["braindrain"] = {"command": launcher, "args": []}
        return config

    if target.style == "toml_mcp_servers":
        mcp_servers = _get_nested(config, "mcp_servers")
        if not isinstance(mcp_servers, dict):
            mcp_servers = {}
            _set_nested(config, "mcp_servers", mcp_servers)
        mcp_servers["braindrain"] = {"command": launcher, "args": []}
        return config

    raise ValueError(f"Unsupported style: {target.style}")


def _build_targets(detected_configs: dict[str, Any]) -> list[Target | CliCommandTarget]:
    defaults: list[tuple[str, str, str, str]] = [
        ("cursor", "Cursor", "~/.cursor/mcp.json", "mcpServers"),
        ("windsurf", "Windsurf", "~/.codeium/windsurf/mcp_config.json", "mcpServers"),
        ("zed", "Zed", "~/.config/zed/settings.json", "context_servers"),
        ("opencode", "OpenCode", "~/.config/opencode/opencode.jsonc", "mcp"),
        ("antigravity", "Antigravity", "~/.gemini/antigravity/mcp_config.json", "mcpServers"),
        ("gemini_cli", "Gemini CLI", "~/.gemini/settings.json", "mcpServers"),
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
        ("kiro", "Kiro", "~/.kiro/settings/mcp.json", "mcpServers"),
        ("warp", "Warp", "~/.warp/mcp.json", "mcpServers"),
        ("amp", "Amp", "~/.amp/mcp.json", "mcpServers"),
        ("goose", "Goose", "~/.config/goose/config.yaml", "goose_yaml"),
        ("codex_cli_toml", "Codex CLI (TOML)", "~/.codex/config.toml", "toml_mcp_servers"),
    ]

    import shutil

    out: list[Target | CliCommandTarget] = []
    for key, display, default_path, style in defaults:
        probe = detected_configs.get(key) if isinstance(detected_configs, dict) else None
        if key == "codex_cli_toml" and probe is None and isinstance(detected_configs, dict):
            probe = detected_configs.get("codex_cli")
        path = Path((probe or {}).get("config_path", default_path)).expanduser()
        detected = bool((probe or {}).get("exists", False))
        out.append(Target(key=key, display=display, path=path, style=style, detected=detected))

    # Detect claude CLI presence
    claude_detected = bool(shutil.which("claude"))
    out.append(
        CliCommandTarget(
            key="claude_code_cli",
            display="Claude Code CLI",
            command_template="claude mcp add braindrain -- {launcher}",
            detected=claude_detected,
        )
    )
    return out


def _ask_selection(targets: list[Target | CliCommandTarget]) -> list[Target | CliCommandTarget]:
    detected = [t for t in targets if t.detected]

    print(f"\n{BOLD}Select MCP targets to configure (interactive checklist):{RESET}")
    if detected:
        detected_names = ", ".join(t.display for t in detected)
        print(f"Enter comma-separated numbers, 'all', or {BOLD}press Enter for detected apps{RESET} ({detected_names}).")
    else:
        print("Enter comma-separated numbers, 'all', or press Enter for Cursor + Zed + Codex CLI (TOML).")

    for idx, target in enumerate(targets, start=1):
        marker = "detected" if target.detected else "not-detected"
        exists = "exists" if target.path.exists() else "new-file"
        line = f"  {idx:>2}) {target.display:<16} [{marker} | {exists}] {target.path}"
        if target.detected:
            print(f"{CYAN}{BOLD}{line}{RESET}")
        else:
            print(line)

    choice = input("\nSelection: ").strip().lower()
    if not choice:
        if detected:
            print(f"Defaulting to detected apps: {CYAN}{', '.join(t.display for t in detected)}{RESET}")
            return detected
        print("Defaulting to Cursor + Zed + Codex CLI (TOML).")
        preferred = {"cursor", "zed", "codex_cli_toml"}
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
    parser.add_argument("--launcher", default="", help="Absolute path to config/braindrain launcher")
    parser.add_argument("--detected-configs", default="", help="JSON object from env_probe summary.app_configs")
    args = parser.parse_args()

    import os
    launcher = args.launcher or os.environ.get("BRAINDRAIN_LAUNCHER_PATH", "")
    if not launcher:
        # derive from script location as last resort
        launcher = str(Path(__file__).parent.parent.parent / "config" / "braindrain")
    launcher = str(Path(launcher).expanduser().resolve())

    detected_configs = {}
    if args.detected_configs:
        try:
            detected_configs = json.loads(args.detected_configs)
        except Exception:
            detected_configs = {}

    targets = _build_targets(detected_configs)
    selected = _ask_selection(targets)

    planned: list[tuple[Target | CliCommandTarget, str, str]] = []
    quoted_launcher = shlex.quote(launcher)
    for target in selected:
        if isinstance(target, CliCommandTarget):
            planned.append((target, "", target.command_template.format(launcher=quoted_launcher)))
            continue
        try:
            before_obj = _load_config(target.path, target.style)
        except Exception as e:
            print(f"\nSkipping {target.display}: could not parse {target.path} ({e})")
            continue
        before_text = target.path.read_text(encoding="utf-8", errors="ignore") if target.path.exists() else ""
        after_obj = _ensure_server_entry(before_obj, target, launcher)
        after_text = _render_output(after_obj, target.style)
        planned.append((target, before_text, after_text))

    if not planned:
        print("\nNo writable config changes planned.")
        return 0

    print("\nPlanned MCP config changes:")
    for target, before, after in planned:
        if isinstance(target, CliCommandTarget):
            print(f"\n--- {target.display} ---")
            print(f"Command: {after}")
            continue

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

    import subprocess
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    applied = 0
    for target, before, after in planned:
        if isinstance(target, CliCommandTarget):
            print(f"\n--- {target.display} ---")
            print(f"Running: {after}")
            try:
                result = subprocess.run(after, shell=True, capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    print(f"{GREEN}✓ APPLIED:{RESET} {target.display}")
                    applied += 1
                else:
                    print(f"FAILED: {result.stderr}")
            except subprocess.TimeoutExpired:
                print(f"FAILED: {target.display} (timed out after 30s)")
            continue

        if before == after:
            continue
        target.path.parent.mkdir(parents=True, exist_ok=True)
        if target.path.exists():
            backup = target.path.with_suffix(target.path.suffix + f".bak.{timestamp}")
            backup.write_text(before, encoding="utf-8")
            print(f"BACKUP: {backup}")
        target.path.write_text(after, encoding="utf-8")
        print(f"{GREEN}✓ APPLIED:{RESET} {target.path}")
        applied += 1

    print(f"\nApplied {applied} config update(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
