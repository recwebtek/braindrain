#!/usr/bin/env python3
"""Generate a daily planning audit report in markdown format.

Priority source order:
1) .cursor/plans/*.plan.md
2) Secondary markdown docs in repo
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = "1.0"
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


@dataclasses.dataclass
class PlanItem:
    item: str
    source: str
    status: str
    confidence: str
    evidence: list[str]
    why: str
    tokens: set[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily planning audit report generator")
    parser.add_argument("--repo-root", default=".", help="Repository root")
    parser.add_argument(
        "--output-dir",
        default="create-subagent",
        help="Output directory for markdown reports (repo-relative if not absolute)",
    )
    parser.add_argument("--report-date", default=dt.date.today().isoformat())
    parser.add_argument("--trigger", default="cursor-stop-daily-gated")
    return parser.parse_args()


def is_secondary_doc(path: Path) -> bool:
    lowered = path.as_posix().lower()
    if "/.git/" in lowered:
        return False
    if "/create-subagent/" in lowered:
        return False
    if "/.cursor/plans/" in lowered:
        return False
    if "/.cursor/agents/" in lowered:
        return False
    if "/config/templates/" in lowered:
        return False
    if path.suffix.lower() != ".md":
        return False
    filename = path.name.lower()
    return any(k in filename for k in ("plan", "roadmap", "todo", "task", "backlog", "milestone", "prd"))


def discover_sources(repo_root: Path) -> tuple[list[Path], list[Path]]:
    primary = sorted((repo_root / ".cursor" / "plans").glob("*.plan.md"))
    secondary: list[Path] = []
    for path in repo_root.rglob("*.md"):
        if is_secondary_doc(path):
            snippet = path.read_text(encoding="utf-8", errors="ignore")[:2500].lower()
            if any(k in snippet for k in PLANNING_KEYWORDS):
                secondary.append(path)
    secondary.sort()
    return primary, secondary


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


def detect_gaps(items: list[PlanItem]) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    for item in items:
        if item.status not in {"Outstanding", "In Progress", "Blocked"}:
            continue
        lowered = item.item.lower()
        has_owner = "@" in item.item or "owner" in lowered
        has_test_hint = "test" in lowered
        has_path_evidence = any("/" in ev for ev in item.evidence)
        missing = []
        if not has_owner:
            missing.append("owner")
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


def build_report(
    report_date: str,
    trigger: str,
    repo_root: Path,
    primary: list[Path],
    secondary: list[Path],
    items: list[PlanItem],
) -> str:
    overlaps = detect_overlaps(items)
    gaps = detect_gaps(items)
    scores = score_report(items, overlaps, gaps)
    summary_counts = Counter(item.status for item in items)
    mem = memory_context(repo_root)

    top_risks: list[str] = []
    if any(i.status == "Blocked" for i in items):
        top_risks.append("Blocked plan items require immediate owner assignment.")
    if gaps:
        top_risks.append("Open items are missing owner/test/evidence details.")
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
            body.append(
                f"- [{item.status}] `{item.source}`: add owner/test/evidence updates for `{item.item}`."
            )
    body.append("")
    return "\n".join(body)


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = repo_root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    primary, secondary = discover_sources(repo_root)

    items: list[PlanItem] = []
    for path in primary:
        items.extend(collect_items(path, repo_root))
    for path in secondary:
        items.extend(collect_items(path, repo_root))

    report = build_report(args.report_date, args.trigger, repo_root, primary, secondary, items)
    dated_path = out_dir / f"plan-audit-{args.report_date}.md"
    dated_path.write_text(report, encoding="utf-8")

    latest_path = out_dir / "latest.md"
    shutil.copyfile(dated_path, latest_path)
    print(str(dated_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
