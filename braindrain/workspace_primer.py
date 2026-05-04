"""Workspace primer — deploy rules, apply Ruler, initialize project memory."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from braindrain.scriptlib import (
    enabled_for_workspace,
    render_guidance as render_scriptlib_guidance,
    seed_if_enabled,
)

TEMPLATES_DIR = Path(__file__).parent.parent / "config" / "templates" / "ruler"
AGENT_TEMPLATES_DIR = Path(__file__).parent.parent / "config" / "templates" / "agents"
CURSOR_HOOK_TEMPLATES_DIR = Path(__file__).parent.parent / "config" / "templates" / "cursor"

# Canonical project-local docs directory (gitignored; never committed).
BRAINDRAIN_DIR = ".braindrain"

# Legacy path kept so existing workspaces can be migrated on first re-prime.
_LEGACY_DEVDOCS_DIR = ".devdocs"

DEFAULT_MEMORY_FILE = f"{BRAINDRAIN_DIR}/AGENT_MEMORY.md"
DEFAULT_INDEX_FILE = ".cursor/hooks/state/continual-learning-index.json"

# Marker file persisted after the first successful prime.
_PRIMED_MARKER = f"{BRAINDRAIN_DIR}/primed.json"
BUNDLES_DIR = Path(__file__).parent.parent / "config" / "bundles"
DEFAULT_BUNDLE = "core"


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

# Cursor sets TERM_PROGRAM when the integrated terminal runs; the MCP server
# subprocess often does NOT inherit CURSOR_TRACE_ID — use this as a fallback.
_TERM_PROGRAM_AGENTS: dict[str, str] = {
    "cursor": "cursor",
    "Cursor": "cursor",
    "vscode": "cursor",  # Cursor is Electron-based; terminal may report vscode
}

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


def detect_prime_agents(target_dir: Optional[Path] = None) -> tuple[list[str], str]:
    """
    Return the best single Ruler agent id for this environment and a short
    label describing how it was chosen (for telemetry / debugging).

    Detection order:
      1. Environment variables (IDE-injected, most reliable).
      2. TERM_PROGRAM (Cursor/VS Code family when MCP child lacks CURSOR_*).
      3. Presence of project-local dotfolders (e.g. .cursor/, .windsurf/).
      4. Fallback: "cursor" (safe default — most common IDE in this codebase).

    Always returns a list with exactly one element for deterministic defaults.
    Call prime() with agents=[...] for explicit multi-agent targeting.
    """
    # 1. Env-based detection (no filesystem access required).
    for env_var, agent_id in _ENV_AGENT_PROBES:
        if os.environ.get(env_var):
            return [agent_id], f"env:{env_var}"

    tp = os.environ.get("TERM_PROGRAM", "").strip()
    if tp in _TERM_PROGRAM_AGENTS:
        return [_TERM_PROGRAM_AGENTS[tp]], f"env:TERM_PROGRAM={tp}"

    # 2. Filesystem-based detection (project-specific).
    if target_dir is not None:
        for rel_path, agent_id in _FS_AGENT_PROBES:
            if (target_dir / rel_path).exists():
                return [agent_id], f"fs:{rel_path}"

    # 3. Fallback.
    return ["cursor"], "fallback:cursor"


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


def _write_primed_state(
    target_dir: Path,
    agents: list[str],
    *,
    bundle: str = DEFAULT_BUNDLE,
    bundle_version: str = "1",
) -> None:
    """Persist primed.json with timestamp and resolved agents."""
    marker = target_dir / _PRIMED_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "primed_at": datetime.now(tz=timezone.utc).isoformat(),
                "agents": agents,
                "bundle": bundle,
                "bundle_version": bundle_version,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _load_bundle_manifest(bundle: str) -> dict:
    """Load bundle manifest from config/bundles/<bundle>.yaml."""
    path = BUNDLES_DIR / f"{bundle}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Bundle manifest not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid bundle manifest format: {path}")
    required = ("name", "version", "agents", "rules", "skills", "mcp_servers")
    missing = [k for k in required if k not in raw]
    if missing:
        raise ValueError(f"Bundle manifest missing keys {missing}: {path}")
    return raw


def _resolve_bundle_manifest(bundle: Optional[str]) -> dict:
    bundle_name = (bundle or DEFAULT_BUNDLE).strip() or DEFAULT_BUNDLE
    return _load_bundle_manifest(bundle_name)


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

def _materialize_ruler_toml_text(
    launcher_path: str,
    *,
    agents: Optional[list[str]],
    all_agents: bool,
) -> str:
    """Build the ruler.toml body that should live on disk for this prime."""
    raw = (TEMPLATES_DIR / "ruler.toml").read_text(encoding="utf-8")
    content = raw.replace("BRAINDRAIN_LAUNCHER_PATH", launcher_path)
    if not all_agents and agents:
        content = _filter_ruler_toml_agents(content, agents)
    return content


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

    **Important:** If `.ruler/ruler.toml` already exists, it is still **replaced**
    when in minimal mode whenever the on-disk content would differ from the
    filtered template. Otherwise Ruler's `--gitignore` and config merge would
    still reflect the old bloated `[agents]` table even though `--agents cursor`
    was passed.

    Returns {filename: {action, backup}}.
    Default mode skips existing files (user-managed) except the minimal-ruler
    refresh path above.
    If sync_templates=True, existing files are backed up then overwritten.
    """
    ruler_dir = target_dir / ".ruler"
    ruler_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, dict[str, str | bool]] = {}
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")

    force_minimal = not all_agents and bool(agents)
    minimal_ruler_updated = False
    scriptlib_guidance_enabled = enabled_for_workspace(target_dir)

    # Phase 1 — ruler.toml first (ordering-independent).
    ruler_dst = ruler_dir / "ruler.toml"
    ruler_dst.parent.mkdir(parents=True, exist_ok=True)
    ruler_content = _materialize_ruler_toml_text(
        launcher_path, agents=agents, all_agents=all_agents
    )
    if force_minimal:
        if not ruler_dst.exists():
            ruler_dst.write_text(ruler_content, encoding="utf-8")
            written["ruler.toml"] = {"action": "created", "backup": ""}
            minimal_ruler_updated = True
        elif ruler_dst.read_text(encoding="utf-8") != ruler_content:
            backup = ruler_dst.with_name(f"{ruler_dst.name}.bak.{ts}")
            shutil.copy2(ruler_dst, backup)
            ruler_dst.write_text(ruler_content, encoding="utf-8")
            written["ruler.toml"] = {
                "action": "updated_minimal_agents",
                "backup": str(backup),
            }
            minimal_ruler_updated = True
        else:
            written["ruler.toml"] = {"action": "skipped_existing", "backup": ""}
    else:
        # Full template: same behaviour as before (skip unless sync).
        if ruler_dst.exists():
            if not sync_templates:
                written["ruler.toml"] = {"action": "skipped_existing", "backup": ""}
            else:
                backup = ruler_dst.with_name(f"{ruler_dst.name}.bak.{ts}")
                shutil.copy2(ruler_dst, backup)
                ruler_dst.write_text(ruler_content, encoding="utf-8")
                written["ruler.toml"] = {"action": "updated", "backup": str(backup)}
        else:
            ruler_dst.write_text(ruler_content, encoding="utf-8")
            written["ruler.toml"] = {"action": "created", "backup": ""}

    refresh_sources = sync_templates or (force_minimal and minimal_ruler_updated)

    # Phase 2 — RULES.md and AGENTS.md (depend on minimal_ruler_updated).
    for name in ("RULES.md", "AGENTS.md"):
        src = TEMPLATES_DIR / name
        if not src.is_file():
            continue
        dst = ruler_dir / name
        content = src.read_text(encoding="utf-8")
        content = render_scriptlib_guidance(content, enabled=scriptlib_guidance_enabled)
        if dst.exists():
            existing_content = dst.read_text(encoding="utf-8")
            if existing_content == content:
                written[name] = {"action": "skipped_existing", "backup": ""}
                continue
            if not refresh_sources:
                backup = dst.with_name(f"{dst.name}.bak.{ts}")
                shutil.copy2(dst, backup)
                dst.write_text(content, encoding="utf-8")
                written[name] = {"action": "updated_scriptlib_guidance", "backup": str(backup)}
                continue
            backup = dst.with_name(f"{dst.name}.bak.{ts}")
            shutil.copy2(dst, backup)
            dst.write_text(content, encoding="utf-8")
            action = "updated" if sync_templates else "updated_with_minimal_ruler"
            written[name] = {"action": action, "backup": str(backup)}
        else:
            dst.write_text(content, encoding="utf-8")
            written[name] = {"action": "created", "backup": ""}

    return written


