"""
braindrain/env_probe.py

Lightweight OS environment fingerprinting probe.
Fires a wide net of read-only commands, captures what succeeds,
silently drops what doesn't. No retries, no conditionals.
Result is cached to ~/.braindrain/env_context.json.
"""

from __future__ import annotations

import json
import os
import platform
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Union

CACHE_PATH = Path.home() / ".braindrain" / "env_context.json"

# ---------------------------------------------------------------------------
# Probe command groups
# Each entry: (key, shell_command)
# All run with stderr suppressed; None result means command failed/missing.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Known app categories for synthesis (keyword → canonical name)
# Used to classify raw /Applications/ and brew cask output.
# ---------------------------------------------------------------------------

_BROWSERS: dict[str, str] = {
    "safari": "Safari",
    "firefox": "Firefox",
    "chrome": "Google Chrome",
    "chromium": "Chromium",
    "zen": "Zen Browser",
    "brave": "Brave Browser",
    "opera": "Opera",
    "vivaldi": "Vivaldi",
    "arc": "Arc",
    "edge": "Microsoft Edge",
    "waterfox": "Waterfox",
    "tor browser": "Tor Browser",
}

_LLM_TOOLS: dict[str, str] = {
    "lm studio": "LM Studio",
    "lmstudio": "LM Studio",
    "anythingllm": "AnythingLLM",
    "anything llm": "AnythingLLM",
    "ollama": "Ollama",
    "jan": "Jan",
    "gpt4all": "GPT4All",
    "msty": "Msty",
    "openwebui": "Open WebUI",
    "llamafile": "llamafile",
}

_VM_TOOLS: dict[str, str] = {
    "virtualbox": "VirtualBox",
    "vmware": "VMware",
    "parallels": "Parallels",
    "utm": "UTM",
    "qemu": "QEMU",
    "multipass": "Multipass",
    "vagrant": "Vagrant",
}

_GUI_TOOLS: dict[str, str] = {
    "raycast": "Raycast",
    "alfred": "Alfred",
    "yabai": "yabai (tiling WM)",
    "skhd": "skhd (hotkeys)",
    "borders": "JankyBorders",
    "amethyst": "Amethyst (tiling WM)",
    "nikitabobko.aerospace": "AeroSpace (tiling WM)",
    "flycut": "Flycut (clipboard)",
    "clipy": "Clipy (clipboard)",
    "maccy": "Maccy (clipboard)",
    "rectangle": "Rectangle (window)",
    "magnet": "Magnet (window)",
    "bartender": "Bartender",
    "hiddenbar": "HiddenBar",
    "istat": "iStat Menus",
    "stats": "Stats (menu bar)",
    "karabiner": "Karabiner-Elements",
    "bettertouchtool": "BetterTouchTool",
    "hammerspoon": "Hammerspoon",
    "spacebar": "Spacebar",
    "übersicht": "Übersicht",
    "uebersicht": "Übersicht",
    "sketchybar": "SketchyBar",
}

_TERMINALS: dict[str, str] = {
    "iterm": "iTerm2",
    "warp": "Warp",
    "ghostty": "Ghostty",
    "termius": "Termius",
    "alacritty": "Alacritty",
    "kitty": "Kitty",
    "wezterm": "WezTerm",
    "tabby": "Tabby",
    "hyper": "Hyper",
    "rio": "Rio",
    "cool-retro-term": "Cool Retro Term",
}

_IDE_AGENTS: dict[str, str] = {
    "cursor": "Cursor",
    "windsurf": "Windsurf",
    "zed": "Zed",
    "codex": "Codex",
    "void": "Void",
    "theia": "Theia",
    "lapce": "Lapce",
    "helix": "Helix",
    "nova": "Nova",
    "bbedit": "BBEdit",
    "textmate": "TextMate",
    "sublime text": "Sublime Text",
    "visual studio code": "VS Code",
    "code": "VS Code",
    "rubymine": "RubyMine",
    "pycharm": "PyCharm",
    "webstorm": "WebStorm",
    "intellij": "IntelliJ IDEA",
    "goland": "GoLand",
    "clion": "CLion",
    "datagrip": "DataGrip",
    "rider": "Rider",
}

_PRODUCTIVITY: dict[str, str] = {
    "logseq": "Logseq",
    "obsidian": "Obsidian",
    "notion": "Notion",
    "zotero": "Zotero",
    "capcut": "CapCut",
    "davinci resolve": "DaVinci Resolve",
    "final cut": "Final Cut Pro",
    "handbrake": "HandBrake",
    "vlc": "VLC",
    "iina": "IINA",
    "discord": "Discord",
    "slack": "Slack",
    "zoom": "Zoom",
    "figma": "Figma",
    "sketch": "Sketch",
    "affinity": "Affinity",
    "gimp": "GIMP",
    "inkscape": "Inkscape",
    "blender": "Blender",
    "docker desktop": "Docker Desktop",
    "tableplus": "TablePlus",
    "insomnia": "Insomnia",
    "postman": "Postman",
    "proxyman": "Proxyman",
    "wireshark": "Wireshark",
    "transmit": "Transmit",
    "cyberduck": "Cyberduck",
}

