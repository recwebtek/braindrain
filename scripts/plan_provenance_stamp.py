#!/usr/bin/env python3
"""Stamp plan frontmatter and active-model state from Cursor hook payloads."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Standalone import from sibling script (no package install required).
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from plan_branch_utils import (  # noqa: E402
    FRONTMATTER_BLOCK_RE,
    parse_plan_frontmatter,
    set_frontmatter_key,
)

ACTIVE_MODEL_FILE = ".braindrain/active-model.json"
ACTIVE_MODEL_MAX_AGE = timedelta(hours=24)
PROVENANCE_KEYS = (
    "created_by_model",
    "created_at",
    "last_modified_by_model",
    "last_modified_at",
    "cursor_mode",
)
FABLE_RE = re.compile(r"fable[-_]?(\d+)", re.IGNORECASE)
EFFORT_SUFFIX_RE = re.compile(r"(?:thinking|effort|reasoning)[-_](low|medium|high)$", re.IGNORECASE)


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _param_effort(model_params: list[object] | None) -> str | None:
    for raw in model_params or []:
        if not isinstance(raw, dict):
            continue
        param_id = str(raw.get("id", "")).strip().lower()
        value = str(raw.get("value", "")).strip().lower()
        if param_id in {"thinking", "effort", "reasoning", "context"} and value:
            return value
    return None


def _slug_effort(slug: str) -> str | None:
    match = EFFORT_SUFFIX_RE.search(slug)
    if match:
        return match.group(1).lower()
    if not re.search(r"(thinking|effort|reasoning)", slug, re.IGNORECASE):
        return None
    for level in ("low", "medium", "high"):
        if slug.endswith(f"-{level}") or slug.endswith(f"_{level}"):
            return level
    return None


def normalize_model_name(
    model: str | None = None,
    model_id: str | None = None,
    model_params: list[object] | None = None,
) -> str:
    """Normalize Cursor hook model fields to a compact provenance label."""
    raw_model = (model or "").strip()
    raw_id = (model_id or "").strip()
    slug = (raw_id or raw_model).strip().lower()

    if not slug or slug == "auto" or raw_model.lower() == "auto":
        return "auto"

    effort = _param_effort(model_params) or _slug_effort(slug)
    fable = FABLE_RE.search(slug)
    if fable:
        base = f"fable-{fable.group(1)}"
        return f"{base}:{effort}" if effort else base

    display = raw_id or raw_model
    if effort and ":" not in display:
        return f"{display}:{effort}"
    return display


def infer_cursor_mode(model: str | None = None, model_id: str | None = None) -> str:
    slug = ((model_id or model) or "").strip().lower()
    if not slug or slug == "auto" or (model or "").strip().lower() == "auto":
        return "auto"
    return "manual"


def extract_model_from_payload(payload: dict[str, object]) -> dict[str, str]:
    model = str(payload.get("model", "") or "")
    model_id = str(payload.get("model_id", "") or "")
    params = payload.get("model_params")
    model_params = params if isinstance(params, list) else []
    normalized = normalize_model_name(model, model_id, model_params)
    return {
        "model": normalized,
        "model_id": model_id or model,
        "cursor_mode": infer_cursor_mode(model, model_id),
        "conversation_id": str(payload.get("conversation_id", "") or ""),
        "updated_at": _iso_now(),
    }


def active_model_path(repo_root: Path) -> Path:
    return repo_root / ACTIVE_MODEL_FILE


def write_active_model(repo_root: Path, info: dict[str, str]) -> Path:
    path = active_model_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(info, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_active_model(
    repo_root: Path, *, max_age: timedelta = ACTIVE_MODEL_MAX_AGE
) -> dict[str, str] | None:
    path = active_model_path(repo_root)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    updated_at = str(payload.get("updated_at", "")).strip()
    if updated_at:
        try:
            stamp = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            if datetime.now(UTC) - stamp.astimezone(UTC) > max_age:
                return None
        except ValueError:
            return None
    model = str(payload.get("model", "")).strip()
    if not model:
        return None
    return {k: str(v) for k, v in payload.items()}


def is_plan_file(path: Path) -> bool:
    parts = path.parts
    return path.suffix == ".md" and path.name.endswith(".plan.md") and "plans" in parts


def resolve_plan_path(
    repo_root: Path, payload: dict[str, object], explicit: str | None
) -> Path | None:
    if explicit:
        candidate = Path(explicit)
        if not candidate.is_absolute():
            candidate = repo_root / candidate
        return candidate if is_plan_file(candidate) else None

    for key in ("file_path", "path"):
        raw = str(payload.get(key, "") or "").strip()
        if not raw:
            continue
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = repo_root / candidate
        if is_plan_file(candidate):
            return candidate
    return None


def stamp_plan_frontmatter(plan_path: Path, info: dict[str, str]) -> bool:
    if not plan_path.is_file():
        return False

    text = plan_path.read_text(encoding="utf-8")
    existing = parse_plan_frontmatter(text)
    now = info.get("updated_at") or _iso_now()
    model = info.get("model", "auto")
    cursor_mode = info.get("cursor_mode", "auto")

    if not existing.get("created_by_model"):
        text = set_frontmatter_key(text, "created_by_model", f'"{model}"')
    if not existing.get("created_at"):
        text = set_frontmatter_key(text, "created_at", f'"{now}"')

    text = set_frontmatter_key(text, "last_modified_by_model", f'"{model}"')
    text = set_frontmatter_key(text, "last_modified_at", f'"{now}"')
    text = set_frontmatter_key(text, "cursor_mode", f'"{cursor_mode}"')

    if not FRONTMATTER_BLOCK_RE.match(text):
        body = text.lstrip("\n")
        text = (
            "---\n"
            f'created_by_model: "{model}"\n'
            f'created_at: "{now}"\n'
            f'last_modified_by_model: "{model}"\n'
            f'last_modified_at: "{now}"\n'
            f'cursor_mode: "{cursor_mode}"\n'
            "---\n\n"
            f"{body}"
        )

    plan_path.write_text(text, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="Workspace root")
    parser.add_argument("--plan-path", default="", help="Optional plan file to stamp")
    parser.add_argument(
        "--state-only",
        action="store_true",
        help="Only refresh .braindrain/active-model.json",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    payload: dict[str, object] = {}
    if not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        if raw:
            try:
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    payload = loaded
            except json.JSONDecodeError:
                pass

    info = extract_model_from_payload(payload)
    write_active_model(repo_root, info)

    if args.state_only:
        return 0

    plan_path = resolve_plan_path(repo_root, payload, args.plan_path or None)
    if plan_path is not None:
        stamp_plan_frontmatter(plan_path, info)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
