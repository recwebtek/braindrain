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
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CACHE_PATH = Path.home() / ".braindrain" / "env_context.json"

# ---------------------------------------------------------------------------
# Probe command groups
# Each entry: (key, shell_command)
# All run with stderr suppressed; None result means command failed/missing.
# ---------------------------------------------------------------------------

_PROBE_COMMANDS: list[tuple[str, str]] = [
    # Identity
    ("hostname",         "hostname"),
    ("computer_name",    "scutil --get ComputerName 2>/dev/null || hostname"),
    ("username",         "whoami"),
    ("uid_info",         "id"),
    # OS
    ("uname",            "uname -a"),
    ("os_release",       "cat /etc/os-release 2>/dev/null || sw_vers 2>/dev/null"),
    ("kernel",           "uname -r"),
    # Network — LAN IPs + interface names
    ("lan_ip",           "ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}'"),
    ("all_ips",          "ifconfig 2>/dev/null | grep 'inet ' | awk '{print $1, $2}' || ip -4 addr show 2>/dev/null | grep inet"),
    ("network_hosts",    "cat /etc/hosts | grep -v '^#' | grep -v '^$' | head -20"),
    # Shell & terminal
    ("shell",            "echo $SHELL"),
    ("shell_version",    "$SHELL --version 2>&1 | head -1"),
    ("term",             "echo $TERM"),
    ("term_program",     "echo $TERM_PROGRAM"),
    # Package managers (presence check)
    ("pkg_managers",     "for pm in brew apt dnf pacman nix port snap flatpak; do which $pm 2>/dev/null && echo $pm; done"),
    ("brew_version",     "brew --version 2>/dev/null | head -1"),
    # Core runtimes
    ("python_version",   "python3 --version 2>/dev/null"),
    ("node_version",     "node -v 2>/dev/null"),
    ("npm_version",      "npm -v 2>/dev/null"),
    ("go_version",       "go version 2>/dev/null"),
    ("rust_version",     "rustc --version 2>/dev/null"),
    ("ruby_version",     "ruby --version 2>/dev/null"),
    ("java_version",     "java -version 2>&1 | head -1"),
    # Version managers
    ("nvm_version",      "nvm --version 2>/dev/null || cat ~/.nvm/alias/default 2>/dev/null"),
    ("pyenv_version",    "pyenv --version 2>/dev/null"),
    ("rbenv_version",    "rbenv --version 2>/dev/null"),
    # Containers / VMs
    ("docker_version",   "docker version --format '{{.Server.Version}}' 2>/dev/null"),
    ("docker_compose",   "docker compose version 2>/dev/null | head -1"),
    ("podman_version",   "podman --version 2>/dev/null"),
    # Editors & IDEs (presence check)
    ("editors",          "for e in nvim vim nano code cursor windsurf zed; do which $e 2>/dev/null && echo $e; done"),
    ("editor_env",       "echo $EDITOR; echo $VISUAL"),
    # Key CLI tools agents commonly use
    ("modern_cli_tools", "for t in fd fzf bat rg jq gh lazygit tmux zoxide atuin delta; do which $t 2>/dev/null && echo $t; done"),
    ("git_version",      "git --version"),
    ("git_config",       "git config --global --list 2>/dev/null | grep -E 'user\\.(name|email)'"),
    # Shell config / aliases
    ("shell_aliases",    "grep -h '^alias' ~/.zshrc ~/.bashrc ~/.config/fish/config.fish 2>/dev/null | head -30"),
    # PATH
    ("path",             "echo $PATH"),
    # XDG / config dirs
    ("xdg_config",       "ls ~/.config/ 2>/dev/null | head -30"),
    # Homebrew installed formulae (top-level)
    ("brew_leaves",      "brew leaves 2>/dev/null | head -50"),
    # System resources
    ("cpu_info",         "sysctl -n machdep.cpu.brand_string 2>/dev/null || lscpu 2>/dev/null | grep 'Model name' | head -1"),
    ("memory",           "sysctl -n hw.memsize 2>/dev/null | awk '{printf \"%.0f GB\\n\", $1/1073741824}' || free -h 2>/dev/null | grep Mem | awk '{print $2}'"),
    # Init system
    ("init_system",      "ps -p 1 -o comm= 2>/dev/null || cat /proc/1/comm 2>/dev/null"),
    # Running services (limited)
    ("running_services", "systemctl --type=service --state=running 2>/dev/null | grep '●' | head -15 || launchctl list 2>/dev/null | head -15"),
    # Arch
    ("arch",             "uname -m"),
    ("os_type",          "uname -s"),
]


