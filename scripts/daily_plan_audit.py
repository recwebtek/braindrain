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
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path


SCHEMA_VERSION = "1.1"
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

# Map disposition -> action verb shown in next-actions queue. The `active`
# disposition resolves to IMPLEMENT only when item-level signals say so;
# otherwise it stays off the triage queue. `scratched` and `implemented`
# never appear in the queue.
DISPOSITION_VERB = {
    "research-needed": "RESEARCH",
    "replan-needed": "REPLAN",
    "merge-ready": "MERGE",
    "needs-fix": "FIX",
    "backlogged": "BACKLOG",
}

# Frontmatter parser regexes (no PyYAML dependency — keeps script standalone).
FRONTMATTER_BLOCK_RE = re.compile(
    r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL
)
FRONTMATTER_KV_RE = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*?)\s*$"
)


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def parse_plan_frontmatter(path_or_text) -> dict[str, object]:
    """Parse a leading YAML frontmatter block.

    Supports the small subset we actually use: scalars, quoted scalars,
    inline lists like `delegated_to: [a, b]`, and indented bullet lists:

        delegated_to:
          - gitops
          - testops

    Anything else (nested maps, anchors) is ignored — keeps the parser
    dependency-free. Returns an empty dict when no frontmatter is present.
    """
    if isinstance(path_or_text, Path):
        text = path_or_text.read_text(encoding="utf-8", errors="ignore")
    else:
        text = str(path_or_text or "")

    match = FRONTMATTER_BLOCK_RE.match(text)
    if not match:
        return {}

    body = match.group(1)
    out: dict[str, object] = {}
    current_key: str | None = None
    current_list: list[str] | None = None

    for raw in body.splitlines():
        if not raw.strip():
            continue
        # Indented bullet for an active list key.
        if current_list is not None and re.match(r"^\s+-\s+", raw):
            value = re.sub(r"^\s+-\s+", "", raw).strip()
            current_list.append(_strip_quotes(value))
            continue
        # New top-level key resets list capture.
        kv = FRONTMATTER_KV_RE.match(raw)
        if not kv:
            current_list = None
            continue
        key = kv.group(1)
        value = kv.group(2)
        current_list = None
        if not value:
            current_list = []
            out[key] = current_list
            current_key = key
            continue
        # Inline list like `[a, b, c]`.
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            parts = [
                _strip_quotes(p.strip())
                for p in inner.split(",")
                if p.strip()
            ]
            out[key] = parts
            current_key = key
            continue
        out[key] = _strip_quotes(value)
        current_key = key
    return out


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
            handle = (
                ctx.get("summary", {})
                .get("identity", {})
                .get("username", "")
            ) or ""
        except Exception:
            handle = ""

    # 3) getpass / env.
    if not handle:
        try:
            handle = getpass.getuser()
        except Exception:
            handle = os.environ.get("USER", "") or os.environ.get(
                "LOGNAME", ""
            )

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

    verb: str                 # RESEARCH | REPLAN | MERGE | IMPLEMENT | BACKLOG | FIX
    plan_slug: str
    plan_source: str
    ide: str
    title: str                # plan title for human display
    reason: str               # short human reason
    hint: str                 # actionable hint
    priority: str             # P0..P3
    item_excerpt: str = ""    # optional — first item snippet that drove this


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
        fm.get("owner")
        or fm.get("dri")
        or default_owner
        or resolve_default_owner(repo_root)
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

    title = ""
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = HEADING_RE.match(line)
        if m:
            title = m.group(1).strip()
            break
    if not title:
        title = str(fm.get("name") or path.stem)

    items = items or []
    counts = Counter(i.status for i in items)

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
    return any(k in filename for k in ("plan", "roadmap", "todo", "task", "backlog", "milestone", "prd"))


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
    cards_by_source: dict[str, "PlanCard"] | None = None,
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
        plan_has_owner = bool(
            plan_card and plan_card.owner and plan_card.owner != "@user"
        )
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
    "MERGE",      # ship now
    "FIX",        # broken regressions
    "REPLAN",     # needs rewrite before more work
    "RESEARCH",   # unblock with investigation
    "IMPLEMENT",  # active work missing tests/evidence
    "BACKLOG",    # surfaced only for high-priority deferred plans
)