# Local LLM server ports (port → tool name)
_LLM_PORTS: dict[int, str] = {
    1234: "LM Studio",
    11434: "Ollama",
    3001: "AnythingLLM",
    8080: "llamafile/LocalAI",
    5000: "Open WebUI (alt)",
    8000: "generic LLM server",
    1337: "LM Studio (alt)",
}

_PROBE_COMMANDS: list[tuple[str, Union[str, Callable[[], Optional[str]]]]] = [
    # Identity
    ("hostname", "hostname"),
    ("computer_name", "scutil --get ComputerName 2>/dev/null || hostname"),
    ("username", "whoami"),
    ("uid_info", "id"),
    # OS
    ("uname", "uname -a"),
    ("os_release", "cat /etc/os-release 2>/dev/null || sw_vers 2>/dev/null"),
    ("kernel", "uname -r"),
    # Window system / Desktop Environment
    (
        "wm_de_info",
        lambda: "\n".join(
            filter(
                None,
                [
                    os.environ.get("XDG_CURRENT_DESKTOP"),
                    os.environ.get("DESKTOP_SESSION"),
                    os.environ.get("XDG_SESSION_TYPE"),
                    _run("sw_vers -productVersion") if os.path.exists("/usr/bin/sw_vers") else None,
                ],
            )
        )
        or None,
    ),
    # Network — LAN IPs + interface names
    (
        "lan_ip",
        "ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}'",
    ),
    (
        "all_ips",
        "ifconfig 2>/dev/null | grep 'inet ' | awk '{print $1, $2}' || ip -4 addr show 2>/dev/null | grep inet",
    ),
    ("network_hosts", "cat /etc/hosts | grep -v '^#' | grep -v '^$' | head -20"),
    # Shell & terminal
    ("shell", lambda: os.environ.get("SHELL") or None),
    (
        "shell_version",
        lambda: _run(f"{shlex.quote(os.environ.get('SHELL', ''))} --version 2>&1 | head -1")
        if os.environ.get("SHELL")
        else None,
    ),
    ("term", lambda: os.environ.get("TERM") or None),
    ("term_program", lambda: os.environ.get("TERM_PROGRAM") or None),
    # Package managers (presence check)
    (
        "pkg_managers",
        "for pm in brew apt dnf pacman nix port snap flatpak; do which $pm 2>/dev/null && echo $pm; done",
    ),
    ("brew_version", "brew --version 2>/dev/null | head -1"),
    # Core runtimes
    ("python_version", "python3 --version 2>/dev/null"),
    ("node_version", "node -v 2>/dev/null"),
    ("npm_version", "npm -v 2>/dev/null"),
    ("go_version", "go version 2>/dev/null"),
    ("rust_version", "rustc --version 2>/dev/null"),
    ("ruby_version", "ruby --version 2>/dev/null"),
    ("java_version", "java -version 2>&1 | head -1"),
    # Python interpreter discovery — ALL python3 binaries in PATH, not just the first
    ("python_all", "which -a python3 2>/dev/null || type -a python3 2>/dev/null"),
    ("python_sys", "/usr/bin/python3 --version 2>/dev/null"),
    ("pyenv_active", "pyenv version 2>/dev/null"),
    ("pyenv_versions", "pyenv versions --bare 2>/dev/null | head -10"),
    ("pyenv_root", "pyenv root 2>/dev/null"),
    # Version managers
    (
        "nvm_version",
        "nvm --version 2>/dev/null || cat ~/.nvm/alias/default 2>/dev/null",
    ),
    ("pyenv_version", "pyenv --version 2>/dev/null"),
    ("rbenv_version", "rbenv --version 2>/dev/null"),
    # Containers / VMs
    ("docker_version", "docker version --format '{{.Server.Version}}' 2>/dev/null"),
    ("docker_compose", "docker compose version 2>/dev/null | head -1"),
    ("podman_version", "podman --version 2>/dev/null"),
    # Editors & IDEs (presence check)
    (
        "editors",
        "for e in nvim vim nano code cursor windsurf zed; do which $e 2>/dev/null && echo $e; done",
    ),
    (
        "editor_env",
        lambda: "\n".join(filter(None, [os.environ.get("EDITOR"), os.environ.get("VISUAL")])) or None,
    ),
    # Key CLI tools agents commonly use
    (
        "modern_cli_tools",
        "for t in fd fzf bat rg jq gh lazygit tmux zoxide atuin delta; do which $t 2>/dev/null && echo $t; done",
    ),
    ("git_version", "git --version"),
    (
        "git_config",
        "git config --global --list 2>/dev/null | grep -E 'user\\.(name|email)'",
    ),
    # Shell config / aliases
    (
        "shell_aliases",
        "grep -h '^alias' ~/.zshrc ~/.bashrc ~/.config/fish/config.fish 2>/dev/null | head -30",
    ),
    # PATH
    ("path", lambda: os.environ.get("PATH") or None),
    # XDG / config dirs
    ("xdg_config", "ls ~/.config/ 2>/dev/null | head -30"),
    # Homebrew installed formulae (top-level)
    ("brew_leaves", "brew leaves 2>/dev/null | head -50"),
    # System resources
    (
        "cpu_info",
        "sysctl -n machdep.cpu.brand_string 2>/dev/null || lscpu 2>/dev/null | grep 'Model name' | head -1",
    ),
    (
        "memory",
        "sysctl -n hw.memsize 2>/dev/null | awk '{printf \"%.0f GB\\n\", $1/1073741824}' || free -h 2>/dev/null | grep Mem | awk '{print $2}'",
    ),
    # Init system
    ("init_system", "ps -p 1 -o comm= 2>/dev/null || cat /proc/1/comm 2>/dev/null"),
    # Running services (limited)
    (
        "running_services",
        "systemctl --type=service --state=running 2>/dev/null | grep '●' | head -15 || launchctl list 2>/dev/null | head -15",
    ),
    # Arch
    ("arch", "uname -m"),
    ("os_type", "uname -s"),
    # ── Bulk installed app discovery (one command, everything) ─────────────
    # macOS: /Applications/ covers GUI apps; ~/Applications/ for user installs
    ("apps_system", "ls /Applications/ 2>/dev/null"),
    ("apps_user", "ls ~/Applications/ 2>/dev/null"),
    # brew casks = GUI apps installed via homebrew
    ("brew_casks", "brew list --cask 2>/dev/null"),
    # Linux bulk: pacman, yay (AUR), apt, dpkg, flatpak, snap
    (
        "linux_pkgs",
        "pacman -Qe 2>/dev/null | awk '{print $1}' | head -100 || "
        "yay -Qm 2>/dev/null | awk '{print $1}' | head -50 || "
        "apt list --installed 2>/dev/null | grep -v WARNING | cut -d/ -f1 | head -100 || "
        "dpkg -l 2>/dev/null | awk '/^ii/{print $2}' | head -100",
    ),
    ("flatpak_list", "flatpak list --app --columns=name 2>/dev/null | head -30"),
    ("snap_list", "snap list 2>/dev/null | awk 'NR>1{print $1}' | head -30"),
    # ── Running processes snapshot (covers LLM servers, GUI tools, VMs) ───
    (
        "procs_notable",
        "ps aux 2>/dev/null | grep -iE "
        "'(lmstudio|lm.studio|anythingllm|anything.llm|ollama|jan[^a-z]|gpt4all|"
        "virtualbox|vboxmanage|vmware|vmrun|parallels|utm[^a-z]|qemu|"
        "raycast|alfred|yabai|skhd|borders|amethyst|aerospace|flycut|clipy|maccy|rectangle|"
        "bartender|karabiner|hammerspoon|sketchybar|spacebar|"
        "logseq|obsidian|zotero|figma|discord|slack|"
        "ghostty|termius|iterm|warp|alacritty|kitty|wezterm|tabby|hyper|"
        "codex|antigravity|gemini.cli)' "
        "| grep -v grep | awk '{print $11}' | sort -u | head -30",
    ),
    # ── Local LLM server port checks (is anything listening?) ─────────────
    (
        "llm_ports_listening",
        "for port in 1234 11434 3001 8080 1337; do "
        "lsof -i :$port 2>/dev/null | grep -q LISTEN && echo $port; "
        "done",
    ),
    # Quick model count from running servers (1s timeout, best-effort)
    (
        "lmstudio_models",
        "curl -s --max-time 1 http://localhost:1234/v1/models 2>/dev/null "
        '| python3 -c "import json,sys; d=json.load(sys.stdin); '
        "print(len(d.get('data',[])), 'models loaded')\" 2>/dev/null",
    ),
    (
        "ollama_models",
        "curl -s --max-time 1 http://localhost:11434/api/tags 2>/dev/null "
        '| python3 -c "import json,sys; d=json.load(sys.stdin); '
        "print(len(d.get('models',[])), 'models loaded')\" 2>/dev/null",
    ),
    # ── VM / hypervisor CLI tools ─────────────────────────────────────────
    (
        "vm_tools",
        "for v in vboxmanage VBoxManage vmrun prlctl utmctl multipass vagrant qemu-system-x86_64; do "
        "which $v 2>/dev/null && echo $v; done",
    ),
    # ── Agent / AI CLI tools ──────────────────────────────────────────────
    (
        "ai_cli_tools",
        "for t in codex claude aider goose sgpt shell-gpt llm gemini opencode antigravity; do "
        "which $t 2>/dev/null && echo $t; done",
    ),
]