_SUBAGENT_ACTION_RANK = {
    "updated": 4,
    "created": 3,
    "created_from_empty": 3,
    "skipped_existing": 2,
    "dry_run": 1,
}


def _deploy_subagent_templates_to_dir(
    *,
    agents_dir: Path,
    sync_subagents: bool,
) -> dict[str, dict[str, str | bool]]:
    """Copy ``config/templates/agents/*.md`` into ``agents_dir``."""
    agents_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, dict[str, str | bool]] = {}
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")

    for src in sorted(AGENT_TEMPLATES_DIR.glob("*.md")):
        dst = agents_dir / src.name
        content = src.read_text(encoding="utf-8")
        if dst.exists():
            if sync_subagents:
                backup = dst.with_name(f"{dst.name}.bak.{ts}")
                shutil.copy2(dst, backup)
                dst.write_text(content, encoding="utf-8")
                written[src.name] = {"action": "updated", "backup": str(backup)}
            else:
                existing = dst.read_text(encoding="utf-8", errors="ignore")
                if existing.strip():
                    written[src.name] = {"action": "skipped_existing", "backup": ""}
                else:
                    dst.write_text(content, encoding="utf-8")
                    written[src.name] = {"action": "created_from_empty", "backup": ""}
        else:
            dst.write_text(content, encoding="utf-8")
            written[src.name] = {"action": "created", "backup": ""}
    return written


def _merge_subagent_deploy_results(
    left: dict[str, dict[str, str | bool]],
    right: dict[str, dict[str, str | bool]],
) -> dict[str, dict[str, str | bool]]:
    """Merge per-file deploy metadata from two destination trees."""
    merged: dict[str, dict[str, str | bool]] = dict(left)
    for fname, meta in right.items():
        if fname not in merged:
            merged[fname] = dict(meta)
            continue
        a = str((merged[fname] or {}).get("action") or "")
        b = str((meta or {}).get("action") or "")
        pick = (
            a
            if _SUBAGENT_ACTION_RANK.get(a, 0) >= _SUBAGENT_ACTION_RANK.get(b, 0)
            else b
        )
        ba = str((merged[fname] or {}).get("backup") or "")
        bb = str((meta or {}).get("backup") or "")
        backup = bb if pick == b and bb else ba
        merged[fname] = {"action": pick, "backup": backup}
    return merged