def _first_active_item_excerpt(card: "PlanCard") -> str:
    for it in card.items:
        if it.status in {"Blocked", "In Progress", "Outstanding"}:
            text = it.item.replace("\n", " ").strip()
            if len(text) > 140:
                text = text[:137] + "..."
            return text
    return ""


def detect_actions(
    cards: list["PlanCard"],
    *,
    backlog_priority_threshold: str = "P1",
) -> list[Action]:
    """Translate plan dispositions + item signals into concrete next-action verbs.

    Rules:
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

        if card.disposition == "active":
            has_active_item = any(
                it.status in {"Blocked", "In Progress", "Outstanding"}
                for it in card.items
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
        }[verb]
        hint = {
            "RESEARCH": "answer the open question(s); update plan with findings",
            "REPLAN": "rewrite the plan; archive the old version",
            "MERGE": "open PR; pass CI; merge",
            "FIX": "reproduce regression; ship fix; add regression test",
            "BACKLOG": "decide: promote to active or scratch",
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


def render_task_board_markdown(
    report_date: str,
    items: list[PlanItem],
    *,
    cards_by_source: dict[str, "PlanCard"] | None = None,
) -> str:
    """Single markdown table of active work, regenerated each audit run.

    When ``cards_by_source`` is provided, the Owner column inherits from the
    parent plan when an item lacks its own ``@name`` marker, and the IDE tag
    travels in a new ``IDE`` column.
    """
    cards_by_source = cards_by_source or {}
    rows: list[PlanItem] = [
        i
        for i in items
        if i.status in {"Blocked", "In Progress", "Outstanding"}
    ]
    rows.sort(
        key=lambda i: (
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
        "| IDE | Status | Owner | Item | Source | Gaps |",
        "|-----|--------|-------|------|--------|------|",
    ]
    for item in rows:
        plan_card = cards_by_source.get(item.source)
        plan_has_owner = bool(
            plan_card and plan_card.owner and plan_card.owner != "@user"
        )
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
        ide_cell = (plan_card.ide if plan_card and plan_card.ide else "—")
        lines.append(
            f"| {ide_cell} | {item.status} | {owner_cell} | {item_cell} | {src_cell} | {gaps_cell} |"
        )
    if not rows:
        lines.append("| — | — | — | _No blocked/in-progress/outstanding items parsed._ | — | — |")
    lines.append("")
    return "\n".join(lines)


def memory_context(repo_root: Path) -> dict[str, object]:
    candidates = [
        repo_root / ".braindrain" / "AGENT_MEMORY.md",
        repo_root / ".cursor" / "hooks" / "state" / "continual-learning-index.json",
    ]
    existing = [p for p in candidates if p.exists()]
    return {
        "used": bool(existing),
        "sources": [p.relative_to(repo_root).as_posix() for p in existing],
    }


def score_report(items: list[PlanItem], overlaps: list[dict[str, str]], gaps: list[dict[str, str]]) -> dict[str, int]:
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
    "research-needed",
    "replan-needed",
    "backlogged",
    "scratched",
    "implemented",
)


def render_plan_cards(
    cards: list["PlanCard"],
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
            top_verb = (
                f"`{top_actions[0].verb}` -> {top_actions[0].hint}"
                if top_actions
                else "—"
            )
            delegated = (
                ", ".join(card.delegated_to) if card.delegated_to else "none"
            )
            lines.append(f"- **{card.title}** (`{card.slug}`)")
            lines.append(f"  - Source: [`{card.source}`]({card.source})")
            lines.append(
                f"  - Owner: {card.owner} (DRI: {card.dri}) — Priority: `{card.priority}`"
            )
            lines.append(f"  - Delegated to: {delegated}")
            lines.append(f"  - Items: {' / '.join(rollup_parts)}")
            lines.append(f"  - Next action: {top_verb}")
            if top_actions and top_actions[0].item_excerpt:
                lines.append(
                    f"  - Excerpt: _{top_actions[0].item_excerpt}_"
                )
        lines.append("")
    return lines


def build_cards_index(
    repo_root: Path,
    primary: list[Path],
    items: list[PlanItem],
    *,
    default_owner: str | None = None,
) -> dict[str, "PlanCard"]:
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
    return cards


# Markdown link extractor used for parsing the curated master plan body.
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def parse_master_plan(master_path: Path, repo_root: Path) -> dict[str, object]:
    """Extract the list of child plans referenced by `_master.plan.md`.

    Returns a dict with:
      - ``frontmatter``: parsed YAML
      - ``children``: list of repo-relative paths in declaration order
    """
    if not master_path.is_file():
        return {"frontmatter": {}, "children": []}

    fm = parse_plan_frontmatter(master_path)
    text = master_path.read_text(encoding="utf-8", errors="ignore")
    # Strip frontmatter so we don't pull links out of it.
    body = FRONTMATTER_BLOCK_RE.sub("", text, count=1)
    master_dir = master_path.parent
    seen: set[str] = set()
    children: list[str] = []
    for label, target in _MD_LINK_RE.findall(body):
        target = target.strip()
        if not target or target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        if not target.endswith(".plan.md"):
            continue
        # Resolve the link relative to the master file, then make repo-relative.
        candidate = (master_dir / target).resolve()
        try:
            rel = candidate.relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            continue
        if rel in seen:
            continue
        seen.add(rel)
        children.append(rel)
    return {"frontmatter": fm, "children": children}


def render_next_actions(
    actions: list[Action],
    *,
    report_date: str = "",
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
    lines.append("")

    if not actions:
        lines.append("- _No active triage actions today._")
        lines.append("")
        return "\n".join(lines)

    grouped: dict[str, list[Action]] = defaultdict(list)
    for action in actions:
        grouped[action.verb].append(action)

    for verb in _VERB_ORDER:
        bucket = grouped.get(verb, [])
        if not bucket:
            continue
        lines.append(f"## {verb} ({len(bucket)})")
        lines.append("")
        for action in bucket:
            tag = f"[{action.ide or '—'}:{action.plan_slug}]"
            lines.append(
                f"- {tag} `({action.priority})` {action.reason} — {action.hint}"
            )
            link = f"  - Source: [`{action.plan_source}`]({action.plan_source})"
            lines.append(link)
            if action.item_excerpt:
                lines.append(f"  - Excerpt: _{action.item_excerpt}_")
        lines.append("")
    return "\n".join(lines)


def render_master_mirror(
    cards: list["PlanCard"],
    master_doc: dict[str, object] | None = None,
    *,
    report_date: str = "",
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
    src_note = (
        ".cursor/plans/_master.plan.md"
        if children
        else "auto (no curated master found)"
    )
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

    if not cards:
        lines.append("- _No plans discovered._")
        lines.append("")
        return "\n".join(lines)

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
                    "| Plan | Owner | Priority | Items (Impl/Active/Blocked/Out/Unk) | Source |"
                )
                lines.append(
                    "|------|-------|----------|--------------------------------------|--------|"
                )
            counts = card.counts or {}
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
                f"| {card.priority} "
                f"| {items_cell} "
                f"| `{card.source}` |"
            )
        lines.append("")

    # Drift detection.
    on_disk = {c.source for c in cards}
    in_master = set(children)
    only_disk = sorted(on_disk - in_master)
    only_master = sorted(in_master - on_disk)

    lines.append("## Drift")
    lines.append("")
    if not children:
        lines.append("- _No curated master found at `.cursor/plans/_master.plan.md`._")
        lines.append(
            f"- {len(only_disk)} plans discovered on disk; "
            "create `_master.plan.md` to formalize the index."
        )
    elif not only_disk and not only_master:
        lines.append("- _No drift: curated master matches discovered plans._")
    else:
        if only_disk:
            lines.append("### On disk but missing from curated master:")
            for src in only_disk:
                lines.append(f"- `{src}`")
        if only_master:
            lines.append("### In curated master but missing from disk:")
            for src in only_master:
                lines.append(f"- `{src}`")
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
    cards_by_source: dict[str, "PlanCard"] | None = None,
) -> str:
    overlaps = detect_overlaps(items)
    cards_by_source = cards_by_source or {}
    gaps = detect_gaps(items, cards_by_source=cards_by_source)
    scores = score_report(items, overlaps, gaps)
    summary_counts = Counter(item.status for item in items)
    mem = memory_context(repo_root)

    def _item_has_inherited_owner(it: PlanItem) -> bool:
        if has_explicit_owner(it.item):
            return True
        c = cards_by_source.get(it.source)
        return bool(c and c.owner and c.owner != "@user")

    top_risks: list[str] = []
    blocked_no_owner = [
        i for i in items
        if i.status == "Blocked" and not _item_has_inherited_owner(i)
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
        top_risks.append(
            "Some items declare `delegate:` without naming a target sub-agent."
        )
    gap_test_or_path = [
        g
        for g in gaps
        if "test" in g["missing"] or "evidence" in g["missing"]
    ]
    if gap_test_or_path:
        top_risks.append("Active items are missing test hints and/or path evidence in plan text.")
    if overlaps:
        top_risks.append("Overlapping plan entries may create duplicated delivery work.")
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

    body: list[str] = []
    body.append("---")
    body.append(f"schema_version: \"{frontmatter['schema_version']}\"")
    body.append(f"report_date: \"{frontmatter['report_date']}\"")
    body.append(f"trigger: \"{frontmatter['trigger']}\"")
    body.append("sources:")
    body.append("  primary_plan_files:")
    for plan_file in frontmatter["sources"]["primary_plan_files"]:
        body.append(f"    - \"{plan_file}\"")
    body.append(f"  secondary_docs_count: {frontmatter['sources']['secondary_docs_count']}")
    body.append("summary_counts:")
    for k, v in frontmatter["summary_counts"].items():
        body.append(f"  {k}: {v}")
    body.append("analysis_scores:")
    for k, v in frontmatter["analysis_scores"].items():
        body.append(f"  {k}: {v}")
    body.append("top_risks:")
    for risk in frontmatter["top_risks"]:
        body.append(f"  - \"{risk}\"")
    body.append("memory_context:")
    body.append(f"  used: {str(frontmatter['memory_context']['used']).lower()}")
    body.append("  sources:")
    for source in frontmatter["memory_context"]["sources"]:
        body.append(f"    - \"{source}\"")
    if not frontmatter["memory_context"]["sources"]:
        body.append("    - \"none\"")
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
    body.append("")
    body.append("## Status Matrix (5-State)")
    body.append("| Status | Count |")
    body.append("|---|---:|")
    for status in STATUS_ORDER:
        body.append(f"| {status} | {summary_counts[status]} |")
    body.append("")

    # Plan-centric cards (new in schema 1.1) — grouped by IDE then disposition.
    actions = detect_actions(list(cards_by_source.values()))
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
                wants.append(
                    "add explicit owner (@name or owner:/assignee:/dri:)"
                )
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
        items.extend(collect_items(path, repo_root))
    for path in secondary:
        items.extend(collect_items(path, repo_root))

    cards_by_source = build_cards_index(
        repo_root, primary, items, default_owner=default_owner
    )

    report = build_report(
        args.report_date,
        args.trigger,
        repo_root,
        primary,
        secondary,
        items,
        cards_by_source=cards_by_source,
    )
    if archive_moves:
        report = (
            report
            + "\n\n## Archived plan files (this run)\n\n"
            + "\n".join(f"- `{p}`" for p in archive_moves)
            + "\n"
        )
    dated_path = out_dir / f"plan-audit-{args.report_date}.md"
    dated_path.write_text(report, encoding="utf-8")

    latest_path = out_dir / "latest.md"
    shutil.copyfile(dated_path, latest_path)

    board = render_task_board_markdown(
        args.report_date, items, cards_by_source=cards_by_source
    )
    (out_dir / "plan-task-board.md").write_text(board, encoding="utf-8")

    # Master mirror (drift-aware).
    if args.master_plan:
        master_candidate = Path(args.master_plan)
        if not master_candidate.is_absolute():
            master_candidate = repo_root / master_candidate
        master_path = master_candidate if master_candidate.is_file() else None
    else:
        master_path = discover_master_plan(repo_root)

    master_doc = parse_master_plan(master_path, repo_root) if master_path else None
    mirror = render_master_mirror(
        list(cards_by_source.values()),
        master_doc,
        report_date=args.report_date,
    )
    (out_dir / "master-plan.md").write_text(mirror, encoding="utf-8")

    # Triage queue (`next-actions.md`).
    actions = detect_actions(list(cards_by_source.values()))
    next_actions = render_next_actions(actions, report_date=args.report_date)
    (out_dir / "next-actions.md").write_text(next_actions, encoding="utf-8")

    print(str(dated_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
