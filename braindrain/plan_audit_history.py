"""Plan audit report history — discover, parse, snapshot, and lifecycle analytics."""

from __future__ import annotations

import datetime as dt
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml
from scripts.plan_branch_utils import FRONTMATTER_BLOCK_RE, parse_plan_frontmatter

HISTORY_ROW_SCHEMA_VERSION = "1.0"
SNAPSHOT_CONTRACT_VERSION = "1.0"
DEFAULT_REPORTS_SUBDIR = ".braindrain/plan-reports"
JSONL_FILENAME = "plan-audit-history.jsonl"

COUNT_KEYS = ("implemented", "in_progress", "blocked", "outstanding", "unknown")
SCORE_KEYS = ("overlap_score", "gap_score", "coverage_score")
ITEM_KEYS = ("implemented", "in_progress", "blocked", "outstanding", "unknown")

DISPOSITION_HEADER_RE = re.compile(r"^#### Disposition:\s*`([^`]+)`\s*$", re.MULTILINE)
PLAN_CARD_TITLE_RE = re.compile(
    r"^- \*\*(.+?)\*\* \(`([^`]+)`\)",
    re.MULTILINE,
)
PLAN_ITEMS_RE = re.compile(
    r"Items:\s*Implemented=(\d+)\s*/\s*InProgress=(\d+)\s*/\s*"
    r"Blocked=(\d+)\s*/\s*Outstanding=(\d+)\s*/\s*Unknown=(\d+)",
)
PLAN_SOURCE_RE = re.compile(r"^\s+- Source:\s*\[`([^`]+)`\]", re.MULTILINE)
DATE_IN_REPORT_RE = re.compile(r"plan-audit-(\d{4}-\d{2}-\d{2})")

STALL_DAYS_DEFAULT = 14
REGRESSION_WINDOW = 7
COVERAGE_ALERT_THRESHOLD = 3


def _reports_dir(repo_root: Path) -> Path:
    return repo_root / DEFAULT_REPORTS_SUBDIR


def _jsonl_path(repo_root: Path) -> Path:
    return _reports_dir(repo_root) / JSONL_FILENAME


def _strip_yaml_scalar(value: str) -> str | int | bool:
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
        return int(value)
    if value in {"true", "false"}:
        return value == "true"
    return value


def parse_audit_frontmatter_body(body: str) -> dict[str, Any]:
    """Parse audit report frontmatter with nested mappings (no PyYAML)."""
    root: dict[str, Any] = {}
    # Each frame: indent level, container dict, optional list key being filled
    stack: list[tuple[int, dict[str, Any], str | None]] = [(0, root, None)]

    for raw in body.splitlines():
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()

        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()

        container = stack[-1][1]

        if stripped.startswith("- "):
            value = _strip_yaml_scalar(stripped[2:])
            list_key = stack[-1][2]
            if list_key and isinstance(container.get(list_key), list):
                container[list_key].append(value)
            continue

        if ":" not in stripped:
            continue
        key, _, rest = stripped.partition(":")
        key = key.strip()
        rest = rest.strip()

        if not rest:
            # Peek ahead: nested mapping vs list
            nested: dict[str, Any] = {}
            container[key] = nested
            stack.append((indent + 2, nested, None))
            continue

        container[key] = _strip_yaml_scalar(rest)

    # Second pass: convert empty dicts that should be lists (list items follow)
    lines = body.splitlines()
    for i, raw in enumerate(lines):
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()
        if ":" not in stripped or stripped.startswith("- "):
            continue
        key, _, rest = stripped.partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest:
            continue
        if i + 1 < len(lines):
            nxt = lines[i + 1]
            if nxt.lstrip().startswith("- "):
                # Walk stack to find parent at this indent
                parent = root
                for raw2 in lines[: i + 1]:
                    if not raw2.strip():
                        continue
                    ind2 = len(raw2) - len(raw2.lstrip(" "))
                    st2 = raw2.strip()
                    if st2.startswith("- "):
                        continue
                    if ":" not in st2:
                        continue
                    k2, _, v2 = st2.partition(":")
                    k2 = k2.strip()
                    v2 = v2.strip()
                    if not v2 and ind2 == indent and k2 == key:
                        parent[key] = []
                        stack_list = parent[key]
                        j = i + 1
                        while j < len(lines):
                            row = lines[j]
                            if not row.strip():
                                j += 1
                                continue
                            if len(row) - len(row.lstrip(" ")) <= indent:
                                break
                            if row.lstrip().startswith("- "):
                                stack_list.append(_strip_yaml_scalar(row.lstrip()[2:]))
                            j += 1
                        break
                    if not v2 and isinstance(parent.get(k2), dict):
                        parent = parent[k2]
    return root