def deploy_subagent_templates(
    target_dir: Path,
    *,
    sync_subagents: bool = False,
    to_cursor: bool = True,
    to_codex: bool = False,
) -> dict[str, dict[str, str | bool]]:
    """
    Deploy subagent markdown from ``config/templates/agents/`` into IDE agent dirs.

    When ``to_cursor`` is True, writes ``.cursor/agents/*.md``.
    When ``to_codex`` is True, writes ``.codex/agents/*.md``.
    Both can be True so a single canonical template tree serves every IDE.

    Default mode is create-only:
      - missing files are created
      - existing non-empty files are preserved
      - existing empty files are filled

    When sync_subagents=True:
      - existing files are backed up to .bak.<timestamp> and overwritten
    """
    if not AGENT_TEMPLATES_DIR.exists():
        return {}

    partials: list[dict[str, dict[str, str | bool]]] = []
    if to_cursor:
        partials.append(
            _deploy_subagent_templates_to_dir(
                agents_dir=target_dir / ".cursor" / "agents",
                sync_subagents=sync_subagents,
            )
        )
    if to_codex:
        partials.append(
            _deploy_subagent_templates_to_dir(
                agents_dir=target_dir / ".codex" / "agents",
                sync_subagents=sync_subagents,
            )
        )
    if not partials:
        return {}

    out = partials[0]
    for p in partials[1:]:
        out = _merge_subagent_deploy_results(out, p)
    return out


def deploy_cursor_hook_templates(
    target_dir: Path,
    *,
    sync_templates: bool = False,
    dry_run: bool = False,
) -> dict[str, dict[str, str | bool]]:
    """
    Deploy Cursor hooks from ``config/templates/cursor`` → ``.cursor/``.

    Writes:

    - ``.cursor/hooks.json``
    - ``.cursor/hooks/on-stop-gitops.sh``
    - ``.cursor/hooks/on-stop-observe.sh``

    Default is create-only (existing files are preserved). When
    ``sync_templates=True``, existing files are backed up then overwritten —
    same contract as ``deploy_templates()`` for Ruler sources.
    """
    if not CURSOR_HOOK_TEMPLATES_DIR.is_dir():
        return {}

    written: dict[str, dict[str, str | bool]] = {}
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    cursor_dir = target_dir / ".cursor"
    hooks_dir = cursor_dir / "hooks"

    def _maybe_chmod_exec(path: Path) -> None:
        if dry_run or not path.is_file():
            return
        try:
            path.chmod(path.stat().st_mode | 0o111)
        except OSError:
            pass

    entries: list[tuple[str, Path, Path, bool]] = []
    hj = CURSOR_HOOK_TEMPLATES_DIR / "hooks.json"
    if hj.is_file():
        entries.append(("hooks.json", hj, cursor_dir / "hooks.json", False))
    shell_src = CURSOR_HOOK_TEMPLATES_DIR / "hooks"
    if shell_src.is_dir():
        for src in sorted(shell_src.glob("*.sh")):
            entries.append(
                (f"hooks/{src.name}", src, hooks_dir / src.name, True)
            )

    for rel, src, dst, executable in entries:
        if dry_run:
            written[rel] = {"action": "dry_run", "backup": ""}
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        content = src.read_text(encoding="utf-8")
        if dst.exists():
            if not sync_templates:
                written[rel] = {"action": "skipped_existing", "backup": ""}
                continue
            backup = dst.with_name(f"{dst.name}.bak.{ts}")
            shutil.copy2(dst, backup)
            dst.write_text(content, encoding="utf-8")
            if executable:
                _maybe_chmod_exec(dst)
            written[rel] = {"action": "updated", "backup": str(backup)}
        else:
            dst.write_text(content, encoding="utf-8")
            if executable:
                _maybe_chmod_exec(dst)
            written[rel] = {"action": "created", "backup": ""}

    return written


def _build_codex_subagent_block(codex_agent_targets: list[str]) -> str:
    """Render managed TOML block for codex subagent path hints."""
    quoted = ", ".join(f'"{p}"' for p in codex_agent_targets)
    return (
        "# BEGIN BRAINDRAIN SUBAGENTS\n"
        "[braindrain_subagents]\n"
        f"paths = [{quoted}]\n"
        "# END BRAINDRAIN SUBAGENTS\n"
    )


def ensure_codex_subagent_config(
    target_dir: Path,
    *,
    codex_agent_targets: list[str],
    dry_run: bool = False,
    sync_subagents: bool = False,
) -> dict[str, str | bool]:
    """
    Manage project-local .codex/config.toml subagent path hints safely.

    Policy:
    - sync_subagents=False: do not mutate existing config; create only if missing.
    - sync_subagents=True: update/append managed block with backup-first writes.
    """
    config_path = target_dir / ".codex" / "config.toml"
    result: dict[str, str | bool] = {
        "ok": True,
        "path": str(config_path),
        "sync_subagents": sync_subagents,
    }
    block = _build_codex_subagent_block(codex_agent_targets)
    begin_marker = "# BEGIN BRAINDRAIN SUBAGENTS"
    end_marker = "# END BRAINDRAIN SUBAGENTS"

    if dry_run:
        if not config_path.exists():
            result["action"] = "dry_run_create"
            return result
        if not sync_subagents:
            result["action"] = "dry_run_skip_existing_no_sync"
            return result
        raw = config_path.read_text(encoding="utf-8", errors="ignore")
        result["action"] = (
            "dry_run_update_managed_block"
            if begin_marker in raw and end_marker in raw
            else "dry_run_append_managed_block"
        )
        return result

    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(block, encoding="utf-8")
        result["action"] = "created"
        return result

    if not sync_subagents:
        result["action"] = "skipped_existing_no_sync"
        return result

    raw = config_path.read_text(encoding="utf-8", errors="ignore")
    managed_re = re.compile(
        r"# BEGIN BRAINDRAIN SUBAGENTS\n.*?# END BRAINDRAIN SUBAGENTS\n?",
        flags=re.DOTALL,
    )
    if managed_re.search(raw):
        next_raw = managed_re.sub(block, raw, count=1)
    else:
        sep = "\n\n" if raw.strip() else ""
        next_raw = raw.rstrip("\n") + sep + block

    if next_raw == raw:
        result["action"] = "skipped_already_up_to_date"
        return result

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = config_path.with_name(f"{config_path.name}.bak.{ts}")
    shutil.copy2(config_path, backup)
    config_path.write_text(
        next_raw if next_raw.endswith("\n") else next_raw + "\n", encoding="utf-8"
    )
    result["action"] = "updated"
    result["backup"] = str(backup)
    return result


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


