"""Project-local and machine-local script library helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml


SCRIPTLIB_DIR = ".scriptlib"
SCRIPTLIB_LIBRARY_DIR = "library"
SCRIPTLIB_ENTRIES_DIR = "entries"
SCRIPTLIB_SETTINGS_FILE = "settings.json"
SCRIPTLIB_INDEX_FILE = "index.json"
SCRIPTLIB_CATALOG_FILE = "catalog.md"
SCRIPTLIB_METADATA_FILE = "script.yaml"
GLOBAL_SCRIPTLIB_ROOT = Path.home() / ".braindrain" / "scriptlib"
DEFAULT_HARVEST_DIRS = ("tests", "scripts")
DEFAULT_IGNORE_DIRS = (
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    "coverage",
    ".next",
    ".turbo",
    ".scriptlib",
)
SCRIPT_EXTENSIONS = {
    ".py",
    ".sh",
    ".bash",
    ".zsh",
    ".js",
    ".ts",
    ".mjs",
    ".cjs",
}
NOTICE_MARKER = "<!-- SCRIPTLIB_GUIDANCE -->"
DEFAULT_SCORE = 50.0
SCRIPTLIB_SCHEMA_VERSION = 2
PINNED_SHARED_DEFAULT_CHANNEL = "stable"

SCRIPTLIB_GUIDANCE = """## Scriptlib Notice

If scriptlib is enabled in this workspace, check scriptlib before writing a new task script.

- Use the scriptlib tools first for reusable operational, test-helper, or validation scripts.
- The librarian can find, adapt, fork, run, promote, and maintain existing scripts with the right workspace context.
- A freestanding reusable script should not be created until librarian has returned `reuse`, `fork`, or `new`.
- Shared script catalog changes require explicit approval; routine scoring and maintenance do not.
"""

_wiki_brain_client = None
_session_store_client = None


@dataclass
class ScriptRoots:
    project_root: Optional[Path]
    global_root: Path


def render_guidance(content: str, *, enabled: bool) -> str:
    """Replace the marker with scriptlib guidance when enabled."""
    replacement = SCRIPTLIB_GUIDANCE if enabled else ""
    if NOTICE_MARKER in content:
        return content.replace(NOTICE_MARKER, replacement)
    if not enabled:
        return content
    sep = "\n\n" if content.endswith("\n") else "\n\n"
    return content + sep + replacement


def now_utc() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def global_scriptlib_root() -> Path:
    return GLOBAL_SCRIPTLIB_ROOT


def project_scriptlib_root(project_path: str | Path) -> Path:
    return Path(project_path).expanduser().resolve() / SCRIPTLIB_DIR


def settings_path(root: Path) -> Path:
    return root / SCRIPTLIB_SETTINGS_FILE


def index_path(root: Path) -> Path:
    return root / SCRIPTLIB_INDEX_FILE


def catalog_path(root: Path) -> Path:
    return root / SCRIPTLIB_CATALOG_FILE


def entries_root(root: Path) -> Path:
    return root / SCRIPTLIB_LIBRARY_DIR / SCRIPTLIB_ENTRIES_DIR


def canonical_id_for_path(path: Path, base_dir: Path) -> str:
    rel = path.resolve().relative_to(base_dir.resolve())
    slug = rel.with_suffix("").as_posix().lower()
    slug = re.sub(r"[^a-z0-9/_-]+", "-", slug)
    return slug.replace("/", "--").strip("-") or "script"


def _default_settings(*, scope: str) -> dict[str, Any]:
    return {
        "enabled": False,
        "scope": scope,
        "schema_version": SCRIPTLIB_SCHEMA_VERSION,
        "harvest_sources": list(DEFAULT_HARVEST_DIRS),
        "ignore_dirs": list(DEFAULT_IGNORE_DIRS),
        "shared_pins": {},
        "maintenance": {"last_run_at": None, "last_report": {}},
    }


def read_settings(root: Path) -> dict[str, Any]:
    p = settings_path(root)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    defaults = _default_settings(scope="global" if root.resolve() == global_scriptlib_root().resolve() else "project")
    defaults.update(data)
    defaults["ignore_dirs"] = sorted({str(item) for item in defaults.get("ignore_dirs", []) or []})
    defaults["shared_pins"] = dict(defaults.get("shared_pins") or {})
    defaults["maintenance"] = dict(defaults.get("maintenance") or {})
    defaults["schema_version"] = SCRIPTLIB_SCHEMA_VERSION
    return defaults


def write_settings(root: Path, data: dict[str, Any]) -> None:
    payload = dict(data)
    payload["schema_version"] = SCRIPTLIB_SCHEMA_VERSION
    payload["ignore_dirs"] = sorted({str(item) for item in payload.get("ignore_dirs", []) or []})
    payload["shared_pins"] = dict(payload.get("shared_pins") or {})
    payload["maintenance"] = dict(payload.get("maintenance") or {})
    root.mkdir(parents=True, exist_ok=True)
    settings_path(root).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def is_enabled(root: Path) -> bool:
    return bool(read_settings(root).get("enabled", False))


def enabled_for_workspace(project_path: str | Path) -> bool:
    return is_enabled(project_scriptlib_root(project_path))


def ensure_root_layout(root: Path, *, scope: str, enabled: bool, dry_run: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "root": str(root),
        "scope": scope,
        "enabled": enabled,
        "dry_run": dry_run,
    }
    if dry_run:
        result["would_create"] = not root.exists()
        return result

    root.mkdir(parents=True, exist_ok=True)
    entries_root(root).mkdir(parents=True, exist_ok=True)
    settings = _default_settings(scope=scope)
    settings.update(read_settings(root))
    settings.update(
        {
            "enabled": enabled,
            "scope": scope,
            "updated_at": now_utc(),
        }
    )
    settings.setdefault("created_at", now_utc())
    write_settings(root, settings)
    if not index_path(root).exists():
        index_path(root).write_text(json.dumps({"entries": [], "generated_at": now_utc()}, indent=2) + "\n", encoding="utf-8")
    if not catalog_path(root).exists():
        catalog_path(root).write_text("# Scriptlib Catalog\n\n_No entries yet._\n", encoding="utf-8")
    result["action"] = "ensured"
    return result


def enable(
    project_path: str = ".",
    *,
    scope: str = "project",
    harvest: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    if scope not in {"project", "global"}:
        return {"ok": False, "error": f"Unsupported scope: {scope}"}
    root = project_scriptlib_root(project_path) if scope == "project" else global_scriptlib_root()
    result = ensure_root_layout(root, scope=scope, enabled=True, dry_run=dry_run)
    if not result.get("ok"):
        return result
    if scope == "project" and harvest and not dry_run:
        harvest_result = harvest_workspace(project_path=project_path, dry_run=False)
        result["harvest"] = harvest_result
    return result


def disable(project_path: str = ".", *, scope: str = "project", dry_run: bool = False) -> dict[str, Any]:
    if scope not in {"project", "global"}:
        return {"ok": False, "error": f"Unsupported scope: {scope}"}
    root = project_scriptlib_root(project_path) if scope == "project" else global_scriptlib_root()
    if dry_run:
        return {"ok": True, "root": str(root), "scope": scope, "dry_run": True}
    settings = read_settings(root)
    settings["enabled"] = False
    settings["updated_at"] = now_utc()
    write_settings(root, settings)
    return {"ok": True, "root": str(root), "scope": scope, "disabled": True}


def _get_wiki_brain():
    global _wiki_brain_client
    if _wiki_brain_client is not None:
        return _wiki_brain_client
    try:
        from braindrain.wiki_brain import WikiBrain
    except Exception:
        return None
    _wiki_brain_client = WikiBrain(Path("~/.braindrain/wiki-brain/brain.db").expanduser())
    return _wiki_brain_client


def _get_session_store():
    global _session_store_client
    if _session_store_client is not None:
        return _session_store_client
    try:
        from braindrain.session import SessionStore
    except Exception:
        return None
    _session_store_client = SessionStore(Path("~/.braindrain/sessions.db").expanduser())
    return _session_store_client


def _record_scriptlib_metric(metric_type: str, *, value: float = 1.0, metadata: dict[str, Any] | None = None) -> None:
    client = _get_wiki_brain()
    if client is None:
        return
    try:
        client.record_metric(metric_type, value=value, source="scriptlib", metadata=metadata or {})
    except Exception:
        return


def _store_scriptlib_fact(
    *,
    title: str,
    content: str,
    record_class: str = "lesson",
    confidence: float = 0.7,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    client = _get_wiki_brain()
    if client is None:
        return
    try:
        client.store_fact(
            content=content,
            record_class=record_class,
            title=title,
            source="scriptlib",
            category="scriptlib",
            confidence=confidence,
            importance=0.7,
            tags=["scriptlib", *(tags or [])],
            metadata=metadata or {},
        )
    except Exception:
        return


def _touch_scriptlib_session(*, tool_name: str, key_decision: str | None = None) -> None:
    store = _get_session_store()
    if store is None:
        return
    try:
        store.touch_session(
            "scriptlib",
            tool_name=tool_name,
            key_decision=key_decision,
        )
    except Exception:
        return


def _detect_language(path: Path, text: str) -> tuple[str, str]:
    suffix = path.suffix.lower()
    if suffix == ".py":
        return "python", "python"
    if suffix in {".sh", ".bash", ".zsh"}:
        return "shell", "bash"
    if suffix in {".js", ".mjs", ".cjs"}:
        return "javascript", "node"
    if suffix == ".ts":
        return "typescript", "node"
    first_line = text.splitlines()[0] if text.splitlines() else ""
    if "python" in first_line:
        return "python", "python"
    if "bash" in first_line or "sh" in first_line:
        return "shell", "bash"
    return "text", "unknown"


def _detect_harness(path: Path, language: str) -> str:
    name = path.name.lower()
    if "pytest" in name or (path.parts and path.parts[0] == "tests" and language == "python"):
        return "pytest"
    if language == "shell":
        return "shell"
    return "generic"


def _path_risk(text: str, rel_path: Path, is_test_script: bool) -> tuple[str, str]:
    signals = [
        "Path(",
        "__file__",
        "config/",
        "tests/",
        "./",
        "cwd(",
        "pwd",
    ]
    score = sum(1 for signal in signals if signal in text)
    if is_test_script or score >= 2:
        return "high", "wrapped"
    if score == 1 or rel_path.parts and rel_path.parts[0] in {"tests", "scripts"}:
        return "medium", "source_context"
    return "low", "native_copy"


def _effect_tier(rel_path: Path, is_test_script: bool) -> str:
    if is_test_script:
        return "read_only"
    if rel_path.parts and rel_path.parts[0] == "scripts":
        return "workspace_write"
    return "workspace_write"


def _compute_summary(path: Path, text: str, is_test_script: bool) -> str:
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if first.startswith("#!"):
        first = next(
            (line.strip() for line in text.splitlines()[1:] if line.strip()),
            "",
        )
    if first.startswith('"""') or first.startswith("'''"):
        first = first.strip("\"'")
    if first.startswith("#"):
        first = first.lstrip("# ").strip()
    base = first or f"Harvested script from {path.as_posix()}"
    if is_test_script and "test" not in base.lower():
        return f"Test helper: {base}"
    return base


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _entry_dir(root: Path, canonical_id: str, variant: str, version: str) -> Path:
    return entries_root(root) / canonical_id / f"{variant}__{version}"


