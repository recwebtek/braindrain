"""LivingDash read-only workspace collectors.

Sidecar isolation: this module only reads filesystem paths (YAML, JSON, JSONL,
SQLite, markdown). It must not import braindrain.server, workspace_primer, or
MCP tool handlers.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

SNAPSHOT_SCHEMA_VERSION = "2.0"
MAX_EXCERPT_CHARS = 12_000
MAX_JSONL_LINES = 200
MAX_OBSERVER_EVENTS = 200


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _expand_path(raw: str | None, *, project_root: Path) -> Path | None:
    if not raw or not str(raw).strip():
        return None
    text = os.path.expanduser(str(raw).strip())
    path = Path(text)
    if not path.is_absolute():
        path = (project_root / path).resolve()
    return path


def load_hub_config(project_root: Path) -> dict[str, Any]:
    config_path = project_root / "config" / "hub_config.yaml"
    if not config_path.exists():
        return {}
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def load_livingdash_config(hub: dict[str, Any]) -> dict[str, Any]:
    block = hub.get("livingdash")
    if not isinstance(block, dict):
        return {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 0,
            "ui_dist": None,
            "data_dir": None,
            "refresh_on_start": True,
            "read_paths": {},
        }
    read_paths = block.get("read_paths")
    if not isinstance(read_paths, dict):
        read_paths = {}
    return {
        "enabled": bool(block.get("enabled", True)),
        "host": str(block.get("host", "127.0.0.1")),
        "port": int(block.get("port", 0) or 0),
        "ui_dist": block.get("ui_dist"),
        "data_dir": block.get("data_dir"),
        "refresh_on_start": bool(block.get("refresh_on_start", True)),
        "read_paths": read_paths,
    }


def resolve_read_paths(project_root: Path, hub: dict[str, Any], ldash: dict[str, Any]) -> dict[str, Path | None]:
    read_paths = ldash.get("read_paths") if isinstance(ldash.get("read_paths"), dict) else {}
    cost = hub.get("cost_tracking") if isinstance(hub.get("cost_tracking"), dict) else {}
    observer = hub.get("observer") if isinstance(hub.get("observer"), dict) else {}

    session_raw = read_paths.get("session_jsonl") or cost.get("log_file")
    observer_raw = read_paths.get("observer_db") or observer.get("storage_path")
    token_raw = read_paths.get("token_metrics") or ".braindrain/token-metrics.jsonl"

    return {
        "session_jsonl": _expand_path(str(session_raw) if session_raw else None, project_root=project_root),
        "observer_db": _expand_path(str(observer_raw) if observer_raw else None, project_root=project_root),
        "token_metrics": _expand_path(str(token_raw) if token_raw else None, project_root=project_root),
    }


def _read_text_excerpt(path: Path, *, max_chars: int = MAX_EXCERPT_CHARS) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "excerpt": "", "truncated": False}
    text = path.read_text(encoding="utf-8", errors="replace")
    truncated = len(text) > max_chars
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": path.stat().st_size,
        "modified_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat().replace("+00:00", "Z"),
        "excerpt": text[:max_chars],
        "truncated": truncated,
    }


def _parse_agent_frontmatter(text: str) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            block = text[3:end].strip()
            try:
                parsed = yaml.safe_load(block) or {}
                if isinstance(parsed, dict):
                    meta = parsed
            except Exception:
                meta = {}
    model = meta.get("model") or meta.get("Model")
    if isinstance(model, str):
        meta["model"] = model
    description = meta.get("description") or meta.get("Description")
    if isinstance(description, str):
        meta["description"] = description
    return meta


def _agent_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob("*.md"))


def collect_workspace_agents(project_root: Path) -> dict[str, Any]:
    template_dir = project_root / "config" / "templates" / "agents"
    templates = {p.stem for p in _agent_files(template_dir)}
    hooks_path = project_root / ".cursor" / "hooks.json"
    hook_scripts: list[str] = []
    if hooks_path.exists():
        try:
            hooks_data = json.loads(hooks_path.read_text(encoding="utf-8"))
            for hook_name, entries in (hooks_data.get("hooks") or {}).items():
                if isinstance(entries, list):
                    for entry in entries:
                        if isinstance(entry, dict) and entry.get("command"):
                            hook_scripts.append(f"{hook_name}:{entry['command']}")
        except Exception:
            pass

    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for provider, rel in (("cursor", ".cursor/agents"), ("codex", ".codex/agents")):
        agent_dir = project_root / rel
        for path in _agent_files(agent_dir):
            name = path.stem
            seen.add(name)
            text = path.read_text(encoding="utf-8", errors="replace")
            meta = _parse_agent_frontmatter(text)
            items.append(
                {
                    "id": name,
                    "name": name,
                    "provider": provider,
                    "path": str(path.relative_to(project_root)),
                    "model": meta.get("model"),
                    "description": (meta.get("description") or "")[:500],
                    "tier": meta.get("tier"),
                    "hooks": hook_scripts,
                    "template_match": name in templates,
                    "installed": True,
                    "last_ran": None,
                }
            )

    for name in sorted(templates - seen):
        template_path = template_dir / f"{name}.md"
        text = template_path.read_text(encoding="utf-8", errors="replace") if template_path.exists() else ""
        meta = _parse_agent_frontmatter(text)
        items.append(
            {
                "id": name,
                "name": name,
                "provider": "template",
                "path": str(template_path.relative_to(project_root)),
                "model": meta.get("model"),
                "description": (meta.get("description") or "")[:500],
                "tier": meta.get("tier"),
                "hooks": hook_scripts,
                "template_match": True,
                "installed": False,
                "last_ran": None,
            }
        )

    return {
        "schema_version": "1.0",
        "count": sum(1 for item in items if item.get("installed")),
        "template_count": len(templates),
        "items": items,
        "updated_at": _now_iso(),
    }


def _skill_entries(root: Path, *, label: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not root.exists():
        return entries
    for skill_file in sorted(root.rglob("SKILL.md")):
        rel = skill_file.relative_to(root)
        name = rel.parts[0] if len(rel.parts) > 1 else skill_file.parent.name
        text = skill_file.read_text(encoding="utf-8", errors="replace")
        first_line = ""
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                first_line = line[:240]
                break
        entries.append(
            {
                "name": name,
                "path": str(skill_file),
                "source": label,
                "excerpt": first_line,
            }
        )
    return entries


def collect_workspace_skills(project_root: Path) -> dict[str, Any]:
    installed = _skill_entries(project_root / ".cursor" / "skills", label="installed")
    templates = _skill_entries(project_root / "config" / "templates" / "cursor-skills", label="template")
    installed_names = {item["name"] for item in installed}
    template_names = {item["name"] for item in templates}
    drift = sorted(template_names - installed_names)
    return {
        "schema_version": "1.0",
        "installed_count": len(installed),
        "template_count": len(templates),
        "drift_missing": drift,
        "installed": installed,
        "templates": templates,
        "updated_at": _now_iso(),
    }


def _dotfile_inventory(project_root: Path) -> list[dict[str, Any]]:
    names = [".cursor", ".codex", ".ruler", ".braindrain", ".ldash", ".env.example", ".gitignore"]
    items = []
    for name in names:
        path = project_root / name
        items.append(
            {
                "name": name,
                "exists": path.exists(),
                "is_dir": path.is_dir() if path.exists() else False,
                "modified_at": (
                    datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat().replace("+00:00", "Z")
                    if path.exists()
                    else None
                ),
            }
        )
    return items


def collect_primer_state(project_root: Path) -> dict[str, Any]:
    primed_path = project_root / ".braindrain" / "primed.json"
    primed: dict[str, Any] = {}
    if primed_path.exists():
        try:
            primed = json.loads(primed_path.read_text(encoding="utf-8"))
        except Exception:
            primed = {}

    bundle = primed.get("bundle") if isinstance(primed.get("bundle"), str) else None
    bundle_path = project_root / "config" / "bundles" / f"{bundle}.yaml" if bundle else None
    bundle_exists = bool(bundle_path and bundle_path.exists())

    return {
        "schema_version": "1.0",
        "primed_path": str(primed_path),
        "last_primed_at": primed.get("primed_at"),
        "bundle": bundle,
        "bundle_exists": bundle_exists,
        "agents_deployed": primed.get("agents"),
        "bundle_version": primed.get("bundle_version"),
        "dotfiles": _dotfile_inventory(project_root),
        "updated_at": _now_iso(),
    }


def _tail_jsonl(path: Path | None, *, limit: int = MAX_JSONL_LINES) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    lines: list[str] = []
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    lines.append(line)
    except Exception:
        return []
    records: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                records.append(item)
        except Exception:
            continue
    return records


def collect_braindrain_telemetry(project_root: Path, paths: dict[str, Path | None]) -> dict[str, Any]:
    session_path = paths.get("session_jsonl")
    token_path = paths.get("token_metrics")
    events = _tail_jsonl(session_path)
    checkpoints = _tail_jsonl(token_path, limit=50)

    tool_totals: dict[str, dict[str, int]] = {}
    saved_total = 0
    for event in events:
        tool = str(event.get("tool") or event.get("tool_name") or "unknown")
        bucket = tool_totals.setdefault(tool, {"calls": 0, "saved": 0, "raw": 0, "actual": 0})
        bucket["calls"] += 1
        raw = int(event.get("tokens_in_raw_est") or event.get("estimated_raw_tokens") or 0)
        actual = int(event.get("tokens_in_actual_est") or event.get("actual_context_tokens") or 0)
        saved = max(0, raw - actual)
        bucket["raw"] += raw
        bucket["actual"] += actual
        bucket["saved"] += saved
        saved_total += saved

    return {
        "schema_version": "1.0",
        "session_jsonl": str(session_path) if session_path else None,
        "session_exists": bool(session_path and session_path.exists()),
        "event_count": len(events),
        "recent_events": events[-40:],
        "tool_totals": [
            {"tool": name, **stats} for name, stats in sorted(tool_totals.items(), key=lambda x: -x[1]["calls"])
        ],
        "tokens_saved_total": saved_total,
        "token_checkpoints": checkpoints[-20:],
        "updated_at": _now_iso(),
    }


def collect_observer_logs(paths: dict[str, Path | None], *, limit: int = MAX_OBSERVER_EVENTS) -> dict[str, Any]:
    db_path = paths.get("observer_db")
    if not db_path or not db_path.exists():
        return {
            "schema_version": "1.0",
            "db_path": str(db_path) if db_path else None,
            "exists": False,
            "stats": {},
            "events": [],
            "updated_at": _now_iso(),
        }

    stats: dict[str, Any] = {"total": 0, "by_type": []}
    events: list[dict[str, Any]] = []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        total_row = conn.execute("SELECT COUNT(*) AS count FROM brain_events").fetchone()
        stats["total"] = int(total_row["count"]) if total_row else 0
        type_rows = conn.execute(
            """
            SELECT event_type, COUNT(*) AS count
            FROM brain_events
            GROUP BY event_type
            ORDER BY count DESC
            LIMIT 20
            """
        ).fetchall()
        stats["by_type"] = [{"event_type": row["event_type"], "count": row["count"]} for row in type_rows]
        rows = conn.execute(
            """
            SELECT event_id, session_id, event_type, timestamp, tool_name, payload_json
            FROM brain_events
            ORDER BY timestamp DESC, event_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        for row in rows:
            payload = {}
            if row["payload_json"]:
                try:
                    payload = json.loads(row["payload_json"])
                except Exception:
                    payload = {"raw": str(row["payload_json"])[:500]}
            events.append(
                {
                    "event_id": row["event_id"],
                    "session_id": row["session_id"],
                    "event_type": row["event_type"],
                    "timestamp": row["timestamp"],
                    "tool_name": row["tool_name"],
                    "payload": payload,
                }
            )
        conn.close()
    except Exception as exc:
        return {
            "schema_version": "1.0",
            "db_path": str(db_path),
            "exists": True,
            "error": str(exc),
            "stats": stats,
            "events": events,
            "updated_at": _now_iso(),
        }

    return {
        "schema_version": "1.0",
        "db_path": str(db_path),
        "exists": True,
        "stats": stats,
        "events": events,
        "updated_at": _now_iso(),
    }