# Cursor: managed region inside project-rules.mdc (user text outside is preserved).
_PROJECT_CONTEXT_START = "<!-- braindrain:project-context:start -->"
_PROJECT_CONTEXT_END = "<!-- braindrain:project-context:end -->"
# Legacy primes duplicated .ruler/RULES.md here — migrate to project-context on next prime.
_PROJECT_RULES_LEGACY_START = "<!-- braindrain:project-rules:start -->"
_PROJECT_RULES_LEGACY_END = "<!-- braindrain:project-rules:end -->"


def _read_braindrain_sidecar_md(target_dir: Path, name: str) -> str | None:
    """Read ``name`` from ``.braindrain/`` or legacy ``.devdocs/``."""
    for sub in (BRAINDRAIN_DIR, _LEGACY_DEVDOCS_DIR):
        p = target_dir / sub / name
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="ignore")
    return None


def _extract_markdown_h2_sections(text: str, titles: tuple[str, ...], max_per: int) -> str:
    """Take full ``## Title`` sections until the next ``## `` heading."""
    chunks: list[str] = []
    for title in titles:
        if title not in text:
            continue
        start = text.index(title)
        rest = text[start:]
        lines: list[str] = []
        first = True
        for line in rest.splitlines():
            if first:
                lines.append(line)
                first = False
                continue
            if line.startswith("## ") and line.strip() != title.strip():
                break
            lines.append(line)
        chunk = "\n".join(lines).strip()
        if len(chunk) > max_per:
            chunk = chunk[: max_per - 24].rstrip() + "\n\n… (truncated)"
        chunks.append(chunk)
    return "\n\n".join(chunks)


def _first_non_empty_lines(text: str, max_lines: int, skip_all_header_lines: bool = False) -> str:
    """First ``max_lines`` substantive lines (light trim; keeps bullets)."""
    lines_out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if skip_all_header_lines and s.startswith("#"):
            continue
        lines_out.append(line.rstrip())
        if len(lines_out) >= max_lines:
            break
    return "\n".join(lines_out)


def _last_dated_or_section_block(text: str, max_chars: int) -> str | None:
    """Prefer last ``### `` subsection; else last ``## `` section."""
    t = text.strip()
    if not t:
        return None
    parts = re.split(r"\n(?=### )", t)
    if len(parts) > 1:
        block = parts[-1].strip()
        return block[:max_chars] if block else None
    parts2 = re.split(r"\n(?=## )", t)
    if len(parts2) > 1:
        block = parts2[-1].strip()
        return block[:max_chars] if block else None
    return t[:max_chars]


def synthesize_project_rules_body(target_dir: Path, *, max_chars: int = 6000) -> str:
    """
    Build markdown for ``project-rules.mdc`` from workspace memory/ops/session docs.

    Conservative and deterministic: no secrets heuristic beyond normal file trust;
    callers store secrets outside these files.
    """
    parts: list[str] = []

    mem = _read_braindrain_sidecar_md(target_dir, "AGENT_MEMORY.md")
    if mem:
        learned = _extract_markdown_h2_sections(
            mem,
            ("## Learned User Preferences", "## Learned Workspace Facts"),
            max_per=2800,
        )
        if learned:
            parts.append("## From AGENT_MEMORY.md\n\n" + learned)

    ops = _read_braindrain_sidecar_md(target_dir, "OPS.md")
    if ops:
        op_lines = _first_non_empty_lines(ops, 45, skip_all_header_lines=True)
        if op_lines:
            parts.append("## From OPS.md (summary)\n\n" + op_lines)

    sess = _read_braindrain_sidecar_md(target_dir, "SESSION_PROGRESS.md")
    if sess:
        block = _last_dated_or_section_block(sess, max_chars=3800)
        if block:
            parts.append("## Recent session / progress\n\n" + block)

    body = "\n\n".join(parts).strip()
    if not body:
        body = (
            "_No project-specific excerpts yet._ Add durable facts to `.braindrain/AGENT_MEMORY.md`, "
            "operational notes to `.braindrain/OPS.md`, and progress to `.braindrain/SESSION_PROGRESS.md` "
            "(legacy `.devdocs/` is read if `.braindrain/` is missing). "
            "Re-run `prime_workspace()` to refresh this block; agents may refine `project-rules.mdc` over time."
        )
    if len(body) > max_chars:
        body = body[: max_chars - 24].rstrip() + "\n\n… (truncated)"
    return body


def _project_rules_mdc_frontmatter() -> str:
    return (
        "---\n"
        "description: Project-specific Cursor rules (from .braindrain; maintained by prime_workspace)\n"
        "alwaysApply: true\n"
        "---\n\n"
    )


def _project_rules_static_intro() -> str:
    return (
        "# Project context\n\n"
        "Do **not** duplicate the BRAINDRAIN protocol here; it lives in `braindrain.mdc`. "
        "The managed block below is refreshed from `.braindrain/` (or legacy `.devdocs/`) when you run "
        "`prime_workspace()`.\n\n"
    )


