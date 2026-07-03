#!/usr/bin/env python3
"""Generate a daily planning audit report in markdown format.

Priority source order:
1) <ide>/plans/*.plan.md  (cursor, codex, kiro, windsurf, ...)
2) Secondary markdown docs in repo
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from plan_branch_utils import (  # noqa: E402, I001
    FRONTMATTER_BLOCK_RE,
    FRONTMATTER_KV_RE,
    _inject_frontmatter_key,
    _strip_quotes,
    parse_frontmatter_body as _parse_frontmatter_body,
    parse_frontmatter_children_spec,
    parse_frontmatter_todos,
    parse_plan_frontmatter,
    remove_frontmatter_block as _remove_frontmatter_block,
    remove_frontmatter_scalar as _remove_frontmatter_scalar,
    set_frontmatter_key as _set_frontmatter_key,
    set_frontmatter_yaml_block as _set_frontmatter_yaml_block,
)

SCHEMA_VERSION = "1.2"
STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "with",
}
PLANNING_KEYWORDS = (
    "roadmap",
    "todo",
    "plan",
    "planning",
    "milestone",
    "backlog",
    "task",
    "next",
    "open",
    "outstanding",
    "shipped",
    "done",
)
STATUS_ORDER = ["Implemented", "In Progress", "Blocked", "Outstanding", "Unknown"]
ITEM_LINE_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.*)$")
CHECKBOX_RE = re.compile(r"^\[([ xX])\]\s*(.*)$")
HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.*)$")
BACKTICK_RE = re.compile(r"`([^`]+)`")
PATHISH_RE = re.compile(r"\b(?:[\w.-]+/)+[\w.-]+\b")
# Strict ownership markers only (no fuzzy "owner" substring in prose).
OWNER_AT_RE = re.compile(r"(?:^|[\s([{<'\"]|[-*]\s+)@([a-zA-Z0-9_.-]{1,64})\b")
OWNER_LABEL_RES = (
    re.compile(r"\bowner\s*:\s*(\S+)", re.IGNORECASE),
    re.compile(r"\bassignee\s*:\s*(\S+)", re.IGNORECASE),
    re.compile(r"\bdri\s*:\s*(\S+)", re.IGNORECASE),
)

# Plans live under <ide>/plans/*.plan.md. The leading dot is stripped to form
# the `ide` tag (e.g. ".cursor" -> "cursor"). Auto-detected via filesystem
# scan, but this list bounds discovery to known IDE conventions so the audit
# does not pick up unrelated dotfolders.
KNOWN_IDE_DOTFOLDERS = (
    ".cursor",
    ".codex",
    ".kiro",
    ".windsurf",
    ".cline",
    ".roo",
    ".zed",
    ".aider",
    ".continue",
)

# Plan-level disposition vocabulary. Validated when reading frontmatter.
VALID_DISPOSITIONS = (
    "active",
    "meta",
    "research-needed",
    "replan-needed",
    "merge-ready",
    "needs-fix",
    "backlogged",
    "scratched",
    "implemented",
    "archived",
)
DEFAULT_DISPOSITION = "active"
ARCHIVED_BATCH_LIMIT = 10

# Map disposition -> action verb shown in next-actions queue. The `active`
# disposition resolves to IMPLEMENT only when item-level signals say so;
# otherwise it stays off the triage queue. `scratched` and `implemented`
# never appear in the queue.
DISPOSITION_VERB = {
    "meta": "SPLIT",
    "research-needed": "RESEARCH",
    "replan-needed": "REPLAN",
    "merge-ready": "MERGE",
    "needs-fix": "FIX",
    "backlogged": "BACKLOG",
}


ACTIVE_MODEL_FILE = ".braindrain/active-model.json"
ACTIVE_MODEL_MAX_AGE_HOURS = 24


def _active_model_path(repo_root: Path) -> Path:
    return repo_root / ACTIVE_MODEL_FILE


def load_active_model_state(
    repo_root: Path,
    *,
    max_age_hours: int = ACTIVE_MODEL_MAX_AGE_HOURS,
) -> dict[str, str] | None:
    """Load recent model provenance captured by plan_provenance_stamp hooks."""
    path = _active_model_path(repo_root)
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
            stamp = dt.datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            age = dt.datetime.now(dt.UTC) - stamp.astimezone(dt.UTC)
            if age > dt.timedelta(hours=max_age_hours):
                return None
        except ValueError:
            return None
    model = str(payload.get("model", "")).strip()
    if not model:
        return None
    return {k: str(v) for k, v in payload.items()}


def resolve_model_name(
    model_name: str | None = None,
    *,
    repo_root: Path | None = None,
) -> str:
    if model_name and model_name.strip():
        return model_name.strip()
    for key in (
        "BRAINDRAIN_ACTIVE_MODEL",
        "CURSOR_ACTIVE_MODEL",
        "CURSOR_MODEL",
        "MODEL_NAME",
    ):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    if repo_root is not None:
        state = load_active_model_state(repo_root)
        if state and state.get("model"):
            return state["model"]
    return "auto"


def resolve_cursor_mode(
    cursor_mode: str | None = None,
    *,
    repo_root: Path | None = None,
) -> str:
    mode = (
        (
            cursor_mode
            or os.environ.get("CURSOR_MODEL_SELECTION", "")
            or os.environ.get("BRAINDRAIN_CURSOR_MODE", "")
        )
        .strip()
        .lower()
    )
    if mode in {"auto", "manual"}:
        return mode
    if repo_root is not None:
        state = load_active_model_state(repo_root)
        if state and state.get("cursor_mode") in {"auto", "manual"}:
            return state["cursor_mode"]
    return "auto"


def load_trace_models(trace_path: Path, limit: int = 1000) -> list[str]:
    if not trace_path.is_file():
        return []
    models: list[str] = []
    for raw in trace_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-limit:]:
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        model_name = str(payload.get("model_name") or "").strip()
        if model_name:
            models.append(model_name)
    return sorted(set(models))


_DEFAULT_OWNER_CACHE: str | None = None


def resolve_default_owner(
    repo_root: Path | None = None,
    *,
    refresh: bool = False,
) -> str:
    """Resolve the default plan owner.

    Priority:
    1) `.braindrain/plan-config.yaml -> default_owner` (if file/key exists).
    2) `braindrain.env_probe.get_env_context()` -> `summary.identity.username`.
    3) `getpass.getuser()` / `$USER` env.
    4) Literal `@user` as last resort.

    The result is always prefixed with `@` and cached for the run.
    """
    global _DEFAULT_OWNER_CACHE
    if _DEFAULT_OWNER_CACHE and not refresh:
        return _DEFAULT_OWNER_CACHE

    handle = ""

    # 1) Optional plan-config override.
    if repo_root is not None:
        cfg_path = repo_root / ".braindrain" / "plan-config.yaml"
        if cfg_path.is_file():
            try:
                fm = parse_plan_frontmatter(
                    "---\n" + cfg_path.read_text(encoding="utf-8") + "\n---\n"
                )
                cfg_owner = fm.get("default_owner")
                if isinstance(cfg_owner, str) and cfg_owner.strip():
                    handle = cfg_owner.strip().lstrip("@")
            except Exception:
                pass

    # 2) Braindrain env_probe (sibling repo on path).
    if not handle:
        try:
            repo = repo_root or Path(__file__).resolve().parent.parent
            if str(repo) not in sys.path:
                sys.path.insert(0, str(repo))
            from braindrain.env_probe import get_env_context  # type: ignore

            ctx = get_env_context()
            handle = (ctx.get("summary", {}).get("identity", {}).get("username", "")) or ""
        except Exception:
            handle = ""

    # 3) getpass / env.
    if not handle:
        try:
            handle = getpass.getuser()
        except Exception:
            handle = os.environ.get("USER", "") or os.environ.get("LOGNAME", "")

    # 4) Last resort.
    if not handle:
        handle = "user"

    _DEFAULT_OWNER_CACHE = f"@{handle.lstrip('@')}"
    return _DEFAULT_OWNER_CACHE


def has_explicit_owner(text: str) -> bool:
    if OWNER_AT_RE.search(text):
        return True
    for rx in OWNER_LABEL_RES:
        if rx.search(text):
            return True
    return False


def extract_owner_display(text: str) -> str:
    m = OWNER_AT_RE.search(text)
    if m:
        return f"@{m.group(1)}"
    for rx in OWNER_LABEL_RES:
        m2 = rx.search(text)
        if m2:
            return m2.group(1).strip(".,;:)]}")
    return "—"


@dataclasses.dataclass
class PlanItem:
    item: str
    source: str
    status: str
    confidence: str
    evidence: list[str]
    why: str
    tokens: set[str]


@dataclasses.dataclass
class Action:
    """A concrete next-action verb attached to a plan (and optionally an item).

    Verbs match the disposition + signal table:
    RESEARCH / REPLAN / MERGE / IMPLEMENT / BACKLOG / SCRATCH / FIX.
    Produced by ``detect_actions`` and consumed by both the per-plan cards
    in the daily report and the next-actions triage queue.
    """

    verb: str  # RESEARCH | REPLAN | MERGE | IMPLEMENT | BACKLOG | FIX
    plan_slug: str
    plan_source: str
    ide: str
    title: str  # plan title for human display
    reason: str  # short human reason
    hint: str  # actionable hint
    priority: str  # P0..P3
    item_excerpt: str = ""  # optional — first item snippet that drove this


@dataclasses.dataclass
class ReadyToArchive:
    """Plan that finished all frontmatter todos but is still disposition-active."""

    plan_slug: str
    plan_source: str
    ide: str
    priority: str
    reason: str
    stale_narrative: bool = False


@dataclasses.dataclass
class PlanCard:
    """Plan-level metadata + child item rollup.

    A plan is the upper-level unit of triage. Items are rolled up into
    `items` and a status histogram is precomputed in `counts`.
    """

    slug: str
    title: str
    source: str
    ide: str
    owner: str
    dri: str
    disposition: str
    priority: str
    parent: str
    delegated_to: list[str]
    is_master: bool
    items: list[PlanItem] = dataclasses.field(default_factory=list)
    counts: dict[str, int] = dataclasses.field(default_factory=dict)
    branch: str = "—"
    branch_source: str = "none"
    pr: str = "—"
    pr_source: str = "none"
    branches: list[str] = dataclasses.field(default_factory=list)
    phase_branches: list[dict[str, str]] = dataclasses.field(default_factory=list)
    todo_summary: dict[str, int] | None = None
    count_source: str = "body"
    stale_narrative: bool = False

    @property
    def is_active_for_triage(self) -> bool:
        """True when the plan should produce next-actions output."""
        return self.disposition not in {"scratched", "implemented", "archived"}


def derive_ide_tag(rel_path: str) -> str:
    """Infer the `ide` tag from a repo-relative plan path.

    `.cursor/plans/x.plan.md` -> `cursor`
    `.codex/plans/y.plan.md`  -> `codex`
    Anything else (secondary docs, legacy `.devdocs/`) -> ``.
    """
    parts = rel_path.split("/", 2)
    if len(parts) >= 2 and parts[0].startswith(".") and parts[1] == "plans":
        return parts[0][1:]
    return ""


def build_plan_card(
    path: Path,
    repo_root: Path,
    items: list[PlanItem] | None = None,
    *,
    default_owner: str | None = None,
) -> PlanCard:
    """Read frontmatter from a plan file and assemble a PlanCard.

    Falls back to sensible defaults when frontmatter is absent so plans
    without metadata are still surfaced (just under `disposition=active`
    with the env-resolved owner). Item list is attached unmodified.
    """
    rel = path.relative_to(repo_root).as_posix()
    fm = parse_plan_frontmatter(path)
    owner_raw = (
        fm.get("owner") or fm.get("dri") or default_owner or resolve_default_owner(repo_root)
    )
    owner = str(owner_raw).strip() if owner_raw else "@user"
    if owner and not owner.startswith("@") and ":" not in owner:
        owner = f"@{owner.lstrip('@')}"
    dri_raw = fm.get("dri") or owner
    dri = str(dri_raw).strip() if dri_raw else owner

    disposition = str(fm.get("disposition") or DEFAULT_DISPOSITION).strip()
    if disposition not in VALID_DISPOSITIONS:
        disposition = DEFAULT_DISPOSITION

    delegated = fm.get("delegated_to") or []
    if isinstance(delegated, str):
        delegated = [delegated]

    ide_tag = str(fm.get("ide") or derive_ide_tag(rel))

    text = path.read_text(encoding="utf-8", errors="ignore")
    title = ""
    for line in text.splitlines():
        m = HEADING_RE.match(line)
        if m:
            title = m.group(1).strip()
            break
    if not title:
        title = str(fm.get("name") or path.stem)

    items = items or []
    counts = Counter(i.status for i in items)
    todos = parse_frontmatter_todos(text)
    todo_summary = compute_todo_summary(todos) if todos else None
    count_source = "todos" if todos else "body"
    stale_narrative = False
    if todos and todo_summary and todo_summary.get("total", 0) > 0:
        if todo_summary.get("completed", 0) == todo_summary["total"]:
            body_items = collect_items(path, repo_root)
            stale_narrative = any(
                it.status in {"Blocked", "In Progress", "Outstanding"} for it in body_items
            )

    branch_list = fm.get("branches") or []
    if isinstance(branch_list, str):
        branch_list = [branch_list]
    branches = [str(item).strip() for item in branch_list if str(item).strip()]
    phase_branches = parse_frontmatter_phase_branches(text)
    fm_branch = str(fm.get("branch") or "").strip()

    return PlanCard(
        slug=path.stem.replace(".plan", ""),
        title=title,
        source=rel,
        ide=ide_tag,
        owner=owner,
        dri=dri,
        disposition=disposition,
        priority=str(fm.get("priority") or "P2"),
        parent=str(fm.get("parent") or "_master"),
        delegated_to=[str(x) for x in delegated],
        is_master=bool(fm.get("isMaster") or fm.get("is_master")),
        items=items,
        counts=dict(counts),
        branch=fm_branch or "—",
        branch_source="frontmatter" if fm_branch else "none",
        branches=branches,
        phase_branches=phase_branches,
        todo_summary=todo_summary,
        count_source=count_source,
        stale_narrative=stale_narrative,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily planning audit report generator")
    parser.add_argument("--repo-root", default=".", help="Repository root")
    parser.add_argument(
        "--output-dir",
        default=".braindrain/plan-reports",
        help="Output directory for markdown reports (repo-relative if not absolute)",
    )
    parser.add_argument("--report-date", default=dt.date.today().isoformat())
    parser.add_argument("--trigger", default="cursor-stop-daily-gated")
    parser.add_argument(
        "--model-name",
        default="",
        help="Model name for provenance metadata (defaults to env lookup or auto).",
    )
    parser.add_argument(
        "--cursor-mode",
        default="",
        help="Cursor model mode for provenance metadata (auto/manual).",
    )
    parser.add_argument(
        "--trace-path",
        default=".braindrain/plan-reports/model-trace.jsonl",
        help="JSONL path for model trace events used to populate subagent model rollups.",
    )
    parser.add_argument(
        "--master-plan",
        default=None,
        help=(
            "Path to a hand-curated `_master.plan.md`. If omitted, the auditor "
            "auto-discovers it under known IDE plan dirs."
        ),
    )
    parser.add_argument(
        "--skip-archive",
        action="store_true",
        help="Do not move plans marked archived into .plan.archives/ (for tests).",
    )
    parser.add_argument(
        "--bootstrap-branches",
        action="store_true",
        help=(
            "Write branch: into plan frontmatter for active/merge-ready plans when "
            "resolved via git_local (high-confidence local git match only)."
        ),
    )
    parser.add_argument(
        "--ensure-branches",
        action="store_true",
        default=True,
        help="Create missing plan branches and write branch: frontmatter (default: on).",
    )
    parser.add_argument(
        "--no-ensure-branches",
        action="store_false",
        dest="ensure_branches",
        help="Skip automatic branch creation for active plans.",
    )
    parser.add_argument(
        "--apply-disposition-sync",
        action="store_true",
        help=(
            "Write disposition: implemented for active plans whose frontmatter "
            "todos are all completed (default: report-only)."
        ),
    )
    parser.add_argument(
        "--apply-archive",
        action="store_true",
        help=(
            "Archive READY_TO_ARCHIVE plans: move to .plan.archives/, set "
            "disposition: archived, rewrite links, update _master.plan.md "
            "(requires explicit human confirmation; default off)."
        ),
    )
    parser.add_argument(
        "--apply-overlap-relations",
        action="store_true",
        help=(
            "Write high-confidence relates_to / duplicates frontmatter for "
            "plan overlap pairs (default: report-only; hub_config can default on)."
        ),
    )
    parser.add_argument(
        "--apply-goal-tags",
        action="store_true",
        help=(
            "Write goal_tags frontmatter from alignment scoring (default: "
            "report-only; hub_config can default on)."
        ),
    )
    parser.add_argument(
        "--overlap-jaccard-threshold",
        type=float,
        default=None,
        help=(
            "Plan-level token overlap threshold (default: planning_auditor in "
            "hub_config.yaml or 0.55)."
        ),
    )
    parser.add_argument(
        "--goal-alignment-min-score",
        type=int,
        default=None,
        help=(
            "Executive-summary low-alignment threshold (default: planning_auditor "
            "in hub_config.yaml or 40)."
        ),
    )
    return parser.parse_args()


def plan_marked_archived(fm: dict[str, object]) -> bool:
    """True when frontmatter says this plan should live under ``.plan.archives/``."""
    disp = str(fm.get("disposition") or "").strip().lower()
    if disp == "archived":
        return True
    st = str(fm.get("status") or "").strip().lower()
    if st == "archived":
        return True
    arch = fm.get("archived")
    if isinstance(arch, bool):
        return arch
    if str(arch).strip().lower() in ("true", "yes", "1"):
        return True
    return False


def relocate_archived_plans(repo_root: Path) -> list[str]:
    """Move archived ``*.plan.md`` files into ``<ide>/plans/.plan.archives/``.

    A plan is archived when its own frontmatter matches `plan_marked_archived`, or
    when ``_master.plan.md`` lists it under ``archived_plans:`` or ``archive:``
    (YAML list of paths relative to that ``plans/`` directory).

    Returns repo-relative paths of files **after** the move (under ``.plan.archives/``).
    """
    moved_to: list[str] = []
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")

    for folder in KNOWN_IDE_DOTFOLDERS:
        plans_dir = repo_root / folder / "plans"
        if not plans_dir.is_dir():
            continue
        archive_dir = plans_dir / ".plan.archives"
        to_move: set[Path] = set()

        master_path = plans_dir / "_master.plan.md"
        if master_path.is_file():
            mfm = parse_plan_frontmatter(master_path)
            raw = mfm.get("archived_plans")
            if raw is None:
                raw = mfm.get("archive")
            if isinstance(raw, str):
                raw = [raw]
            if isinstance(raw, list):
                for entry in raw:
                    rel = str(entry).strip().strip('"').strip("'")
                    if not rel or rel.startswith(("/", "http://", "https://")):
                        continue
                    candidate = (plans_dir / rel).resolve()
                    try:
                        candidate.relative_to(repo_root.resolve())
                    except ValueError:
                        continue
                    if candidate.is_file() and candidate.suffix.lower() == ".md":
                        to_move.add(candidate)

        for path in sorted(plans_dir.glob("*.plan.md")):
            if path.name.startswith("_master"):
                continue
            if plan_marked_archived(parse_plan_frontmatter(path)):
                to_move.add(path.resolve())

        for src in sorted(to_move, key=lambda p: p.as_posix()):
            if not src.is_file():
                continue
            if src.name.startswith("_master"):
                continue
            try:
                rel_check = src.resolve().relative_to(plans_dir.resolve())
            except ValueError:
                continue
            if rel_check.parts[:1] == (".plan.archives",):
                continue

            archive_dir.mkdir(parents=True, exist_ok=True)
            dest = archive_dir / src.name
            if dest.exists():
                dest = archive_dir / f"{src.stem}.bak.{ts}{src.suffix}"
            shutil.move(str(src), str(dest))
            try:
                moved_to.append(dest.resolve().relative_to(repo_root.resolve()).as_posix())
            except ValueError:
                moved_to.append(dest.as_posix())

    return moved_to


def plan_archive_rel_path(repo_root: Path, plan_source: str) -> str | None:
    """Return archive location when a plan was moved under ``.plan.archives/``."""
    norm = _normalize_plan_source_path(plan_source)
    parts = norm.split("/")
    if len(parts) < 3 or parts[1] != "plans":
        return None
    archive_rel = "/".join(parts[:-1] + [".plan.archives", parts[-1]])
    candidate = repo_root / archive_rel
    return archive_rel if candidate.is_file() else None


def resolve_plan_link_path(repo_root: Path, link_rel: str) -> str | None:
    """Resolve a master/plan markdown link to an on-disk repo-relative path."""
    norm = _normalize_plan_source_path(link_rel)
    if (repo_root / norm).is_file():
        return norm
    return plan_archive_rel_path(repo_root, norm)


def master_archived_metadata_entries(master_doc: dict[str, object] | None) -> set[str]:
    """Basenames/paths listed in master ``archived_plans`` / ``archive`` metadata."""
    if not master_doc:
        return set()
    fm = master_doc.get("frontmatter") or {}
    raw = fm.get("archived_plans")
    if raw is None:
        raw = fm.get("archive")
    if isinstance(raw, str):
        raw = [raw]
    entries: set[str] = set()
    if not isinstance(raw, list):
        return entries
    for entry in raw:
        rel = str(entry).strip().strip('"').strip("'")
        if not rel:
            continue
        entries.add(rel)
        entries.add(Path(rel).name)
    return entries


def rewrite_markdown_plan_links(text: str, old_rel: str, new_rel: str) -> str:
    """Rewrite markdown links that point at a plan path (rewrite_all)."""
    old_norm = _normalize_plan_source_path(old_rel)
    new_norm = _normalize_plan_source_path(new_rel)
    old_name = Path(old_norm).name
    new_name = Path(new_norm).name
    patterns = (
        (f"]({old_norm})", f"]({new_norm})"),
        (f"](./{old_norm})", f"]({new_norm})"),
        (f"]({old_name})", f"]({new_name})"),
        (f"](/{old_norm})", f"]({new_norm})"),
    )
    out = text
    for old_pat, new_pat in patterns:
        out = out.replace(old_pat, new_pat)
    return out


def rewrite_plan_links_in_paths(
    paths: list[Path],
    old_rel: str,
    new_rel: str,
) -> list[str]:
    """Rewrite plan links inside the given files; return updated paths."""
    touched: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        current = path.read_text(encoding="utf-8", errors="ignore")
        updated = rewrite_markdown_plan_links(current, old_rel, new_rel)
        if updated != current:
            path.write_text(updated, encoding="utf-8")
            touched.append(path.as_posix())
    return touched


def prune_stale_master_body_links(
    master_path: Path,
    repo_root: Path,
    master_doc: dict[str, object],
) -> list[str]:
    """Remove broken plan bullets from master body (metadata-only archives)."""
    if not master_path.is_file():
        return []
    metadata = master_archived_metadata_entries(master_doc)
    text = master_path.read_text(encoding="utf-8", errors="ignore")
    fm_match = FRONTMATTER_BLOCK_RE.match(text)
    fm_block = fm_match.group(0) if fm_match else ""
    body_lines = text[len(fm_block) :].splitlines()
    removed: list[str] = []
    kept: list[str] = []
    for line in body_lines:
        drop = False
        for _label, target in _MD_LINK_RE.findall(line):
            target = target.strip()
            if not target.endswith(".plan.md"):
                continue
            resolved = resolve_plan_link_path(repo_root, target)
            if resolved:
                continue
            base = Path(_normalize_plan_source_path(target)).name
            if base in metadata or target in metadata:
                drop = True
                removed.append(target)
                break
        if not drop:
            kept.append(line)
    if not removed:
        return []
    master_path.write_text(fm_block + "\n".join(kept).rstrip() + "\n", encoding="utf-8")
    return removed


def _move_master_plan_between_sections(
    master_path: Path,
    repo_root: Path,
    card: PlanCard,
    old_rel: str,
    new_rel: str,
) -> None:
    """Move a plan bullet from ``## active`` (or any section) to ``## archived``."""
    text = master_path.read_text(encoding="utf-8", errors="ignore")
    fm_match = FRONTMATTER_BLOCK_RE.match(text)
    fm_block = fm_match.group(0) if fm_match else ""
    body_lines = text[len(fm_block) :].splitlines()
    master_dir = master_path.parent
    new_link = os.path.relpath(
        (repo_root / new_rel).resolve(),
        start=master_dir.resolve(),
    ).replace("\\", "/")
    old_name = Path(old_rel).name
    new_lines: list[str] = []
    for line in body_lines:
        skip_line = False
        for _label, target in _MD_LINK_RE.findall(line):
            t = target.strip()
            if t.endswith(".plan.md") and (
                _normalize_plan_source_path(t) == _normalize_plan_source_path(old_rel)
                or Path(t).name == old_name
            ):
                skip_line = True
                break
        if not skip_line:
            new_lines.append(line)
    bullet = f"- [{card.title}]({new_link}) — DRI: {card.dri}"
    header = "## archived"
    insert_at = len(new_lines)
    for idx, line in enumerate(new_lines):
        if line.strip().lower() == header:
            for j in range(idx + 1, len(new_lines)):
                if new_lines[j].startswith("## "):
                    insert_at = j
                    break
            else:
                insert_at = len(new_lines)
            break
    else:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append(header)
        new_lines.append("")
        insert_at = len(new_lines)
    new_lines.insert(insert_at, bullet)
    master_path.write_text(fm_block + "\n".join(new_lines).rstrip() + "\n", encoding="utf-8")


