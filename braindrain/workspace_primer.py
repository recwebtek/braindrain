"""Workspace primer — deploy rules, apply Ruler, initialize project memory."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional


TEMPLATES_DIR = Path(__file__).parent.parent / "config" / "templates" / "ruler"
DEFAULT_MEMORY_FILE = ".devdocs/AGENT_MEMORY.md"
DEFAULT_INDEX_FILE = ".cursor/hooks/state/continual-learning-index.json"


def _get_launcher_path() -> str:
    return os.environ.get(
        "BRAINDRAIN_LAUNCHER_PATH",
        str(Path(__file__).parent.parent / "config" / "braindrain"),
    )


def deploy_templates(
    target_dir: Path,
    launcher_path: str,
    *,
    sync_templates: bool = False,
) -> dict[str, dict[str, str | bool]]:
    """
    Copy Ruler templates into <target_dir>/.ruler/, substituting launcher path.
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
        agents:     Explicit agent list. When None and not all_agents mode,
                    omit --agents so Ruler applies every agent in the local file.
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


def initialize_project_memory(target_dir: Path, dry_run: bool = False) -> dict:
    """
    Initialize durable project memory artifacts used by continual learning.

    Artifacts:
    - .devdocs/AGENT_MEMORY.md (high-signal durable memory, not generated rules)
    - .cursor/hooks/state/continual-learning-index.json (incremental transcript index)
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

    return {"ok": True, "dry_run": False, "artifacts": results}


def prime(
    path: str = ".",
    agents: Optional[list[str]] = None,
    dry_run: bool = False,
    sync_templates: bool = False,
) -> dict:
    """
    Full prime flow: deploy templates + run ruler apply + initialize memory.
    Returns structured result for MCP tool response.
    """
    target_dir = Path(path).expanduser().resolve()
    if not target_dir.exists():
        return {"ok": False, "error": f"Path does not exist: {target_dir}"}

    # If no agents specified, auto-detect IDEs or default to 'agents_md' (CLAUDE.md)
    if agents is None:
        agents = []
        # Check for Trae
        if (target_dir / ".trae").exists():
            agents.append("trae")
        # Check for Cursor
        if (target_dir / ".cursor").exists():
            agents.append("cursor")
        # Check for Windsurf
        if (target_dir / ".windsurf").exists() or (target_dir / ".codeium").exists():
            agents.append("windsurf")
        # Check for VS Code
        if (target_dir / ".vscode").exists():
            # Ruler uses 'cline' or similar for VS Code rule injection usually, 
            # but we'll stick to what it listed in valid agents.
            # In the error message, 'vscode' was invalid, but 'cline' is valid.
            agents.append("cline")
        
        # Default fallback: CLAUDE.md/AGENTS.md
        if not agents:
            agents = ["agents_md", "claude"]

    launcher_path = _get_launcher_path()

    # Step 1: deploy templates
    if not dry_run:
        template_results = deploy_templates(
            target_dir,
            launcher_path,
            sync_templates=sync_templates,
        )
    else:
        template_results = {
            str(f.relative_to(TEMPLATES_DIR)): {"action": "dry_run", "backup": ""}
            for f in TEMPLATES_DIR.rglob("*") if f.is_file()
        }

    # Step 2: run ruler apply
    ruler_result = run_ruler_apply(target_dir, agents=agents, dry_run=dry_run, local_only=True)
    # Step 3: initialize memory artifacts
    memory_init = initialize_project_memory(target_dir, dry_run=dry_run)

    return {
        "ok": bool(ruler_result["ok"] and memory_init.get("ok", False)),
        "target": str(target_dir),
        "launcher_path": launcher_path,
        "dry_run": dry_run,
        "sync_templates": sync_templates,
        "templates": {
            "source": str(TEMPLATES_DIR),
            "deployed": template_results,
            "new_files": sum(1 for v in template_results.values() if v["action"] == "created"),
            "updated_files": sum(1 for v in template_results.values() if v["action"] == "updated"),
            "skipped_existing": sum(1 for v in template_results.values() if v["action"] == "skipped_existing"),
        },
        "ruler": ruler_result,
        "memory_init": memory_init,
        "next_steps": (
            []
            if ruler_result["ok"] and memory_init.get("ok", False)
            else [
                "Check Node.js is installed",
                "Run: npx @intellectronica/ruler apply",
                "Run init_project_memory() to initialize project memory artifacts",
            ]
        ),
    }