# ---------------------------------------------------------------------------
# IDE / Agent MCP config locations
# Checked by path existence; content parsed if JSON/JSONC.
# Format: (app_key, display_name, config_path, mcp_key_path)
#   mcp_key_path: dot-separated path into the JSON to find server map
#   e.g. "mcpServers" or "mcp" or "context_servers"
# ---------------------------------------------------------------------------

_APP_CONFIG_PROBES: list[tuple[str, str, str, str]] = [
    # (app_key, display_name, config_path, mcp_servers_json_key)
    ("cursor", "Cursor", "~/.cursor/mcp.json", "mcpServers"),
    ("windsurf", "Windsurf", "~/.codeium/windsurf/mcp_config.json", "mcpServers"),
    ("zed", "Zed", "~/.config/zed/settings.json", "context_servers"),
    ("opencode", "OpenCode", "~/.config/opencode/opencode.jsonc", "mcp"),
    (
        "antigravity",
        "Antigravity",
        "~/.gemini/antigravity/mcp_config.json",
        "mcpServers",
    ),
    ("gemini_cli", "Gemini CLI", "~/.gemini/settings.json", "mcpServers"),
    (
        "claude_desktop",
        "Claude Desktop",
        "~/Library/Application Support/Claude/claude_desktop_config.json",
        "mcpServers",
    ),
    (
        "claude_config",
        "Claude CLI",
        "~/.config/claude/claude_desktop_config.json",
        "mcpServers",
    ),
    ("codex_cli", "Codex CLI", "~/.codex/config.json", "mcpServers"),
    ("codex_openai", "Codex (OpenAI)", "~/.openai/mcp.json", "mcpServers"),
    ("continue", "Continue", "~/.continue/config.json", "mcpServers"),
    ("vscode", "VS Code", "~/.vscode/settings.json", "mcp.servers"),
    ("void", "Void", "~/.void/mcp.json", "mcpServers"),
    ("aider", "Aider", "~/.aider/mcp.json", "mcpServers"),
]