def _scope_for_root(root: Path) -> str:
    try:
        if root.resolve() == global_scriptlib_root().resolve():
            return "shared"
    except OSError:
        pass
    return "project"


def _parse_revision(value: Any, *, default: int = 1) -> int:
    if isinstance(value, int):
        return max(1, value)
    if isinstance(value, str):
        match = re.search(r"(?:^|[^0-9])r?(\d+)$", value)
        if match:
            return max(1, int(match.group(1)))
    return default


def _normalize_channel(value: str | None, *, default: str) -> str:
    if not value:
        return default
    return value.strip().lower() or default


def _approval_actions(scope: str, promotion_state: str) -> list[str]:
    if scope == "shared":
        return ["apply_update", "deprecate"]
    if promotion_state == "harvested":
        return ["promote"]
    return []


def _normalize_entry(entry: dict[str, Any], *, root: Path) -> dict[str, Any]:
    scope = entry.get("scope") or _scope_for_root(root)
    promotion_state = entry.get("promotion_state") or ("promoted" if scope == "shared" else "harvested")
    default_channel = PINNED_SHARED_DEFAULT_CHANNEL if scope == "shared" else "workspace"
    channel = _normalize_channel(entry.get("channel"), default=default_channel)
    revision = _parse_revision(entry.get("revision") or entry.get("version"), default=1)
    entry["scope"] = scope
    entry["promotion_state"] = promotion_state
    entry["channel"] = channel
    entry["revision"] = revision
    entry["schema_version"] = SCRIPTLIB_SCHEMA_VERSION
    entry["approval_required_actions"] = list(entry.get("approval_required_actions") or _approval_actions(scope, promotion_state))
    entry["requires_approval"] = bool(entry["approval_required_actions"])
    entry["provenance"] = dict(
        entry.get("provenance")
        or {
            "source_workspace_root": entry.get("source_workspace_root"),
            "source_path": entry.get("source_path"),
            "original_source_workspace_root": entry.get("source_workspace_root"),
            "original_source_path": entry.get("source_path"),
        }
    )
    entry["tags"] = list(dict.fromkeys(entry.get("tags") or []))
    if scope == "shared":
        for tag in ("shared", "promoted"):
            if tag not in entry["tags"]:
                entry["tags"].append(tag)
    else:
        if "project" not in entry["tags"]:
            entry["tags"].append("project")
    entry.setdefault("update_availability", None)
    entry.setdefault("shared_pin", None)
    return entry