def parse_audit_frontmatter(path: Path) -> dict[str, Any]:
    """Parse leading YAML frontmatter from a dated audit report."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    match = FRONTMATTER_BLOCK_RE.match(text)
    if not match:
        return parse_plan_frontmatter(text)
    body = match.group(1)
    try:
        loaded = yaml.safe_load(body)
        if isinstance(loaded, dict):
            return loaded
    except yaml.YAMLError:
        pass
    return parse_audit_frontmatter_body(body)


def discover_audit_reports(reports_dir: Path) -> list[Path]:
    """Glob plan-audit-*.md, skip *-final.md, dedupe by report_date (newest mtime)."""
    if not reports_dir.is_dir():
        return []
    by_date: dict[str, Path] = {}
    mtimes: dict[str, float] = {}
    for path in sorted(reports_dir.glob("plan-audit-*.md")):
        name = path.name
        if name.endswith("-final.md"):
            continue
        m = DATE_IN_REPORT_RE.search(name)
        if not m:
            continue
        date_key = m.group(1)
        mtime = path.stat().st_mtime
        prev = mtimes.get(date_key, -1.0)
        if date_key not in by_date or mtime > prev:
            by_date[date_key] = path
            mtimes[date_key] = mtime
    return [by_date[k] for k in sorted(by_date)]


_RISK_STOP_WORDS = frozenset({"or", "and", "the", "a", "plans", "plan"})


def normalize_risk(text: str) -> str:
    """Canonicalize top_risks strings for recurrence counting."""
    s = str(text or "").lower()
    s = re.sub(r"\d+", "", s)
    s = re.sub(r"\d{4}-\d{2}-\d{2}", "", s)
    s = re.sub(r"[@#:,.`—–\-()]", " ", s)
    words = [w for w in re.sub(r"\s+", " ", s).split() if w and w not in _RISK_STOP_WORDS]
    return " ".join(words)


def parse_plan_cards(body: str) -> list[dict[str, Any]]:
    """Extract per-plan rollups from v1.1+ plan card sections."""
    if "#### Disposition:" not in body and "Items: Implemented=" not in body:
        return []
    cards: list[dict[str, Any]] = []
    disposition = "unknown"
    for line in body.splitlines():
        disp_m = DISPOSITION_HEADER_RE.match(line)
        if disp_m:
            disposition = disp_m.group(1).strip()
            continue
        title_m = PLAN_CARD_TITLE_RE.match(line)
        if not title_m:
            continue
        slug = title_m.group(2).strip()
        cards.append(
            {
                "slug": slug,
                "title": title_m.group(1).strip(),
                "disposition": disposition,
                "source": "",
                "items": {k: 0 for k in ITEM_KEYS},
            }
        )
    for card in cards:
        slug = card["slug"]
        slug_pat = re.escape(slug)
        block_m = re.search(
            rf"- \*\*[^*]+\*\* \(`{slug_pat}`\)(.*?)(?=\n- \*\*|\n#### |\Z)",
            body,
            re.DOTALL,
        )
        if not block_m:
            continue
        block = block_m.group(1)
        src_m = PLAN_SOURCE_RE.search(block)
        if src_m:
            card["source"] = src_m.group(1).strip()
        items_m = PLAN_ITEMS_RE.search(block)
        if items_m:
            card["items"] = {
                "implemented": int(items_m.group(1)),
                "in_progress": int(items_m.group(2)),
                "blocked": int(items_m.group(3)),
                "outstanding": int(items_m.group(4)),
                "unknown": int(items_m.group(5)),
            }
    return cards


def _coerce_counts(raw: Any) -> dict[str, int]:
    out = {k: 0 for k in COUNT_KEYS}
    if isinstance(raw, dict):
        for k in COUNT_KEYS:
            val = raw.get(k, 0)
            try:
                out[k] = int(val)
            except (TypeError, ValueError):
                out[k] = 0
    return out


def _coerce_scores(raw: Any) -> dict[str, int]:
    out = {k: 0 for k in SCORE_KEYS}
    if isinstance(raw, dict):
        for k in SCORE_KEYS:
            val = raw.get(k, 0)
            try:
                out[k] = int(val)
            except (TypeError, ValueError):
                out[k] = 0
    return out


def _parse_sources(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return {"primary_plan_files": raw, "secondary_docs_count": 0}
    return {"primary_plan_files": [], "secondary_docs_count": 0}


def _series_entry_from_report(path: Path, fm: dict[str, Any], body: str) -> dict[str, Any]:
    report_date = str(fm.get("report_date") or "")
    if not report_date:
        m = DATE_IN_REPORT_RE.search(path.name)
        report_date = m.group(1) if m else ""
    sources = _parse_sources(fm.get("sources"))
    primary = sources.get("primary_plan_files") or []
    plan_count = len(primary) if isinstance(primary, list) else 0
    schema = str(fm.get("schema_version") or "1.0")
    plans = parse_plan_cards(body) if schema >= "1.1" or "Plan Cards" in body else []
    if plans:
        plan_count = len(plans)
    return {
        "date": report_date,
        "trigger": str(fm.get("trigger") or "unknown"),
        "counts": _coerce_counts(fm.get("summary_counts")),
        "scores": _coerce_scores(fm.get("analysis_scores")),
        "plan_count": plan_count,
        "plans": plans,
        "source_file": path.name,
        "schema_version": schema,
        "top_risks": list(fm.get("top_risks") or [])
        if isinstance(fm.get("top_risks"), list)
        else [],
    }


def parse_audit_report(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Parse one report file; return (series_entry, skip_reason)."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        fm = parse_audit_frontmatter(path)
        if not fm.get("report_date") and not DATE_IN_REPORT_RE.search(path.name):
            return None, "missing report_date"
        body = text
        match = FRONTMATTER_BLOCK_RE.match(text)
        if match:
            body = text[match.end() :]
        return _series_entry_from_report(path, fm, body), None
    except OSError as exc:
        return None, str(exc)
    except Exception as exc:
        return None, f"parse error: {exc}"


def load_jsonl_history(repo_root: Path) -> list[dict[str, Any]]:
    path = _jsonl_path(repo_root)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            if isinstance(row, dict) and row.get("date"):
                rows.append(row)
        except json.JSONDecodeError:
            continue
    return rows


def compact_series_row(entry: dict[str, Any]) -> dict[str, Any]:
    """Compact row for JSONL append (no bulky fields)."""
    plans = entry.get("plans") or []
    compact_plans = []
    for p in plans:
        if not isinstance(p, dict):
            continue
        compact_plans.append(
            {
                "slug": p.get("slug", ""),
                "source": p.get("source", ""),
                "disposition": p.get("disposition", ""),
                "items": p.get("items") or {},
            }
        )
    return {
        "schema_version": HISTORY_ROW_SCHEMA_VERSION,
        "date": entry.get("date", ""),
        "trigger": entry.get("trigger", ""),
        "counts": entry.get("counts") or {},
        "scores": entry.get("scores") or {},
        "plan_count": entry.get("plan_count", 0),
        "plans": compact_plans,
        "source_file": entry.get("source_file", ""),
    }


def append_history_jsonl_row(repo_root: Path, entry: dict[str, Any]) -> Path:
    """Append or replace JSONL row for the same report_date (idempotent)."""
    path = _jsonl_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = compact_series_row(entry)
    date_key = row.get("date", "")
    existing: list[dict[str, Any]] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict) and parsed.get("date") != date_key:
                    existing.append(parsed)
            except json.JSONDecodeError:
                continue
    existing.append(row)
    existing.sort(key=lambda r: str(r.get("date", "")))
    path.write_text(
        "\n".join(json.dumps(r, separators=(",", ":")) for r in existing) + "\n",
        encoding="utf-8",
    )
    return path


def _parse_reports_to_series(
    reports_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    series: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for path in discover_audit_reports(reports_dir):
        entry, reason = parse_audit_report(path)
        if entry is None:
            skipped.append({"file": path.name, "reason": reason or "unknown"})
            continue
        series.append(entry)
    series.sort(key=lambda s: s.get("date", ""))
    return series, skipped


def _merge_jsonl_with_md(
    jsonl_rows: list[dict[str, Any]],
    md_series: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Prefer JSONL when present; fill gaps from markdown re-parse."""
    by_date: dict[str, dict[str, Any]] = {}
    for row in md_series:
        by_date[str(row.get("date", ""))] = row
    for row in jsonl_rows:
        by_date[str(row.get("date", ""))] = row
    return [by_date[k] for k in sorted(by_date)]


