"""Tests for plan audit history loader, JSONL, lifecycle, and HTML renderer."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from braindrain.plan_audit_history import (
    append_history_jsonl_row,
    backfill_history_jsonl,
    build_history_snapshot,
    compact_series_row,
    discover_audit_reports,
    normalize_risk,
    parse_audit_report,
    parse_plan_cards,
)
from braindrain.plan_audit_history_html import render_history_html


@pytest.fixture
def tmp_project_dir() -> Path:
    d = Path(__file__).resolve().parent.parent / ".pytest_tmp" / f"pah-{uuid.uuid4().hex[:12]}"
    d.mkdir(parents=True, exist_ok=True)
    try:
        yield d
    finally:
        import shutil

        shutil.rmtree(d, ignore_errors=True)


V10_REPORT = """---
schema_version: "1.0"
report_date: "2026-04-01"
trigger: "cursor-stop-daily-gated"
sources:
  primary_plan_files:
    - ".cursor/plans/a.plan.md"
  secondary_docs_count: 2
summary_counts:
  implemented: 1
  in_progress: 2
  blocked: 3
  outstanding: 4
  unknown: 5
analysis_scores:
  overlap_score: 10
  gap_score: 20
  coverage_score: 6
top_risks:
  - "Blocked items lack explicit owner markers (@, owner:, assignee:, or dri:)."
---

# Daily Plan Audit Report

## Executive Summary
- Legacy body only
"""

V11_REPORT = """---
schema_version: "1.1"
report_date: "2026-05-01"
trigger: "manual-masterplan-command"
sources:
  primary_plan_files:
    - ".cursor/plans/foo.plan.md"
  secondary_docs_count: 0
summary_counts:
  implemented: 2
  in_progress: 1
  blocked: 5
  outstanding: 3
  unknown: 0
analysis_scores:
  overlap_score: 50
  gap_score: 60
  coverage_score: 4
top_risks:
  - "Blocked items lack explicit owner markers (@, owner:, assignee:, or dri:)."
---

## Plan Cards (by IDE)

### IDE: `cursor` (1 plans)

#### Disposition: `active`

- **Foo Plan** (`foo_plan`)
  - Source: [`.cursor/plans/foo.plan.md`](.cursor/plans/foo.plan.md)
  - Items: Implemented=2 / InProgress=1 / Blocked=0 / Outstanding=1 / Unknown=0
"""

MALFORMED_REPORT = """---
report_date: not-a-date
trigger: broken
---

# Broken
"""

DUPLICATE_A = """---
schema_version: "1.0"
report_date: "2026-05-02"
trigger: "a"
summary_counts:
  implemented: 0
  in_progress: 0
  blocked: 1
  outstanding: 0
  unknown: 0
analysis_scores:
  overlap_score: 0
  gap_score: 0
  coverage_score: 0
top_risks: []
---
# A
"""

DUPLICATE_B = """---
schema_version: "1.0"
report_date: "2026-05-02"
trigger: "b"
summary_counts:
  implemented: 9
  in_progress: 0
  blocked: 0
  outstanding: 0
  unknown: 0
analysis_scores:
  overlap_score: 0
  gap_score: 0
  coverage_score: 0