def _normalize_index_entry(entry: dict[str, Any], *, root: Path, project_path: str | None = None) -> dict[str, Any]:
    scope = entry.get("scope") or _scope_for_root(root)
    promotion_state = entry.get("promotion_state") or ("promoted" if scope == "shared" else "harvested")
    default_channel = PINNED_SHARED_DEFAULT_CHANNEL if scope == "shared" else "workspace"
    revision = _parse_revision(entry.get("revision") or entry.get("version"), default=1)
    payload = dict(entry)
    payload["scope"] = scope
    payload["promotion_state"] = promotion_state
    payload["channel"] = _normalize_channel(payload.get("channel"), default=default_channel)
    payload["revision"] = revision
    payload["approval_required_actions"] = list(payload.get("approval_required_actions") or _approval_actions(scope, promotion_state))
    payload["requires_approval"] = bool(payload["approval_required_actions"])
    payload.setdefault("provenance", {})
    payload.setdefault("shared_pin", None)
    payload.setdefault("update_availability", None)
    if project_path:
        pin = _project_pin(project_path, payload.get("canonical_id", ""))
        if pin and scope == "shared":
            payload["shared_pin"] = pin
            latest = _latest_shared_entry(global_scriptlib_root(), payload["canonical_id"], channel=pin.get("channel"))
            payload["update_availability"] = bool(latest and latest.get("revision", 0) > int(pin.get("revision", 0)))
    return payload