def merge_project_rules_mdc(
    existing: str | None,
    synthesized: str,
) -> str:
    """
    Insert or replace the managed project-context region, preserving user suffix text.

    Migrates legacy ``project-rules`` markers that duplicated ``RULES.md``.
    """
    intro = _project_rules_static_intro()
    fm = _project_rules_mdc_frontmatter()
    managed = (
        f"{_PROJECT_CONTEXT_START}\n{synthesized}\n{_PROJECT_CONTEXT_END}\n"
    )

    ex_raw = existing or ""
    if not ex_raw.strip():
        return fm + intro + managed

    if _PROJECT_CONTEXT_START in ex_raw and _PROJECT_CONTEXT_END in ex_raw:
        before, _, rest = ex_raw.partition(_PROJECT_CONTEXT_START)
        _, _, after = rest.partition(_PROJECT_CONTEXT_END)
        return before + _PROJECT_CONTEXT_START + "\n" + synthesized + "\n" + _PROJECT_CONTEXT_END + after

    if _PROJECT_RULES_LEGACY_START in ex_raw and _PROJECT_RULES_LEGACY_END in ex_raw:
        _, _, rest = ex_raw.partition(_PROJECT_RULES_LEGACY_START)
        _, _, after_old = rest.partition(_PROJECT_RULES_LEGACY_END)
        return fm + intro + managed + after_old.lstrip("\n")

    sep = "\n\n"
    return ex_raw.rstrip() + sep + "## Project context (managed)\n\n" + managed

# Appended to .gitignore by prime_workspace (Ruler’s own --gitignore is off by default).
_GITIGNORE_PROTOCOL_BEGIN = "# BEGIN BRAINDRAIN GITIGNORE PROTOCOL"

_GITIGNORE_PROTOCOL_BLOCK = """# BEGIN BRAINDRAIN GITIGNORE PROTOCOL — do not remove (maintained by prime_workspace)
# Ruler does NOT own .gitignore here: we pass --gitignore false to ruler apply and maintain this block instead.
# Root-level dotfiles/dotdirs are local-only (IDE, MCP, secrets). Add ! exceptions only for paths that must ship.
/.*
!/.github/
!/.gitignore
!/.gitattributes
!/.gitmodules
!/.env.example
# If your team commits other root dotdirs (e.g. .husky), add: !/.husky/
# END BRAINDRAIN GITIGNORE PROTOCOL
"""


def ensure_gitignore_braindrain_protocol(
    target_dir: Path,
    *,
    dry_run: bool = False,
) -> dict[str, str | bool]:
    """
    Append the BRAINDRAIN root dotfile gitignore block if missing.

    This is the supported way to keep local dotfiles out of git; Ruler’s
    built-in --gitignore updates are disabled in run_ruler_apply by default
    so we are not fighting two writers.
    """
    gi = target_dir / ".gitignore"
    result: dict[str, str | bool] = {"ok": True, "path": str(gi)}
    if dry_run:
        exists = gi.is_file()
        has_block = exists and _GITIGNORE_PROTOCOL_BEGIN in gi.read_text(encoding="utf-8", errors="ignore")
        result["dry_run"] = True
        result["would_append"] = not has_block
        return result

    text = gi.read_text(encoding="utf-8", errors="ignore") if gi.is_file() else ""
    if _GITIGNORE_PROTOCOL_BEGIN in text:
        result["action"] = "skipped_already_present"
        return result

    sep = "\n\n" if text.strip() else ""
    gi.write_text(text.rstrip() + sep + _GITIGNORE_PROTOCOL_BLOCK + "\n", encoding="utf-8")
    result["action"] = "appended"
    return result


def ensure_cursor_mcp_json_server_name_at(
    path: Path,
    *,
    dry_run: bool = False,
) -> dict[str, str | bool]:
    """
    Set ``serverName`` on each entry under ``mcpServers`` in the given ``mcp.json`` path.

    Cursor’s MCP adapter logs a warning when ``serverName`` is absent (identifier
    falls back to the JSON key, e.g. ``user-braindrain``).  We set ``serverName``
    to the key with the ``user-`` prefix stripped so the adapter has a stable name.
    """
    result: dict[str, str | bool] = {"ok": True, "path": str(path)}
    if not path.is_file():
        result["skipped"] = "no_file"
        return result

    raw = path.read_text(encoding="utf-8", errors="ignore")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        result["ok"] = False
        result["error"] = "invalid_json"
        return result

    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        result["skipped"] = "no_mcpServers"
        return result

    changed = False
    for key, entry in servers.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("serverName"):
            continue
        if "command" not in entry and "url" not in entry:
            continue
        name = str(key).removeprefix("user-")
        entry["serverName"] = name
        changed = True

    if dry_run:
        result["dry_run"] = True
        result["would_patch"] = changed
        return result

    if changed:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        result["action"] = "patched"
    else:
        result["action"] = "skipped_all_had_serverName"

    return result


def ensure_cursor_mcp_json_server_name(
    target_dir: Path,
    *,
    dry_run: bool = False,
) -> dict[str, str | bool]:
    """Patch ``<target_dir>/.cursor/mcp.json`` (project-local Cursor MCP config)."""
    return ensure_cursor_mcp_json_server_name_at(
        target_dir / ".cursor" / "mcp.json",
        dry_run=dry_run,
    )


def create_prime_snapshot(target_dir: Path, *, dry_run: bool = False) -> dict[str, str | bool]:
    """Create a lightweight rollback snapshot before mutating prime files."""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    snapshot_dir = target_dir / BRAINDRAIN_DIR / "rollback" / ts
    tracked = [
        target_dir / ".ruler" / "ruler.toml",
        target_dir / ".cursor" / "mcp.json",
        target_dir / ".cursor" / "rules" / "project-rules.mdc",
        target_dir / ".cursor" / "rules" / "braindrain.mdc",
    ]
    if dry_run:
        return {"ok": True, "dry_run": True, "snapshot_dir": str(snapshot_dir)}
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src in tracked:
        if not src.exists():
            continue
        rel = src.relative_to(target_dir)
        dst = snapshot_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1
    return {"ok": True, "snapshot_dir": str(snapshot_dir), "files_copied": copied}