def _parse_next_actions(text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for line in text.splitlines():
        match = re.match(r"^- \[(.+?)\]\s+`([^`]+)`\s+.*", line.strip())
        if match:
            items.append({"verb": match.group(1), "plan_id": match.group(2)})
    return items[:40]


def collect_plan_reports(project_root: Path) -> dict[str, Any]:
    reports_dir = project_root / ".braindrain" / "plan-reports"
    master = reports_dir / "master-plan.md"
    next_actions = reports_dir / "next-actions.md"
    latest = reports_dir / "latest.md"
    audit_files = sorted(reports_dir.glob("plan-audit-*.md"), reverse=True)

    return {
        "schema_version": "1.0",
        "reports_dir": str(reports_dir),
        "master_plan": _read_text_excerpt(master, max_chars=6000) if master.exists() else {"exists": False},
        "next_actions": {
            **_read_text_excerpt(next_actions, max_chars=4000),
            "items": _parse_next_actions(next_actions.read_text(encoding="utf-8", errors="replace"))
            if next_actions.exists()
            else [],
        },
        "latest_audit": _read_text_excerpt(latest, max_chars=2000) if latest.exists() else {"exists": False},
        "audit_files": [p.name for p in audit_files[:8]],
        "updated_at": _now_iso(),
    }


def collect_project_memory(project_root: Path) -> dict[str, Any]:
    brain = project_root / ".braindrain"
    files = {
        "agent_memory": brain / "AGENT_MEMORY.md",
        "ops": brain / "OPS.md",
        "session_progress": brain / "SESSION_PROGRESS.md",
    }
    return {
        "schema_version": "1.0",
        "files": {key: _read_text_excerpt(path) for key, path in files.items()},
        "updated_at": _now_iso(),
    }


def _redact_config_tree(node: Any) -> Any:
    if isinstance(node, dict):
        redacted: dict[str, Any] = {}
        for key, value in node.items():
            lower = str(key).lower()
            if any(token in lower for token in ("password", "secret", "token", "api_key", "key")):
                redacted[key] = "***redacted***" if value else value
            else:
                redacted[key] = _redact_config_tree(value)
        return redacted
    if isinstance(node, list):
        return [_redact_config_tree(item) for item in node]
    return node


def collect_hub_config_summary(project_root: Path) -> dict[str, Any]:
    hub = load_hub_config(project_root)
    livingdash = load_livingdash_config(hub)
    subset = {
        "project_name": hub.get("project_name"),
        "livingdash": livingdash,
        "modules": hub.get("modules"),
        "cost_tracking": hub.get("cost_tracking"),
        "observer": hub.get("observer"),
        "provenance": hub.get("provenance"),
        "models": hub.get("models"),
        "mcp_tools_count": len(hub.get("mcp_tools") or []) if isinstance(hub.get("mcp_tools"), list) else 0,
    }
    return {
        "schema_version": "1.0",
        "config_path": str(project_root / "config" / "hub_config.yaml"),
        "tree": _redact_config_tree(subset),
        "updated_at": _now_iso(),
    }


def collect_workspace_tests(project_root: Path) -> dict[str, Any]:
    tests_dir = project_root / "tests"
    py_tests = sorted(tests_dir.glob("test_*.py")) if tests_dir.exists() else []
    ui_tests_dir = project_root / ".ldash" / "ui"
    workflows_dir = project_root / ".github" / "workflows"
    workflows: list[dict[str, Any]] = []
    if workflows_dir.exists():
        for wf in sorted(workflows_dir.glob("*.yml")) + sorted(workflows_dir.glob("*.yaml")):
            text = wf.read_text(encoding="utf-8", errors="replace")
            jobs = []
            for line in text.splitlines():
                if re.match(r"^  [A-Za-z0-9_-]+:\s*$", line) and not line.strip().startswith("#"):
                    job = line.strip().rstrip(":")
                    if job not in ("on", "env", "permissions", "concurrency"):
                        jobs.append(job)
            workflows.append({"file": wf.name, "jobs": jobs[:12]})

    scripts: list[dict[str, str]] = []
    pyproject = project_root / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text(encoding="utf-8", errors="replace")
        if "[tool.pytest" in text or "pytest" in text:
            scripts.append({"id": "pytest", "label": "pytest", "command": "./.venv/bin/python -m pytest"})
    package_json = project_root / ".ldash" / "ui" / "package.json"
    if package_json.exists():
        try:
            pkg = json.loads(package_json.read_text(encoding="utf-8"))
            for key, value in (pkg.get("scripts") or {}).items():
                if "test" in key.lower():
                    scripts.append({"id": key, "label": key, "command": f"pnpm run {key}", "cwd": ".ldash/ui"})
        except Exception:
            pass

    return {
        "schema_version": "1.0",
        "python_tests": [str(p.relative_to(project_root)) for p in py_tests],
        "python_test_count": len(py_tests),
        "ui_has_vitest": package_json.exists(),
        "scripts": scripts,
        "ci_workflows": workflows,
        "updated_at": _now_iso(),
    }


def collect_env_context_summary(project_root: Path) -> dict[str, Any]:
    env_path = project_root / ".braindrain" / "env-context.json"
    if env_path.exists():
        try:
            data = json.loads(env_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {"schema_version": "1.0", "source": str(env_path), "summary": data, "updated_at": _now_iso()}
        except Exception:
            pass
    return {
        "schema_version": "1.0",
        "source": None,
        "summary": {"note": "No cached env-context.json; use Primer dotfile matrix."},
        "updated_at": _now_iso(),
    }


def compute_insights(
    *,
    telemetry: dict[str, Any],
    primer: dict[str, Any],
    agents: dict[str, Any],
) -> dict[str, Any]:
    token_saving_active = bool(telemetry.get("tokens_saved_total", 0) > 0 or telemetry.get("event_count", 0) > 0)
    drift = 0
    if isinstance(primer.get("dotfiles"), list):
        drift += sum(1 for item in primer["dotfiles"] if isinstance(item, dict) and not item.get("exists"))
    skills_drift = 0  # filled by caller if needed
    return {
        "token_saving_active": token_saving_active,
        "env_drift": drift + skills_drift,
        "agents_online": int(agents.get("count", 0) or 0),
    }


def collect_workspace_bundle(project_root: str | Path) -> dict[str, Any]:
    """Aggregate all read-only collector payloads for API routes and snapshot v2."""
    project_root = Path(project_root).expanduser().resolve()
    hub = load_hub_config(project_root)
    ldash = load_livingdash_config(hub)
    read_paths = resolve_read_paths(project_root, hub, ldash)

    agents = collect_workspace_agents(project_root)
    skills = collect_workspace_skills(project_root)
    primer = collect_primer_state(project_root)
    telemetry = collect_braindrain_telemetry(project_root, read_paths)
    observer = collect_observer_logs(read_paths)
    plans = collect_plan_reports(project_root)
    memory = collect_project_memory(project_root)
    config_summary = collect_hub_config_summary(project_root)
    tests = collect_workspace_tests(project_root)
    env_context = collect_env_context_summary(project_root)

    insights = compute_insights(telemetry=telemetry, primer=primer, agents=agents)
    insights["env_drift"] += len(skills.get("drift_missing") or [])

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "collected_at": _now_iso(),
        "livingdash_config": ldash,
        "read_paths": {k: str(v) if v else None for k, v in read_paths.items()},
        "agents": agents,
        "skills": skills,
        "primer": primer,
        "telemetry": telemetry,
        "observer": observer,
        "plans": plans,
        "memory": memory,
        "config": config_summary,
        "tests": tests,
        "env_context": env_context,
        "insights": insights,
    }