def _load_entry(meta_path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
    raw["_metadata_path"] = str(meta_path)
    raw["_entry_dir"] = str(meta_path.parent)
    root = meta_path.parents[2]
    return _normalize_entry(raw, root=root)


def _iter_entry_metadata(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    base = entries_root(root)
    if not base.exists():
        return out
    for meta_path in sorted(base.glob(f"*/*/{SCRIPTLIB_METADATA_FILE}")):
        try:
            out.append(_load_entry(meta_path))
        except Exception:
            continue
    return out


def _score_from_runs(entry: dict[str, Any]) -> float:
    runs = entry.get("run_history") or []
    total = len(runs)
    successes = sum(1 for run in runs if run.get("outcome") == "success")
    failures = sum(1 for run in runs if run.get("outcome") != "success")
    success_rate = successes / total if total else 0.5
    status_bonus = {
        "draft": 0,
        "validated": 10,
        "approved": 20,
        "deprecated": -20,
    }.get(entry.get("status", "draft"), 0)
    native_bonus = 5 if entry.get("execution_mode") == "native_copy" else 0
    shared_bonus = 5 if entry.get("scope") == "shared" else 0
    flaky_penalty = min(failures * 2, 15)
    score = (success_rate * 80.0) + 10.0 + status_bonus + native_bonus + shared_bonus - flaky_penalty
    return round(max(0.0, min(100.0, score)), 2)


def _index_entry(entry: dict[str, Any]) -> dict[str, Any]:
    search_text = " ".join(
        [
            entry.get("canonical_id", ""),
            entry.get("summary", ""),
            entry.get("source_path", ""),
            entry.get("language", ""),
            entry.get("runtime", ""),
            entry.get("harness", ""),
            entry.get("scope", ""),
            entry.get("channel", ""),
            " ".join(entry.get("tags", []) or []),
            " ".join(entry.get("common_mistakes", []) or []),
        ]
    ).lower()
    return {
        "script_id": entry.get("script_id"),
        "canonical_id": entry.get("canonical_id"),
        "summary": entry.get("summary"),
        "status": entry.get("status"),
        "success_score": entry.get("success_score"),
        "execution_mode": entry.get("execution_mode"),
        "effect_tier": entry.get("effect_tier"),
        "language": entry.get("language"),
        "runtime": entry.get("runtime"),
        "harness": entry.get("harness"),
        "tags": entry.get("tags", []),
        "variant": entry.get("variant"),
        "version": entry.get("version"),
        "scope": entry.get("scope"),
        "promotion_state": entry.get("promotion_state"),
        "channel": entry.get("channel"),
        "revision": entry.get("revision"),
        "approval_required_actions": entry.get("approval_required_actions", []),
        "provenance": entry.get("provenance", {}),
        "source_path": entry.get("source_path"),
        "copy_path": entry.get("copy_path"),
        "path_risk": entry.get("path_risk"),
        "is_test_script": entry.get("is_test_script", False),
        "search_text": search_text,
    }


def refresh_index(root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    entries = _iter_entry_metadata(root)
    indexed = []
    for entry in entries:
        entry["success_score"] = _score_from_runs(entry)
        indexed.append(_index_entry(entry))
        if not dry_run:
            meta_path = Path(entry["_metadata_path"])
            payload = {k: v for k, v in entry.items() if not k.startswith("_")}
            meta_path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False), encoding="utf-8")

    index_payload = {
        "generated_at": now_utc(),
        "entries": sorted(indexed, key=lambda item: (-float(item.get("success_score", 0.0)), item.get("script_id", ""))),
    }
    if not dry_run:
        root.mkdir(parents=True, exist_ok=True)
        index_path(root).write_text(json.dumps(index_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        catalog_path(root).write_text(build_catalog(index_payload["entries"], root=root), encoding="utf-8")
    return {"ok": True, "root": str(root), "entries": len(indexed), "dry_run": dry_run}


def build_catalog(entries: list[dict[str, Any]], *, root: Path) -> str:
    lines = [
        "# Scriptlib Catalog",
        "",
        f"_Generated: {now_utc()}_",
        "",
    ]
    if not entries:
        lines.append("_No entries yet._")
        lines.append("")
        return "\n".join(lines)

    lines.extend(
        [
            "| Script ID | Scope | Channel | Rev | Summary | Mode | Score | Source |",
            "|---|---|---|---:|---|---|---:|---|",
        ]
    )
    for entry in entries:
        lines.append(
            "| {script_id} | {scope} | {channel} | {revision} | {summary} | {mode} | {score} | {source} |".format(
                script_id=entry.get("script_id", ""),
                scope=entry.get("scope", ""),
                channel=entry.get("channel", ""),
                revision=entry.get("revision", 1),
                summary=str(entry.get("summary", "")).replace("|", "/"),
                mode=entry.get("execution_mode", ""),
                score=entry.get("success_score", DEFAULT_SCORE),
                source=entry.get("source_path", ""),
            )
        )
    lines.append("")
    lines.append(f"Root: `{root}`")
    return "\n".join(lines)


def _read_shebang(path: Path) -> str:
    try:
        with path.open("rb") as fh:
            return fh.readline(256).decode("utf-8", errors="ignore")
    except OSError:
        return ""


def _looks_like_script(path: Path) -> bool:
    if path.suffix.lower() in SCRIPT_EXTENSIONS:
        return True
    return _read_shebang(path).startswith("#!")


def _should_ignore_dir(rel_path: Path, ignore_dirs: set[str]) -> bool:
    parts = [part for part in rel_path.parts if part not in {"."}]
    if any(part in ignore_dirs for part in parts):
        return True
    rel = rel_path.as_posix()
    return rel in ignore_dirs


def _candidate_files(project_root: Path, *, ignore_dirs: list[str] | None = None) -> list[Path]:
    ignore_set = {str(item) for item in (ignore_dirs or [])}
    out: list[Path] = []
    for current_root, dirnames, filenames in os.walk(project_root, topdown=True):
        current = Path(current_root)
        rel_current = current.relative_to(project_root)
        dirnames[:] = [
            name
            for name in dirnames
            if not _should_ignore_dir(rel_current / name, ignore_set)
        ]
        for filename in filenames:
            path = current / filename
            if _looks_like_script(path):
                out.append(path)
    return sorted(set(out))


def _project_settings(project_path: str | Path) -> dict[str, Any]:
    root = project_scriptlib_root(project_path)
    return read_settings(root)


def _project_pin(project_path: str | Path, canonical_id: str) -> dict[str, Any] | None:
    settings = _project_settings(project_path)
    return dict((settings.get("shared_pins") or {}).get(canonical_id) or {}) or None


def _find_entry_in_root(script_id: str, *, root: Path, variant: str | None = None) -> tuple[Optional[dict[str, Any]], Optional[Path]]:
    for entry in _iter_entry_metadata(root):
        if entry.get("script_id") == script_id or entry.get("canonical_id") == script_id:
            if variant and entry.get("variant") != variant:
                continue
            return entry, root
    return None, None


def _latest_shared_entry(root: Path, canonical_id: str, *, channel: str | None = None) -> dict[str, Any] | None:
    entries = [
        entry
        for entry in _iter_entry_metadata(root)
        if entry.get("canonical_id") == canonical_id and entry.get("scope") == "shared"
    ]
    if channel:
        entries = [entry for entry in entries if entry.get("channel") == channel]
    if not entries:
        return None
    entries.sort(key=lambda item: (int(item.get("revision", 1)), item.get("updated_at", "")), reverse=True)
    return entries[0]


def _promotion_candidates(project_path: str | Path) -> list[dict[str, Any]]:
    root = project_scriptlib_root(project_path)
    if not is_enabled(root):
        return []
    global_root = global_scriptlib_root()
    out: list[dict[str, Any]] = []
    for entry in _iter_entry_metadata(root):
        if entry.get("scope") != "project":
            continue
        if entry.get("status") not in {"validated", "approved"}:
            continue
        if float(entry.get("success_score", 0.0)) < 70.0:
            continue
        latest = _latest_shared_entry(global_root, entry["canonical_id"], channel=PINNED_SHARED_DEFAULT_CHANNEL)
        if latest and latest.get("source_hash") == entry.get("source_hash"):
            continue
        out.append(
            {
                "script_id": entry["script_id"],
                "canonical_id": entry["canonical_id"],
                "summary": entry["summary"],
                "success_score": entry["success_score"],
                "status": entry["status"],
                "recommended_channel": PINNED_SHARED_DEFAULT_CHANNEL,
            }
        )
    return out


def harvest_workspace(project_path: str = ".", *, dry_run: bool = False) -> dict[str, Any]:
    project_root = Path(project_path).expanduser().resolve()
    root = project_scriptlib_root(project_root)
    if not is_enabled(root):
        return {"ok": False, "error": "scriptlib is not enabled for this workspace", "root": str(root)}

    ensure_root_layout(root, scope="project", enabled=True, dry_run=False)
    settings = read_settings(root)
    ignore_dirs = list(settings.get("ignore_dirs") or DEFAULT_IGNORE_DIRS)

    scanned = _candidate_files(project_root, ignore_dirs=ignore_dirs)
    copied = 0
    updated = 0
    skipped = 0
    harvested: list[dict[str, Any]] = []

    for src in scanned:
        rel = src.relative_to(project_root)
        text = src.read_text(encoding="utf-8", errors="ignore")
        canonical_id = canonical_id_for_path(src, project_root)
        language, runtime = _detect_language(src, text)
        is_test_script = rel.parts and rel.parts[0] == "tests"
        harness = _detect_harness(rel, language)
        path_risk, execution_mode = _path_risk(text, rel, is_test_script)
        variant = language
        version = "v1"
        dst_dir = _entry_dir(root, canonical_id, variant, version)
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst_script = dst_dir / src.name
        meta_path = dst_dir / SCRIPTLIB_METADATA_FILE
        source_hash = _file_hash(src)

        existing_hash = None
        existing_entry: dict[str, Any] | None = None
        if meta_path.exists():
            try:
                existing_entry = _load_entry(meta_path)
                existing_hash = existing_entry.get("source_hash")
            except Exception:
                existing_hash = None
                existing_entry = None

        entry = _normalize_entry(
            {
                "script_id": f"{canonical_id}:{variant}:{version}",
                "canonical_id": canonical_id,
                "summary": _compute_summary(rel, text, is_test_script),
                "source_path": rel.as_posix(),
                "source_workspace_root": str(project_root),
                "execution_cwd": str(project_root),
                "language": language,
                "runtime": runtime,
                "harness": harness,
                "effect_tier": _effect_tier(rel, is_test_script),
                "is_test_script": is_test_script,
                "copy_timestamp": now_utc(),
                "variant": variant,
                "version": version,
                "status": "draft",
                "success_score": DEFAULT_SCORE,
                "path_risk": path_risk,
                "execution_mode": execution_mode,
                "copy_path": str(dst_script),
                "source_hash": source_hash,
                "common_mistakes": [],
                "run_history": [],
                "tags": [language, harness, "test" if is_test_script else "script"],
                "scope": "project",
                "promotion_state": "harvested",
                "channel": "workspace",
                "revision": 1,
                "approval_required_actions": ["promote"],
                "provenance": {
                    "source_workspace_root": str(project_root),
                    "source_path": rel.as_posix(),
                    "original_source_workspace_root": str(project_root),
                    "original_source_path": rel.as_posix(),
                },
            },
            root=root,
        )
        if existing_entry:
            entry["status"] = existing_entry.get("status", entry["status"])
            entry["success_score"] = existing_entry.get("success_score", entry["success_score"])
            entry["common_mistakes"] = existing_entry.get("common_mistakes", [])
            entry["run_history"] = existing_entry.get("run_history", [])
            entry["approval_required_actions"] = existing_entry.get("approval_required_actions", entry["approval_required_actions"])
            if existing_entry.get("execution_mode") == "native_copy":
                entry["execution_mode"] = "native_copy"

        if dry_run:
            harvested.append(entry)
            continue

        if existing_hash == source_hash and dst_script.exists():
            skipped += 1
        else:
            shutil.copy2(src, dst_script)
            if existing_hash is None:
                copied += 1
            else:
                updated += 1

        meta_path.write_text(yaml.safe_dump({k: v for k, v in entry.items() if not k.startswith("_")}, sort_keys=False, allow_unicode=False), encoding="utf-8")
        harvested.append(entry)

    if not dry_run:
        refresh_index(root)
        _record_scriptlib_metric(
            "scriptlib_harvest",
            value=float(len(harvested)),
            metadata={"project_root": str(project_root), "files_copied": copied, "files_updated": updated},
        )
        _touch_scriptlib_session(tool_name="scriptlib_harvest_workspace", key_decision="harvested project scripts")

    return {
        "ok": True,
        "root": str(root),
        "files_scanned": len(scanned),
        "files_copied": copied,
        "files_updated": updated,
        "files_skipped": skipped,
        "entries_requiring_wrapper": sum(
            1 for entry in harvested if entry.get("execution_mode") in {"wrapped", "source_context"}
        ),
        "path_risks": {
            "high": sum(1 for entry in harvested if entry.get("path_risk") == "high"),
            "medium": sum(1 for entry in harvested if entry.get("path_risk") == "medium"),
            "low": sum(1 for entry in harvested if entry.get("path_risk") == "low"),
        },
        "ignore_dirs": ignore_dirs,
        "promotion_candidates": _promotion_candidates(project_root)[:10],
        "dry_run": dry_run,
    }


def _load_index(root: Path) -> dict[str, Any]:
    path = index_path(root)
    if not path.is_file():
        refresh_index(root)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"entries": []}


def _active_roots(project_path: str = ".") -> list[Path]:
    project_root = project_scriptlib_root(project_path)
    roots: list[Path] = []
    if is_enabled(project_root):
        roots.append(project_root)
    global_root = global_scriptlib_root()
    if is_enabled(global_root):
        roots.append(global_root)
    return roots


def _reuse_decision(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {
            "reuseDecision": "new",
            "scriptId": "",
            "whySelected": "No acceptable existing script matched the request.",
            "riskLevel": "unknown",
            "nextAction": "Create a new freestanding reusable script and record it through librarian.",
        }
    top = results[0]
    score = float(top.get("success_score", 0.0))
    if score >= 70.0:
        decision = "reuse"
        why = "Top candidate is validated enough to reuse directly."
        next_action = "Reuse the existing script as-is or run it through scriptlib."
    elif score >= 40.0:
        decision = "fork"
        why = "Top candidate is close, but should be adapted instead of rewritten."
        next_action = "Fork the existing script and adapt it."
    else:
        decision = "new"
        why = "Available candidates are too weak or too risky to trust directly."
        next_action = "Create a new script after recording the miss through librarian."
    return {
        "reuseDecision": decision,
        "scriptId": top.get("script_id", ""),
        "whySelected": why,
        "riskLevel": top.get("path_risk", "unknown"),
        "nextAction": next_action,
    }


def search(
    query: str,
    *,
    project_path: str = ".",
    capability: str | None = None,
    language: str | None = None,
    harness: str | None = None,
    effect_tier: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    roots = _active_roots(project_path)
    if not roots:
        return {"ok": False, "error": "scriptlib is disabled for both project and global scopes"}

    tokens = [tok for tok in re.split(r"[^a-z0-9]+", query.lower()) if tok]
    ranked: list[dict[str, Any]] = []
    project_root = str(project_scriptlib_root(project_path))
    for root in roots:
        for entry in (_load_index(root).get("entries") or []):
            entry = _normalize_index_entry(entry, root=root, project_path=project_path)
            if capability and capability not in (entry.get("tags") or []):
                continue
            if language and entry.get("language") != language:
                continue
            if harness and entry.get("harness") != harness:
                continue
            if effect_tier and entry.get("effect_tier") != effect_tier:
                continue
            haystack = entry.get("search_text", "")
            match_score = sum(haystack.count(token) for token in tokens) if tokens else 1
            overlay_bonus = 15.0 if str(root) == project_root else 0.0
            pin_bonus = 10.0 if entry.get("shared_pin") else 0.0
            score = (match_score * 5.0) + float(entry.get("success_score", 0.0)) / 10.0 + overlay_bonus + pin_bonus
            ranked.append({**entry, "_library_root": str(root), "_score": round(score, 2)})

    ranked.sort(key=lambda item: (-item["_score"], -float(item.get("success_score", 0.0)), item.get("script_id", "")))
    top = ranked[:limit]
    return {
        "ok": True,
        "query": query,
        "decision": _reuse_decision(top),
        "results": top,
        "roots": [str(root) for root in roots],
    }


def _find_entry(script_id: str, *, project_path: str = ".", variant: str | None = None) -> tuple[Optional[dict[str, Any]], Optional[Path]]:
    for root in _active_roots(project_path):
        for entry in _iter_entry_metadata(root):
            if entry.get("script_id") == script_id or entry.get("canonical_id") == script_id:
                if variant and entry.get("variant") != variant:
                    continue
                return entry, root
    return None, None


def describe(script_id: str, *, project_path: str = ".", variant: str | None = None) -> dict[str, Any]:
    entry, root = _find_entry(script_id, project_path=project_path, variant=variant)
    if entry is None or root is None:
        return {"ok": False, "error": f"Script not found: {script_id}"}
    payload = {k: v for k, v in entry.items() if not k.startswith("_")}
    payload["library_root"] = str(root)
    payload["recommended_run_mode"] = entry.get("execution_mode")
    if payload.get("scope") == "shared":
        pin = _project_pin(project_path, payload.get("canonical_id", ""))
        latest = _latest_shared_entry(global_scriptlib_root(), payload["canonical_id"], channel=payload.get("channel"))
        payload["shared_pin"] = pin
        payload["update_availability"] = bool(pin and latest and latest.get("revision", 0) > int(pin.get("revision", 0)))
    return {"ok": True, "script": payload}


def _command_for_entry(entry: dict[str, Any], *, use_copy: bool) -> list[str]:
    target = entry.get("copy_path") if use_copy else str(Path(entry["source_workspace_root"]) / entry["source_path"])
    runtime = entry.get("runtime")
    if runtime == "python":
        return [sys.executable, target]
    if runtime == "bash":
        return ["bash", target]
    if runtime == "node":
        return ["node", target]
    return [target]


def record_result(
    script_id: str,
    *,
    project_path: str = ".",
    variant: str | None = None,
    outcome: str,
    notes: str | None = None,
    duration_ms: int | None = None,
    promote_status: str | None = None,
    validate_native_copy: bool = False,
) -> dict[str, Any]:
    entry, root = _find_entry(script_id, project_path=project_path, variant=variant)
    if entry is None or root is None:
        return {"ok": False, "error": f"Script not found: {script_id}"}

    run_history = list(entry.get("run_history") or [])
    run_history.append(
        {
            "timestamp": now_utc(),
            "outcome": outcome,
            "notes": notes or "",
            "duration_ms": duration_ms,
        }
    )
    entry["run_history"] = run_history[-25:]

    if notes and outcome != "success":
        mistakes = list(entry.get("common_mistakes") or [])
        if notes not in mistakes:
            mistakes.append(notes)
        entry["common_mistakes"] = mistakes[-10:]

    if promote_status:
        entry["status"] = promote_status
    if validate_native_copy:
        entry["execution_mode"] = "native_copy"

    entry["success_score"] = _score_from_runs(entry)
    meta_path = Path(entry["_metadata_path"])
    payload = {k: v for k, v in entry.items() if not k.startswith("_")}
    meta_path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False), encoding="utf-8")
    refresh_index(root)
    _record_scriptlib_metric(
        "scriptlib_run_success" if outcome == "success" else "scriptlib_run_failure",
        metadata={"script_id": payload["script_id"], "scope": payload.get("scope"), "status": payload.get("status")},
    )
    return {
        "ok": True,
        "script_id": payload["script_id"],
        "success_score": payload["success_score"],
        "status": payload["status"],
        "scope": payload.get("scope"),
    }


def run(
    script_id: str,
    *,
    project_path: str = ".",
    variant: str | None = None,
    args: list[str] | None = None,
    dry_run: bool = False,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    entry, _root = _find_entry(script_id, project_path=project_path, variant=variant)
    if entry is None:
        return {"ok": False, "error": f"Script not found: {script_id}"}

    args = args or []
    execution_mode = entry.get("execution_mode", "wrapped")
    use_copy = execution_mode == "native_copy"
    cwd = Path(entry.get("execution_cwd") or entry["source_workspace_root"]).resolve()
    command = _command_for_entry(entry, use_copy=use_copy) + args

    env = os.environ.copy()
    env.update(
        {
            "SCRIPTLIB_EXECUTION_MODE": execution_mode,
            "SCRIPTLIB_SOURCE_PATH": entry["source_path"],
            "SCRIPTLIB_SOURCE_WORKSPACE_ROOT": entry["source_workspace_root"],
            "SCRIPTLIB_LIBRARY_COPY": entry["copy_path"],
            "SCRIPTLIB_SCOPE": entry.get("scope", "project"),
            "SCRIPTLIB_CHANNEL": entry.get("channel", "workspace"),
            "SCRIPTLIB_REVISION": str(entry.get("revision", 1)),
        }
    )

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "script_id": entry.get("script_id"),
            "scope": entry.get("scope"),
            "channel": entry.get("channel"),
            "revision": entry.get("revision"),
            "execution_mode": execution_mode,
            "resolved_cwd": str(cwd),
            "command": command,
            "risk_level": entry.get("effect_tier"),
        }

    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
        )
        outcome = "success" if proc.returncode == 0 else "failure"
        record_result(
            entry["script_id"],
            project_path=project_path,
            variant=variant,
            outcome=outcome,
            notes=proc.stderr.strip()[:300] if proc.returncode != 0 else None,
        )
        return {
            "ok": proc.returncode == 0,
            "script_id": entry.get("script_id"),
            "scope": entry.get("scope"),
            "channel": entry.get("channel"),
            "revision": entry.get("revision"),
            "execution_mode": execution_mode,
            "resolved_cwd": str(cwd),
            "risk_level": entry.get("effect_tier"),
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "score_update_hint": "Run scriptlib_record_result with promote_status='validated' after manual review.",
        }
    except subprocess.TimeoutExpired as exc:
        record_result(
            entry["script_id"],
            project_path=project_path,
            variant=variant,
            outcome="failure",
            notes=f"Timed out after {timeout_seconds}s",
        )
        return {
            "ok": False,
            "script_id": entry.get("script_id"),
            "scope": entry.get("scope"),
            "channel": entry.get("channel"),
            "revision": entry.get("revision"),
            "execution_mode": execution_mode,
            "resolved_cwd": str(cwd),
            "risk_level": entry.get("effect_tier"),
            "error": f"Script timed out after {timeout_seconds}s",
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
        }


def fork(
    script_id: str,
    *,
    project_path: str = ".",
    new_variant_or_version: str,
) -> dict[str, Any]:
    entry, root = _find_entry(script_id, project_path=project_path)
    if entry is None or root is None:
        return {"ok": False, "error": f"Script not found: {script_id}"}

    variant = entry.get("variant", "copy")
    version = new_variant_or_version
    src_dir = Path(entry["_entry_dir"])
    dst_dir = _entry_dir(root, entry["canonical_id"], variant, version)
    if dst_dir.exists():
        return {"ok": False, "error": f"Target version already exists: {version}"}
    shutil.copytree(src_dir, dst_dir)
    meta_path = dst_dir / SCRIPTLIB_METADATA_FILE
    payload = _normalize_entry(yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}, root=root)
    script_copy = next((p for p in dst_dir.iterdir() if p.is_file() and p.name != SCRIPTLIB_METADATA_FILE), None)
    payload["version"] = version
    payload["revision"] = _parse_revision(version, default=int(entry.get("revision", 1)))
    payload["script_id"] = f"{payload['canonical_id']}:{payload['variant']}:{version}"
    payload["status"] = "draft"
    payload["success_score"] = DEFAULT_SCORE
    payload["copy_timestamp"] = now_utc()
    payload["run_history"] = []
    if script_copy is not None:
        payload["copy_path"] = str(script_copy)
    meta_path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False), encoding="utf-8")
    refresh_index(root)
    return {
        "ok": True,
        "script_id": payload["script_id"],
        "entry_dir": str(dst_dir),
        "scope": payload.get("scope"),
    }