def _run(cmd: str) -> str | None:
    """Run a shell command, return stdout or None on failure.
    NOTE: cmd must be properly quoted if it contains external input.
    """
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout if result.stdout else None
    except Exception:
        return None


def _strip_jsonc_comments(text: str) -> str:
    """Strip // and /* */ comments from JSONC so json.loads can parse it."""
    import re

    # Remove block comments
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # Remove line comments (but not URLs — only strip // not preceded by :)
    text = re.sub(r"(?<!:)//[^\n]*", "", text)
    return text


def _read_json_file(path: Path) -> dict | None:
    """Read a JSON or JSONC file, return parsed dict or None."""
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Try JSONC stripping
            return json.loads(_strip_jsonc_comments(raw))
    except Exception:
        return None


def _get_nested(d: dict, dot_path: str) -> Any:
    """Walk a dot-separated key path into a nested dict."""
    parts = dot_path.split(".")
    cur = d
    for part in parts:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def probe_app_configs() -> dict[str, Any]:
    """
    Check each known IDE/agent config location.
    Returns a dict keyed by app_key with:
      - exists: bool
      - path: str
      - mcp_servers: list of server names configured (if any)
      - raw_mcp_block: the raw MCP servers dict (for debugging)
    """
    results: dict[str, Any] = {}

    for app_key, display_name, config_path_str, mcp_key in _APP_CONFIG_PROBES:
        path = Path(config_path_str).expanduser()
        if not path.exists():
            results[app_key] = {
                "name": display_name,
                "config_path": str(path),
                "exists": False,
                "mcp_servers": [],
            }
            continue

        parsed = _read_json_file(path)
        mcp_block = _get_nested(parsed, mcp_key) if parsed else None

        server_names: list[str] = []
        if isinstance(mcp_block, dict):
            server_names = [
                k
                for k, v in mcp_block.items()
                if isinstance(v, dict) and not v.get("disabled", False)
            ]

        results[app_key] = {
            "name": display_name,
            "config_path": str(path),
            "exists": True,
            "mcp_servers": server_names,
            "mcp_servers_disabled": [
                k
                for k, v in (mcp_block or {}).items()
                if isinstance(v, dict) and v.get("disabled", False)
            ],
        }

    return results