def verify_prime_install(target_dir: Path, bundle_manifest: dict) -> dict:
    """Run a lightweight verification checklist after prime."""
    checks = {
        "bundle_manifest_loaded": bool(bundle_manifest),
        "ruler_config_exists": (target_dir / ".ruler" / "ruler.toml").exists(),
        "memory_file_exists": (target_dir / DEFAULT_MEMORY_FILE).exists(),
        "index_file_exists": (target_dir / DEFAULT_INDEX_FILE).exists(),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
    }


def compact_prime_result_for_mcp(
    result: dict,
    *,
    max_ruler_text: int = 8000,
) -> dict:
    """
    Shrink ``prime()`` output for MCP JSON-RPC responses.

    Large payloads (full ``templates.deployed``, long Ruler stdout) can exceed
    client buffers or timing, causing ``ClosedResourceError`` when the host
    closes the stdio stream before the full tool result is written.
    """
    if not isinstance(result, dict):
        return result
    out = {k: v for k, v in result.items() if k not in ("templates", "ruler", "memory_init", "cursor_hooks")}
    tpl = result.get("templates") or {}
    deployed = tpl.get("deployed") or {}
    out["templates"] = {
        "source": tpl.get("source"),
        "new_files": tpl.get("new_files"),
        "updated_files": tpl.get("updated_files"),
        "skipped_existing": tpl.get("skipped_existing"),
        "deployed_summary": [
            {"file": k, "action": (v or {}).get("action")}
            for k, v in deployed.items()
        ],
    }
    r = dict(result.get("ruler") or {})
    for key in ("stdout", "stderr"):
        val = r.get(key)
        if isinstance(val, str) and len(val) > max_ruler_text:
            extra = len(val) - max_ruler_text
            r[key] = val[:max_ruler_text] + f"\n… [{extra} chars truncated]"
            r[f"{key}_truncated"] = True
    out["ruler"] = r
    mem = dict(result.get("memory_init") or {})
    arts = mem.get("artifacts")
    if isinstance(arts, dict):
        slim: dict[str, dict[str, str | bool]] = {}
        for k, v in arts.items():
            if isinstance(v, dict):
                slim[k] = {
                    kk: vv
                    for kk, vv in v.items()
                    if kk in ("created", "exists", "valid_json", "would_create")
                }
            else:
                slim[k] = v  # type: ignore[assignment]
        mem["artifacts"] = slim
    out["memory_init"] = mem
    ch = result.get("cursor_hooks") or {}
    deployed_ch = ch.get("deployed") or {}
    if isinstance(deployed_ch, dict) and deployed_ch:
        out["cursor_hooks"] = {
            "source": ch.get("source"),
            "skipped": ch.get("skipped"),
            "new_files": ch.get("new_files"),
            "updated_files": ch.get("updated_files"),
            "skipped_existing": ch.get("skipped_existing"),
            "deployed_summary": [
                {"file": k, "action": (v or {}).get("action")}
                for k, v in deployed_ch.items()
            ],
        }
    out["subagents"] = result.get("subagents")
    out["codex_subagent_config"] = result.get("codex_subagent_config")
    out["_mcp_response_compact"] = True
    return out


def sync_cursor_rules_from_ruler(
    target_dir: Path,
    *,
    dry_run: bool = False,
    include_cursor: bool = True,
) -> dict[str, str | bool]:
    """
    Ensure Cursor has BRAINDRAIN protocol rules and separate project-context rules.

    Writes:
      - `.cursor/rules/braindrain.mdc` — full protocol from `.ruler/RULES.md` (alwaysApply).
      - `.cursor/rules/project-rules.mdc` — **project-only** excerpts from
        `.braindrain/` (``AGENT_MEMORY.md``, ``OPS.md``, ``SESSION_PROGRESS.md``),
        with legacy `.devdocs/` as fallback. Managed between
        ``<!-- braindrain:project-context:start/end -->``; does **not** duplicate
        ``RULES.md``. Legacy ``project-rules`` markers that mirrored the protocol
        are migrated on the next prime.

    Ruler may also emit `braindrain.mdc`; we overwrite with template-driven
    content so behaviour is predictable after prime.
    """
    result: dict[str, str | bool] = {"ok": True, "dry_run": dry_run}
    if not include_cursor:
        result["skipped"] = "include_cursor=False"
        return result

    rules_path = target_dir / ".ruler" / "RULES.md"
    if not rules_path.is_file():
        result["ok"] = False
        result["error"] = f"Missing {rules_path}"
        return result

    body = rules_path.read_text(encoding="utf-8").strip()
    frontmatter = (
        "---\n"
        "description: BRAINDRAIN protocol (synced from .ruler/RULES.md by prime_workspace)\n"
        "alwaysApply: true\n"
        "---\n\n"
    )
    mdc_full = frontmatter + body + "\n"

    synthesized = synthesize_project_rules_body(target_dir)

    rules_dir = target_dir / ".cursor" / "rules"
    bd_path = rules_dir / "braindrain.mdc"
    pr_path = rules_dir / "project-rules.mdc"

    if dry_run:
        result["would_write"] = [str(bd_path), str(pr_path)]
        result["project_rules_synthesized_chars"] = len(synthesized)
        return result

    rules_dir.mkdir(parents=True, exist_ok=True)

    # Always mirror full RULES.md into braindrain.mdc.
    bd_path.write_text(mdc_full, encoding="utf-8")
    result["braindrain.mdc"] = "written"

    existing_pr = pr_path.read_text(encoding="utf-8") if pr_path.is_file() else None
    new_pr = merge_project_rules_mdc(existing_pr, synthesized)

    if new_pr == (existing_pr or ""):
        result["project-rules.mdc"] = "unchanged"
        return result

    pr_path.write_text(new_pr, encoding="utf-8")

    if existing_pr is None:
        result["project-rules.mdc"] = "created"
    elif _PROJECT_CONTEXT_START in (existing_pr or "") and _PROJECT_CONTEXT_END in (existing_pr or ""):
        result["project-rules.mdc"] = "updated_managed_region"
    elif _PROJECT_RULES_LEGACY_START in (existing_pr or "") and _PROJECT_RULES_LEGACY_END in (existing_pr or ""):
        result["project-rules.mdc"] = "migrated_legacy_markers"
    else:
        result["project-rules.mdc"] = "updated"

    return result