def promote(
    script_id: str,
    *,
    project_path: str = ".",
    variant: str | None = None,
    channel: str = PINNED_SHARED_DEFAULT_CHANNEL,
    approved: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    project_root = project_scriptlib_root(project_path)
    entry, _ = _find_entry_in_root(script_id, root=project_root, variant=variant)
    if entry is None:
        return {"ok": False, "error": f"Project script not found: {script_id}"}
    if not approved:
        return {
            "ok": False,
            "error": "Shared promotion requires explicit approval.",
            "approval_required": True,
            "pending_action": "promote",
            "script_id": entry["script_id"],
        }

    shared_root = global_scriptlib_root()
    ensure_root_layout(shared_root, scope="global", enabled=True, dry_run=dry_run)
    normalized_channel = _normalize_channel(channel, default=PINNED_SHARED_DEFAULT_CHANNEL)
    latest = _latest_shared_entry(shared_root, entry["canonical_id"], channel=normalized_channel)
    if latest and latest.get("source_hash") == entry.get("source_hash"):
        return {
            "ok": True,
            "action": "already_current",
            "shared_script_id": latest["script_id"],
            "channel": normalized_channel,
            "revision": latest.get("revision", 1),
            "root": str(shared_root),
        }

    next_revision = (int(latest.get("revision", 0)) if latest else 0) + 1
    version = f"{normalized_channel}-r{next_revision}"
    shared_dir = _entry_dir(shared_root, entry["canonical_id"], entry.get("variant", "copy"), version)
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "action": "promote",
            "shared_script_id": f"{entry['canonical_id']}:{entry.get('variant', 'copy')}:{version}",
            "channel": normalized_channel,
            "revision": next_revision,
            "root": str(shared_root),
        }

    shutil.copytree(Path(entry["_entry_dir"]), shared_dir)
    shared_meta = shared_dir / SCRIPTLIB_METADATA_FILE
    payload = _normalize_entry(yaml.safe_load(shared_meta.read_text(encoding="utf-8")) or {}, root=shared_root)
    shared_script = next((p for p in shared_dir.iterdir() if p.is_file() and p.name != SCRIPTLIB_METADATA_FILE), None)
    payload.update(
        {
            "script_id": f"{entry['canonical_id']}:{entry.get('variant', 'copy')}:{version}",
            "scope": "shared",
            "promotion_state": "promoted",
            "channel": normalized_channel,
            "revision": next_revision,
            "version": version,
            "status": "approved",
            "copy_timestamp": now_utc(),
            "approval_required_actions": ["apply_update", "deprecate"],
            "provenance": {
                "source_workspace_root": entry.get("source_workspace_root"),
                "source_path": entry.get("source_path"),
                "original_source_workspace_root": entry.get("provenance", {}).get("original_source_workspace_root", entry.get("source_workspace_root")),
                "original_source_path": entry.get("provenance", {}).get("original_source_path", entry.get("source_path")),
                "promoted_from_script_id": entry.get("script_id"),
                "promoted_from_library_root": str(project_root),
            },
        }
    )
    if shared_script is not None:
        payload["copy_path"] = str(shared_script)
    shared_meta.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False), encoding="utf-8")
    refresh_index(shared_root)
    _record_scriptlib_metric(
        "scriptlib_promote",
        metadata={"canonical_id": entry["canonical_id"], "channel": normalized_channel, "revision": next_revision},
    )
    _store_scriptlib_fact(
        title=f"Promoted script {entry['canonical_id']}",
        content=f"Promoted {entry['script_id']} into shared scriptlib as {payload['script_id']}.",
        tags=[normalized_channel, "promotion"],
        metadata={"shared_script_id": payload["script_id"]},
    )
    _touch_scriptlib_session(tool_name="scriptlib_promote", key_decision=f"promoted {entry['canonical_id']} to shared")
    return {
        "ok": True,
        "action": "promoted",
        "shared_script_id": payload["script_id"],
        "channel": normalized_channel,
        "revision": next_revision,
        "root": str(shared_root),
    }


