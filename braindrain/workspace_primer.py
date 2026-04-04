"""Workspace primer — deploy rules, apply Ruler, initialize project memory."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


TEMPLATES_DIR = Path(__file__).parent.parent / "config" / "templates" / "ruler"

# Canonical project-local docs directory (gitignored; never committed).
BRAINDRAIN_DIR = ".braindrain"

# Legacy path kept so existing workspaces can be migrated on first re-prime.
_LEGACY_DEVDOCS_DIR = ".devdocs"

DEFAULT_MEMORY_FILE = f"{BRAINDRAIN_DIR}/AGENT_MEMORY.md"
DEFAULT_INDEX_FILE = ".cursor/hooks/state/continual-learning-index.json"

# Marker file persisted after the first successful prime.
_PRIMED_MARKER = f"{BRAINDRAIN_DIR}/primed.json"


def _get_launcher_path() -> str:
    return os.environ.get(
        "BRAINDRAIN_LAUNCHER_PATH",
        str(Path(__file__).parent.parent / "config" / "braindrain"),
    )


# ---------------------------------------------------------------------------
# Agent detection
# ---------------------------------------------------------------------------

# Ordered list of (env_var, ruler_agent_id) probes.
# The first match wins — environment signals beat filesystem signals.
_ENV_AGENT_PROBES: list[tuple[str, str]] = [
    ("CURSOR_TRACE_ID", "cursor"),
    ("CURSOR_AGENT", "cursor"),
    ("CLAUDE_CODE_ENTRYPOINT", "claude"),
    ("CODEX_ENTRYPOINT", "codex"),
    ("OPENCODE_SESSION", "opencode"),
    ("WINDSURF_SESSION", "windsurf"),
    ("ZED_TERM", "zed"),
]

# Ordered list of (relative_path, ruler_agent_id) filesystem probes.
_FS_AGENT_PROBES: list[tuple[str, str]] = [
    (".cursor", "cursor"),
    (".windsurf", "windsurf"),
    (".codeium", "windsurf"),
    (".trae", "trae"),
    (".zed", "zed"),
    (".kiro", "kiro"),
    (".opencode", "opencode"),
    (".codex", "codex"),
]


def detect_prime_agents(target_dir: Optional[Path] = None) -> list[str]:
    """
    Return the best single Ruler agent id for this environment.

    Detection order:
      1. Environment variables (IDE-injected, most reliable).
      2. Presence of project-local dotfolders (e.g. .cursor/, .windsurf/).
      3. Fallback: "cursor" (safe default — most common IDE in this codebase).

    Always returns a list with exactly one element for deterministic defaults.
    Call prime() with agents=[...] for explicit multi-agent targeting.
    """
    # 1. Env-based detection (no filesystem access required).
    for env_var, agent_id in _ENV_AGENT_PROBES:
        if os.environ.get(env_var):
            return [agent_id]

    # 2. Filesystem-based detection (project-specific).
    if target_dir is not None:
        for rel_path, agent_id in _FS_AGENT_PROBES:
            if (target_dir / rel_path).exists():
                return [agent_id]

    # 3. Fallback.
    return ["cursor"]


# ---------------------------------------------------------------------------
# Primed-state marker
# ---------------------------------------------------------------------------

def _read_primed_state(target_dir: Path) -> Optional[dict]:
    """Return deserialized primed.json or None if absent/corrupt."""
    marker = target_dir / _PRIMED_MARKER
    if not marker.exists():
        return None
    try:
        return json.loads(marker.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_primed_state(target_dir: Path, agents: list[str]) -> None:
    """Persist primed.json with timestamp and resolved agents."""
    marker = target_dir / _PRIMED_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "primed_at": datetime.now(tz=timezone.utc).isoformat(),
                "agents": agents,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Legacy migration helper
# ---------------------------------------------------------------------------

def _migrate_devdocs(target_dir: Path) -> dict[str, str]:
    """
    One-time migration: copy .devdocs/ files into .braindrain/ if the
    legacy directory exists and the new one does not yet have the files.

    Returns a dict mapping filename -> action ("migrated" | "skipped_exists").
    """
    legacy = target_dir / _LEGACY_DEVDOCS_DIR
    new_dir = target_dir / BRAINDRAIN_DIR
    results: dict[str, str] = {}

    if not legacy.exists():
        return results

    migrate_files = ["AGENT_MEMORY.md", "SESSION_PROGRESS.md", "OPS.md"]
    new_dir.mkdir(parents=True, exist_ok=True)

    for fname in migrate_files:
        src = legacy / fname
        dst = new_dir / fname
        if not src.exists():
            continue
        if dst.exists():
            results[fname] = "skipped_exists"
        else:
            shutil.copy2(src, dst)
            results[fname] = "migrated"

    return results


# ---------------------------------------------------------------------------
# Template deployment
# ---------------------------------------------------------------------------

def deploy_templates(
    target_dir: Path,
    launcher_path: str,
    *,
    sync_templates: bool = False,
    agents: Optional[list[str]] = None,
    all_agents: bool = False,
) -> dict[str, dict[str, str | bool]]:
    """
    Copy Ruler templates into <target_dir>/.ruler/, substituting launcher path.

    When all_agents=False (default) and agents is provided, writes a minimal
    ruler.toml that only includes agent entries for the resolved agents plus the
    full mcp_servers/mcp_targets sections.  When all_agents=True, the full
    template is copied unchanged (all agent entries).

    Returns {filename: {action, backup}}.
    Default mode skips existing files (user-managed).
    If sync_templates=True, existing files are backed up then overwritten.
    """
    ruler_dir = target_dir / ".ruler"
    ruler_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, dict[str, str | bool]] = {}
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")

    for src in TEMPLATES_DIR.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(TEMPLATES_DIR)
        dst = ruler_dir / rel

        dst.parent.mkdir(parents=True, exist_ok=True)
        content = src.read_text(encoding="utf-8")

        if src.name == "ruler.toml":
            content = content.replace("BRAINDRAIN_LAUNCHER_PATH", launcher_path)
            # When not deploying all agents, filter the [agents] table to only
            # the resolved agent(s) so the file accurately reflects intent.
            if not all_agents and agents:
                content = _filter_ruler_toml_agents(content, agents)

        if dst.exists():
            if not sync_templates:
                written[str(rel)] = {"action": "skipped_existing", "backup": ""}
                continue
            backup = dst.with_name(f"{dst.name}.bak.{ts}")
            shutil.copy2(dst, backup)
            dst.write_text(content, encoding="utf-8")
            written[str(rel)] = {"action": "updated", "backup": str(backup)}
            continue

        dst.write_text(content, encoding="utf-8")
        written[str(rel)] = {"action": "created", "backup": ""}

    return written


def _filter_ruler_toml_agents(toml_content: str, agents: list[str]) -> str:
    """
    Strip [agents] table entries that are NOT in the given agents list.

    Operates as a simple line-by-line filter — preserves comments, formatting,
    and all other TOML sections intact.  Only removes lines of the form:
        <key> = { source = "RULES.md" }
    when <key> is not in the agents set.
    """
    agent_set = set(agents)
    lines = toml_content.splitlines(keepends=True)
    result: list[str] = []
    in_agents_table = False

    for line in lines:
        stripped = line.strip()

        # Detect section headers.
        if stripped.startswith("["):
            in_agents_table = stripped == "[agents]"
            result.append(line)
            continue

        if in_agents_table:
            # Skip blank lines and comments unconditionally inside [agents].
            if not stripped or stripped.startswith("#"):
                result.append(line)
                continue
            # key = { ... } lines: keep only if key is in agent_set.
            key = stripped.split("=")[0].strip()
            if key in agent_set:
                result.append(line)
            # else: silently drop the entry.
        else:
            result.append(line)

    return "".join(result)


# ---------------------------------------------------------------------------
# Ruler apply
# ---------------------------------------------------------------------------

def run_ruler_apply(
    target_dir: Path,
    *,
    agents: Optional[list[str]] = None,
    dry_run: bool = False,
    local_only: bool = True,
) -> dict:
    """
    Run `npx @intellectronica/ruler apply` in target_dir.

    Args:
        agents:     Explicit agent list. When None (all_agents mode), omit
                    --agents so Ruler applies every agent in the local file.
        local_only: When True (default), passes --local-only to skip global
                    XDG config merging and keep changes project-scoped.

    Returns {"ok": bool, "stdout": str, "stderr": str, "command": str}.
    """
    ruler_config = target_dir / ".ruler" / "ruler.toml"
    if not ruler_config.exists():
        return {
            "ok": False,
            "error": f".ruler/ruler.toml not found in {target_dir}",
            "stdout": "",
            "stderr": "",
        }

    cmd = ["npx", "--yes", "@intellectronica/ruler", "apply",
           "--config", str(ruler_config)]
    if dry_run:
        cmd.append("--dry-run")
    if local_only:
        cmd.append("--local-only")
    if agents:
        cmd += ["--agents", ",".join(agents)]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(target_dir),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "command": " ".join(cmd),
            "returncode": result.returncode,
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "error": "npx not found — install Node.js to use prime_workspace",
            "stdout": "",
            "stderr": "",
            "command": " ".join(cmd),
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "ruler apply timed out after 60s",
            "stdout": "",
            "stderr": "",
            "command": " ".join(cmd),
        }


# ---------------------------------------------------------------------------
# Project memory initialization
# ---------------------------------------------------------------------------

def initialize_project_memory(target_dir: Path, dry_run: bool = False) -> dict:
    """
    Initialize durable project memory artifacts used by continual learning.

    Artifacts written under .braindrain/ (gitignored):
    - .braindrain/AGENT_MEMORY.md  (high-signal durable memory)
    - .cursor/hooks/state/continual-learning-index.json (incremental transcript index)

    Also migrates any existing .devdocs/ files to .braindrain/ on first call.
    """
    memory_file = target_dir / DEFAULT_MEMORY_FILE
    index_file = target_dir / DEFAULT_INDEX_FILE

    memory_template = """# Agent Memory

