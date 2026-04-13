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

SCRIPTLIB_GUIDANCE = """## Scriptlib Notice

If scriptlib is enabled in this workspace, check scriptlib before writing a new task script.

- Use the scriptlib tools first for reusable operational, test-helper, or validation scripts.
- The librarian can find, adapt, fork, and run existing scripts with the right workspace context.
- Scriptlib with a smart librarian has your back when paths or harness details would otherwise drift.
"""


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


def read_settings(root: Path) -> dict[str, Any]:
    p = settings_path(root)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def write_settings(root: Path, data: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    settings_path(root).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


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
    settings = read_settings(root)
    settings.update(
        {
            "enabled": enabled,
            "scope": scope,
            "updated_at": now_utc(),
        }
    )
    settings.setdefault("created_at", now_utc())
    settings.setdefault("harvest_sources", list(DEFAULT_HARVEST_DIRS))
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


def _load_entry(meta_path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
    raw["_metadata_path"] = str(meta_path)
    raw["_entry_dir"] = str(meta_path.parent)
    return raw


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
    flaky_penalty = min(failures * 2, 15)
    score = (success_rate * 80.0) + 10.0 + status_bonus + native_bonus - flaky_penalty
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
            "| Script ID | Summary | Mode | Score | Source |",
            "|---|---|---|---:|---|",
        ]
    )
    for entry in entries:
        lines.append(
            "| {script_id} | {summary} | {mode} | {score} | {source} |".format(
                script_id=entry.get("script_id", ""),
                summary=str(entry.get("summary", "")).replace("|", "/"),
                mode=entry.get("execution_mode", ""),
                score=entry.get("success_score", DEFAULT_SCORE),
                source=entry.get("source_path", ""),
            )
        )
    lines.append("")
    lines.append(f"Root: `{root}`")
    return "\n".join(lines)


def _candidate_files(project_root: Path) -> list[Path]:
    out: list[Path] = []
    # Top-level scripts (e.g. repo-root operational helpers)
    try:
        for path in project_root.iterdir():
            if not path.is_file():
                continue
            if path.suffix.lower() in SCRIPT_EXTENSIONS:
                out.append(path)
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if text.startswith("#!"):
                out.append(path)
    except OSError:
        pass
    for rel_dir in DEFAULT_HARVEST_DIRS:
        base = project_root / rel_dir
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() in SCRIPT_EXTENSIONS:
                out.append(path)
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if text.startswith("#!"):
                out.append(path)
    return sorted(set(out))


def harvest_workspace(project_path: str = ".", *, dry_run: bool = False) -> dict[str, Any]:
    project_root = Path(project_path).expanduser().resolve()
    root = project_scriptlib_root(project_root)
    if not is_enabled(root):
        return {"ok": False, "error": "scriptlib is not enabled for this workspace", "root": str(root)}

    ensure_root_layout(root, scope="project", enabled=True, dry_run=False)

    scanned = _candidate_files(project_root)
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

        entry = {
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
        }
        if existing_entry:
            entry["status"] = existing_entry.get("status", entry["status"])
            entry["success_score"] = existing_entry.get("success_score", entry["success_score"])
            entry["common_mistakes"] = existing_entry.get("common_mistakes", [])
            entry["run_history"] = existing_entry.get("run_history", [])
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

        meta_path.write_text(yaml.safe_dump(entry, sort_keys=False, allow_unicode=False), encoding="utf-8")
        harvested.append(entry)

    if not dry_run:
        refresh_index(root)

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
            score = (match_score * 5.0) + float(entry.get("success_score", 0.0)) / 10.0 + overlay_bonus
            ranked.append({**entry, "_library_root": str(root), "_score": round(score, 2)})

    ranked.sort(key=lambda item: (-item["_score"], -float(item.get("success_score", 0.0)), item.get("script_id", "")))
    return {
        "ok": True,
        "query": query,
        "results": ranked[:limit],
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
    if entry is None:
        return {"ok": False, "error": f"Script not found: {script_id}"}
    payload = {k: v for k, v in entry.items() if not k.startswith("_")}
    payload["library_root"] = str(root)
    payload["recommended_run_mode"] = entry.get("execution_mode")
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
    return {"ok": True, "script_id": payload["script_id"], "success_score": payload["success_score"], "status": payload["status"]}


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
        }
    )

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "script_id": entry.get("script_id"),
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
    payload = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
    script_copy = next((p for p in dst_dir.iterdir() if p.is_file() and p.name != SCRIPTLIB_METADATA_FILE), None)
    payload["version"] = version
    payload["script_id"] = f"{payload['canonical_id']}:{payload['variant']}:{version}"
    payload["status"] = "draft"
    payload["success_score"] = DEFAULT_SCORE
    payload["copy_timestamp"] = now_utc()
    payload["run_history"] = []
    if script_copy is not None:
        payload["copy_path"] = str(script_copy)
    meta_path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False), encoding="utf-8")
    refresh_index(root)
    return {"ok": True, "script_id": payload["script_id"], "entry_dir": str(dst_dir)}


def seed_if_enabled(project_path: str = ".", *, dry_run: bool = False) -> dict[str, Any]:
    root = project_scriptlib_root(project_path)
    if not is_enabled(root):
        return {"ok": True, "skipped": "scriptlib_disabled", "root": str(root), "guidance_enabled": False}
    result = ensure_root_layout(root, scope="project", enabled=True, dry_run=dry_run)
    result["guidance_enabled"] = True
    return result