def _resolve_shared_entry(script_id: str, *, channel: str | None = None, target_revision: int | None = None) -> dict[str, Any] | None:
    shared_root = global_scriptlib_root()
    exact, _ = (None, None)
    if script_id.count(":") >= 2:
        exact, _ = _find_entry_in_root(script_id, root=shared_root)
    if exact is not None:
        return exact
    normalized_channel = _normalize_channel(channel, default=PINNED_SHARED_DEFAULT_CHANNEL)
    latest = _latest_shared_entry(shared_root, script_id, channel=normalized_channel)
    if latest is None:
        return None
    if target_revision is None:
        return latest
    for entry in _iter_entry_metadata(shared_root):
        if (
            entry.get("canonical_id") == latest.get("canonical_id")
            and entry.get("channel") == normalized_channel
            and int(entry.get("revision", 1)) == target_revision
        ):
            return entry
    return None


def list_updates(project_path: str = ".") -> dict[str, Any]:
    root = project_scriptlib_root(project_path)
    settings = read_settings(root)
    pins = dict(settings.get("shared_pins") or {})
    updates: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for canonical_id, pin in sorted(pins.items()):
        latest = _latest_shared_entry(global_scriptlib_root(), canonical_id, channel=pin.get("channel"))
        item = {
            "canonical_id": canonical_id,
            "current_pin": pin,
            "latest_shared": None,
            "update_available": False,
            "status": "current",
        }
        if latest is None:
            item["status"] = "missing_upstream"
            updates.append(item)
            continue
        item["latest_shared"] = {
            "script_id": latest["script_id"],
            "channel": latest["channel"],
            "revision": latest["revision"],
            "summary": latest["summary"],
        }
        if int(latest.get("revision", 1)) > int(pin.get("revision", 0)):
            item["update_available"] = True
            item["status"] = "update_available"
            updates.append(item)
        current.append(item)
    return {"ok": True, "root": str(root), "pins": len(pins), "updates": updates, "current": current}