def _set_master_archived_plans_frontmatter(
    master_path: Path,
    plan_basenames: list[str],
) -> None:
    """Replace ``archived_plans:`` with the current archived batch (max 10)."""
    text = master_path.read_text(encoding="utf-8", errors="ignore")
    match = FRONTMATTER_BLOCK_RE.match(text)
    if not match:
        return
    body = match.group(1).splitlines()
    new_body: list[str] = []
    replaced = False
    for line in body:
        if line.startswith("archived_plans:") or line.startswith("archive:"):
            if not replaced:
                new_body.append("archived_plans:")
                for entry in plan_basenames:
                    new_body.append(f"  - {entry}")
                replaced = True
            continue
        if replaced and re.match(r"^\s+-\s+", line):
            continue
        new_body.append(line)
    if not replaced:
        new_body.append("archived_plans:")
        for entry in plan_basenames:
            new_body.append(f"  - {entry}")
    new_fm = "---\n" + "\n".join(new_body) + "\n---\n"
    rest = text[match.end() :]
    master_path.write_text(new_fm + rest, encoding="utf-8")


def _master_section_bounds(
    body_lines: list[str],
    section_name: str,
) -> tuple[int, int] | None:
    header = f"## {section_name}"
    start = None
    for idx, line in enumerate(body_lines):
        if line.strip().lower() == header.lower():
            start = idx
            break
    if start is None:
        return None
    end = len(body_lines)
    for idx in range(start + 1, len(body_lines)):
        if body_lines[idx].startswith("## "):
            end = idx
            break
    return start, end


def _replace_master_section(
    master_path: Path,
    section_name: str,
    section_lines: list[str],
) -> None:
    """Replace the body of a ``## section`` in ``_master.plan.md``."""
    text = master_path.read_text(encoding="utf-8", errors="ignore")
    fm_match = FRONTMATTER_BLOCK_RE.match(text)
    fm_block = fm_match.group(0) if fm_match else ""
    body_lines = text[len(fm_block) :].splitlines()
    bounds = _master_section_bounds(body_lines, section_name)
    if bounds is None:
        if body_lines and body_lines[-1].strip():
            body_lines.append("")
        body_lines.append(f"## {section_name}")
        body_lines.append("")
        body_lines.extend(section_lines)
    else:
        start, end = bounds
        body_lines = body_lines[: start + 1] + [""] + section_lines + body_lines[end:]
    master_path.write_text(fm_block + "\n".join(body_lines).rstrip() + "\n", encoding="utf-8")


def _is_archived_storage_path(rel_path: str) -> bool:
    return "/.plan.archives/" in rel_path.replace("\\", "/")


def discover_recent_archived_plans(
    repo_root: Path,
    *,
    limit: int = ARCHIVED_BATCH_LIMIT,
) -> list[Path]:
    """Newest archived plan files under ``<ide>/plans/.plan.archives/``."""
    paths: list[Path] = []
    for folder in KNOWN_IDE_DOTFOLDERS:
        archive_dir = repo_root / folder / "plans" / ".plan.archives"
        if archive_dir.is_dir():
            paths.extend(archive_dir.glob("*.plan.md"))
    paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return paths[:limit]


def _fetch_pr_details(
    repo_root: Path,
    branch: str,
    *,
    state: str = "open",
) -> dict[str, str] | None:
    """Return PR title/body/url/state for ``branch`` via gh, or None."""
    if not branch or branch in {"—", "-"}:
        return None
    try:
        proc = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--head",
                branch,
                "--state",
                state,
                "--json",
                "number,title,body,url,state",
                "--limit",
                "1",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        payload = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list) or not payload:
        return None
    row = payload[0]
    if not isinstance(row, dict):
        return None
    return {
        "number": str(row.get("number") or ""),
        "title": str(row.get("title") or "").strip(),
        "body": str(row.get("body") or "").strip(),
        "url": str(row.get("url") or "").strip(),
        "state": str(row.get("state") or "").strip().lower(),
    }


def _truncate_summary(text: str, limit: int = 220) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _format_archived_master_lines(
    card: PlanCard,
    rel_link: str,
    fm: dict[str, object],
    pr_details: dict[str, str] | None,
) -> list[str]:
    """Multi-line archived entry for ``_master.plan.md``."""
    summary = _truncate_summary(str(fm.get("overview") or fm.get("name") or card.title))
    lines = [
        f"- [{card.title}]({rel_link}) — DRI: {card.dri}",
        f"  - Branch: `{card.branch}`",
    ]
    if pr_details and pr_details.get("url"):
        state = pr_details.get("state") or "unknown"
        num = pr_details.get("number") or "?"
        title = pr_details.get("title") or "PR"
        url = pr_details["url"]
        lines.append(f"  - PR: [#{num} {state}]({url}) — {title}")
        pr_body = _truncate_summary(pr_details.get("body") or "", limit=180)
        if pr_body:
            lines.append(f"  - PR description: {pr_body}")
    elif card.pr not in {"—", "none"}:
        lines.append(f"  - PR: {card.pr}")
    else:
        lines.append("  - PR: none")
    lines.append(f"  - Plan summary: {summary}")
    return lines


def sync_master_archived_batch(
    repo_root: Path,
    master_path: Path,
    *,
    default_owner: str | None = None,
) -> list[str]:
    """Rewrite ``## archived`` with the latest batch (branch, PR, summary)."""
    if not master_path.is_file():
        return []

    archived_paths = discover_recent_archived_plans(repo_root)
    section_lines: list[str] = [
        f"_Last archived batch (newest first, max {ARCHIVED_BATCH_LIMIT}). "
        "Regenerated by `scripts/daily_plan_audit.py` — not the active build queue._",
        "",
    ]
    basenames: list[str] = []

    if not archived_paths:
        section_lines.append("- _No archived plans on disk._")
    else:
        archived_cards: dict[str, PlanCard] = {}
        for path in archived_paths:
            rel = path.relative_to(repo_root).as_posix()
            basenames.append(path.name)
            plan_items = collect_plan_items(path, repo_root)
            archived_cards[rel] = build_plan_card(
                path,
                repo_root,
                items=plan_items,
                default_owner=default_owner,
            )
        apply_branch_resolution(archived_cards, repo_root)
        apply_pr_resolution(archived_cards, repo_root)

        master_dir = master_path.parent
        for path in archived_paths:
            rel = path.relative_to(repo_root).as_posix()
            card = archived_cards[rel]
            fm = parse_plan_frontmatter(path)
            rel_link = os.path.relpath(
                path.resolve(),
                start=master_dir.resolve(),
            ).replace("\\", "/")
            pr_details = _fetch_pr_details(repo_root, card.branch)
            section_lines.extend(_format_archived_master_lines(card, rel_link, fm, pr_details))
            section_lines.append("")

    _replace_master_section(master_path, "archived", section_lines)
    _set_master_archived_plans_frontmatter(master_path, basenames)
    return basenames


def apply_archive_plans(
    repo_root: Path,
    ready: list[ReadyToArchive],
    cards_by_source: dict[str, PlanCard],
    *,
    master_path: Path | None,
    report_paths: list[Path],
) -> list[str]:
    """Archive READY_TO_ARCHIVE plans: move file, frontmatter, master, link rewrite."""
    archived: list[str] = []
    for entry in ready:
        card = cards_by_source.get(entry.plan_source)
        if not card:
            continue
        src_path = repo_root / entry.plan_source
        if not src_path.is_file():
            continue
        plans_dir = src_path.parent
        archive_dir = plans_dir / ".plan.archives"
        archive_dir.mkdir(parents=True, exist_ok=True)
        current = src_path.read_text(encoding="utf-8", errors="ignore")
        updated = _set_frontmatter_key(current, "disposition", "archived")
        updated = _set_frontmatter_key(updated, "archived", "true")
        src_path.write_text(updated, encoding="utf-8")
        dest = archive_dir / src_path.name
        if dest.exists():
            ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            dest = archive_dir / f"{src_path.stem}.bak.{ts}{src_path.suffix}"
        shutil.move(str(src_path), str(dest))
        old_rel = entry.plan_source
        new_rel = dest.relative_to(repo_root.resolve()).as_posix()
        card.disposition = "archived"
        card.source = new_rel
        cards_by_source[new_rel] = card
        cards_by_source.pop(old_rel, None)
        plan_paths: list[Path] = []
        for folder in KNOWN_IDE_DOTFOLDERS:
            plans_root = repo_root / folder / "plans"
            if plans_root.is_dir():
                plan_paths.extend(plans_root.rglob("*.plan.md"))
        if master_path and master_path.is_file():
            plan_paths.append(master_path)
        plan_paths.extend(report_paths)
        rewrite_plan_links_in_paths(plan_paths, old_rel, new_rel)
        archived.append(new_rel)
    if master_path and master_path.is_file() and archived:
        sync_master_archived_batch(repo_root, master_path)
    return archived


def is_secondary_doc(path: Path) -> bool:
    lowered = path.as_posix().lower()
    if "/.git/" in lowered:
        return False
    if "/.plan.archives/" in lowered:
        return False
    if "/create-subagent/" in lowered:
        return False
    if "/.braindrain/plan-reports/" in lowered:
        return False
    if "/.devdocs/" in lowered:
        return False
    if "/.cursor/agents/" in lowered:
        return False
    if "/config/templates/" in lowered:
        return False
    # Exclude IDE plan directories — they're discovered as primary sources.
    for folder in KNOWN_IDE_DOTFOLDERS:
        if f"/{folder}/plans/" in lowered or f"/{folder}/agents/" in lowered:
            return False
    if path.suffix.lower() != ".md":
        return False
    filename = path.name.lower()
    return any(
        k in filename for k in ("plan", "roadmap", "todo", "task", "backlog", "milestone", "prd")
    )


def discover_sources(
    repo_root: Path,
    *,
    ide_dotfolders: tuple[str, ...] = KNOWN_IDE_DOTFOLDERS,
) -> tuple[list[Path], list[Path]]:
    """Discover primary plan files across known IDE dotfolders + secondary docs.

    Primary plans live under ``<ide>/plans/*.plan.md``. The auditor scans
    every IDE dotfolder in ``ide_dotfolders`` so plans authored for Cursor,
    Codex, Kiro, Windsurf, etc. are all captured.

    Master plans (``_master.plan.md``) are excluded from the primary list
    because they are an index, not a workstream. Renderer reads the master
    separately via build_plan_card.
    """
    primary: list[Path] = []
    seen: set[Path] = set()
    for folder in ide_dotfolders:
        plans_dir = repo_root / folder / "plans"
        if not plans_dir.is_dir():
            continue
        for path in sorted(plans_dir.glob("*.plan.md")):
            resolved = path.resolve()
            if resolved in seen:
                continue
            if path.name.startswith("_master"):
                continue
            seen.add(resolved)
            primary.append(path)
    primary.sort(key=lambda p: p.relative_to(repo_root).as_posix())

    secondary: list[Path] = []
    for path in repo_root.rglob("*.md"):
        if is_secondary_doc(path):
            snippet = path.read_text(encoding="utf-8", errors="ignore")[:2500].lower()
            if any(k in snippet for k in PLANNING_KEYWORDS):
                secondary.append(path)
    secondary.sort()
    return primary, secondary


def discover_master_plan(
    repo_root: Path,
    *,
    ide_dotfolders: tuple[str, ...] = KNOWN_IDE_DOTFOLDERS,
) -> Path | None:
    """Find the hand-curated `_master.plan.md` if it exists.

    Search order: every IDE dotfolder in `ide_dotfolders`. First match wins.
    """
    for folder in ide_dotfolders:
        candidate = repo_root / folder / "plans" / "_master.plan.md"
        if candidate.is_file():
            return candidate
    return None


def tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if len(w) > 2 and w not in STOP_WORDS}