def _downsample_series(
    series: list[dict[str, Any]],
    *,
    window_days: int | None,
    max_points: int | None,
) -> list[dict[str, Any]]:
    if not series:
        return series
    if window_days is not None and window_days > 0:
        cutoff = (dt.date.today() - dt.timedelta(days=window_days)).isoformat()
        series = [s for s in series if str(s.get("date", "")) >= cutoff]
    if max_points is not None and len(series) > max_points > 0:
        if len(series) <= max_points:
            return series
        step = max(1, len(series) // max_points)
        sampled = [series[i] for i in range(0, len(series), step)]
        if sampled[-1] != series[-1]:
            sampled.append(series[-1])
        return sampled[:max_points]
    return series


def _derive_recurring_risks(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for point in series:
        date = str(point.get("date", ""))
        for risk in point.get("top_risks") or []:
            norm = normalize_risk(str(risk))
            if not norm:
                continue
            if norm not in buckets:
                buckets[norm] = {
                    "text": str(risk),
                    "occurrences": 0,
                    "first_seen": date,
                    "last_seen": date,
                }
            buckets[norm]["occurrences"] += 1
            buckets[norm]["last_seen"] = date
    ranked = sorted(buckets.values(), key=lambda r: (-int(r["occurrences"]), r["text"]))
    return ranked[:20]


def _derive_plan_lifecycles(
    series: list[dict[str, Any]],
    *,
    stall_days: int = STALL_DAYS_DEFAULT,
) -> list[dict[str, Any]]:
    by_slug: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for point in series:
        date = str(point.get("date", ""))
        for plan in point.get("plans") or []:
            if not isinstance(plan, dict):
                continue
            slug = str(plan.get("slug") or "").strip()
            if not slug:
                continue
            by_slug[slug].append((date, plan))

    lifecycles: list[dict[str, Any]] = []
    for slug, observations in sorted(by_slug.items()):
        observations.sort(key=lambda x: x[0])
        first_seen = observations[0][0]
        last_seen = observations[-1][0]
        transitions: list[dict[str, str]] = []
        prev_disp = ""
        prev_items: dict[str, int] | None = None
        unchanged_runs = 0
        for date, plan in observations:
            disp = str(plan.get("disposition") or "")
            items = plan.get("items") or {}
            if prev_disp and disp and disp != prev_disp:
                transitions.append({"date": date, "from": prev_disp, "to": disp})
            if prev_items is not None and items == prev_items:
                unchanged_runs += 1
            else:
                unchanged_runs = 0
            prev_disp = disp or prev_disp
            prev_items = dict(items) if isinstance(items, dict) else prev_items

        try:
            days_active = (
                dt.date.fromisoformat(last_seen) - dt.date.fromisoformat(first_seen)
            ).days
        except ValueError:
            days_active = 0

        last_plan = observations[-1][1]
        last_disp = str(last_plan.get("disposition") or "")
        stalled = last_disp == "active" and unchanged_runs >= 2 and days_active >= stall_days

        impl_30d = 0
        if len(observations) >= 2:
            try:
                end_d = dt.date.fromisoformat(last_seen)
                start_cut = (end_d - dt.timedelta(days=30)).isoformat()
                window = [(d, p) for d, p in observations if d >= start_cut]
                if len(window) >= 2:
                    first_items = window[0][1].get("items") or {}
                    last_items = window[-1][1].get("items") or {}
                    impl_30d = int(last_items.get("implemented", 0)) - int(
                        first_items.get("implemented", 0)
                    )
            except ValueError:
                impl_30d = 0

        lifecycles.append(
            {
                "slug": slug,
                "first_seen": first_seen,
                "last_seen": last_seen,
                "disposition_transitions": transitions,
                "days_active": days_active,
                "stalled": stalled,
                "implemented_delta_30d": impl_30d,
                "last_disposition": last_disp,
            }
        )
    return lifecycles


def _detect_regressions(
    series: list[dict[str, Any]], window: int = REGRESSION_WINDOW
) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    if len(series) < window + 1:
        return flags
    for i in range(window, len(series)):
        window_slice = series[i - window : i + 1]
        blocked_start = int((window_slice[0].get("counts") or {}).get("blocked", 0))
        blocked_end = int((window_slice[-1].get("counts") or {}).get("blocked", 0))
        impl_start = int((window_slice[0].get("counts") or {}).get("implemented", 0))
        impl_end = int((window_slice[-1].get("counts") or {}).get("implemented", 0))
        if blocked_end > blocked_start and impl_end <= impl_start:
            flags.append(
                {
                    "type": "regression",
                    "date": str(window_slice[-1].get("date", "")),
                    "message": (
                        f"Blocked rose {blocked_start}→{blocked_end} while implemented "
                        f"stayed flat ({impl_start}→{impl_end}) over {window} reports"
                    ),
                }
            )
    return flags[-3:]


def _coverage_alerts(
    series: list[dict[str, Any]], threshold: int = COVERAGE_ALERT_THRESHOLD
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for point in series[-5:]:
        score = int((point.get("scores") or {}).get("coverage_score", 100))
        if score < threshold:
            alerts.append(
                {
                    "type": "coverage",
                    "date": str(point.get("date", "")),
                    "score": score,
                    "message": (
                        f"Coverage score {score} below threshold {threshold} — "
                        "review ownership/test-evidence gaps in auditor rules"
                    ),
                }
            )
    return alerts


def _summary_from_series(series: list[dict[str, Any]]) -> dict[str, Any]:
    if not series:
        return {
            "report_count": 0,
            "date_range": [],
            "deltas": {k: 0 for k in COUNT_KEYS},
            "peak_blocked": {"date": "", "value": 0},
            "trigger_counts": {},
            "recurring_risks": [],
            "pre_card_era_end": "",
        }
    first, last = series[0], series[-1]
    deltas = {}
    for k in COUNT_KEYS:
        deltas[k] = int((last.get("counts") or {}).get(k, 0)) - int(
            (first.get("counts") or {}).get(k, 0)
        )
    peak_blocked = {"date": "", "value": 0}
    for point in series:
        val = int((point.get("counts") or {}).get("blocked", 0))
        if val >= peak_blocked["value"]:
            peak_blocked = {"date": str(point.get("date", "")), "value": val}
    triggers = Counter(str(p.get("trigger") or "unknown") for p in series)
    pre_card_end = ""
    for point in series:
        if point.get("plans"):
            break
        pre_card_end = str(point.get("date", ""))
    return {
        "report_count": len(series),
        "date_range": [str(first.get("date", "")), str(last.get("date", ""))],
        "deltas": deltas,
        "peak_blocked": peak_blocked,
        "trigger_counts": dict(triggers),
        "recurring_risks": _derive_recurring_risks(series),
        "pre_card_era_end": pre_card_end,
    }


def build_history_snapshot(
    repo_root: Path,
    *,
    window_days: int | None = None,
    max_points: int | None = None,
    prefer_jsonl: bool = True,
) -> dict[str, Any]:
    """Build versioned history snapshot JSON from reports + optional JSONL cache."""
    repo_root = Path(repo_root).resolve()
    reports_dir = _reports_dir(repo_root)
    md_series, skipped = _parse_reports_to_series(reports_dir)
    jsonl_rows = load_jsonl_history(repo_root) if prefer_jsonl else []
    if jsonl_rows and len(jsonl_rows) < len(md_series):
        series = _merge_jsonl_with_md(jsonl_rows, md_series)
    elif jsonl_rows:
        series = _merge_jsonl_with_md(jsonl_rows, md_series)
    else:
        series = md_series

    full_count = len(series)
    series = _downsample_series(series, window_days=window_days, max_points=max_points)
    summary = _summary_from_series(series if series else md_series)
    lifecycles = _derive_plan_lifecycles(md_series)
    stalled = [lc for lc in lifecycles if lc.get("stalled")]
    regressions = _detect_regressions(md_series)
    coverage_alerts = _coverage_alerts(md_series)

    return {
        "contract_version": SNAPSHOT_CONTRACT_VERSION,
        "generated_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "reports_dir": DEFAULT_REPORTS_SUBDIR,
        "series": series,
        "full_series_count": full_count,
        "summary": summary,
        "plan_lifecycles": lifecycles,
        "alerts": {
            "stalled_plans": stalled[:15],
            "regressions": regressions,
            "coverage": coverage_alerts,
        },
        "skipped": skipped,
    }


def backfill_history_jsonl(repo_root: Path) -> dict[str, Any]:
    """Scan all audit .md files and seed/replace JSONL rows."""
    repo_root = Path(repo_root).resolve()
    reports_dir = _reports_dir(repo_root)
    series, skipped = _parse_reports_to_series(reports_dir)
    path = _jsonl_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [compact_series_row(entry) for entry in series]
    path.write_text(
        "\n".join(json.dumps(r, separators=(",", ":")) for r in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
    return {"jsonl_path": str(path), "rows_written": len(rows), "skipped": skipped}