def run_probe() -> dict[str, Any]:
    """Execute all probe commands + app config discovery, return raw results dict."""
    import concurrent.futures

    raw: dict[str, Any] = {
        "probe_timestamp": datetime.now(timezone.utc).isoformat(),
        "platform_python": platform.platform(),
    }

    # Run all shell commands in parallel (all have 5s timeouts)
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        futures = {}
        for key, cmd in _PROBE_COMMANDS:
            if callable(cmd):
                futures[pool.submit(cmd)] = key
            else:
                futures[pool.submit(_run, cmd)] = key

        for future in concurrent.futures.as_completed(futures):
            key = futures[future]
            try:
                val = future.result()
                raw[key] = val.strip() if isinstance(val, str) else val
            except Exception:
                raw[key] = None

    # App config discovery runs separately (file I/O, not subprocess)
    raw["_app_configs"] = probe_app_configs()

    return raw


# ---------------------------------------------------------------------------
# Synthesizer — turns raw probe output into a structured summary
# ---------------------------------------------------------------------------


def _classify_apps(
    raw_app_lines: list[str],
    categories: dict[str, dict[str, str]],
) -> dict[str, list[str]]:
    """
    Given a flat list of app names (from /Applications/ or brew casks),
    classify them into category buckets using keyword matching.
    Returns {category_name: [canonical_name, ...]}
    """
    result: dict[str, list[str]] = {cat: [] for cat in categories}
    seen: set[str] = set()

    for app_raw in raw_app_lines:
        app_lower = app_raw.lower().replace(".app", "").strip()
        for category, keywords in categories.items():
            for keyword, canonical in keywords.items():
                if keyword in app_lower and canonical not in seen:
                    result[category].append(canonical)
                    seen.add(canonical)
                    break

    return result