# ---------------------------------------------------------------------------
# Ruler apply
# ---------------------------------------------------------------------------

def run_ruler_apply(
    target_dir: Path,
    *,
    agents: Optional[list[str]] = None,
    dry_run: bool = False,
    local_only: bool = True,
    ruler_updates_gitignore: bool = False,
) -> dict:
    """
    Run `npx @intellectronica/ruler apply` in target_dir.

    Args:
        agents:     Explicit agent list. When None (all_agents mode), omit
                    --agents so Ruler applies every agent in the local file.
        local_only: When True (default), passes --local-only to skip global
                    XDG config merging and keep changes project-scoped.
        ruler_updates_gitignore: When False (default), passes ``--no-gitignore``
            so Ruler does not append its own block; use
            ``ensure_gitignore_braindrain_protocol()`` for a single policy.

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
    if not ruler_updates_gitignore:
        cmd.append("--no-gitignore")
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
    sync_subagents: bool = False,
    all_agents: bool = False,
    local_only: bool = True,
    patch_user_cursor_mcp: bool = False,
    bundle: str = DEFAULT_BUNDLE,
    codex_agent_targets: Optional[list[str]] = None,
) -> dict:
    """
    Full prime flow: deploy templates + subagents + Cursor hook templates + run ruler apply
    + initialize memory.

    Resolution order for agents:
      1. If agents is provided explicitly → use it.
      2. If all_agents=True → deploy full template, run apply without --agents
         (Ruler applies every [agents] entry in the local file).
      3. Otherwise → detect_prime_agents() → single best-fit agent.

    On second+ runs (primed.json marker exists), the marker is updated and
    the same flow re-runs. `.cursor/agents/*.md` defaults to create-only unless
    sync_subagents=True, which overwrites with timestamped backups.
    When Cursor is in scope, ``config/templates/cursor`` → ``.cursor/hooks.json``
    and ``.cursor/hooks/*.sh`` are deployed (create-only; use sync_templates=True
    to refresh hooks from templates).
    Synthesis of project memory / project-rules.mdc is handled in
    initialize_project_memory().

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
    detect_method: Optional[str] = None
    if agents is not None:
        apply_agents = agents
        detect_method = "explicit:agents_parameter"
    elif all_agents:
        apply_agents = None  # Let Ruler enumerate all entries in local file.
        detect_method = "all_agents:true"
    else:
        apply_agents, detect_method = detect_prime_agents(target_dir)

    cursor_in_scope = bool(
        all_agents or apply_agents is None or "cursor" in (apply_agents or [])
    )
    codex_in_scope = bool(
        all_agents or apply_agents is None or "codex" in (apply_agents or [])
    )

    launcher_path = _get_launcher_path()
    try:
        bundle_manifest = _resolve_bundle_manifest(bundle)
    except Exception as e:
        return {"ok": False, "error": str(e), "bundle": bundle}

    codex_targets = codex_agent_targets or [".codex/agents"]

    # Step 1: deploy templates.
    snapshot = create_prime_snapshot(target_dir, dry_run=dry_run)
    if not dry_run:
        template_results = deploy_templates(
            target_dir,
            launcher_path,
            sync_templates=sync_templates,
            agents=apply_agents,
            all_agents=all_agents,
        )
        subagent_results = deploy_subagent_templates(
            target_dir,
            sync_subagents=sync_subagents,
            to_cursor=cursor_in_scope,
            to_codex=codex_in_scope,
        )
        cursor_hook_results = (
            deploy_cursor_hook_templates(
                target_dir,
                sync_templates=sync_templates,
                dry_run=False,
            )
            if cursor_in_scope
            else {}
        )
    else:
        template_results = {
            str(f.relative_to(TEMPLATES_DIR)): {"action": "dry_run", "backup": ""}
            for f in TEMPLATES_DIR.rglob("*") if f.is_file()
        }
        subagent_results = {
            str(f.name): {"action": "dry_run", "backup": ""}
            for f in AGENT_TEMPLATES_DIR.glob("*.md")
        } if (cursor_in_scope or codex_in_scope) and AGENT_TEMPLATES_DIR.exists() else {}
        cursor_hook_results = (
            deploy_cursor_hook_templates(
                target_dir,
                sync_templates=sync_templates,
                dry_run=True,
            )
            if cursor_in_scope
            else {}
        )

    # Step 2: run ruler apply (Ruler does not touch .gitignore unless ruler_updates_gitignore).
    ruler_result = run_ruler_apply(
        target_dir,
        agents=apply_agents,
        dry_run=dry_run,
        local_only=local_only,
    )

    # Step 3: .gitignore protocol (braindrain-owned; Ruler --gitignore off by default).
    gitignore_protocol = ensure_gitignore_braindrain_protocol(
        target_dir, dry_run=dry_run
    )

    # Step 4: Cursor project rules from .ruler/RULES.md (Ruler may omit or differ).
    cursor_rules: dict[str, str | bool] = {"skipped": True}
    if cursor_in_scope and not dry_run:
        cursor_rules = sync_cursor_rules_from_ruler(
            target_dir, dry_run=False, include_cursor=True
        )
    elif cursor_in_scope and dry_run:
        cursor_rules = sync_cursor_rules_from_ruler(
            target_dir, dry_run=True, include_cursor=True
        )

    # Step 5: Cursor MCP JSON — serverName for adapter (fixes MCP Allowlist warning).
    cursor_mcp_json: dict[str, str | bool | dict] = {"skipped": True}
    if cursor_in_scope and not dry_run:
        proj_mcp = ensure_cursor_mcp_json_server_name(target_dir, dry_run=False)
        if patch_user_cursor_mcp:
            user_mcp = ensure_cursor_mcp_json_server_name_at(
                Path.home() / ".cursor" / "mcp.json",
                dry_run=False,
            )
            cursor_mcp_json = {"project": proj_mcp, "user_global": user_mcp}
        else:
            cursor_mcp_json = proj_mcp
    elif cursor_in_scope and dry_run:
        proj_mcp = ensure_cursor_mcp_json_server_name(target_dir, dry_run=True)
        if patch_user_cursor_mcp:
            user_mcp = ensure_cursor_mcp_json_server_name_at(
                Path.home() / ".cursor" / "mcp.json",
                dry_run=True,
            )
            cursor_mcp_json = {"project": proj_mcp, "user_global": user_mcp}
        else:
            cursor_mcp_json = proj_mcp

    # Step 6: codex subagent config policy (after ruler apply to avoid overwrite).
    codex_subagent_config: dict[str, str | bool] = {"skipped": True}
    if codex_in_scope:
        codex_subagent_config = ensure_codex_subagent_config(
            target_dir,
            codex_agent_targets=codex_targets,
            dry_run=dry_run,
            sync_subagents=sync_subagents,
        )

    # Step 7: initialize memory artifacts (includes one-time .devdocs migration).
    memory_init = initialize_project_memory(target_dir, dry_run=dry_run)

    # Step 8: seed scriptlib only when the workspace has explicitly enabled it.
    try:
        scriptlib_result = seed_if_enabled(target_dir, dry_run=dry_run)
    except Exception as exc:
        scriptlib_result = {
            "ok": False,
            "error": str(exc),
            "root": str(target_dir / ".scriptlib"),
            "guidance_enabled": False,
        }

    # Step 9: persist primed marker (skip on dry_run).
    if not dry_run and ruler_result.get("ok"):
        _write_primed_state(
            target_dir,
            apply_agents or ["all"],
            bundle=bundle_manifest.get("name", bundle),
            bundle_version=str(bundle_manifest.get("version", "1")),
        )

    verification = verify_prime_install(target_dir, bundle_manifest) if not dry_run else {
        "ok": True,
        "checks": {"dry_run": True},
    }
    ok = bool(ruler_result["ok"] and memory_init.get("ok", False) and verification.get("ok", False))

    return {
        "ok": ok,
        "target": str(target_dir),
        "launcher_path": launcher_path,
        "dry_run": dry_run,
        "sync_templates": sync_templates,
        "sync_subagents": sync_subagents,
        "all_agents": all_agents,
        "local_only": local_only,
        "is_first_prime": is_first_prime,
        "resolved_agents": apply_agents,
        "bundle": bundle_manifest.get("name", bundle),
        "bundle_manifest_version": str(bundle_manifest.get("version", "1")),
        "bundle_manifest": {
            "agents": bundle_manifest.get("agents", []),
            "rules": bundle_manifest.get("rules", []),
            "skills": bundle_manifest.get("skills", []),
            "mcp_servers": bundle_manifest.get("mcp_servers", []),
        },
        "detect_method": detect_method,
        "rollback_snapshot": snapshot,
        "gitignore_protocol": gitignore_protocol,
        "cursor_rules": cursor_rules,
        "cursor_mcp_json": cursor_mcp_json,
        "codex_subagent_config": codex_subagent_config,
        "templates": {
            "source": str(TEMPLATES_DIR),
            "deployed": template_results,
            "new_files": sum(1 for v in template_results.values() if v["action"] == "created"),
            "updated_files": sum(1 for v in template_results.values() if v["action"] == "updated"),
            "skipped_existing": sum(
                1 for v in template_results.values() if v["action"] == "skipped_existing"
            ),
        },
        "subagents": {
            "source": str(AGENT_TEMPLATES_DIR),
            "deployed": subagent_results,
            "new_files": sum(
                1
                for v in subagent_results.values()
                if v["action"] in ("created", "created_from_empty")
            ),
            "updated_files": sum(1 for v in subagent_results.values() if v["action"] == "updated"),
            "skipped_existing": sum(
                1 for v in subagent_results.values() if v["action"] == "skipped_existing"
            ),
        },
        "cursor_hooks": {
            "source": str(CURSOR_HOOK_TEMPLATES_DIR),
            "skipped": not cursor_in_scope,
            "deployed": cursor_hook_results,
            "new_files": sum(
                1 for v in cursor_hook_results.values() if v.get("action") == "created"
            ),
            "updated_files": sum(
                1 for v in cursor_hook_results.values() if v.get("action") == "updated"
            ),
            "skipped_existing": sum(
                1 for v in cursor_hook_results.values() if v.get("action") == "skipped_existing"
            ),
        },
        "ruler": ruler_result,
        "memory_init": memory_init,
        "verification": verification,
        "scriptlib": scriptlib_result,
        "next_steps": (
            []
            if ok
            else [
                "Check Node.js is installed (npx must be on PATH)",
                "Run: npx @intellectronica/ruler apply --config .ruler/ruler.toml --local-only --no-gitignore",
                "Run init_project_memory() to initialize project memory artifacts",
                "Inspect result.verification.checks for failing deployment checks",
            ]
        ),
    }