def apply_update(
    script_id: str,
    *,
    project_path: str = ".",
    channel: str | None = None,
    target_revision: int | None = None,
    approved: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not approved:
        return {
            "ok": False,
            "error": "Pinning or upgrading a shared script requires explicit approval.",
            "approval_required": True,
            "pending_action": "apply_update",
            "script_id": script_id,
        }

    target = _resolve_shared_entry(script_id, channel=channel, target_revision=target_revision)
    if target is None:
        return {"ok": False, "error": f"Shared script not found: {script_id}"}

    root = project_scriptlib_root(project_path)
    ensure_root_layout(root, scope="project", enabled=True, dry_run=dry_run)
    settings = read_settings(root)
    shared_pins = dict(settings.get("shared_pins") or {})
    current = shared_pins.get(target["canonical_id"])
    action = "updated" if current else "pinned"
    pin_payload = {
        "script_id": target["script_id"],
        "canonical_id": target["canonical_id"],
        "channel": target["channel"],
        "revision": target["revision"],
        "library_root": str(global_scriptlib_root()),
        "summary": target["summary"],
        "updated_at": now_utc(),
    }
    if dry_run:
        return {"ok": True, "dry_run": True, "action": action, "pin": pin_payload}

    shared_pins[target["canonical_id"]] = pin_payload
    settings["shared_pins"] = shared_pins
    settings["updated_at"] = now_utc()
    write_settings(root, settings)
    _record_scriptlib_metric(
        "scriptlib_apply_update",
        metadata={"canonical_id": target["canonical_id"], "channel": target["channel"], "revision": target["revision"]},
    )
    _touch_scriptlib_session(tool_name="scriptlib_apply_update", key_decision=f"pinned {target['canonical_id']} to {target['script_id']}")
    return {"ok": True, "action": action, "pin": pin_payload}


def catalog_status(project_path: str = ".", *, include_entries: bool = False, limit: int = 20) -> dict[str, Any]:
    project_root = project_scriptlib_root(project_path)
    shared_root = global_scriptlib_root()
    project_enabled = is_enabled(project_root)
    shared_enabled = is_enabled(shared_root)
    project_entries = _load_index(project_root).get("entries", []) if project_enabled else []
    shared_entries = _load_index(shared_root).get("entries", []) if shared_enabled else []
    settings = read_settings(project_root)
    updates = list_updates(project_path=project_path)
    status = {
        "ok": True,
        "project_root": {
            "path": str(project_root),
            "enabled": project_enabled,
            "entries": len(project_entries),
            "ignore_dirs": settings.get("ignore_dirs", []),
        },
        "shared_root": {
            "path": str(shared_root),
            "enabled": shared_enabled,
            "entries": len(shared_entries),
        },
        "shared_pins": dict(settings.get("shared_pins") or {}),
        "updates": updates["updates"],
        "promotion_candidates": _promotion_candidates(project_path)[:limit],
    }
    if include_entries:
        status["project_entries"] = project_entries[:limit]
        status["shared_entries"] = shared_entries[:limit]
    return status


def _duplicate_candidates(project_path: str = ".") -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for root in _active_roots(project_path):
        for entry in _iter_entry_metadata(root):
            key = entry.get("source_hash") or entry.get("canonical_id")
            groups.setdefault(str(key), []).append(entry)
    duplicates = []
    for key, entries in groups.items():
        if len(entries) < 2:
            continue
        duplicates.append(
            {
                "key": key,
                "script_ids": [entry["script_id"] for entry in entries],
                "canonical_ids": sorted({entry["canonical_id"] for entry in entries}),
            }
        )
    return duplicates


def run_maintenance(
    project_path: str = ".",
    *,
    scope: str = "all",
    dry_run: bool = False,
    add_ignore_dirs: list[str] | None = None,
) -> dict[str, Any]:
    if scope not in {"project", "global", "all"}:
        return {"ok": False, "error": f"Unsupported scope: {scope}"}

    project_root = project_scriptlib_root(project_path)
    shared_root = global_scriptlib_root()
    roots: list[Path] = []
    if scope in {"project", "all"} and is_enabled(project_root):
        roots.append(project_root)
    if scope in {"global", "all"} and is_enabled(shared_root):
        roots.append(shared_root)

    refreshed = [refresh_index(root, dry_run=dry_run) for root in roots]
    settings = read_settings(project_root)
    ignore_dirs = sorted({*(settings.get("ignore_dirs") or []), *((add_ignore_dirs or []))})
    if add_ignore_dirs and not dry_run:
        settings["ignore_dirs"] = ignore_dirs
        settings["maintenance"] = {
            "last_run_at": now_utc(),
            "last_report": {
                "added_ignore_dirs": list(add_ignore_dirs),
            },
        }
        write_settings(project_root, settings)
    report = {
        "ok": True,
        "scope": scope,
        "refreshed": refreshed,
        "duplicate_candidates": _duplicate_candidates(project_path),
        "promotion_candidates": _promotion_candidates(project_path),
        "updates": list_updates(project_path=project_path)["updates"],
        "ignore_dirs": ignore_dirs,
        "dry_run": dry_run,
    }
    if not dry_run:
        _record_scriptlib_metric(
            "scriptlib_maintenance",
            metadata={
                "scope": scope,
                "duplicates": len(report["duplicate_candidates"]),
                "promotion_candidates": len(report["promotion_candidates"]),
                "updates": len(report["updates"]),
            },
        )
        if report["promotion_candidates"] or report["updates"] or add_ignore_dirs:
            _store_scriptlib_fact(
                title="Scriptlib maintenance summary",
                content=(
                    f"Maintenance surfaced {len(report['promotion_candidates'])} promotion candidates, "
                    f"{len(report['updates'])} updates, and {len(report['duplicate_candidates'])} duplicate groups."
                ),
                tags=["maintenance"],
                metadata={
                    "promotion_candidates": report["promotion_candidates"][:10],
                    "updates": report["updates"][:10],
                    "duplicate_groups": len(report["duplicate_candidates"]),
                },
            )
        _touch_scriptlib_session(tool_name="scriptlib_run_maintenance", key_decision="ran scriptlib maintenance")
    return report


def seed_if_enabled(project_path: str = ".", *, dry_run: bool = False) -> dict[str, Any]:
    root = project_scriptlib_root(project_path)
    if not is_enabled(root):
        return {"ok": True, "skipped": "scriptlib_disabled", "root": str(root), "guidance_enabled": False}
    result = ensure_root_layout(root, scope="project", enabled=True, dry_run=dry_run)
    result["guidance_enabled"] = True
    return result