def _parse_installed_apps(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Parse bulk app discovery sources into categorised sections.
    Sources: apps_system, apps_user, brew_casks, linux_pkgs, flatpak_list, snap_list
    Returns structured dict with browsers, llm_tools, vm_tools, gui_tools,
    ide_agents, productivity, and all_app_names (raw deduplicated list).
    """
    all_lines: list[str] = []

    for key in (
        "apps_system",
        "apps_user",
        "brew_casks",
        "linux_pkgs",
        "flatpak_list",
        "snap_list",
    ):
        raw_val = raw.get(key) or ""
        for line in raw_val.splitlines():
            line = line.strip()
            if line:
                all_lines.append(line)

    # Also include brew_leaves (formulae — catches yabai, skhd, borders etc.)
    for line in (raw.get("brew_leaves") or "").splitlines():
        line = line.strip()
        if line:
            all_lines.append(line)

    categories = {
        "browsers": _BROWSERS,
        "terminals": _TERMINALS,
        "llm_tools": _LLM_TOOLS,
        "vm_tools": _VM_TOOLS,
        "gui_tools": _GUI_TOOLS,
        "ide_agents": _IDE_AGENTS,
        "productivity": _PRODUCTIVITY,
    }
    classified = _classify_apps(all_lines, categories)

    # Deduplicated raw list (strip .app suffix, sort)
    seen: set[str] = set()
    clean: list[str] = []
    for line in all_lines:
        name = line.replace(".app", "").strip()
        if name and name not in seen:
            seen.add(name)
            clean.append(name)
    clean.sort()

    return {**classified, "all_app_names": clean}


def _parse_running_notable(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Parse procs_notable output into categories of what's currently running.
    Also checks llm_ports_listening + model counts from live servers.
    """
    procs_raw = raw.get("procs_notable") or ""
    proc_paths = [l.strip() for l in procs_raw.splitlines() if l.strip()]
    proc_lower = " ".join(proc_paths).lower()

    # Detect which LLM servers are running
    llm_running: list[dict[str, Any]] = []
    ports_raw = raw.get("llm_ports_listening") or ""
    listening_ports = {
        int(p.strip()) for p in ports_raw.splitlines() if p.strip().isdigit()
    }

    for port, name in _LLM_PORTS.items():
        if port in listening_ports:
            entry: dict[str, Any] = {"name": name, "port": port, "status": "running"}
            # Attach model count if we got it
            if port == 1234 and raw.get("lmstudio_models"):
                entry["models"] = raw["lmstudio_models"]
            elif port == 11434 and raw.get("ollama_models"):
                entry["models"] = raw["ollama_models"]
            llm_running.append(entry)

    # Detect other notable running processes
    gui_running: list[str] = []
    for keyword, canonical in {**_GUI_TOOLS, **_VM_TOOLS, **_PRODUCTIVITY}.items():
        if keyword in proc_lower and canonical not in gui_running:
            gui_running.append(canonical)

    return {
        "llm_servers": llm_running,
        "other_notable": gui_running,
        "raw_proc_paths": proc_paths,
    }


def _parse_python_interpreters(raw: dict[str, Any]) -> list[dict[str, str]]:
    """
    Build a list of all Python interpreters found, with their versions.
    Deduplicates by resolved real path.
    """
    interpreters: list[dict[str, str]] = []
    seen_paths: set[str] = set()

    all_raw = raw.get("python_all") or ""
    for line in all_raw.splitlines():
        line = line.strip()
        if not line:
            continue
        real = str(Path(line).resolve())
        if real in seen_paths:
            continue
        seen_paths.add(real)
        # Get version for this specific interpreter
        ver = _run(f"{shlex.quote(line)} --version 2>/dev/null") or "unknown"
        interpreters.append({"path": line, "real_path": real, "version": ver})

    # Always include the venv Python if we can find it (common project patterns)
    for venv_candidate in ["~/.venv/bin/python3", ".venv/bin/python3"]:
        venv_path = Path(venv_candidate).expanduser()
        if venv_path.exists():
            real = str(venv_path.resolve())
            if real not in seen_paths:
                seen_paths.add(real)
                ver = _run(f"{shlex.quote(str(venv_path))} --version 2>/dev/null") or "unknown"
                interpreters.append(
                    {"path": str(venv_path), "real_path": real, "version": ver}
                )

    return interpreters


def synthesize(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Convert raw probe dict into a clean structured summary.
    This is deterministic — no LLM needed.
    """

    def _val(key: str) -> str:
        return raw.get(key) or ""

    # Detect OS family
    os_type = _val("os_type")
    is_mac = "Darwin" in os_type
    is_linux = "Linux" in os_type

    # Window Manager / Desktop Environment info
    wm_de_raw = _val("wm_de_info").splitlines()
    wm_de = " · ".join([l.strip() for l in wm_de_raw if l.strip()])

    # Package manager (first found wins)
    pkg_mgrs = [l.strip() for l in _val("pkg_managers").splitlines() if l.strip()]

    # Installed editors
    editors = [l.strip() for l in _val("editors").splitlines() if l.strip()]
    editor_env = [
        e for e in _val("editor_env").splitlines() if e.strip() and e.strip() != "''"
    ]

    # Modern CLI tools present
    modern_tools = [
        l.strip() for l in _val("modern_cli_tools").splitlines() if l.strip()
    ]

    # Runtimes — only include what's actually installed
    runtimes: dict[str, str] = {}
    for label, key in [
        ("python3", "python_version"),
        ("node", "node_version"),
        ("go", "go_version"),
        ("rust", "rust_version"),
        ("ruby", "ruby_version"),
        ("java", "java_version"),
    ]:
        v = _val(key)
        if v:
            runtimes[label] = v

    # LAN IPs — parse cleanly
    all_ips_raw = _val("all_ips") or _val("lan_ip") or ""
    lan_ips = list(
        {
            line.split()[-1]
            for line in all_ips_raw.splitlines()
            if line.strip() and "127.0.0.1" not in line and "::1" not in line
        }
    )

    # Python interpreters — all of them, with versions
    python_interpreters = _parse_python_interpreters(raw)

    # pyenv info
    pyenv_info: dict[str, str] = {}
    if _val("pyenv_active"):
        pyenv_info["active"] = _val("pyenv_active")
    if _val("pyenv_root"):
        pyenv_info["root"] = _val("pyenv_root")
    if _val("pyenv_versions"):
        pyenv_info["installed"] = _val("pyenv_versions")

    # App configs
    app_configs: dict[str, Any] = raw.get("_app_configs", {})

    # Installed apps (categorised from bulk discovery)
    installed_apps = _parse_installed_apps(raw)

    # Running notable processes + LLM servers
    running = _parse_running_notable(raw)

    # AI CLI tools
    ai_cli_raw = raw.get("ai_cli_tools") or ""
    ai_cli_tools = [l.strip() for l in ai_cli_raw.splitlines() if l.strip()]

    # Agent behaviour hints — derived from what's installed
    agent_hints: list[str] = []
    if "fd" in modern_tools:
        agent_hints.append("prefer `fd` over `find`")
    if "bat" in modern_tools:
        agent_hints.append("prefer `bat` over `cat`")
    if "rg" in modern_tools:
        agent_hints.append("prefer `rg` over `grep`")
    if pkg_mgrs:
        agent_hints.append(f"use `{pkg_mgrs[0]}` for package installs")
    if is_mac:
        agent_hints.append(
            "macOS — avoid Linux-only flags (e.g. `--no-preserve-root`, `date -d`)"
        )
    if is_linux:
        agent_hints.append(
            "Linux — systemd available" if "systemd" in _val("init_system") else "Linux"
        )

    # LLM server hints
    for server in running.get("llm_servers", []):
        model_note = f" ({server['models']})" if server.get("models") else ""
        agent_hints.append(
            f"{server['name']} running on :{server['port']}{model_note} — "
            f"use http://localhost:{server['port']}/v1 for OpenAI-compat API"
        )

    # Python interpreter warning
    if len(python_interpreters) > 1:
        versions = [f"{p['path']} → {p['version']}" for p in python_interpreters]
        agent_hints.append(
            f"MULTIPLE python3 interpreters in PATH — verify venv is active before running python. "
            f"Found: {'; '.join(versions)}"
        )
    if pyenv_info.get("active"):
        agent_hints.append(
            f"pyenv active: {pyenv_info['active']} — bare `python3` resolves through pyenv shims"
        )

    summary = {
        "generated_at": raw.get("probe_timestamp", ""),
        "identity": {
            "username": _val("username"),
            "hostname": _val("computer_name") or _val("hostname"),
            "lan_ips": lan_ips,
        },
        "os": {
            "type": "macOS" if is_mac else ("Linux" if is_linux else os_type),
            "detail": _val("os_release").split("\n")[0] if _val("os_release") else "",
            "kernel": _val("kernel"),
            "arch": _val("arch"),
            "wm_de": wm_de,
        },
        "hardware": {
            "cpu": _val("cpu_info"),
            "memory": _val("memory"),
        },
        "shell": {
            "path": _val("shell"),
            "version": _val("shell_version"),
            "term": _val("term_program") or _val("term"),
        },
        "package_managers": pkg_mgrs,
        "runtimes": runtimes,
        "python_interpreters": python_interpreters,
        "pyenv": pyenv_info,
        "installed_apps": installed_apps,
        "running": running,
        "ai_cli_tools": ai_cli_tools,
        "containers": {
            "docker": _val("docker_version"),
            "docker_compose": _val("docker_compose"),
            "podman": _val("podman_version"),
        },
        "editors": editors,
        "editor_env": editor_env,
        "modern_cli_tools": modern_tools,
        "git": {
            "version": _val("git_version"),
            "config": _val("git_config"),
        },
        "agent_hints": agent_hints,
        "app_configs": app_configs,
        "ai_cli_tools": ai_cli_tools,
        "brew_packages": [
            l.strip() for l in _val("brew_leaves").splitlines() if l.strip()
        ],
        "path_entries": [p for p in _val("path").split(":") if p],
        "xdg_config_dirs": [
            l.strip() for l in _val("xdg_config").splitlines() if l.strip()
        ],
        "shell_aliases_sample": [
            l.strip() for l in _val("shell_aliases").splitlines() if l.strip()
        ],
    }

    # Strip empty containers
    summary["containers"] = {k: v for k, v in summary["containers"].items() if v}

    return summary


def render_agents_md_block(summary: dict[str, Any]) -> str:
    """Render the AGENTS.md snippet from a summary dict."""
    ident = summary.get("identity", {})
    os_info = summary.get("os", {})
    hw = summary.get("hardware", {})
    shell = summary.get("shell", {})
    runtimes = summary.get("runtimes", {})
    containers = summary.get("containers", {})
    editors = summary.get("editors", [])
    tools = summary.get("modern_cli_tools", [])
    hints = summary.get("agent_hints", [])
    git = summary.get("git", {})
    python_interpreters = summary.get("python_interpreters", [])
    pyenv = summary.get("pyenv", {})
    app_configs = summary.get("app_configs", {})

    lines = [
        "## OS Environment Context",
        f"<!-- generated by braindrain env_context — {summary.get('generated_at', '')[:10]} -->",
        "",
        f"- **User**: `{ident.get('username', 'unknown')}` on `{ident.get('hostname', 'unknown')}`",
        f"- **LAN IPs**: {', '.join(f'`{ip}`' for ip in ident.get('lan_ips', [])) or 'n/a'}",
        f"- **OS**: {os_info.get('type', '')} — {os_info.get('detail', '')} · {os_info.get('arch', '')}",
        f"- **Windowing**: `{os_info.get('wm_de', 'n/a')}`",
        f"- **Kernel**: `{os_info.get('kernel', 'n/a')}`",
    ]

    if hw.get("cpu") or hw.get("memory"):
        lines.append(
            f"- **Hardware**: {hw.get('cpu', '')} · {hw.get('memory', '')} RAM"
        )

    lines.append(
        f"- **Shell**: `{shell.get('path', '')}` · terminal: `{shell.get('term', '')}`"
    )

    pkg_mgrs = summary.get("package_managers", [])
    if pkg_mgrs:
        lines.append(
            f"- **Package manager**: `{pkg_mgrs[0]}`"
            + (f" (also: {', '.join(pkg_mgrs[1:])})" if len(pkg_mgrs) > 1 else "")
        )

    if runtimes:
        runtime_str = " · ".join(
            f"`{k}` {v.split()[-1] if v else ''}" for k, v in runtimes.items()
        )
        lines.append(f"- **Runtimes**: {runtime_str}")

    # Python interpreters — explicit list so agents never guess
    if python_interpreters:
        lines.append("- **Python interpreters in PATH**:")
        for interp in python_interpreters:
            lines.append(f"  - `{interp['path']}` → {interp['version']}")
        if pyenv.get("active"):
            lines.append(
                f"  - ⚠️ pyenv active: `{pyenv['active']}` — bare `python3` goes through shims"
            )

    if containers:
        c_str = ", ".join(f"`{k}` {v}" for k, v in containers.items() if v)
        lines.append(f"- **Containers**: {c_str}")

    if editors:
        lines.append(f"- **Editors**: {', '.join(f'`{e}`' for e in editors)}")

    if tools:
        lines.append(f"- **Key CLI tools**: {', '.join(f'`{t}`' for t in tools)}")

    if git.get("config"):
        lines.append(
            f"- **Git**: {git.get('version', '')} · {git.get('config', '').replace(chr(10), ', ')}"
        )

    # Installed app categories
    installed = summary.get("installed_apps", {})
    running = summary.get("running", {})
    ai_cli = summary.get("ai_cli_tools", [])

    if installed.get("browsers"):
        lines.append(f"- **Browsers**: {', '.join(installed['browsers'])}")

    if installed.get("terminals"):
        lines.append(f"- **Terminals**: {', '.join(installed['terminals'])}")

    if installed.get("llm_tools"):
        lines.append(f"- **LLM tools installed**: {', '.join(installed['llm_tools'])}")

    if running.get("llm_servers"):
        for srv in running["llm_servers"]:
            model_note = f" · {srv['models']}" if srv.get("models") else ""
            lines.append(
                f"- **{srv['name']}** running on `localhost:{srv['port']}`{model_note}"
            )

    if installed.get("vm_tools"):
        lines.append(f"- **VM tools**: {', '.join(installed['vm_tools'])}")

    if installed.get("gui_tools"):
        lines.append(f"- **GUI/WM tools**: {', '.join(installed['gui_tools'])}")

    if installed.get("ide_agents"):
        lines.append(
            f"- **IDEs/agents installed**: {', '.join(installed['ide_agents'])}"
        )

    if installed.get("productivity"):
        lines.append(
            f"- **Productivity/media apps**: {', '.join(installed['productivity'])}"
        )

    if ai_cli:
        # Strip full paths — just the binary names
        names = list({p.split("/")[-1] for p in ai_cli})
        lines.append(f"- **AI CLI tools**: {', '.join(names)}")

    # IDE / Agent MCP configs — the key section that eliminates config-hunting
    configured_apps = {k: v for k, v in app_configs.items() if v.get("exists")}
    if configured_apps:
        lines.append("- **IDE/Agent MCP configs**:")
        for app_key, info in configured_apps.items():
            servers = info.get("mcp_servers", [])
            disabled = info.get("mcp_servers_disabled", [])
            server_str = (
                ", ".join(f"`{s}`" for s in servers) if servers else "_(none active)_"
            )
            path_str = info.get("config_path", "")
            line = f"  - **{info['name']}** → `{path_str}`"
            line += f" · servers: {server_str}"
            if disabled:
                line += f" · disabled: {', '.join(f'`{s}`' for s in disabled)}"
            lines.append(line)

    missing_apps = {k: v for k, v in app_configs.items() if not v.get("exists")}
    if missing_apps:
        names = ", ".join(v["name"] for v in missing_apps.values())
        lines.append(f"- **No MCP config found for**: {names}")

    if hints:
        lines.append(f"- **Agent notes**: {' · '.join(hints)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def load_cache() -> dict[str, Any] | None:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except Exception:
            return None
    return None


def save_cache(data: dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def get_env_context(refresh: bool = False) -> dict[str, Any]:
    """
    Return cached env context summary, or run fresh probe if refresh=True
    or no cache exists.
    Returns: { summary, agents_md_block, cached, probe_timestamp }
    """
    cached_data = load_cache()

    if cached_data and not refresh:
        return {
            "summary": cached_data.get("summary", {}),
            "agents_md_block": cached_data.get("agents_md_block", ""),
            "cached": True,
            "probe_timestamp": cached_data.get("summary", {}).get(
                "generated_at", "unknown"
            ),
        }

    # Run fresh probe
    raw = run_probe()
    summary = synthesize(raw)
    agents_md = render_agents_md_block(summary)

    payload = {
        "summary": summary,
        "agents_md_block": agents_md,
        "raw": raw,  # kept for debugging, not normally exposed
    }
    save_cache(payload)

    return {
        "summary": summary,
        "agents_md_block": agents_md,
        "cached": False,
        "probe_timestamp": summary.get("generated_at", ""),
    }