This file stores high-signal, durable project memory extracted from repeated user corrections
and stable workspace facts. Do not store secrets or one-off transient notes here.

## Learned User Preferences
- (add recurring preferences only)

## Learned Workspace Facts
- (add stable, long-lived facts only)
"""

    results: dict[str, dict[str, str | bool]] = {
        "memory_file": {
            "path": str(memory_file),
            "created": False,
            "exists": memory_file.exists(),
        },
        "index_file": {
            "path": str(index_file),
            "created": False,
            "exists": index_file.exists(),
        },
    }

    if dry_run:
        if not memory_file.exists():
            results["memory_file"]["would_create"] = True
        if not index_file.exists():
            results["index_file"]["would_create"] = True
        return {"ok": True, "dry_run": True, "artifacts": results}

    # One-time migration from legacy .devdocs/ to .braindrain/.
    migration = _migrate_devdocs(target_dir)

    if not memory_file.exists():
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text(memory_template, encoding="utf-8")
        results["memory_file"]["created"] = True
        results["memory_file"]["exists"] = True

    if not index_file.exists():
        index_file.parent.mkdir(parents=True, exist_ok=True)
        index_file.write_text("{}\n", encoding="utf-8")
        results["index_file"]["created"] = True
        results["index_file"]["exists"] = True
    else:
        # Validate index JSON and preserve existing content.
        try:
            json.loads(index_file.read_text(encoding="utf-8"))
            results["index_file"]["valid_json"] = True
        except json.JSONDecodeError:
            results["index_file"]["valid_json"] = False
            return {
                "ok": False,
                "error": f"Invalid JSON in index file: {index_file}",
                "artifacts": results,
            }

    return {"ok": True, "dry_run": False, "artifacts": results, "migration": migration}


# ---------------------------------------------------------------------------
# Prime (full flow)
# ---------------------------------------------------------------------------

def prime(
    path: str = ".",
    agents: Optional[list[str]] = None,
    dry_run: bool = False,
    sync_templates: bool = False,
    all_agents: bool = False,
    local_only: bool = True,
) -> dict:
    """
    Full prime flow: deploy templates + run ruler apply + initialize memory.

    Resolution order for agents:
      1. If agents is provided explicitly → use it.
      2. If all_agents=True → deploy full template, run apply without --agents
         (Ruler applies every [agents] entry in the local file).
      3. Otherwise → detect_prime_agents() → single best-fit agent.

    On second+ runs (primed.json marker exists), the marker is updated and
    the same flow re-runs. Synthesis of project memory / project-rules.mdc
    is handled in initialize_project_memory().

    Returns structured result for MCP tool response.
    """
    target_dir = Path(path).expanduser().resolve()
    if not target_dir.exists():
        return {"ok": False, "error": f"Path does not exist: {target_dir}"}

    # Determine whether this is a first prime or a re-prime.
    prior_state = _read_primed_state(target_dir)
    is_first_prime = prior_state is None

    # Resolve agents according to priority order.
    apply_agents: Optional[list[str]]
    if agents is not None:
        apply_agents = agents
    elif all_agents:
        apply_agents = None  # Let Ruler enumerate all entries in local file.
    else:
        apply_agents = detect_prime_agents(target_dir)

    launcher_path = _get_launcher_path()

    # Step 1: deploy templates.
    if not dry_run:
        template_results = deploy_templates(
            target_dir,
            launcher_path,
            sync_templates=sync_templates,
            agents=apply_agents,
            all_agents=all_agents,
        )
    else:
        template_results = {
            str(f.relative_to(TEMPLATES_DIR)): {"action": "dry_run", "backup": ""}
            for f in TEMPLATES_DIR.rglob("*") if f.is_file()
        }

    # Step 2: run ruler apply.
    ruler_result = run_ruler_apply(
        target_dir,
        agents=apply_agents,
        dry_run=dry_run,
        local_only=local_only,
    )

    # Step 3: initialize memory artifacts (includes one-time .devdocs migration).
    memory_init = initialize_project_memory(target_dir, dry_run=dry_run)

    # Step 4: persist primed marker (skip on dry_run).
    if not dry_run and ruler_result.get("ok"):
        _write_primed_state(target_dir, apply_agents or ["all"])

    ok = bool(ruler_result["ok"] and memory_init.get("ok", False))

    return {
        "ok": ok,
        "target": str(target_dir),
        "launcher_path": launcher_path,
        "dry_run": dry_run,
        "sync_templates": sync_templates,
        "all_agents": all_agents,
        "local_only": local_only,
        "is_first_prime": is_first_prime,
        "resolved_agents": apply_agents,
        "templates": {
            "source": str(TEMPLATES_DIR),
            "deployed": template_results,
            "new_files": sum(1 for v in template_results.values() if v["action"] == "created"),
            "updated_files": sum(1 for v in template_results.values() if v["action"] == "updated"),
            "skipped_existing": sum(
                1 for v in template_results.values() if v["action"] == "skipped_existing"
            ),
        },
        "ruler": ruler_result,
        "memory_init": memory_init,
        "next_steps": (
            []
            if ok
            else [
                "Check Node.js is installed (npx must be on PATH)",
                "Run: npx @intellectronica/ruler apply --config .ruler/ruler.toml --local-only",
                "Run init_project_memory() to initialize project memory artifacts",
            ]
        ),
    }