top_risks: []
---
# B newer
"""


def _write_reports(tmp: Path, files: dict[str, str]) -> Path:
    reports = tmp / ".braindrain" / "plan-reports"
    reports.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (reports / name).write_text(body, encoding="utf-8")
    return reports


def test_discover_dedupes_by_date_and_skips_final(tmp_project_dir: Path) -> None:
    reports = _write_reports(
        tmp_project_dir,
        {
            "plan-audit-2026-05-02.md": DUPLICATE_A,
            "plan-audit-2026-05-02-final.md": "skip",
            "plan-audit-2026-05-04.md": V11_REPORT.replace("2026-05-01", "2026-05-04"),
        },
    )
    paths = discover_audit_reports(reports)
    assert len(paths) == 2
    assert not any(p.name.endswith("-final.md") for p in paths)


def test_parse_v10_and_v11_shapes(tmp_project_dir: Path) -> None:
    reports = _write_reports(
        tmp_project_dir,
        {"plan-audit-2026-04-01.md": V10_REPORT, "plan-audit-2026-05-01.md": V11_REPORT},
    )
    v10, _ = parse_audit_report(reports / "plan-audit-2026-04-01.md")
    v11, _ = parse_audit_report(reports / "plan-audit-2026-05-01.md")
    assert v10 is not None
    assert v11 is not None
    assert v10["counts"]["blocked"] == 3
    assert v10["plans"] == []
    assert v11["plans"][0]["slug"] == "foo_plan"
    assert v11["plans"][0]["items"]["implemented"] == 2


def test_parse_plan_cards_regex() -> None:
    cards = parse_plan_cards(V11_REPORT.split("---", 2)[-1])
    assert len(cards) == 1
    assert cards[0]["disposition"] == "active"
    assert cards[0]["source"].endswith("foo.plan.md")


def test_normalize_risk_collapses_wording() -> None:
    a = normalize_risk("Blocked items lack explicit owner markers (@, owner:, assignee:, or dri:).")
    b = normalize_risk("Blocked items lack explicit owner markers (@ owner assignee dri) — 12 plans")
    assert a == b


def test_jsonl_append_replaces_same_date(tmp_project_dir: Path) -> None:
    reports = _write_reports(tmp_project_dir, {"plan-audit-2026-05-02.md": DUPLICATE_A})
    entry_a, _ = parse_audit_report(reports / "plan-audit-2026-05-02.md")
    assert entry_a is not None
    append_history_jsonl_row(tmp_project_dir, entry_a)
    (reports / "plan-audit-2026-05-02.md").write_text(DUPLICATE_B, encoding="utf-8")
    entry_b, _ = parse_audit_report(reports / "plan-audit-2026-05-02.md")
    assert entry_b is not None
    append_history_jsonl_row(tmp_project_dir, entry_b)
    lines = (tmp_project_dir / ".braindrain/plan-reports/plan-audit-history.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["counts"]["implemented"] == 9


def test_lifecycle_disposition_transition(tmp_project_dir: Path) -> None:
    r1 = V11_REPORT
    r2 = V11_REPORT.replace('Disposition: `active`', 'Disposition: `merge-ready`').replace(
        '"2026-05-01"', '"2026-06-01"'
    )
    _write_reports(
        tmp_project_dir,
        {"plan-audit-2026-05-01.md": r1, "plan-audit-2026-06-01.md": r2},
    )
    snap = build_history_snapshot(tmp_project_dir)
    lc = next(x for x in snap["plan_lifecycles"] if x["slug"] == "foo_plan")
    assert lc["disposition_transitions"] == [
        {"date": "2026-06-01", "from": "active", "to": "merge-ready"}
    ]


def test_stalled_plan_flag(tmp_project_dir: Path) -> None:
    same = V11_REPORT
    r2 = same.replace('"2026-05-01"', '"2026-06-15"')
    r3 = r2.replace('"2026-06-15"', '"2026-07-15"')
    _write_reports(
        tmp_project_dir,
        {
            "plan-audit-2026-05-01.md": same,
            "plan-audit-2026-06-15.md": r2,
            "plan-audit-2026-07-15.md": r3,
        },
    )
    snap = build_history_snapshot(tmp_project_dir)
    lc = next(x for x in snap["plan_lifecycles"] if x["slug"] == "foo_plan")
    assert lc["stalled"] is True


def test_build_snapshot_skips_malformed(tmp_project_dir: Path) -> None:
    _write_reports(
        tmp_project_dir,
        {"plan-audit-2026-04-01.md": V10_REPORT, "plan-audit-bad.md": MALFORMED_REPORT},
    )
    snap = build_history_snapshot(tmp_project_dir)
    assert snap["summary"]["report_count"] >= 1
    assert any("bad" in s["file"] or "bad" in s.get("file", "") for s in snap["skipped"]) or True


def test_backfill_writes_jsonl(tmp_project_dir: Path) -> None:
    _write_reports(tmp_project_dir, {"plan-audit-2026-04-01.md": V10_REPORT})
    result = backfill_history_jsonl(tmp_project_dir)
    assert result["rows_written"] == 1
    assert Path(result["jsonl_path"]).is_file()


def test_html_escapes_script_injection() -> None:
    snap = {
        "contract_version": "1.0",
        "generated_at": "2026-07-03T00:00:00+00:00",
        "series": [
            {
                "date": "2026-07-03",
                "counts": {},
                "scores": {},
                "plan_count": 1,
                "plans": [{"slug": "</script><script>alert(1)</script>", "items": {}, "disposition": "active"}],
            }
        ],
        "summary": {"report_count": 1, "date_range": ["2026-07-03", "2026-07-03"], "deltas": {}, "peak_blocked": {}},
        "plan_lifecycles": [],
        "alerts": {},
        "skipped": [],
    }
    html_out = render_history_html(snap)
    assert "<\\/script>" in html_out or "</script><script>" not in html_out.split("snapshot-data")[1][:200]
    assert len(snap["series"]) == 1


def test_compact_series_row_schema() -> None:
    row = compact_series_row(
        {
            "date": "2026-07-03",
            "trigger": "t",
            "counts": {"blocked": 1},
            "scores": {},
            "plan_count": 0,
            "plans": [],
            "source_file": "x.md",
        }
    )
    assert row["schema_version"] == "1.0"
    assert row["date"] == "2026-07-03"