def extract_path_refs(text: str) -> list[str]:
    refs = set(BACKTICK_RE.findall(text))
    refs.update(PATHISH_RE.findall(text))
    cleaned = []
    for ref in refs:
        value = ref.strip().strip(".,;:()[]{}")
        if "/" in value and not value.startswith("http"):
            cleaned.append(value)
    return sorted(set(cleaned))


def classify_status(text: str, checked: str | None) -> tuple[str, str]:
    lowered = text.lower()
    if checked == "x":
        return "Implemented", "high"
    if any(k in lowered for k in ["blocked", "waiting on", "depends on", "dependency"]):
        return "Blocked", "medium"
    if any(k in lowered for k in ["in progress", "wip", "ongoing", "active"]):
        return "In Progress", "medium"
    if checked == " ":
        return "Outstanding", "high"
    if any(k in lowered for k in ["todo", "next", "open", "planned"]):
        return "Outstanding", "medium"
    return "Unknown", "low"


def collect_items(path: Path, repo_root: Path) -> list[PlanItem]:
    items: list[PlanItem] = []
    current_heading = ""
    heading_planning = False
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()

    for line in lines:
        heading_match = HEADING_RE.match(line)
        if heading_match:
            current_heading = heading_match.group(1).strip()
            heading_planning = any(k in current_heading.lower() for k in PLANNING_KEYWORDS)
            continue

        item_match = ITEM_LINE_RE.match(line)
        if not item_match:
            continue

        body = item_match.group(1).strip()
        checked: str | None = None
        checkbox = CHECKBOX_RE.match(body)
        if checkbox:
            checked = checkbox.group(1).lower()
            body = checkbox.group(2).strip()

        if len(body) < 8:
            continue

        status, confidence = classify_status(body, checked)
        if status == "Unknown" and not heading_planning and checked is None:
            continue
        path_refs = extract_path_refs(body)
        evidence: list[str] = []
        for ref in path_refs[:3]:
            resolved = (repo_root / ref).resolve()
            if resolved.exists():
                evidence.append(ref)
        if not evidence:
            evidence.append(f"{path.relative_to(repo_root).as_posix()}#{current_heading or 'item'}")

        why = f"Derived from {'checked' if checked == 'x' else 'unchecked' if checked == ' ' else 'textual'} signal."
        item = PlanItem(
            item=body,
            source=path.relative_to(repo_root).as_posix(),
            status=status,
            confidence=confidence,
            evidence=evidence,
            why=why,
            tokens=tokenize(body),
        )
        items.append(item)
    return items


TODO_ITEM_STATUS_MAP = {
    "completed": "Implemented",
    "in_progress": "In Progress",
    "pending": "Outstanding",
}


def compute_todo_summary(todos: list[dict[str, str]]) -> dict[str, int]:
    summary = {
        "total": len(todos),
        "completed": 0,
        "pending": 0,
        "in_progress": 0,
        "cancelled": 0,
    }
    for todo in todos:
        status = str(todo.get("status") or "pending").lower()
        if status == "completed":
            summary["completed"] += 1
        elif status == "in_progress":
            summary["in_progress"] += 1
        elif status == "cancelled":
            summary["cancelled"] += 1
        else:
            summary["pending"] += 1
    return summary


def plan_all_todos_completed(card: PlanCard) -> bool:
    summary = card.todo_summary
    if not summary or summary.get("total", 0) == 0:
        return False
    done = summary.get("completed", 0) + summary.get("cancelled", 0)
    return done >= summary["total"]


PHASE_BRANCH_ITEM_KEYS = ("branch", "phase", "pr", "pr_state", "note")


def parse_frontmatter_phase_branches(text: str) -> list[dict[str, str]]:
    """Parse ``phase_branches:`` list entries from plan frontmatter."""
    fm_lines: list[str] = []
    pos = 0
    while pos < len(text):
        match = FRONTMATTER_BLOCK_RE.match(text[pos:])
        if not match:
            break
        fm_lines.extend(match.group(1).splitlines())
        pos += match.end()
        remainder = text[pos:].lstrip("\n")
        if remainder.startswith("---"):
            pos = len(text) - len(remainder)
            continue
        break
    if not fm_lines:
        return []
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    in_block = False
    for raw in fm_lines:
        stripped = raw.strip()
        if not stripped:
            continue
        if re.match(r"^phase_branches:\s*$", stripped):
            in_block = True
            continue
        if not in_block:
            continue
        item_start = re.match(r"^\s*-\s+branch:\s*(.+)$", raw)
        if item_start:
            if current:
                entries.append(current)
            current = {
                "branch": _strip_quotes(item_start.group(1).strip()),
            }
            continue
        if current is None:
            if FRONTMATTER_KV_RE.match(raw):
                in_block = False
            continue
        matched_field = False
        for key in PHASE_BRANCH_ITEM_KEYS[1:]:
            field_match = re.match(rf"^\s+{key}:\s*(.+)$", raw)
            if field_match:
                current[key] = _strip_quotes(field_match.group(1).strip())
                matched_field = True
                break
        if not matched_field and FRONTMATTER_KV_RE.match(raw):
            in_block = False
            if current:
                entries.append(current)
                current = None
    if current:
        entries.append(current)
    return entries


def _infer_phase_label(branch_name: str) -> str:
    match = re.search(r"-phase([0-9]+(?:-[0-9]+)?)$", branch_name)
    if match:
        return match.group(1)
    return ""


def _plan_branch_family_prefix(card: PlanCard) -> str:
    for branch_name in card.branches or []:
        match = re.match(r"^(.*)-phase", branch_name)
        if match and match.group(1):
            return match.group(1)
    slug = card.slug.replace("_", "-")
    match = re.match(r"^(.*?)(?:-[0-9a-f]{6,}|\.plan)?$", slug)
    if match and match.group(1):
        return match.group(1).rstrip("-")
    return slug


def discover_plan_branch_registry(
    card: PlanCard,
    local_branches: list[str],
) -> list[str]:
    """Return ordered phase branch names for a multi-phase plan."""
    if card.branches:
        return list(card.branches)
    prefix = _plan_branch_family_prefix(card)
    if not prefix:
        return []
    matches = [
        branch
        for branch in local_branches
        if branch == prefix or branch.startswith(f"{prefix}-phase")
    ]

    def sort_key(name: str) -> tuple[int, str]:
        phase = _infer_phase_label(name)
        if not phase:
            return (0, name)
        head = phase.split("-", 1)[0]
        try:
            return (int(head), phase)
        except ValueError:
            return (999, phase)

    return sorted(set(matches), key=sort_key)


def _phase_branch_pr_fallback(
    branch_name: str,
    ordered_branches: list[str],
    resolved: dict[str, dict[str, str]],
) -> dict[str, str] | None:
    """When an earlier phase branch has no PR head, inherit from a later phase."""
    try:
        idx = ordered_branches.index(branch_name)
    except ValueError:
        return None
    for later in ordered_branches[idx + 1 :]:
        details = resolved.get(later)
        if details and details.get("url"):
            return {
                **details,
                "note": (
                    f"no separate PR head; inherited from `{later}` (#{details.get('number', '?')})"
                ),
            }
    return None