def _run(cmd: str) -> str | None:
    """Run a shell command, return stdout stripped or None on failure."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        out = result.stdout.strip()
        return out if out else None
    except Exception:
        return None


def run_probe() -> dict[str, Any]:
    """Execute all probe commands, return raw results dict."""
    raw: dict[str, Any] = {
        "probe_timestamp": datetime.now(timezone.utc).isoformat(),
        "platform_python": platform.platform(),
    }
    for key, cmd in _PROBE_COMMANDS:
        raw[key] = _run(cmd)
    return raw


# ---------------------------------------------------------------------------
# Synthesizer — turns raw probe output into a structured summary
# ---------------------------------------------------------------------------

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

    # Package manager (first found wins)
    pkg_mgrs = [l.strip() for l in _val("pkg_managers").splitlines() if l.strip()]

    # Installed editors
    editors = [l.strip() for l in _val("editors").splitlines() if l.strip()]
    editor_env = [e for e in _val("editor_env").splitlines() if e.strip() and e.strip() != "''"]

    # Modern CLI tools present
    modern_tools = [l.strip() for l in _val("modern_cli_tools").splitlines() if l.strip()]

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
    lan_ips = list({
        line.split()[-1]
        for line in all_ips_raw.splitlines()
        if line.strip() and "127.0.0.1" not in line and "::1" not in line
    })

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
        agent_hints.append("macOS — avoid Linux-only flags (e.g. `--no-preserve-root`, `date -d`)")
    if is_linux:
        agent_hints.append("Linux — systemd available" if "systemd" in _val("init_system") else "Linux")

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
        "brew_packages": [l.strip() for l in _val("brew_leaves").splitlines() if l.strip()],
        "path_entries": [p for p in _val("path").split(":") if p],
        "xdg_config_dirs": [l.strip() for l in _val("xdg_config").splitlines() if l.strip()],
        "shell_aliases_sample": [l.strip() for l in _val("shell_aliases").splitlines() if l.strip()],
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

    lines = [
        f"## OS Environment Context",
        f"<!-- generated by braindrain env_context — {summary.get('generated_at', '')[:10]} -->",
        f"",
        f"- **User**: `{ident.get('username', 'unknown')}` on `{ident.get('hostname', 'unknown')}`",
        f"- **LAN IPs**: {', '.join(f'`{ip}`' for ip in ident.get('lan_ips', [])) or 'n/a'}",
        f"- **OS**: {os_info.get('type', '')} — {os_info.get('detail', '')} · {os_info.get('arch', '')}",
        f"- **Kernel**: `{os_info.get('kernel', 'n/a')}`",
    ]

    if hw.get("cpu") or hw.get("memory"):
        lines.append(f"- **Hardware**: {hw.get('cpu', '')} · {hw.get('memory', '')} RAM")

    lines.append(f"- **Shell**: `{shell.get('path', '')}` · terminal: `{shell.get('term', '')}`")

    pkg_mgrs = summary.get("package_managers", [])
    if pkg_mgrs:
        lines.append(f"- **Package manager**: `{pkg_mgrs[0]}`" + (f" (also: {', '.join(pkg_mgrs[1:])})" if len(pkg_mgrs) > 1 else ""))

    if runtimes:
        runtime_str = " · ".join(f"`{k}` {v.split()[-1] if v else ''}" for k, v in runtimes.items())
        lines.append(f"- **Runtimes**: {runtime_str}")

    if containers:
        c_str = ", ".join(f"`{k}` {v}" for k, v in containers.items() if v)
        lines.append(f"- **Containers**: {c_str}")

    if editors:
        lines.append(f"- **Editors**: {', '.join(f'`{e}`' for e in editors)}")

    if tools:
        lines.append(f"- **Key CLI tools**: {', '.join(f'`{t}`' for t in tools)}")

    if git.get("config"):
        lines.append(f"- **Git**: {git.get('version', '')} · {git.get('config', '').replace(chr(10), ', ')}")

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
            "probe_timestamp": cached_data.get("summary", {}).get("generated_at", "unknown"),
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