def build_phase_branch_records(
    repo_root: Path,
    branch_names: list[str],
    existing: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Resolve gh PR metadata for each phase branch."""
    existing_by_branch = {
        str(row.get("branch") or "").strip(): row
        for row in (existing or [])
        if str(row.get("branch") or "").strip()
    }
    resolved: dict[str, dict[str, str]] = {}
    for branch_name in branch_names:
        details = _fetch_pr_details(repo_root, branch_name, state="all")
        if details:
            resolved[branch_name] = details
    records: list[dict[str, str]] = []
    for branch_name in branch_names:
        prior = existing_by_branch.get(branch_name, {})
        details = resolved.get(branch_name)
        if not details:
            details = _phase_branch_pr_fallback(branch_name, branch_names, resolved)
        record = {
            "branch": branch_name,
            "phase": prior.get("phase") or _infer_phase_label(branch_name),
            "pr": (details or {}).get("url") or prior.get("pr") or "",
            "pr_state": (details or {}).get("state") or prior.get("pr_state") or "",
            "note": prior.get("note") or (details or {}).get("note") or "",
        }
        if details and details.get("note") and not prior.get("note"):
            record["note"] = details["note"]
        records.append(record)
    return records


def _render_phase_branches_frontmatter(records: list[dict[str, str]]) -> list[str]:
    lines = ["phase_branches:"]
    for record in records:
        lines.append(f"  - branch: {record.get('branch', '')}")
        phase = record.get("phase") or _infer_phase_label(record.get("branch", ""))
        if phase:
            lines.append(f'    phase: "{phase}"')
        pr_url = str(record.get("pr") or "").strip()
        if pr_url:
            lines.append(f"    pr: {pr_url}")
        pr_state = str(record.get("pr_state") or "").strip()
        if pr_state:
            lines.append(f"    pr_state: {pr_state}")
        note = str(record.get("note") or "").strip()
        if note:
            escaped = note.replace('"', '\\"')
            lines.append(f'    note: "{escaped}"')
    return lines


def format_plan_pr_summary(card: PlanCard) -> str:
    """Aggregate PR numbers from phase branch registry when present."""
    if not card.phase_branches:
        return card.pr
    numbers: list[int] = []
    for row in card.phase_branches:
        url = str(row.get("pr") or "")
        match = re.search(r"/pull/(\d+)", url)
        if match:
            numbers.append(int(match.group(1)))
    if not numbers:
        return card.pr
    unique = sorted(set(numbers))
    return ", ".join(f"#{num}" for num in unique)


def sync_plan_phase_branches(
    repo_root: Path,
    cards: dict[str, PlanCard],
) -> list[str]:
    """Sync ``phase_branches`` + ``branches`` frontmatter for multi-phase plans."""
    local_branches = _list_repo_branches(repo_root)
    updated: list[str] = []
    for source, card in cards.items():
        if card.is_master:
            continue
        branch_names = discover_plan_branch_registry(card, local_branches)
        if len(branch_names) < 2 and not card.branches:
            continue
        if not branch_names and card.branch and card.branch not in {"—", ""}:
            branch_names = [card.branch]
        if len(branch_names) < 2:
            continue
        path = repo_root / source
        if not path.is_file():
            continue
        current = path.read_text(encoding="utf-8", errors="ignore")
        records = build_phase_branch_records(
            repo_root,
            branch_names,
            existing=parse_frontmatter_phase_branches(current),
        )
        new_text = _set_frontmatter_yaml_block(
            current,
            "phase_branches",
            _render_phase_branches_frontmatter(records),
        )
        match = FRONTMATTER_BLOCK_RE.match(new_text)
        if match:
            fm_body = match.group(1)
            fm_body = _remove_frontmatter_scalar(fm_body, "pr")
            if branch_names != card.branches:
                branches_lines = ["branches:"] + [
                    f"  - {branch_name}" for branch_name in branch_names
                ]
                fm_body = _remove_frontmatter_block(fm_body, "branches")
                fm_body = fm_body.rstrip() + "\n" + "\n".join(branches_lines) + "\n"
            new_block = f"---\n{fm_body}---\n"
            new_text = new_block + new_text[len(match.group(0)) :]
        if new_text != current:
            path.write_text(new_text, encoding="utf-8")
            updated.append(source)
        card.branches = branch_names
        card.phase_branches = records
        card.pr = format_plan_pr_summary(card)
        card.pr_source = "phase_branches"
    return updated


def append_plan_branch_registry(
    repo_root: Path,
    plan_source: str,
    branch_name: str,
) -> bool:
    """Append a newly created phase branch to plan ``branches:`` registry."""
    path = repo_root / plan_source
    if not path.is_file() or not branch_name:
        return False
    current = path.read_text(encoding="utf-8", errors="ignore")
    fm = parse_plan_frontmatter(current)
    branches = fm.get("branches") or []
    if isinstance(branches, str):
        branches = [branches]
    branch_list = [str(item).strip() for item in branches if str(item).strip()]
    if branch_name in branch_list:
        return False
    branch_list.append(branch_name)
    match = FRONTMATTER_BLOCK_RE.match(current)
    if not match:
        return False
    fm_body = match.group(1)
    fm_body = _remove_frontmatter_block(fm_body, "branches")
    branches_lines = ["branches:"] + [f"  - {name}" for name in branch_list]
    fm_body = fm_body.rstrip() + "\n" + "\n".join(branches_lines) + "\n"
    new_block = f"---\n{fm_body}---\n"
    new_text = new_block + current[len(match.group(0)) :]
    if new_text == current:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def items_from_todos(
    path: Path,
    repo_root: Path,
    todos: list[dict[str, str]],
) -> list[PlanItem]:
    """Build PlanItem rows from frontmatter todos (status histogram source)."""
    rel = path.relative_to(repo_root).as_posix()
    items: list[PlanItem] = []
    for todo in todos:
        todo_id = str(todo.get("id") or "todo").strip() or "todo"
        raw_status = str(todo.get("status") or "pending").lower()
        if raw_status == "cancelled":
            continue
        status = TODO_ITEM_STATUS_MAP.get(raw_status, "Unknown")
        body = str(todo.get("content") or todo_id).strip() or todo_id
        confidence = "high" if raw_status in {"completed", "pending"} else "medium"
        items.append(
            PlanItem(
                item=body,
                source=rel,
                status=status,
                confidence=confidence,
                evidence=[f"{rel}#todo:{todo_id}"],
                why=f"Derived from frontmatter todo `{todo_id}` status `{raw_status}`.",
                tokens=tokenize(body),
            )
        )
    return items


def collect_plan_items(path: Path, repo_root: Path) -> list[PlanItem]:
    """Collect plan items: frontmatter todos when present, else body bullets."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    todos = parse_frontmatter_todos(text)
    if todos:
        return items_from_todos(path, repo_root, todos)
    return collect_items(path, repo_root)


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def detect_overlaps(items: list[PlanItem]) -> list[dict[str, str]]:
    overlaps: list[dict[str, str]] = []
    for idx, a in enumerate(items):
        for b in items[idx + 1 :]:
            if a.source == b.source:
                continue
            score = jaccard(a.tokens, b.tokens)
            if score < 0.55:
                continue
            severity = "high" if a.status != b.status else "medium"
            overlaps.append(
                {
                    "item_a": a.item,
                    "source_a": a.source,
                    "item_b": b.item,
                    "source_b": b.source,
                    "similarity": f"{score:.2f}",
                    "severity": severity,
                }
            )
    overlaps.sort(key=lambda x: (x["severity"] != "high", -float(x["similarity"])))
    return overlaps


PLAN_RELATION_KEYS = ("supersedes", "duplicates", "relates_to", "blocks")
GOAL_SECTION_HEADING_RE = re.compile(
    r"^\s*#{1,3}\s+(goals|success criteria|objectives)\b",
    re.IGNORECASE,
)
STAGE_HEADING_RE = re.compile(r"^\s*##\s+Stage\s+\d+", re.IGNORECASE)
DEFAULT_GOAL_ALIGNMENT_MIN_SCORE = 40
DEFAULT_OVERLAP_JACCARD_THRESHOLD = 0.55

PLANNING_AUDITOR_DEFAULTS: dict[str, object] = {
    "overlap_jaccard_threshold": DEFAULT_OVERLAP_JACCARD_THRESHOLD,
    "apply_overlap_relations": False,
    "apply_goal_tags": False,
    "goal_alignment_min_score": DEFAULT_GOAL_ALIGNMENT_MIN_SCORE,
}


def _resolve_hub_config_path(repo_root: Path) -> Path | None:
    env_path = os.environ.get("BRAINDRAIN_CONFIG", "").strip()
    if env_path:
        candidate = Path(env_path).expanduser()
        if candidate.is_file():
            return candidate
    hub_default = repo_root / "config" / "hub_config.yaml"
    if hub_default.is_file():
        return hub_default
    return None


def load_planning_auditor_config(repo_root: Path) -> dict[str, object]:
    """Load ``planning_auditor`` block from hub_config (safe defaults if missing)."""
    settings = dict(PLANNING_AUDITOR_DEFAULTS)
    config_path = _resolve_hub_config_path(repo_root)
    if not config_path:
        return settings
    try:
        import yaml
    except ImportError:
        return settings
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except OSError:
        return settings
    block = raw.get("planning_auditor")
    if not isinstance(block, dict):
        return settings
    if "overlap_jaccard_threshold" in block:
        settings["overlap_jaccard_threshold"] = float(block["overlap_jaccard_threshold"])
    if "apply_overlap_relations" in block:
        settings["apply_overlap_relations"] = bool(block["apply_overlap_relations"])
    if "apply_goal_tags" in block:
        settings["apply_goal_tags"] = bool(block["apply_goal_tags"])
    if "goal_alignment_min_score" in block:
        settings["goal_alignment_min_score"] = int(block["goal_alignment_min_score"])
    return settings


def resolve_planning_auditor_runtime(
    args: argparse.Namespace,
    repo_root: Path,
) -> dict[str, object]:
    """Merge hub_config defaults with explicit CLI flags (CLI wins when set)."""
    runtime = load_planning_auditor_config(repo_root)
    if getattr(args, "overlap_jaccard_threshold", None) is not None:
        runtime["overlap_jaccard_threshold"] = float(args.overlap_jaccard_threshold)
    if getattr(args, "goal_alignment_min_score", None) is not None:
        runtime["goal_alignment_min_score"] = int(args.goal_alignment_min_score)
    if getattr(args, "apply_overlap_relations", False):
        runtime["apply_overlap_relations"] = True
    if getattr(args, "apply_goal_tags", False):
        runtime["apply_goal_tags"] = True
    return runtime


@dataclasses.dataclass
class PlanOverlapEdge:
    """Plan-level overlap signal between two active plans."""

    source_a: str
    source_b: str
    signal: str
    severity: str
    detail: str
    similarity: float = 0.0

    def to_dict(self) -> dict[str, str]:
        return {
            "source_a": self.source_a,
            "source_b": self.source_b,
            "signal": self.signal,
            "severity": self.severity,
            "detail": self.detail,
            "similarity": f"{self.similarity:.2f}" if self.similarity else "",
        }


@dataclasses.dataclass
class PlanGoalAlignment:
    """Goal-alignment score for an active plan."""

    source: str
    slug: str
    title: str
    goal_tags: list[str]
    alignment_score: int
    unaligned_risk: str


class _UnionFind:
    def __init__(self, nodes: list[str]) -> None:
        self.parent = {n: n for n in nodes}

    def find(self, node: str) -> str:
        while self.parent[node] != node:
            self.parent[node] = self.parent[self.parent[node]]
            node = self.parent[node]
        return node

    def union(self, left: str, right: str) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left != root_right:
            self.parent[root_right] = root_left

    def clusters(self) -> list[list[str]]:
        groups: dict[str, list[str]] = defaultdict(list)
        for node in self.parent:
            groups[self.find(node)].append(node)
        return [sorted(group) for group in groups.values() if len(group) > 1]


def _frontmatter_relation_values(fm: dict[str, object], key: str) -> list[str]:
    raw = fm.get(key)
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    value = str(raw).strip()
    return [value] if value else []


def _resolve_plan_relation_target(
    target: str,
    from_source: str,
    repo_root: Path,
) -> list[str]:
    target = target.strip()
    if not target:
        return []
    plans_dir = (repo_root / Path(from_source).parent).resolve()
    candidates = [
        (plans_dir / target).resolve(),
        (repo_root / target).resolve(),
    ]
    found: list[str] = []
    for candidate in candidates:
        try:
            rel = candidate.relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            continue
        if rel.endswith(".plan.md"):
            found.append(rel)
    if found:
        return found
    base = Path(target).name
    for folder in KNOWN_IDE_DOTFOLDERS:
        plans_dir = repo_root / folder / "plans"
        if not plans_dir.is_dir():
            continue
        for path in plans_dir.rglob(base):
            if path.is_file():
                found.append(path.relative_to(repo_root).as_posix())
    return found


def _is_overlap_eligible(card: PlanCard) -> bool:
    return not card.is_master and card.is_active_for_triage


def _collect_plan_path_refs(items: list[PlanItem], source: str) -> set[str]:
    active_statuses = {"Outstanding", "In Progress", "Blocked"}
    refs: set[str] = set()
    for item in items:
        if item.source != source or item.status not in active_statuses:
            continue
        for evidence in item.evidence:
            if "/" in evidence and not evidence.startswith("http"):
                refs.add(evidence.split("#", 1)[0])
        refs.update(extract_path_refs(item.item))
    return refs


def _aggregate_plan_tokens(items: list[PlanItem], source: str) -> set[str]:
    tokens: set[str] = set()
    for item in items:
        if item.source == source:
            tokens.update(item.tokens)
    return tokens


def _titles_align(card_a: PlanCard, card_b: PlanCard) -> bool:
    left = tokenize(card_a.title)
    right = tokenize(card_b.title)
    if not left or not right:
        return False
    return jaccard(left, right) >= 0.4


def detect_plan_overlaps(
    cards_by_source: dict[str, PlanCard],
    items: list[PlanItem],
    *,
    repo_root: Path,
    jaccard_threshold: float = 0.55,
) -> tuple[list[PlanOverlapEdge], list[list[str]]]:
    """Detect plan-level overlap via paths, tokens, branches, and relations."""
    eligible = {
        source: card for source, card in cards_by_source.items() if _is_overlap_eligible(card)
    }
    sources = sorted(eligible.keys())
    seen: set[tuple[str, str, str]] = set()
    edges: list[PlanOverlapEdge] = []

    def add_edge(
        left: str,
        right: str,
        signal: str,
        severity: str,
        detail: str,
        *,
        similarity: float = 0.0,
    ) -> None:
        if left == right:
            return
        pair = (left, right) if left <= right else (right, left)
        dedupe_key = (pair[0], pair[1], signal)
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
        edges.append(
            PlanOverlapEdge(
                pair[0],
                pair[1],
                signal,
                severity,
                detail,
                similarity=similarity,
            )
        )

    paths_by_source = {source: _collect_plan_path_refs(items, source) for source in sources}
    for idx, source_a in enumerate(sources):
        for source_b in sources[idx + 1 :]:
            shared = paths_by_source[source_a] & paths_by_source[source_b]
            if shared:
                sample = ", ".join(sorted(shared)[:3])
                add_edge(
                    source_a,
                    source_b,
                    "path",
                    "high",
                    f"shared paths: {sample}",
                )

    tokens_by_source = {source: _aggregate_plan_tokens(items, source) for source in sources}
    for idx, source_a in enumerate(sources):
        for source_b in sources[idx + 1 :]:
            score = jaccard(tokens_by_source[source_a], tokens_by_source[source_b])
            if score >= jaccard_threshold:
                severity = "high" if score >= 0.75 else "medium"
                add_edge(
                    source_a,
                    source_b,
                    "token",
                    severity,
                    f"plan-level token jaccard={score:.2f}",
                    similarity=score,
                )

    branch_map: dict[str, list[str]] = defaultdict(list)
    for source, card in eligible.items():
        if card.branch and card.branch not in ("—", ""):
            branch_map[card.branch].append(source)
    for branch, branch_sources in branch_map.items():
        if len(branch_sources) < 2:
            continue
        ordered = sorted(branch_sources)
        for idx, source_a in enumerate(ordered):
            for source_b in ordered[idx + 1 :]:
                add_edge(
                    source_a,
                    source_b,
                    "branch",
                    "high",
                    f"identical branch `{branch}`",
                )

    for source, card in eligible.items():
        path = repo_root / source
        if not path.is_file():
            continue
        fm = parse_plan_frontmatter(path)
        for target in _frontmatter_relation_values(fm, "supersedes"):
            for other in _resolve_plan_relation_target(target, source, repo_root):
                if other in eligible and other != source:
                    add_edge(
                        source,
                        other,
                        "supersedes",
                        "informational",
                        f"`{card.slug}` supersedes `{Path(other).stem}`",
                    )

    union_find = _UnionFind(sources)
    for edge in edges:
        if edge.severity in {"high", "medium"}:
            union_find.union(edge.source_a, edge.source_b)
    clusters = union_find.clusters()
    edges.sort(
        key=lambda edge: (
            edge.severity == "informational",
            edge.severity == "medium",
            -edge.similarity,
            edge.source_a,
            edge.source_b,
        )
    )
    return edges, clusters


def _append_frontmatter_list_value(text: str, key: str, value: str) -> str:
    """Append a list item under ``key`` without overwriting existing relation keys."""
    match = FRONTMATTER_BLOCK_RE.match(text)
    if not match:
        return f"---\n{key}:\n  - {value}\n---\n\n{text}"
    fm_body = match.group(1)
    fm = _parse_frontmatter_body(fm_body)
    existing = _frontmatter_relation_values(fm, key)
    if value in existing or any(Path(item).name == Path(value).name for item in existing):
        return text
    if key not in fm:
        updated_body = fm_body.rstrip() + f"\n{key}:\n  - {value}\n"
    elif isinstance(fm.get(key), str) and str(fm.get(key)).strip():
        old = str(fm[key]).strip()
        updated_body = re.sub(
            rf"(?m)^{re.escape(key)}\s*:\s*.+$",
            f"{key}:\n  - {old}\n  - {value}",
            fm_body,
            count=1,
        )
    else:
        lines = fm_body.splitlines()
        insert_at = len(lines)
        in_key = False
        for idx, line in enumerate(lines):
            if re.match(rf"^{re.escape(key)}\s*:\s*$", line.strip()):
                in_key = True
                continue
            if in_key and line and not line.startswith((" ", "-")):
                insert_at = idx
                break
        lines.insert(insert_at, f"  - {value}")
        updated_body = "\n".join(lines)
        if not updated_body.endswith("\n"):
            updated_body += "\n"
    new_block = f"---\n{updated_body}---\n"
    return new_block + text[len(match.group(0)) :]


def apply_overlap_relations(
    repo_root: Path,
    cards_by_source: dict[str, PlanCard],
    edges: list[PlanOverlapEdge],
    *,
    duplicate_similarity: float = 0.75,
) -> list[str]:
    """Opt-in write-back for high-confidence plan overlap relations."""
    updated: list[str] = []
    for edge in edges:
        if edge.severity not in {"high", "medium"}:
            continue
        card_a = cards_by_source.get(edge.source_a)
        card_b = cards_by_source.get(edge.source_b)
        if not card_a or not card_b:
            continue
        use_duplicates = (
            edge.signal == "token"
            and edge.similarity >= duplicate_similarity
            and _titles_align(card_a, card_b)
        )
        relation_key = "duplicates" if use_duplicates else "relates_to"
        for source, other_source in (
            (edge.source_a, edge.source_b),
            (edge.source_b, edge.source_a),
        ):
            if edge.signal == "path" or edge.signal == "branch" or edge.signal == "token":
                pass
            else:
                continue
            path = repo_root / source
            if not path.is_file():
                continue
            current = path.read_text(encoding="utf-8", errors="ignore")
            fm = parse_plan_frontmatter(current)
            if _frontmatter_relation_values(fm, "supersedes"):
                continue
            if _frontmatter_relation_values(fm, "duplicates"):
                continue
            if use_duplicates and _frontmatter_relation_values(fm, "duplicates"):
                continue
            other_name = Path(other_source).name
            if relation_key == "relates_to":
                if any(
                    Path(item).name == other_name
                    for item in _frontmatter_relation_values(fm, "relates_to")
                ):
                    continue
            key = relation_key
            new_text = _append_frontmatter_list_value(current, key, other_name)
            if new_text != current:
                path.write_text(new_text, encoding="utf-8")
                if source not in updated:
                    updated.append(source)
    return updated


def apply_goal_tags(
    repo_root: Path,
    cards_by_source: dict[str, PlanCard],
    alignments: list[PlanGoalAlignment],
) -> list[str]:
    """Opt-in write-back for goal_tags on active plans with alignment matches."""
    updated: list[str] = []
    by_source = {row.source: row for row in alignments}
    for source, card in cards_by_source.items():
        if card.disposition not in {"active", "merge-ready", "needs-fix", "research-needed"}:
            continue
        row = by_source.get(source)
        if not row or not row.goal_tags:
            continue
        path = repo_root / source
        if not path.is_file():
            continue
        current = path.read_text(encoding="utf-8", errors="ignore")
        fm = parse_plan_frontmatter(current)
        existing = _frontmatter_relation_values(fm, "goal_tags")
        if existing:
            continue
        new_text = current
        for tag in row.goal_tags[:3]:
            new_text = _append_frontmatter_list_value(new_text, "goal_tags", tag)
        if new_text != current:
            path.write_text(new_text, encoding="utf-8")
            updated.append(source)
    return updated


def render_overlap_clusters_section(
    edges: list[PlanOverlapEdge],
    clusters: list[list[str]],
    cards_by_source: dict[str, PlanCard],
) -> list[str]:
    lines = ["## Overlap clusters", ""]
    if not edges and not clusters:
        lines.append("- _No plan-level overlaps detected._")
        lines.append("")
        return lines
    if clusters:
        lines.append("### Clusters")
        for idx, cluster in enumerate(clusters, start=1):
            labels = []
            for source in cluster:
                card = cards_by_source.get(source)
                labels.append(card.slug if card else Path(source).stem)
            lines.append(f"- Cluster {idx}: " + ", ".join(f"`{label}`" for label in labels))
        lines.append("")
    lines.append("### Pairs")
    if not edges:
        lines.append("- _None_")
    else:
        for edge in edges[:25]:
            sim = f", similarity={edge.similarity:.2f}" if edge.similarity else ""
            lines.append(
                f"- `{edge.source_a}` <-> `{edge.source_b}` "
                f"({edge.signal}, {edge.severity}{sim}): {edge.detail}"
            )
    lines.append("")
    return lines


def render_overlap_relations_markdown(
    report_date: str,
    edges: list[PlanOverlapEdge],
    clusters: list[list[str]],
    cards_by_source: dict[str, PlanCard],
) -> str:
    lines = [
        "# Overlap relations",
        "",
        f"_Generated {report_date} by `scripts/daily_plan_audit.py`. "
        "Report-only by default; use `--apply-overlap-relations` to write "
        "high-confidence `relates_to` / `duplicates` frontmatter._",
        "",
    ]
    lines.extend(render_overlap_clusters_section(edges, clusters, cards_by_source))
    return "\n".join(lines)


def load_goal_context(
    repo_root: Path,
    master_doc: dict[str, object] | None = None,
) -> dict[str, object]:
    """Load goal lines from PRD, TASK-GRAPH, intake JSON, and master goalposts."""
    goals: list[str] = []
    sources: list[str] = []

    prd_path = repo_root / ".cursor" / "PRD.md"
    if prd_path.is_file():
        prd_text = prd_path.read_text(encoding="utf-8", errors="ignore")
        in_goal_section = False
        for line in prd_text.splitlines():
            if GOAL_SECTION_HEADING_RE.match(line):
                in_goal_section = True
                goals.append(line.lstrip("#").strip())
                continue
            if in_goal_section:
                if re.match(r"^\s*#{1,3}\s+", line) and not GOAL_SECTION_HEADING_RE.match(line):
                    in_goal_section = False
                    continue
                bullet = ITEM_LINE_RE.match(line)
                if bullet:
                    goals.append(bullet.group(1).strip())
        if goals:
            sources.append(".cursor/PRD.md")

    task_graph_path = repo_root / ".cursor" / "TASK-GRAPH.md"
    if task_graph_path.is_file():
        stage_lines = [
            line.lstrip("#").strip()
            for line in task_graph_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            if STAGE_HEADING_RE.match(line)
        ]
        if stage_lines:
            goals.extend(stage_lines)
            sources.append(".cursor/TASK-GRAPH.md")

    project_context_path = repo_root / ".cursor" / "project-context.json"
    if project_context_path.is_file():
        try:
            payload = json.loads(project_context_path.read_text(encoding="utf-8"))
            added = False
            for key in ("goals", "success_criteria"):
                raw = payload.get(key)
                if isinstance(raw, list):
                    goals.extend(str(item).strip() for item in raw if str(item).strip())
                    added = True
                elif isinstance(raw, str) and raw.strip():
                    goals.append(raw.strip())
                    added = True
            if added:
                sources.append(".cursor/project-context.json")
        except (json.JSONDecodeError, OSError):
            pass

    master_doc = master_doc or {}
    frontmatter = master_doc.get("frontmatter") or {}
    goalposts = frontmatter.get("goalposts")
    if isinstance(goalposts, list):
        posted = [str(item).strip() for item in goalposts if str(item).strip()]
        if posted:
            goals.extend(posted)
            sources.append("_master.plan.md:goalposts")

    seen: set[str] = set()
    unique_goals: list[str] = []
    for goal in goals:
        normalized = goal.strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            unique_goals.append(normalized)
    return {"goals": unique_goals, "sources": sources}


def score_plan_goal_alignment(card: PlanCard, goal_lines: list[str]) -> PlanGoalAlignment:
    if not goal_lines:
        return PlanGoalAlignment(
            source=card.source,
            slug=card.slug,
            title=card.title,
            goal_tags=[],
            alignment_score=0,
            unaligned_risk="unknown",
        )
    plan_text = card.title + " " + " ".join(item.item for item in card.items)
    plan_tokens = tokenize(plan_text)
    scored: list[tuple[str, float]] = []
    for goal in goal_lines:
        goal_tokens = tokenize(goal)
        if not goal_tokens:
            continue
        scored.append((goal, jaccard(plan_tokens, goal_tokens)))
    scored.sort(key=lambda pair: -pair[1])
    top_matches = scored[:3]
    goal_tags = [goal for goal, score in top_matches if score > 0]
    best_score = top_matches[0][1] if top_matches else 0.0
    alignment_score = int(round(best_score * 100))
    if alignment_score >= 70:
        risk = "low"
    elif alignment_score >= DEFAULT_GOAL_ALIGNMENT_MIN_SCORE:
        risk = "medium"
    else:
        risk = "high"
    return PlanGoalAlignment(
        source=card.source,
        slug=card.slug,
        title=card.title,
        goal_tags=goal_tags[:3],
        alignment_score=alignment_score,
        unaligned_risk=risk,
    )


def compute_goal_alignments(
    cards_by_source: dict[str, PlanCard],
    goal_context: dict[str, object],
) -> list[PlanGoalAlignment]:
    goal_lines = list(goal_context.get("goals") or [])
    alignments: list[PlanGoalAlignment] = []
    for card in cards_by_source.values():
        if card.is_master or not card.is_active_for_triage:
            continue
        if card.disposition in {"scratched", "implemented", "archived", "backlogged"}:
            continue
        alignments.append(score_plan_goal_alignment(card, goal_lines))
    alignments.sort(key=lambda row: (row.alignment_score, row.slug))
    return alignments


def render_goal_alignment_section(
    alignments: list[PlanGoalAlignment],
    goal_context: dict[str, object],
) -> list[str]:
    lines = ["## Goal alignment", ""]
    sources = list(goal_context.get("sources") or [])
    if sources:
        lines.append("_Goal sources: " + ", ".join(f"`{source}`" for source in sources) + "_")
        lines.append("")
    if not alignments:
        lines.append("- _No active plans to score._")
        lines.append("")
        return lines
    lines.extend(
        [
            "| Plan | Goal tags | Score | Unaligned risk |",
            "|------|-----------|------:|----------------|",
        ]
    )
    for row in sorted(alignments, key=lambda item: item.alignment_score):
        tags = ", ".join(row.goal_tags[:3]) if row.goal_tags else "—"
        if len(tags) > 72:
            tags = tags[:69] + "..."
        title_cell = row.title.replace("|", "\\|")
        lines.append(
            f"| [{title_cell}]({row.source}) | {tags} | {row.alignment_score} | {row.unaligned_risk} |"
        )
    lines.append("")
    return lines


# Item-level delegation marker: `delegate:` followed by a non-empty target.
# Used to detect "agent says they're handing this off but didn't say to whom".
DELEGATION_DECLARED_RE = re.compile(r"\bdelegate(?:d_to|s_to|s|d)?\s*:", re.IGNORECASE)
DELEGATION_TARGETED_RE = re.compile(
    r"\bdelegate(?:d_to|s_to|s|d)?\s*:\s*(?P<target>[A-Za-z@][A-Za-z0-9@_.-]{1,64})",
    re.IGNORECASE,
)


def has_unresolved_delegation(text: str) -> bool:
    """True when an item declares `delegate:` without a non-empty target."""
    if not DELEGATION_DECLARED_RE.search(text):
        return False
    match = DELEGATION_TARGETED_RE.search(text)
    if not match:
        return True
    target = match.group("target").strip(" .,;:)]}")
    return not target


def detect_gaps(
    items: list[PlanItem],
    *,
    cards_by_source: dict[str, PlanCard] | None = None,
) -> list[dict[str, str]]:
    """Detect missing-signal gaps for active items.

    When ``cards_by_source`` is provided, items inherit ownership from their
    parent plan: an item without an `@name` is *not* flagged as missing
    `explicit_owner` if its plan declares a non-default owner. Items that
    declare delegation (`delegate:`) without a target raise the new
    ``delegation_unresolved`` signal regardless of plan ownership.
    """
    cards_by_source = cards_by_source or {}
    gaps: list[dict[str, str]] = []
    for item in items:
        if item.status not in {"Outstanding", "In Progress", "Blocked"}:
            continue
        lowered = item.item.lower()
        has_owner = has_explicit_owner(item.item)
        plan_card = cards_by_source.get(item.source)
        plan_has_owner = bool(plan_card and plan_card.owner and plan_card.owner != "@user")
        has_test_hint = "test" in lowered
        has_path_evidence = any("/" in ev for ev in item.evidence)
        missing: list[str] = []
        if not has_owner and not plan_has_owner:
            missing.append("explicit_owner")
        if has_unresolved_delegation(item.item):
            missing.append("delegation_unresolved")
        if not has_test_hint:
            missing.append("test")
        if not has_path_evidence:
            missing.append("evidence")
        if missing:
            risk = "high" if item.status == "Blocked" else "medium"
            gaps.append(
                {
                    "item": item.item,
                    "source": item.source,
                    "missing": ", ".join(missing),
                    "risk": risk,
                }
            )
    gaps.sort(key=lambda x: (x["risk"] != "high", x["missing"]))
    return gaps


# Priority ordering used by next-actions sort.
_PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
# Verbs in the order they appear in the triage queue.
_VERB_ORDER = (
    "MERGE",  # ship now
    "FIX",  # broken regressions
    "REPLAN",  # needs rewrite before more work
    "RESEARCH",  # unblock with investigation
    "SPLIT",  # meta plan → child plan files
    "IMPLEMENT",  # active work missing tests/evidence
    "BACKLOG",  # surfaced only for high-priority deferred plans
)


def _first_active_item_excerpt(card: PlanCard) -> str:
    for it in card.items:
        if it.status in {"Blocked", "In Progress", "Outstanding"}:
            text = it.item.replace("\n", " ").strip()
            if len(text) > 140:
                text = text[:137] + "..."
            return text
    return ""


def meta_plan_missing_child_files(card: PlanCard, repo_root: Path) -> list[str]:
    """Return child plan filenames from ``children_spec`` that are not on disk."""
    plan_path = repo_root / card.source
    if not plan_path.is_file():
        return []
    text = plan_path.read_text(encoding="utf-8", errors="ignore")
    specs = parse_frontmatter_children_spec(text)
    if not specs:
        return ["<children_spec missing>"]
    plans_dir = plan_path.parent
    missing: list[str] = []
    for spec in specs:
        child_file = str(spec.get("file") or "").strip()
        if child_file and not (plans_dir / child_file).is_file():
            missing.append(child_file)
    return missing


def detect_actions(
    cards: list[PlanCard],
    *,
    repo_root: Path | None = None,
    backlog_priority_threshold: str = "P1",
) -> list[Action]:
    """Translate plan dispositions + item signals into concrete next-action verbs.

    Rules:
    - ``meta`` + missing child files -> SPLIT
    - ``research-needed`` -> RESEARCH
    - ``replan-needed``   -> REPLAN
    - ``merge-ready``     -> MERGE
    - ``needs-fix``       -> FIX
    - ``backlogged``      -> BACKLOG (only when priority <= threshold; default P1)
    - ``active`` + has any blocked/outstanding/in-progress item lacking a test
      hint -> IMPLEMENT (with the first such item as ``item_excerpt``)
    - ``scratched`` / ``implemented`` -> excluded.
    """
    threshold = _PRIORITY_RANK.get(backlog_priority_threshold, 1)
    actions: list[Action] = []
    for card in cards:
        if not card.is_active_for_triage:
            continue
        verb = DISPOSITION_VERB.get(card.disposition)
        excerpt = _first_active_item_excerpt(card)

        if card.disposition == "meta" and repo_root is not None:
            missing = meta_plan_missing_child_files(card, repo_root)
            plan_path = repo_root / card.source
            todos = (
                parse_frontmatter_todos(plan_path.read_text(encoding="utf-8", errors="ignore"))
                if plan_path.is_file()
                else []
            )
            pending_split = any(
                todo.get("id", "").startswith("split-")
                and todo.get("status", "pending") != "completed"
                for todo in todos
            )
            if missing or pending_split:
                hint_files = ", ".join(missing[:5])
                if len(missing) > 5:
                    hint_files += f" (+{len(missing) - 5} more)"
                actions.append(
                    Action(
                        verb="SPLIT",
                        plan_slug=card.slug,
                        plan_source=card.source,
                        ide=card.ide or "—",
                        title=card.title,
                        reason="meta plan missing child plan files",
                        hint=(
                            f"run /metaplan-closeout; missing: {hint_files}"
                            if missing
                            else "run /metaplan-closeout to finish child plan bodies"
                        ),
                        priority=card.priority,
                        item_excerpt=excerpt,
                    )
                )
            continue

        if card.disposition == "active":
            if plan_all_todos_completed(card):
                continue
            has_active_item = any(
                it.status in {"Blocked", "In Progress", "Outstanding"} for it in card.items
            )
            if has_active_item:
                missing_test = any(
                    "test" not in it.item.lower()
                    for it in card.items
                    if it.status in {"Blocked", "In Progress", "Outstanding"}
                )
                actions.append(
                    Action(
                        verb="IMPLEMENT",
                        plan_slug=card.slug,
                        plan_source=card.source,
                        ide=card.ide or "—",
                        title=card.title,
                        reason="active plan with open work",
                        hint=(
                            "add tests + evidence; ship the next item"
                            if missing_test
                            else "ship the next item"
                        ),
                        priority=card.priority,
                        item_excerpt=excerpt,
                    )
                )
            continue

        if verb == "BACKLOG":
            rank = _PRIORITY_RANK.get(card.priority, 3)
            if rank > threshold:
                continue

        if not verb:
            continue

        reason = {
            "RESEARCH": "needs investigation before commit",
            "REPLAN": "design has drifted; rewrite required",
            "MERGE": "implemented; ready to ship",
            "FIX": "implemented but broken/regressed",
            "BACKLOG": "deferred but priority-elevated",
            "SPLIT": "meta plan needs child plan files",
        }[verb]
        hint = {
            "RESEARCH": "answer the open question(s); update plan with findings",
            "REPLAN": "rewrite the plan; archive the old version",
            "MERGE": "open PR; pass CI; merge",
            "FIX": "reproduce regression; ship fix; add regression test",
            "BACKLOG": "decide: promote to active or scratch",
            "SPLIT": "run /metaplan-closeout; then Build on one child plan",
        }[verb]

        actions.append(
            Action(
                verb=verb,
                plan_slug=card.slug,
                plan_source=card.source,
                ide=card.ide or "—",
                title=card.title,
                reason=reason,
                hint=hint,
                priority=card.priority,
                item_excerpt=excerpt,
            )
        )

    actions.sort(
        key=lambda a: (
            _VERB_ORDER.index(a.verb) if a.verb in _VERB_ORDER else 99,
            _PRIORITY_RANK.get(a.priority, 3),
            a.ide,
            a.plan_slug,
        )
    )
    return actions


def detect_ready_to_archive(
    cards: list[PlanCard],
    *,
    include_implemented: bool = False,
) -> list[ReadyToArchive]:
    """Plans with all todos completed that should leave the active queue.

    Report mode (default): ``disposition: active`` only.
    Apply-archive mode: also ``implemented`` plans not yet under ``.plan.archives/``.
    """
    ready: list[ReadyToArchive] = []
    for card in cards:
        if card.is_master or card.disposition in {"archived", "scratched"}:
            continue
        if card.disposition == "active":
            pass
        elif include_implemented and card.disposition == "implemented":
            pass
        else:
            continue
        if not plan_all_todos_completed(card):
            continue
        if card.disposition == "active":
            reason = "all todos completed; disposition still active"
        else:
            reason = "all todos completed; disposition implemented — ready for archive"
        if card.stale_narrative:
            reason += "; stale narrative in body"
        ready.append(
            ReadyToArchive(
                plan_slug=card.slug,
                plan_source=card.source,
                ide=card.ide or "—",
                priority=card.priority,
                reason=reason,
                stale_narrative=card.stale_narrative,
            )
        )
    ready.sort(key=lambda r: (_PRIORITY_RANK.get(r.priority, 3), r.ide, r.plan_slug))
    return ready


def apply_disposition_sync(
    repo_root: Path,
    cards: dict[str, PlanCard],
) -> list[str]:
    """Set ``disposition: implemented`` when all todos are completed."""
    updated: list[str] = []
    for rel, card in cards.items():
        if card.is_master or card.disposition != "active":
            continue
        if not plan_all_todos_completed(card):
            continue
        path = repo_root / rel
        if not path.is_file():
            continue
        current = path.read_text(encoding="utf-8", errors="ignore")
        new_text = _set_frontmatter_key(current, "disposition", "implemented")
        if new_text != current:
            path.write_text(new_text, encoding="utf-8")
            card.disposition = "implemented"
            updated.append(rel)
    return updated


def render_ready_to_archive_section(
    entries: list[ReadyToArchive],
    *,
    report_date: str = "",
) -> list[str]:
    """Markdown lines for the READY_TO_ARCHIVE triage section."""
    lines: list[str] = ["## READY_TO_ARCHIVE (confirm with user)"]
    if report_date:
        lines.append("")
        lines.append(
            f"_Generated {report_date}. Run with `--apply-disposition-sync` and "
            "`--apply-archive` only after you confirm this list._"
        )
    lines.append("")
    if not entries:
        lines.append("- _None today._")
        lines.append("")
        return lines
    for entry in entries:
        tag = f"[{entry.ide}:{entry.plan_slug}]"
        lines.append(f"- {tag} `({entry.priority})` {entry.reason} — confirm archive?")
        lines.append(f"  - Source: [`{entry.plan_source}`]({entry.plan_source})")
    lines.append("")
    return lines


def render_implementation_sequence_section(
    cards_by_source: dict[str, PlanCard],
    plan_ranks: dict[str, int],
    *,
    rank_source: str = "heuristic",
    actions: list[Action] | None = None,
) -> list[str]:
    """Markdown section: numbered build queue from ``compute_plan_ranks``."""
    actions = actions or []
    actions_by_source: dict[str, list[Action]] = defaultdict(list)
    for action in actions:
        actions_by_source[action.plan_source].append(action)

    queue_cards = [
        cards_by_source[src]
        for src, _rank in sorted(plan_ranks.items(), key=lambda x: x[1])
        if src in cards_by_source and _card_in_build_queue(cards_by_source[src])
    ]
    lines: list[str] = [
        "## Implementation sequence (build queue)",
        "",
        f"_Rank source: `{rank_source}` — order from `_master.plan.md` "
        "(`execution_order:` or `## active` links), then heuristic tail._",
        "",
    ]
    if not queue_cards:
        lines.append("- _No plans in the build queue._")
        lines.append("")
        return lines

    lines.extend(
        [
            "| # | Plan | Priority | Disposition | Branch | Next verb | Source |",
            "|---|------|----------|-------------|--------|-----------|--------|",
        ]
    )
    for card in queue_cards:
        seq = plan_ranks.get(card.source, 0)
        acts = actions_by_source.get(card.source, [])
        next_verb = acts[0].verb if acts else DISPOSITION_VERB.get(card.disposition, "—")
        if card.disposition == "active" and next_verb == "—":
            if plan_all_todos_completed(card):
                next_verb = "—"
            elif any(it.status in {"Blocked", "In Progress", "Outstanding"} for it in card.items):
                next_verb = "IMPLEMENT"
        title_cell = card.title.replace("|", "\\|")
        if len(title_cell) > 60:
            title_cell = title_cell[:57] + "..."
        lines.append(
            f"| {seq} "
            f"| [{title_cell}]({card.source}) "
            f"| {card.priority} "
            f"| `{card.disposition}` "
            f"| `{card.branch}` "
            f"| {next_verb} "
            f"| `{card.source}` |"
        )
    lines.append("")
    return lines


def render_task_board_markdown(
    report_date: str,
    items: list[PlanItem],
    *,
    cards_by_source: dict[str, PlanCard] | None = None,
    plan_ranks: dict[str, int] | None = None,
    provenance: dict[str, object] | None = None,
) -> str:
    """Single markdown table of active work, regenerated each audit run.

    When ``cards_by_source`` is provided, the Owner column inherits from the
    parent plan when an item lacks its own ``@name`` marker, and the IDE tag
    travels in a new ``IDE`` column.
    """
    cards_by_source = cards_by_source or {}
    plan_ranks = plan_ranks or {}
    rows: list[PlanItem] = [
        i for i in items if i.status in {"Blocked", "In Progress", "Outstanding"}
    ]
    rows.sort(
        key=lambda i: (
            plan_ranks.get(i.source, 9999),
            {"Blocked": 0, "In Progress": 1, "Outstanding": 2}[i.status],
            i.source,
            i.item[:80],
        )
    )
    lines = [
        "# Plan task board",
        "",
        f"_Generated {report_date} by `scripts/daily_plan_audit.py` (daily hook). "
        "Do not edit by hand — ownership inherits from the parent plan's "
        "frontmatter (`owner:` / `dri:`) unless an item explicitly delegates._",
        "",
    ]
    provenance = provenance or {}
    lines.extend(
        [
            f"_model: {provenance.get('last_modified_by_model', 'auto')} | "
            f"cursor_mode: {provenance.get('cursor_mode', 'auto')} | "
            f"date: {provenance.get('last_modified_at', report_date)}_",
            "",
        ]
    )
    lines.extend(
        [
            "| Seq | Plan | IDE | Status | Owner | Item | Source | Gaps |",
            "|-----|------|-----|--------|-------|------|--------|------|",
        ]
    )
    for item in rows:
        plan_card = cards_by_source.get(item.source)
        plan_has_owner = bool(plan_card and plan_card.owner and plan_card.owner != "@user")
        gap_parts: list[str] = []
        if not has_explicit_owner(item.item) and not plan_has_owner:
            gap_parts.append("explicit_owner")
        if has_unresolved_delegation(item.item):
            gap_parts.append("delegation_unresolved")
        if "test" not in item.item.lower():
            gap_parts.append("test")
        if not any("/" in ev for ev in item.evidence):
            gap_parts.append("path_evidence")
        gaps_cell = ", ".join(gap_parts) if gap_parts else "—"
        own_from_item = extract_owner_display(item.item)
        if own_from_item == "—" and plan_card:
            owner_cell = plan_card.owner or "—"
        else:
            owner_cell = own_from_item
        item_cell = item.item.replace("|", "\\|").replace("\n", " ")
        if len(item_cell) > 120:
            item_cell = item_cell[:117] + "..."
        src_cell = f"`{item.source}`"
        ide_cell = plan_card.ide if plan_card and plan_card.ide else "—"
        seq_cell = str(plan_ranks.get(item.source, "—"))
        plan_cell = "—"
        if plan_card:
            plan_cell = plan_card.title.replace("|", "\\|")
            if len(plan_cell) > 40:
                plan_cell = plan_cell[:37] + "..."
        lines.append(
            f"| {seq_cell} | {plan_cell} | {ide_cell} | {item.status} | {owner_cell} | "
            f"{item_cell} | {src_cell} | {gaps_cell} |"
        )
    if not rows:
        lines.append(
            "| — | — | — | — | — | _No blocked/in-progress/outstanding items parsed._ | — | — |"
        )
    lines.append("")
    return "\n".join(lines)


def memory_context(
    repo_root: Path,
    *,
    master_doc: dict[str, object] | None = None,
) -> dict[str, object]:
    candidates = [
        repo_root / ".braindrain" / "AGENT_MEMORY.md",
        repo_root / ".cursor" / "hooks" / "state" / "continual-learning-index.json",
        repo_root / ".cursor" / "PRD.md",
        repo_root / ".cursor" / "TASK-GRAPH.md",
        repo_root / ".cursor" / "project-context.json",
    ]
    existing = [path for path in candidates if path.exists()]
    goal_context = load_goal_context(repo_root, master_doc)
    goal_sources = [str(source) for source in goal_context.get("sources", [])]
    return {
        "used": bool(existing) or bool(goal_context.get("goals")),
        "sources": [path.relative_to(repo_root).as_posix() for path in existing],
        "goal_sources": goal_sources,
        "goal_count": len(goal_context.get("goals") or []),
    }


def score_report(
    items: list[PlanItem], overlaps: list[dict[str, str]], gaps: list[dict[str, str]]
) -> dict[str, int]:
    counts = Counter(i.status for i in items)
    known = max(1, sum(counts[s] for s in STATUS_ORDER[:-1]))
    coverage = int((counts["Implemented"] / known) * 100)
    overlap_score = min(100, len(overlaps) * 15)
    gap_score = min(100, len(gaps) * 12)
    return {
        "overlap_score": overlap_score,
        "gap_score": gap_score,
        "coverage_score": coverage,
    }


def render_status_section(title: str, items: list[PlanItem]) -> list[str]:
    lines = [f"## {title}", ""]
    if not items:
        lines.append("- None")
        lines.append("")
        return lines

    for entry in items:
        lines.append(f"- Item: {entry.item}")
        lines.append(f"  - Source: `{entry.source}`")
        lines.append(f"  - Status: `{entry.status}`")
        lines.append(f"  - Confidence: `{entry.confidence}`")
        lines.append("  - Evidence:")
        for ev in entry.evidence[:3]:
            lines.append(f"    - `{ev}`")
        lines.append(f"  - Why: {entry.why}")
    lines.append("")
    return lines


# Disposition display order in plan cards.
_DISPOSITION_ORDER = (
    "merge-ready",
    "needs-fix",
    "active",
    "meta",
    "research-needed",
    "replan-needed",
    "backlogged",
    "scratched",
    "implemented",
)

# Plans excluded from the overseer "build queue" / implementation sequence.
_BUILD_QUEUE_EXCLUDED_DISPOSITIONS = frozenset({"implemented", "archived", "merge-ready", "meta"})


def render_plan_cards(
    cards: list[PlanCard],
    actions: list[Action],
) -> list[str]:
    """Render per-plan cards grouped by IDE then disposition.

    One card per plan with: title, slug, owner, disposition, priority,
    item rollup counts (Implemented/Active/Blocked/Outstanding/Unknown), and
    the top action verb (if any) so the daily report becomes plan-centric.
    """
    if not cards:
        return ["## Plan Cards (by IDE)", "", "- None", ""]

    actions_by_source: dict[str, list[Action]] = defaultdict(list)
    for action in actions:
        actions_by_source[action.plan_source].append(action)

    by_ide: dict[str, list[PlanCard]] = defaultdict(list)
    for card in cards:
        by_ide[card.ide or "—"].append(card)

    lines: list[str] = ["## Plan Cards (by IDE)", ""]
    for ide in sorted(by_ide.keys()):
        ide_cards = by_ide[ide]
        lines.append(f"### IDE: `{ide}` ({len(ide_cards)} plans)")
        lines.append("")
        ide_cards.sort(
            key=lambda c: (
                _DISPOSITION_ORDER.index(c.disposition)
                if c.disposition in _DISPOSITION_ORDER
                else 99,
                _PRIORITY_RANK.get(c.priority, 3),
                c.slug,
            )
        )
        current_disp = ""
        for card in ide_cards:
            if card.disposition != current_disp:
                current_disp = card.disposition
                lines.append(f"#### Disposition: `{current_disp}`")
                lines.append("")
            counts = card.counts or {}
            rollup_parts = [
                f"Implemented={counts.get('Implemented', 0)}",
                f"InProgress={counts.get('In Progress', 0)}",
                f"Blocked={counts.get('Blocked', 0)}",
                f"Outstanding={counts.get('Outstanding', 0)}",
                f"Unknown={counts.get('Unknown', 0)}",
            ]
            top_actions = actions_by_source.get(card.source, [])
            top_verb = f"`{top_actions[0].verb}` -> {top_actions[0].hint}" if top_actions else "—"
            delegated = ", ".join(card.delegated_to) if card.delegated_to else "none"
            lines.append(f"- **{card.title}** (`{card.slug}`)")
            lines.append(f"  - Source: [`{card.source}`]({card.source})")
            lines.append(f"  - Owner: {card.owner} (DRI: {card.dri}) — Priority: `{card.priority}`")
            lines.append(f"  - Branch: `{card.branch}` (source: `{card.branch_source}`)")
            lines.append(f"  - PR: {format_plan_pr_summary(card)} (source: `{card.pr_source}`)")
            if len(card.phase_branches) > 1:
                lines.append("  - Phase branches:")
                for row in card.phase_branches:
                    phase = row.get("phase") or _infer_phase_label(row.get("branch", ""))
                    pr_url = str(row.get("pr") or "").strip()
                    pr_cell = pr_url if pr_url else "—"
                    note = str(row.get("note") or "").strip()
                    label = f"phase {phase}" if phase else row.get("branch", "")
                    line = f"    - `{row.get('branch', '')}` ({label}): {pr_cell}"
                    if note:
                        line += f" — _{note}_"
                    lines.append(line)
            lines.append(f"  - Delegated to: {delegated}")
            lines.append(f"  - Items: {' / '.join(rollup_parts)}")
            lines.append(f"  - Next action: {top_verb}")
            if top_actions and top_actions[0].item_excerpt:
                lines.append(f"  - Excerpt: _{top_actions[0].item_excerpt}_")
        lines.append("")
    return lines


def build_cards_index(
    repo_root: Path,
    primary: list[Path],
    items: list[PlanItem],
    *,
    default_owner: str | None = None,
) -> dict[str, PlanCard]:
    """Build a map of plan source path -> PlanCard with item rollup attached."""
    items_by_source: dict[str, list[PlanItem]] = defaultdict(list)
    for item in items:
        items_by_source[item.source].append(item)
    cards: dict[str, PlanCard] = {}
    for plan_path in primary:
        rel = plan_path.relative_to(repo_root).as_posix()
        card = build_plan_card(
            plan_path,
            repo_root,
            items=items_by_source.get(rel, []),
            default_owner=default_owner,
        )
        cards[rel] = card
    apply_branch_resolution(cards, repo_root)
    apply_pr_resolution(cards, repo_root)
    sync_plan_phase_branches(repo_root, cards)
    return cards


def _normalize_branch_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def _read_gitops_queue(repo_root: Path) -> list[dict[str, object]]:
    queue_path = repo_root / ".cursor" / ".gitops-queue.json"
    if not queue_path.is_file():
        return []
    try:
        raw = json.loads(queue_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    return []


def _extract_branch_from_memory_entry(entry: dict[str, object]) -> str:
    for key in ("branch", "branchName", "branchCreated"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    ctx = entry.get("context")
    if isinstance(ctx, dict):
        for key in ("branch", "branchName", "planBranch"):
            value = ctx.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _read_gitops_memory(repo_root: Path, limit: int = 200) -> list[dict[str, object]]:
    memory_path = repo_root / ".cursor" / ".gitops-memory.jsonl"
    if not memory_path.is_file():
        return []
    out: list[dict[str, object]] = []
    lines = memory_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-limit:]
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            out.append(payload)
    return out


def _plan_match_tokens(card: PlanCard) -> list[str]:
    slug = card.slug or ""
    # Common pattern: <name>_<8hex>.plan.md -> strip the suffix for matching.
    slug_base = re.sub(r"_[0-9a-f]{8,}$", "", slug)
    title_norm = _normalize_branch_text(card.title)
    rel_norm = _normalize_branch_text(card.source)
    return [
        t
        for t in {
            _normalize_branch_text(slug),
            _normalize_branch_text(slug_base),
            title_norm,
            rel_norm,
        }
        if t
    ]


def _best_matching_branch(card: PlanCard, branch_names: list[str]) -> str:
    tokens = _plan_match_tokens(card)
    if not tokens:
        return ""
    best = ""
    best_score = -1
    for branch in branch_names:
        bn = _normalize_branch_text(branch)
        score = 0
        for token in tokens:
            if token and token in bn:
                score = max(score, len(token))
        if score > best_score:
            best_score = score
            best = branch
    # Require a minimum signal quality to avoid random matches.
    if best_score < 8:
        return ""
    return best


def _normalize_plan_source_path(path: str) -> str:
    return path.strip().lstrip("./").replace("\\", "/")


def _queue_branch_for_card(card: PlanCard, queue_entries: list[dict[str, object]]) -> str:
    """Match gitops queue entry by explicit planSource when present."""
    card_source = _normalize_plan_source_path(card.source)
    for entry in queue_entries:
        plan_source = entry.get("planSource")
        if not isinstance(plan_source, str) or not plan_source.strip():
            continue
        ps = _normalize_plan_source_path(plan_source)
        if ps == card_source or ps.endswith("/" + card_source) or card_source.endswith("/" + ps):
            value = entry.get("branchName") or entry.get("branch")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _list_repo_branches(repo_root: Path) -> list[str]:
    """List local and origin remote branch short names (read-only)."""
    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "for-each-ref",
                "refs/heads",
                "refs/remotes/origin",
                "--format=%(refname:short)",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    names: list[str] = []
    seen: set[str] = set()
    for line in proc.stdout.splitlines():
        name = line.strip()
        if not name or name == "origin/HEAD":
            continue
        if name.startswith("origin/"):
            short = name[len("origin/") :]
            if short and short not in seen:
                seen.add(short)
                names.append(short)
            continue
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _dedupe_branch_candidates(
    candidates: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Keep first source label per branch name."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for branch, source in candidates:
        b = branch.strip()
        if not b or b == "—" or b in seen:
            continue
        seen.add(b)
        out.append((b, source))
    return out


def pick_best_branch_candidate(
    repo_root: Path,
    candidates: list[tuple[str, str]],
    local_branches: list[str],
    *,
    gh_runner: Callable[[Path, str], list[dict[str, object]] | None] | None = None,
) -> tuple[str, str]:
    """Choose branch using git refs + gh PR state, not frontmatter alone.

    Prefers branches that exist locally/remotely and/or have an open PR over stale
    synthetic frontmatter names (e.g. truncated ``branch_name_for_plan`` slugs).
    """
    runner = gh_runner or _run_gh_pr_lookup
    local_set = set(local_branches)
    best_branch = ""
    best_source = "none"
    best_score = -999

    for branch, source in _dedupe_branch_candidates(candidates):
        score = 0
        pr_data = runner(repo_root, branch)
        if pr_data is None:
            score -= 5
        elif pr_data:
            state = str(pr_data[0].get("state") or "").strip().upper()
            if state == "OPEN":
                score += 120
            elif state in {"MERGED", "CLOSED"}:
                score += 60
        if branch in local_set:
            score += 40
        if source == "git_local":
            score += 25
        if source == "gitops_queue":
            score += 20
        if source == "gitops_memory":
            score += 15
        if source == "frontmatter":
            if branch in local_set:
                score += 10
            else:
                score -= 50

        if score > best_score:
            best_score = score
            best_branch = branch
            best_source = source

    if not best_branch:
        return "—", "none"
    return best_branch, best_source


def apply_branch_resolution(cards: dict[str, PlanCard], repo_root: Path) -> None:
    """Resolve plan branch using hybrid precedence reconciled with git + gh.

    Collect candidates from frontmatter, gitops queue/memory, and git_local fuzzy
    match, then ``pick_best_branch_candidate`` scores them using local refs and
    ``gh pr list --head``. Stale frontmatter alone must not hide an existing branch/PR.
    """
    queue_entries = _read_gitops_queue(repo_root)
    queue_branches: list[str] = []
    for entry in queue_entries:
        value = entry.get("branchName") or entry.get("branch")
        if isinstance(value, str) and value.strip():
            queue_branches.append(value.strip())

    memory_entries = _read_gitops_memory(repo_root)
    memory_branches: list[str] = []
    for entry in memory_entries:
        value = _extract_branch_from_memory_entry(entry)
        if value:
            memory_branches.append(value)

    local_branches = _list_repo_branches(repo_root)

    for card in cards.values():
        plan_path = repo_root / card.source
        fm = parse_plan_frontmatter(plan_path) if plan_path.is_file() else {}
        fm_branch = str(fm.get("branch") or "").strip()
        candidates: list[tuple[str, str]] = []
        if fm_branch:
            candidates.append((fm_branch, "frontmatter"))
        direct_queue = _queue_branch_for_card(card, queue_entries)
        if direct_queue:
            candidates.append((direct_queue, "gitops_queue"))
        queue_match = _best_matching_branch(card, queue_branches)
        if queue_match:
            candidates.append((queue_match, "gitops_queue"))
        memory_match = _best_matching_branch(card, memory_branches)
        if memory_match:
            candidates.append((memory_match, "gitops_memory"))
        git_match = _best_matching_branch(card, local_branches)
        if git_match:
            candidates.append((git_match, "git_local"))
        branch, source = pick_best_branch_candidate(repo_root, candidates, local_branches)
        card.branch = branch
        card.branch_source = source
        explicit_branch = str(fm.get("branch") or "").strip()
        if explicit_branch and explicit_branch not in {"—", "-"}:
            card.branch = explicit_branch
            card.branch_source = "frontmatter"


def _run_gh_pr_lookup(repo_root: Path, branch: str) -> list[dict[str, object]] | None:
    """Return parsed gh JSON list or None when gh is unavailable."""
    try:
        proc = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--head",
                branch,
                "--state",
                "all",
                "--json",
                "number,state,url",
                "--limit",
                "1",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        payload = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return None
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    return None


def format_pr_cell(pr_data: list[dict[str, object]] | None) -> tuple[str, str]:
    """Format PR table cell and pr_source from gh lookup result."""
    if pr_data is None:
        return "—", "unavailable"
    if not pr_data:
        return "none", "none"
    row = pr_data[0]
    number = row.get("number")
    state = str(row.get("state") or "").strip().lower()
    url = str(row.get("url") or "").strip()
    if number is None:
        return "none", "none"
    label = f"#{number} {state}" if state else f"#{number}"
    if url:
        return f"[{label}]({url})", "gh"
    return label, "gh"


def resolve_pr_for_branch(
    repo_root: Path,
    branch: str,
    *,
    gh_runner: Callable[[Path, str], list[dict[str, object]] | None] | None = None,
) -> tuple[str, str]:
    """Resolve PR display cell for a branch via gh CLI."""
    if not branch or branch == "—":
        return "—", "none"
    runner = gh_runner or _run_gh_pr_lookup
    return format_pr_cell(runner(repo_root, branch))


def apply_pr_resolution(
    cards: dict[str, PlanCard],
    repo_root: Path,
    *,
    gh_runner: Callable[[Path, str], list[dict[str, object]] | None] | None = None,
) -> None:
    local_branches = _list_repo_branches(repo_root)
    for card in cards.values():
        pr_cell, pr_source = resolve_pr_for_branch(repo_root, card.branch, gh_runner=gh_runner)
        if pr_cell in {"none", "—"} and card.branch and card.branch != "—":
            alt = _best_matching_branch(card, local_branches)
            if alt and alt != card.branch:
                alt_cell, alt_source = resolve_pr_for_branch(repo_root, alt, gh_runner=gh_runner)
                if alt_cell not in {"none", "—"}:
                    card.branch = alt
                    card.branch_source = "git_local"
                    pr_cell, pr_source = alt_cell, alt_source
        card.pr = pr_cell
        card.pr_source = pr_source


def _upsert_gitops_queue_entry(repo_root: Path, entry: dict[str, object]) -> None:
    """Append or replace queue entry matching planSource."""
    queue_path = repo_root / ".cursor" / ".gitops-queue.json"
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    entries = _read_gitops_queue(repo_root)
    plan_source = _normalize_plan_source_path(str(entry.get("planSource") or ""))
    filtered = [
        e
        for e in entries
        if _normalize_plan_source_path(str(e.get("planSource") or "")) != plan_source
    ]
    filtered.append(entry)
    queue_path.write_text(json.dumps(filtered, indent=2) + "\n", encoding="utf-8")


def ensure_plan_branches(
    repo_root: Path,
    cards: dict[str, PlanCard],
) -> list[str]:
    """Create missing branches for active plans and persist branch: frontmatter."""
    from plan_branch_utils import (
        branch_name_for_plan,
        branch_ref_exists,
        create_branch_ref,
        resolve_base_branch,
    )

    bootstrap_dispositions = {"active", "merge-ready"}
    created_sources: list[str] = []
    base = resolve_base_branch(repo_root)

    for source, card in cards.items():
        if card.disposition not in bootstrap_dispositions:
            continue
        if card.branch and card.branch != "—":
            continue
        plan_path = repo_root / source
        if not plan_path.is_file():
            continue
        branch = branch_name_for_plan(plan_path)
        if not branch_ref_exists(repo_root, branch):
            ok, _msg = create_branch_ref(repo_root, branch, base)
            if not ok:
                continue
        _upsert_gitops_queue_entry(
            repo_root,
            {
                "action": "branch-setup",
                "branchName": branch,
                "baseBranch": base,
                "planSource": source,
                "status": "done",
                "source": "daily_plan_audit",
            },
        )
        current = plan_path.read_text(encoding="utf-8", errors="ignore")
        if not re.search(r"(?m)^branch\s*:", current):
            new_text = _inject_frontmatter_key(current, "branch", branch)
            if new_text != current:
                plan_path.write_text(new_text, encoding="utf-8")
        append_plan_branch_registry(repo_root, source, branch)
        created_sources.append(source)
        card.branch = branch
        card.branch_source = "audit_created"

    return created_sources


def bootstrap_plan_branches_from_git_local(
    repo_root: Path,
    cards: dict[str, PlanCard],
) -> list[str]:
    """Persist reconciled branch into frontmatter for active/merge-ready plans."""
    from plan_branch_utils import branch_ref_exists

    bootstrap_dispositions = {"active", "merge-ready"}
    trusted_sources = {"git_local", "gitops_queue", "gitops_memory"}
    updated: list[str] = []
    for source, card in cards.items():
        if card.disposition not in bootstrap_dispositions:
            continue
        if card.branch_source not in trusted_sources:
            continue
        if not card.branch or card.branch == "—":
            continue
        path = repo_root / source
        if not path.is_file():
            continue
        fm = parse_plan_frontmatter(path)
        fm_branch = str(fm.get("branch") or "").strip()
        if fm_branch == card.branch:
            continue
        has_pr = card.pr not in {"none", "—"}
        if not has_pr and not branch_ref_exists(repo_root, card.branch):
            continue
        current = path.read_text(encoding="utf-8", errors="ignore")
        new_text = _set_frontmatter_key(current, "branch", card.branch)
        if new_text != current:
            path.write_text(new_text, encoding="utf-8")
            updated.append(source)
    return updated


def persist_resolved_plan_branches(
    repo_root: Path,
    cards: dict[str, PlanCard],
) -> list[str]:
    """Persist resolved branches into plan frontmatter when missing.

    Only writes branch values that were resolved from existing gitops state
    (`gitops_queue` / `gitops_memory`) so the script remains additive and
    does not invent new branch names.
    """
    updated: list[str] = []
    for source, card in cards.items():
        if card.branch_source not in {"gitops_queue", "gitops_memory"}:
            continue
        if not card.branch or card.branch == "—":
            continue
        path = repo_root / source
        if not path.is_file():
            continue
        current = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"(?m)^branch\s*:", current):
            continue
        new_text = _inject_frontmatter_key(current, "branch", card.branch)
        if new_text != current:
            path.write_text(new_text, encoding="utf-8")
            updated.append(source)
    return updated


# Markdown link extractor used for parsing the curated master plan body.
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _resolve_master_plan_link(
    target: str,
    master_dir: Path,
    repo_root: Path,
    *,
    seen: set[str] | None = None,
) -> str | None:
    """Resolve a markdown plan link to a repo-relative ``*.plan.md`` path."""
    target = target.strip()
    if not target or target.startswith(("http://", "https://", "#", "mailto:")):
        return None
    if not target.endswith(".plan.md"):
        return None
    candidates = [
        (master_dir / target).resolve(),
        (repo_root / target).resolve(),
    ]
    rel: str | None = None
    for candidate in candidates:
        try:
            rel = candidate.relative_to(repo_root.resolve()).as_posix()
            break
        except ValueError:
            continue
    if rel is None:
        return None
    if seen is not None:
        if rel in seen:
            return None
        seen.add(rel)
    return rel


def _collect_master_section_children(
    body: str,
    section: str,
    master_dir: Path,
    repo_root: Path,
) -> list[str]:
    """Plan links under ``## <section>`` in declaration order (top-to-bottom)."""
    lines = body.splitlines()
    header = f"## {section}"
    start: int | None = None
    for idx, line in enumerate(lines):
        if line.strip().lower() == header.lower():
            start = idx + 1
            break
    if start is None:
        return []
    seen: set[str] = set()
    children: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        for _label, target in _MD_LINK_RE.findall(line):
            rel = _resolve_master_plan_link(target, master_dir, repo_root, seen=seen)
            if rel:
                children.append(rel)
    return children


def _resolve_execution_order_entries(
    entries: list[object],
    master_dir: Path,
    repo_root: Path,
) -> list[str]:
    """Normalize ``execution_order`` frontmatter paths to repo-relative sources."""
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in entries:
        if not isinstance(raw, str) or not raw.strip():
            continue
        rel = _resolve_master_plan_link(raw.strip(), master_dir, repo_root, seen=seen)
        if rel:
            ordered.append(rel)
    return ordered


def _card_in_build_queue(card: PlanCard) -> bool:
    if card.is_master:
        return False
    if card.disposition in _BUILD_QUEUE_EXCLUDED_DISPOSITIONS:
        return False
    if _is_archived_storage_path(card.source):
        return False
    return True


def _heuristic_plan_sort_key(card: PlanCard) -> tuple[object, ...]:
    return (
        _DISPOSITION_ORDER.index(card.disposition)
        if card.disposition in _DISPOSITION_ORDER
        else 99,
        _PRIORITY_RANK.get(card.priority, 3),
        card.slug,
    )


def compute_plan_ranks(
    master_doc: dict[str, object] | None,
    cards_by_source: dict[str, PlanCard],
    *,
    repo_root: Path,
    master_path: Path | None = None,
) -> tuple[dict[str, int], str]:
    """Assign 1-based execution ranks for the build queue.

    Order precedence:
      1. ``execution_order:`` frontmatter on ``_master.plan.md``
      2. Markdown links under ``## active`` (top-to-bottom)
      3. Active-disposition subset of all master body links
      4. Heuristic disposition + priority + slug when no master
    """
    ranks: dict[str, int] = {}
    rank_source = "heuristic"
    ordered_sources: list[str] = []

    master_dir = (
        master_path.parent.resolve()
        if master_path and master_path.is_file()
        else (repo_root / ".cursor" / "plans").resolve()
    )

    if master_doc:
        fm = master_doc.get("frontmatter") or {}
        exec_raw = fm.get("execution_order")
        if isinstance(exec_raw, list) and exec_raw:
            ordered_sources = _resolve_execution_order_entries(exec_raw, master_dir, repo_root)
            rank_source = "master_frontmatter"
        else:
            active_children: list[str] = list(
                master_doc.get("active_children", [])  # type: ignore[arg-type]
            )
            if active_children:
                ordered_sources = active_children
                rank_source = "master_body"
            else:
                children: list[str] = list(master_doc.get("children", []))  # type: ignore[arg-type]
                ordered_sources = [
                    src
                    for src in children
                    if (c := cards_by_source.get(src)) and c.disposition == "active"
                ]
                if ordered_sources:
                    rank_source = "master_body"

    rank_counter = 0
    for src in ordered_sources:
        card = cards_by_source.get(src)
        if not card or not _card_in_build_queue(card):
            continue
        rank_counter += 1
        ranks[src] = rank_counter

    unranked = [
        c for c in cards_by_source.values() if _card_in_build_queue(c) and c.source not in ranks
    ]
    if unranked:
        unranked.sort(key=_heuristic_plan_sort_key)
        for card in unranked:
            rank_counter += 1
            ranks[card.source] = rank_counter
        if rank_source == "heuristic" and not ordered_sources:
            pass
        elif ordered_sources:
            rank_source = f"{rank_source}+heuristic_tail"

    if not master_doc and not ranks:
        all_queue = [c for c in cards_by_source.values() if _card_in_build_queue(c)]
        all_queue.sort(key=_heuristic_plan_sort_key)
        for idx, card in enumerate(all_queue, start=1):
            ranks[card.source] = idx
        rank_source = "heuristic"

    return ranks, rank_source


def parse_master_plan(master_path: Path, repo_root: Path) -> dict[str, object]:
    """Extract the list of child plans referenced by `_master.plan.md`.

    Returns a dict with:
      - ``frontmatter``: parsed YAML
      - ``children``: list of repo-relative paths in declaration order (full body)
      - ``active_children``: links under ``## active`` only (execution order default)
    """
    if not master_path.is_file():
        return {"frontmatter": {}, "children": [], "active_children": []}

    fm = parse_plan_frontmatter(master_path)
    text = master_path.read_text(encoding="utf-8", errors="ignore")
    # Strip frontmatter so we don't pull links out of it.
    body = FRONTMATTER_BLOCK_RE.sub("", text, count=1)
    master_dir = master_path.parent
    seen: set[str] = set()
    children: list[str] = []
    for _label, target in _MD_LINK_RE.findall(body):
        rel = _resolve_master_plan_link(target, master_dir, repo_root, seen=seen)
        if rel:
            children.append(rel)
    active_children = _collect_master_section_children(body, "active", master_dir, repo_root)
    return {
        "frontmatter": fm,
        "children": children,
        "active_children": active_children,
    }


def sync_master_plan(
    master_path: Path | None,
    repo_root: Path,
    cards: list[PlanCard],
) -> list[str]:
    """Auto-add missing discovered plans into curated `_master.plan.md`.

    Missing plans are grouped under their disposition heading (e.g. `## active`).
    Returns the repo-relative source paths that were inserted.
    """
    if not master_path or not master_path.is_file():
        return []

    master_doc = parse_master_plan(master_path, repo_root)
    in_master: set[str] = set(master_doc.get("children", []))  # type: ignore[arg-type]
    by_source = {card.source: card for card in cards if not card.is_master}
    missing = sorted(set(by_source.keys()) - in_master)
    if not missing:
        return []

    text = master_path.read_text(encoding="utf-8", errors="ignore")
    fm_match = FRONTMATTER_BLOCK_RE.match(text)
    fm_block = fm_match.group(0) if fm_match else ""
    body = text[len(fm_block) :]
    body_lines = body.splitlines()

    def section_bounds(section_name: str) -> tuple[int, int] | None:
        header = f"## {section_name}"
        start = None
        for idx, line in enumerate(body_lines):
            if line.strip().lower() == header.lower():
                start = idx
                break
        if start is None:
            return None
        end = len(body_lines)
        for idx in range(start + 1, len(body_lines)):
            if body_lines[idx].startswith("## "):
                end = idx
                break
        return start, end

    inserted: list[str] = []
    # Keep insertion stable by disposition order, then source path.
    ordered_missing = sorted(
        missing,
        key=lambda src: (
            _DISPOSITION_ORDER.index(by_source[src].disposition)
            if by_source[src].disposition in _DISPOSITION_ORDER
            else 99,
            src,
        ),
    )
    for src in ordered_missing:
        card = by_source[src]
        target_abs = (repo_root / src).resolve()
        rel_link = os.path.relpath(target_abs, start=master_path.parent.resolve()).replace(
            "\\", "/"
        )
        bullet = f"- [{card.title}]({rel_link}) — DRI: {card.dri}"

        bounds = section_bounds(card.disposition)
        if bounds is None:
            if body_lines and body_lines[-1].strip():
                body_lines.append("")
            body_lines.append(f"## {card.disposition}")
            body_lines.append("")
            body_lines.append(bullet)
            inserted.append(src)
            continue

        start, end = bounds
        insert_at = end
        # Keep a blank line between section content and next heading.
        while insert_at > start + 1 and not body_lines[insert_at - 1].strip():
            insert_at -= 1
        body_lines.insert(insert_at, bullet)
        inserted.append(src)

    new_body = "\n".join(body_lines).rstrip() + "\n"
    master_path.write_text(fm_block + new_body, encoding="utf-8")
    return inserted


def render_next_actions(
    actions: list[Action],
    *,
    ready_to_archive: list[ReadyToArchive] | None = None,
    report_date: str = "",
    provenance: dict[str, object] | None = None,
    plan_ranks: dict[str, int] | None = None,
) -> str:
    """Render the triage queue grouped by verb.

    Lines look like:
        - [cursor:plan-slug] (P1) reason — hint
            > item excerpt (if any)

    Order: verbs follow ``_VERB_ORDER`` (MERGE first), inside each verb
    actions sort by priority then ide then slug. Empty queue still emits a
    valid file with a friendly message so consumers can tail it safely.
    """
    lines: list[str] = ["# Plan triage queue (next actions)"]
    if report_date:
        lines.append("")
        lines.append(
            f"_Generated {report_date} by `scripts/daily_plan_audit.py`. "
            "Do not edit by hand. Action a verb by editing the parent plan's "
            "`disposition:` and re-running the audit._"
        )
        provenance = provenance or {}
        lines.append(
            f"_model: {provenance.get('last_modified_by_model', 'auto')} | "
            f"cursor_mode: {provenance.get('cursor_mode', 'auto')} | "
            f"date: {provenance.get('last_modified_at', report_date)}_"
        )
    lines.append("")

    if not actions:
        lines.append("- _No active triage actions today._")
        lines.append("")
    else:
        grouped: dict[str, list[Action]] = defaultdict(list)
        for action in actions:
            grouped[action.verb].append(action)

        for verb in _VERB_ORDER:
            bucket = grouped.get(verb, [])
            if not bucket:
                continue
            lines.append(f"## {verb} ({len(bucket)})")
            lines.append("")
            plan_ranks = plan_ranks or {}
            bucket.sort(
                key=lambda a: (
                    plan_ranks.get(a.plan_source, 9999),
                    _PRIORITY_RANK.get(a.priority, 3),
                    a.ide,
                    a.plan_slug,
                )
            )
            for action in bucket:
                tag = f"[{action.ide or '—'}:{action.plan_slug}]"
                lines.append(f"- {tag} `({action.priority})` {action.reason} — {action.hint}")
                link = f"  - Source: [`{action.plan_source}`]({action.plan_source})"
                lines.append(link)
                if action.item_excerpt:
                    lines.append(f"  - Excerpt: _{action.item_excerpt}_")
            lines.append("")
    if ready_to_archive is not None:
        lines.extend(render_ready_to_archive_section(ready_to_archive, report_date=report_date))
    return "\n".join(lines)


def render_master_mirror(
    cards: list[PlanCard],
    master_doc: dict[str, object] | None = None,
    *,
    repo_root: Path | None = None,
    report_date: str = "",
    provenance: dict[str, object] | None = None,
    plan_ranks: dict[str, int] | None = None,
    rank_source: str = "heuristic",
    actions: list[Action] | None = None,
    overlap_edges: list[PlanOverlapEdge] | None = None,
    overlap_clusters: list[list[str]] | None = None,
    goal_alignments: list[PlanGoalAlignment] | None = None,
    goal_context: dict[str, object] | None = None,
) -> str:
    """Generated mirror of the master plan with rollup + drift detection.

    Layout:
      # Master plan (mirror)
      _Generated <date>; do not edit by hand. Source: <_master.plan.md or "auto">_

      ## IDE: cursor
      ### Disposition: merge-ready
      | Plan | Owner | Priority | Items | Source |
      ### Disposition: active
      ...

      ## Drift
      - on disk but missing from curated master: ...
      - in curated master but missing from disk: ...
    """
    master_doc = master_doc or {"frontmatter": {}, "children": []}
    children: list[str] = list(master_doc.get("children", []))  # type: ignore[arg-type]

    lines: list[str] = ["# Master plan (mirror)", ""]
    src_note = ".cursor/plans/_master.plan.md" if children else "auto (no curated master found)"
    if report_date:
        lines.append(
            f"_Generated {report_date} by `scripts/daily_plan_audit.py`. "
            f"Do not edit by hand. Source: {src_note}._"
        )
    else:
        lines.append(
            "_Generated by `scripts/daily_plan_audit.py`. "
            f"Do not edit by hand. Source: {src_note}._"
        )
    lines.append("")
    provenance = provenance or {}
    lines.append(
        f"_model: {provenance.get('last_modified_by_model', 'auto')} | "
        f"cursor_mode: {provenance.get('cursor_mode', 'auto')} | "
        f"date: {provenance.get('last_modified_at', report_date or '')}_"
    )
    lines.append("")

    if not cards:
        lines.append("- _No plans discovered._")
        lines.append("")
        return "\n".join(lines)

    plan_ranks = plan_ranks or {}
    cards_by_source = {c.source: c for c in cards if not c.is_master}
    lines.extend(
        render_implementation_sequence_section(
            cards_by_source,
            plan_ranks,
            rank_source=rank_source,
            actions=actions,
        )
    )
    overlap_edges = overlap_edges or []
    overlap_clusters = overlap_clusters or []
    goal_alignments = goal_alignments or []
    goal_context = goal_context or {}
    lines.extend(
        render_overlap_clusters_section(
            overlap_edges,
            overlap_clusters,
            cards_by_source,
        )
    )
    lines.extend(render_goal_alignment_section(goal_alignments, goal_context))

    by_ide: dict[str, list[PlanCard]] = defaultdict(list)
    for card in cards:
        by_ide[card.ide or "—"].append(card)

    for ide in sorted(by_ide.keys()):
        ide_cards = by_ide[ide]
        lines.append(f"## IDE: `{ide}` ({len(ide_cards)} plans)")
        lines.append("")
        ide_cards.sort(
            key=lambda c: (
                _DISPOSITION_ORDER.index(c.disposition)
                if c.disposition in _DISPOSITION_ORDER
                else 99,
                _PRIORITY_RANK.get(c.priority, 3),
                c.slug,
            )
        )
        current_disp = ""
        for card in ide_cards:
            if card.disposition != current_disp:
                if current_disp:
                    lines.append("")
                current_disp = card.disposition
                lines.append(f"### Disposition: `{current_disp}`")
                lines.append("")
                lines.append(
                    "| Plan | Owner | Branch | PR | Priority | Todos (done/total) | Items (Impl/Active/Blocked/Out/Unk) | Source |"
                )
                lines.append(
                    "|------|-------|--------|----|----------|--------------------|--------------------------------------|--------|"
                )
            counts = card.counts or {}
            if card.todo_summary:
                ts = card.todo_summary
                todos_cell = f"{ts.get('completed', 0)}/{ts.get('total', 0)}"
            else:
                todos_cell = "—"
            items_cell = (
                f"{counts.get('Implemented', 0)}/"
                f"{counts.get('In Progress', 0)}/"
                f"{counts.get('Blocked', 0)}/"
                f"{counts.get('Outstanding', 0)}/"
                f"{counts.get('Unknown', 0)}"
            )
            title_cell = card.title.replace("|", "\\|")
            if len(title_cell) > 80:
                title_cell = title_cell[:77] + "..."
            lines.append(
                f"| [{title_cell}]({card.source}) "
                f"| {card.owner} "
                f"| `{card.branch}` "
                f"| {format_plan_pr_summary(card)} "
                f"| {card.priority} "
                f"| {todos_cell} "
                f"| {items_cell} "
                f"| `{card.source}` |"
            )
        lines.append("")

    # Drift detection: active index vs on-disk plans (not archive storage).
    on_disk_active = {c.source for c in cards if not _is_archived_storage_path(c.source)}
    in_master = set(children)
    metadata = master_archived_metadata_entries(master_doc)
    only_master: list[str] = []
    for src in sorted(in_master - on_disk_active):
        if _is_archived_storage_path(src):
            continue
        if repo_root and resolve_plan_link_path(repo_root, src):
            continue
        base = Path(_normalize_plan_source_path(src)).name
        if src in metadata or base in metadata:
            continue
        only_master.append(src)
    only_disk = sorted(p for p in (on_disk_active - in_master) if not _is_archived_storage_path(p))
    unranked_build = sorted(
        src
        for src, card in cards_by_source.items()
        if _card_in_build_queue(card) and src not in plan_ranks
    )
    archived_on_disk = 0
    if repo_root is not None:
        archived_on_disk = len(discover_recent_archived_plans(repo_root, limit=999))

    lines.append("## Drift")
    lines.append("")
    if not children:
        lines.append("- _No curated master found at `.cursor/plans/_master.plan.md`._")
        lines.append(
            f"- {len(only_disk)} plans discovered on disk; "
            "create `_master.plan.md` to formalize the index."
        )
    elif not only_disk and not only_master:
        lines.append("- _No drift: curated master matches discovered active plans._")
        if archived_on_disk:
            lines.append(
                f"- {archived_on_disk} archived plan(s) under `.plan.archives/` "
                f"(see `_master.plan.md` ## archived, max {ARCHIVED_BATCH_LIMIT} shown)."
            )
    else:
        if only_disk:
            lines.append("### On disk but missing from curated master:")
            for src in only_disk:
                lines.append(f"- `{src}`")
        if only_master:
            lines.append("### In curated master but missing from disk:")
            for src in only_master:
                lines.append(f"- `{src}`")
        if unranked_build and children:
            lines.append("### Build-queue plans not in master index:")
            for src in unranked_build:
                lines.append(f"- `{src}` (ranked at end via heuristic)")
    lines.append("")
    return "\n".join(lines)


def build_report(
    report_date: str,
    trigger: str,
    repo_root: Path,
    primary: list[Path],
    secondary: list[Path],
    items: list[PlanItem],
    *,
    cards_by_source: dict[str, PlanCard] | None = None,
    ready_to_archive: list[ReadyToArchive] | None = None,
    provenance: dict[str, object] | None = None,
    master_doc: dict[str, object] | None = None,
    overlap_edges: list[PlanOverlapEdge] | None = None,
    overlap_clusters: list[list[str]] | None = None,
    goal_alignments: list[PlanGoalAlignment] | None = None,
    goal_context: dict[str, object] | None = None,
    goal_alignment_min_score: int = DEFAULT_GOAL_ALIGNMENT_MIN_SCORE,
) -> str:
    overlaps = detect_overlaps(items)
    cards_by_source = cards_by_source or {}
    gaps = detect_gaps(items, cards_by_source=cards_by_source)
    scores = score_report(items, overlaps, gaps)
    summary_counts = Counter(item.status for item in items)
    mem = memory_context(repo_root, master_doc=master_doc)
    overlap_edges = overlap_edges or []
    overlap_clusters = overlap_clusters or []
    goal_alignments = goal_alignments or []
    goal_context = goal_context or {}

    def _item_has_inherited_owner(it: PlanItem) -> bool:
        if has_explicit_owner(it.item):
            return True
        c = cards_by_source.get(it.source)
        return bool(c and c.owner and c.owner != "@user")

    top_risks: list[str] = []
    blocked_no_owner = [
        i for i in items if i.status == "Blocked" and not _item_has_inherited_owner(i)
    ]
    if blocked_no_owner:
        top_risks.append(
            "Blocked items lack explicit owner markers (@, owner:, assignee:, or dri:)."
        )
    elif any(i.status == "Blocked" for i in items):
        top_risks.append(
            "Blocked items have owner markers; resolve dependencies and unblock execution."
        )
    if any("explicit_owner" in g["missing"] for g in gaps) and not blocked_no_owner:
        top_risks.append(
            "Some active items lack explicit owner markers (@, owner:, assignee:, or dri:)."
        )
    if any("delegation_unresolved" in g["missing"] for g in gaps):
        top_risks.append("Some items declare `delegate:` without naming a target sub-agent.")
    gap_test_or_path = [g for g in gaps if "test" in g["missing"] or "evidence" in g["missing"]]
    if gap_test_or_path:
        top_risks.append("Active items are missing test hints and/or path evidence in plan text.")
    if overlaps:
        top_risks.append("Overlapping plan entries may create duplicated delivery work.")
    low_alignment = [
        row
        for row in goal_alignments
        if row.alignment_score < goal_alignment_min_score and row.unaligned_risk == "high"
    ]
    if low_alignment:
        top_risks.append(
            f"{len(low_alignment)} active plan(s) score below {goal_alignment_min_score} "
            "on goal alignment."
        )
    if overlap_edges:
        top_risks.append(
            f"{len(overlap_edges)} plan-level overlap signal(s) detected "
            "(paths, tokens, branches, or relations)."
        )
    if not top_risks:
        top_risks.append("No major risks detected from current planning artifacts.")

    frontmatter = {
        "schema_version": SCHEMA_VERSION,
        "report_date": report_date,
        "trigger": trigger,
        "sources": {
            "primary_plan_files": [p.relative_to(repo_root).as_posix() for p in primary],
            "secondary_docs_count": len(secondary),
        },
        "summary_counts": {
            "implemented": summary_counts["Implemented"],
            "in_progress": summary_counts["In Progress"],
            "blocked": summary_counts["Blocked"],
            "outstanding": summary_counts["Outstanding"],
            "unknown": summary_counts["Unknown"],
        },
        "analysis_scores": scores,
        "top_risks": top_risks[:5],
        "memory_context": mem,
    }
    provenance = provenance or {}

    body: list[str] = []
    body.append("---")
    body.append(f'schema_version: "{frontmatter["schema_version"]}"')
    body.append(f'report_date: "{frontmatter["report_date"]}"')
    body.append(f'trigger: "{frontmatter["trigger"]}"')
    body.append("sources:")
    body.append("  primary_plan_files:")
    for plan_file in frontmatter["sources"]["primary_plan_files"]:
        body.append(f'    - "{plan_file}"')
    body.append(f"  secondary_docs_count: {frontmatter['sources']['secondary_docs_count']}")
    body.append("summary_counts:")
    for k, v in frontmatter["summary_counts"].items():
        body.append(f"  {k}: {v}")
    body.append("analysis_scores:")
    for k, v in frontmatter["analysis_scores"].items():
        body.append(f"  {k}: {v}")
    body.append("top_risks:")
    for risk in frontmatter["top_risks"]:
        body.append(f'  - "{risk}"')
    body.append("memory_context:")
    body.append(f"  used: {str(frontmatter['memory_context']['used']).lower()}")
    body.append("  sources:")
    for source in frontmatter["memory_context"]["sources"]:
        body.append(f'    - "{source}"')
    if not frontmatter["memory_context"]["sources"]:
        body.append('    - "none"')
    body.append("  goal_sources:")
    for source in frontmatter["memory_context"].get("goal_sources", []):
        body.append(f'    - "{source}"')
    if not frontmatter["memory_context"].get("goal_sources"):
        body.append('    - "none"')
    body.append(f"  goal_count: {frontmatter['memory_context'].get('goal_count', 0)}")
    body.append("provenance:")
    body.append(f'  created_by_model: "{str(provenance.get("created_by_model", "auto"))}"')
    body.append(f'  created_at: "{str(provenance.get("created_at", report_date))}"')
    body.append(
        f'  last_modified_by_model: "{str(provenance.get("last_modified_by_model", "auto"))}"'
    )
    body.append(f'  last_modified_at: "{str(provenance.get("last_modified_at", report_date))}"')
    body.append(f'  cursor_mode: "{str(provenance.get("cursor_mode", "auto"))}"')
    body.append("  subagent_models_used:")
    for model in provenance.get("subagent_models_used", []) or ["auto"]:
        body.append(f'    - "{model}"')
    body.append("---")
    body.append("")
    body.append("# Daily Plan Audit Report")
    body.append("")
    body.append("## Executive Summary")
    body.append(
        f"- Scanned {len(primary)} primary plan files and {len(secondary)} secondary markdown docs."
    )
    body.append(
        f"- Status totals: Implemented={summary_counts['Implemented']}, In Progress={summary_counts['In Progress']}, Blocked={summary_counts['Blocked']}, Outstanding={summary_counts['Outstanding']}, Unknown={summary_counts['Unknown']}."
    )
    body.append(
        f"- Scores: coverage={scores['coverage_score']}, overlap={scores['overlap_score']}, gap={scores['gap_score']}."
    )
    ready_to_archive = ready_to_archive or []
    legacy_todo_plans = sum(
        1 for c in cards_by_source.values() if not c.is_master and c.count_source == "body"
    )
    if legacy_todo_plans:
        body.append(
            f"- {legacy_todo_plans} plan(s) lack structured frontmatter todos "
            "(using body checklist for counts)."
        )
    if ready_to_archive:
        body.append(
            f"- READY_TO_ARCHIVE: {len(ready_to_archive)} plan(s) — confirm with user before "
            "`--apply-archive`."
        )
    if low_alignment:
        body.append(
            f"- Goal alignment: {len(low_alignment)} active plan(s) score below "
            f"{goal_alignment_min_score} — review Goal alignment in `master-plan.md`."
        )
    body.append("")
    if ready_to_archive:
        body.extend(render_ready_to_archive_section(ready_to_archive, report_date=report_date))
    body.append("## Status Matrix (5-State)")
    body.append("| Status | Count |")
    body.append("|---|---:|")
    for status in STATUS_ORDER:
        body.append(f"| {status} | {summary_counts[status]} |")
    body.append("")

    # Plan-centric cards (new in schema 1.1) — grouped by IDE then disposition.
    actions = detect_actions(list(cards_by_source.values()), repo_root=repo_root)
    body.extend(render_plan_cards(list(cards_by_source.values()), actions))

    grouped = defaultdict(list)
    for item in items:
        grouped[item.status].append(item)

    body.extend(render_status_section("Implemented", grouped["Implemented"]))
    body.extend(render_status_section("In Progress", grouped["In Progress"]))
    body.extend(render_status_section("Blocked", grouped["Blocked"]))
    body.extend(render_status_section("Outstanding", grouped["Outstanding"]))
    body.extend(render_status_section("Unknown", grouped["Unknown"]))

    body.append("## Overlap Analysis")
    if not overlaps and not overlap_edges:
        body.append("- None")
    else:
        if overlap_edges:
            body.append("### Plan-level overlaps")
            for edge in overlap_edges[:20]:
                sim = f", similarity={edge.similarity:.2f}" if edge.similarity else ""
                body.append(
                    f"- `{edge.source_a}` <-> `{edge.source_b}` "
                    f"({edge.signal}, {edge.severity}{sim}): {edge.detail}"
                )
            if overlap_clusters:
                body.append("")
                body.append("### Overlap clusters")
                for idx, cluster in enumerate(overlap_clusters[:10], start=1):
                    body.append(
                        f"- Cluster {idx}: "
                        + ", ".join(f"`{Path(source).stem}`" for source in cluster)
                    )
            body.append("")
        body.append("### Item-level overlaps")
        if not overlaps:
            body.append("- None")
        else:
            for overlap in overlaps[:20]:
                body.append(
                    "- "
                    f"`{overlap['source_a']}` <-> `{overlap['source_b']}` "
                    f"(similarity={overlap['similarity']}, severity={overlap['severity']})"
                )
                body.append(f"  - A: {overlap['item_a']}")
                body.append(f"  - B: {overlap['item_b']}")
    body.append("")

    if goal_alignments:
        body.extend(render_goal_alignment_section(goal_alignments, goal_context))

    body.append("## Gap Analysis")
    if not gaps:
        body.append("- None")
    else:
        for gap in gaps[:20]:
            body.append(
                f"- `{gap['source']}` ({gap['risk']} risk): missing {gap['missing']} -> {gap['item']}"
            )
    body.append("")

    body.append("## Memory Context Used")
    body.append(f"- Used: `{str(mem['used']).lower()}`")
    if mem["sources"]:
        for source in mem["sources"]:
            body.append(f"- Source: `{source}`")
    else:
        body.append("- Source: none available")
    if mem.get("goal_sources"):
        body.append("- Goal sources:")
        for source in mem.get("goal_sources", []):
            body.append(f"  - `{source}`")
    body.append(f"- Goal lines loaded: `{mem.get('goal_count', 0)}`")
    body.append("")

    body.append("## Recommended Next Actions")
    prioritized = sorted(
        [item for item in items if item.status in {"Blocked", "Outstanding", "In Progress"}],
        key=lambda i: (i.status != "Blocked", i.status != "Outstanding", i.confidence != "high"),
    )
    if not prioritized:
        body.append("- Keep roadmap and todos synchronized with implementation references.")
    else:
        for item in prioritized[:7]:
            wants: list[str] = []
            if not has_explicit_owner(item.item):
                wants.append("add explicit owner (@name or owner:/assignee:/dri:)")
            if "test" not in item.item.lower():
                wants.append("add test hint")
            if not any("/" in ev for ev in item.evidence):
                wants.append("link path evidence")
            hint = "; ".join(wants) if wants else "review for drift vs implementation"
            body.append(f"- [{item.status}] `{item.source}`: {hint} — `{item.item}`")
    body.append("")
    return "\n".join(body)


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    auditor_runtime = resolve_planning_auditor_runtime(args, repo_root)
    overlap_jaccard_threshold = float(auditor_runtime["overlap_jaccard_threshold"])
    goal_alignment_min_score = int(auditor_runtime["goal_alignment_min_score"])
    should_apply_overlap_relations = bool(auditor_runtime["apply_overlap_relations"])
    should_apply_goal_tags = bool(auditor_runtime["apply_goal_tags"])
    trace_path = Path(args.trace_path)
    if not trace_path.is_absolute():
        trace_path = repo_root / trace_path
    model_name = resolve_model_name(args.model_name, repo_root=repo_root)
    cursor_mode = resolve_cursor_mode(args.cursor_mode, repo_root=repo_root)
    provenance = {
        "created_by_model": model_name,
        "created_at": args.report_date,
        "last_modified_by_model": model_name,
        "last_modified_at": args.report_date,
        "cursor_mode": cursor_mode,
        "subagent_models_used": load_trace_models(trace_path),
    }
    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = repo_root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    archive_moves: list[str] = []
    if not getattr(args, "skip_archive", False):
        archive_moves = relocate_archived_plans(repo_root)

    default_owner = resolve_default_owner(repo_root)
    primary, secondary = discover_sources(repo_root)

    items: list[PlanItem] = []
    for path in primary:
        items.extend(collect_plan_items(path, repo_root))
    for path in secondary:
        items.extend(collect_plan_items(path, repo_root))

    cards_by_source = build_cards_index(repo_root, primary, items, default_owner=default_owner)
    branches_created: list[str] = []
    if getattr(args, "ensure_branches", True):
        branches_created = ensure_plan_branches(repo_root, cards_by_source)
        apply_branch_resolution(cards_by_source, repo_root)
        apply_pr_resolution(cards_by_source, repo_root)
    branch_frontmatter_updated = bootstrap_plan_branches_from_git_local(repo_root, cards_by_source)
    if branch_frontmatter_updated:
        apply_branch_resolution(cards_by_source, repo_root)
        apply_pr_resolution(cards_by_source, repo_root)
    branch_links = persist_resolved_plan_branches(repo_root, cards_by_source)

    disposition_synced: list[str] = []
    if getattr(args, "apply_disposition_sync", False):
        disposition_synced = apply_disposition_sync(repo_root, cards_by_source)

    card_list = list(cards_by_source.values())
    archive_targets: list[ReadyToArchive] = []
    if getattr(args, "apply_archive", False):
        archive_targets = detect_ready_to_archive(card_list, include_implemented=True)
    ready_to_archive = detect_ready_to_archive(card_list)

    if args.master_plan:
        master_candidate = Path(args.master_plan)
        if not master_candidate.is_absolute():
            master_candidate = repo_root / master_candidate
        master_path = master_candidate if master_candidate.is_file() else None
    else:
        master_path = discover_master_plan(repo_root)

    master_doc = parse_master_plan(master_path, repo_root) if master_path else None
    pruned_stale_links: list[str] = []
    if master_path and master_doc:
        pruned_stale_links = prune_stale_master_body_links(master_path, repo_root, master_doc)
        if pruned_stale_links:
            master_doc = parse_master_plan(master_path, repo_root)

    archive_applied: list[str] = []
    if getattr(args, "apply_archive", False) and archive_targets:
        archive_applied = apply_archive_plans(
            repo_root,
            archive_targets,
            cards_by_source,
            master_path=master_path,
            report_paths=[],
        )
        primary, secondary = discover_sources(repo_root)
        items = []
        for path in primary:
            items.extend(collect_plan_items(path, repo_root))
        for path in secondary:
            items.extend(collect_plan_items(path, repo_root))
        cards_by_source = build_cards_index(repo_root, primary, items, default_owner=default_owner)
        if getattr(args, "ensure_branches", True):
            apply_branch_resolution(cards_by_source, repo_root)
            apply_pr_resolution(cards_by_source, repo_root)
        ready_to_archive = detect_ready_to_archive(list(cards_by_source.values()))

    overlap_edges, overlap_clusters = detect_plan_overlaps(
        cards_by_source,
        items,
        repo_root=repo_root,
        jaccard_threshold=overlap_jaccard_threshold,
    )
    overlap_relations_applied: list[str] = []
    if should_apply_overlap_relations:
        overlap_relations_applied = apply_overlap_relations(
            repo_root,
            cards_by_source,
            overlap_edges,
        )

    goal_context = load_goal_context(repo_root, master_doc)
    goal_alignments = compute_goal_alignments(cards_by_source, goal_context)
    goal_tags_applied: list[str] = []
    if should_apply_goal_tags:
        goal_tags_applied = apply_goal_tags(
            repo_root,
            cards_by_source,
            goal_alignments,
        )

    report = build_report(
        args.report_date,
        args.trigger,
        repo_root,
        primary,
        secondary,
        items,
        cards_by_source=cards_by_source,
        ready_to_archive=ready_to_archive,
        provenance=provenance,
        master_doc=master_doc,
        overlap_edges=overlap_edges,
        overlap_clusters=overlap_clusters,
        goal_alignments=goal_alignments,
        goal_context=goal_context,
        goal_alignment_min_score=goal_alignment_min_score,
    )
    if archive_moves:
        report = (
            report
            + "\n\n## Archived plan files (this run)\n\n"
            + "\n".join(f"- `{p}`" for p in archive_moves)
            + "\n"
        )
    if branch_links:
        report = (
            report
            + "\n\n## Plan branches linked from gitops context (this run)\n\n"
            + "\n".join(f"- `{p}`" for p in branch_links)
            + "\n"
        )
    if branches_created:
        report = (
            report
            + "\n\n## Plan branches created (this run)\n\n"
            + "\n".join(f"- `{p}`" for p in branches_created)
            + "\n"
        )
    if disposition_synced:
        report = (
            report
            + "\n\n## Disposition sync (this run)\n\n"
            + "\n".join(f"- `disposition: implemented` → `{p}`" for p in disposition_synced)
            + "\n"
        )
    if archive_applied:
        report = (
            report
            + "\n\n## Plans archived (this run)\n\n"
            + "\n".join(f"- `{p}`" for p in archive_applied)
            + "\n"
        )
    if pruned_stale_links:
        report = (
            report
            + "\n\n## Stale master links removed (this run)\n\n"
            + "\n".join(f"- `{p}`" for p in pruned_stale_links)
            + "\n"
        )
    if overlap_relations_applied:
        report = (
            report
            + "\n\n## Plan files updated (overlap)\n\n"
            + "\n".join(f"- `{p}`" for p in overlap_relations_applied)
            + "\n"
        )
    if goal_tags_applied:
        report = (
            report
            + "\n\n## Plan files updated (goal tags)\n\n"
            + "\n".join(f"- `{p}`" for p in goal_tags_applied)
            + "\n"
        )
    dated_path = out_dir / f"plan-audit-{args.report_date}.md"
    dated_path.write_text(report, encoding="utf-8")

    latest_path = out_dir / "latest.md"
    shutil.copyfile(dated_path, latest_path)

    plan_ranks, rank_source = compute_plan_ranks(
        master_doc,
        cards_by_source,
        repo_root=repo_root,
        master_path=master_path,
    )
    actions = detect_actions(list(cards_by_source.values()), repo_root=repo_root)

    board = render_task_board_markdown(
        args.report_date,
        items,
        cards_by_source=cards_by_source,
        plan_ranks=plan_ranks,
        provenance=provenance,
    )
    (out_dir / "plan-task-board.md").write_text(board, encoding="utf-8")

    if master_path and master_path.is_file():
        sync_master_archived_batch(
            repo_root,
            master_path,
            default_owner=default_owner,
        )
        master_doc = parse_master_plan(master_path, repo_root)

    # Master mirror (drift-aware).
    synced_master_entries = sync_master_plan(
        master_path,
        repo_root,
        list(cards_by_source.values()),
    )
    if synced_master_entries and master_path:
        master_doc = parse_master_plan(master_path, repo_root)
    mirror = render_master_mirror(
        list(cards_by_source.values()),
        master_doc,
        repo_root=repo_root,
        report_date=args.report_date,
        provenance=provenance,
        plan_ranks=plan_ranks,
        rank_source=rank_source,
        actions=actions,
        overlap_edges=overlap_edges,
        overlap_clusters=overlap_clusters,
        goal_alignments=goal_alignments,
        goal_context=goal_context,
    )
    (out_dir / "master-plan.md").write_text(mirror, encoding="utf-8")

    overlap_relations = render_overlap_relations_markdown(
        args.report_date,
        overlap_edges,
        overlap_clusters,
        cards_by_source,
    )
    (out_dir / "overlap-relations.md").write_text(overlap_relations, encoding="utf-8")

    # Triage queue (`next-actions.md`).
    next_actions = render_next_actions(
        actions,
        ready_to_archive=ready_to_archive,
        report_date=args.report_date,
        provenance=provenance,
        plan_ranks=plan_ranks,
    )
    if synced_master_entries:
        next_actions += (
            "\n## Master plan sync (this run)\n\n"
            + "\n".join(f"- added to `_master.plan.md`: `{src}`" for src in synced_master_entries)
            + "\n"
        )
    if branch_links:
        next_actions += (
            "\n## Plan branch links (this run)\n\n"
            + "\n".join(f"- frontmatter updated: `{src}`" for src in branch_links)
            + "\n"
        )
    if disposition_synced:
        next_actions += (
            "\n## Disposition sync (this run)\n\n"
            + "\n".join(f"- `disposition: implemented` → `{src}`" for src in disposition_synced)
            + "\n"
        )
    if archive_applied:
        next_actions += (
            "\n## Plans archived (this run)\n\n"
            + "\n".join(f"- `{src}`" for src in archive_applied)
            + "\n"
        )
    if overlap_relations_applied:
        next_actions += (
            "\n## Overlap relations applied (this run)\n\n"
            + "\n".join(f"- `{src}`" for src in overlap_relations_applied)
            + "\n"
        )
    if goal_tags_applied:
        next_actions += (
            "\n## Goal tags applied (this run)\n\n"
            + "\n".join(f"- `{src}`" for src in goal_tags_applied)
            + "\n"
        )
    (out_dir / "next-actions.md").write_text(next_actions, encoding="utf-8")

    print(str(dated_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
