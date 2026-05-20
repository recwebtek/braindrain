"""Regression tests for WikiBrain.detect_contradiction (Bolt PR #69)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from braindrain.wiki_brain import BrainRecord, WikiBrain


def _wiki_brain(tmp_path: Path) -> WikiBrain:
    return WikiBrain(tmp_path / "brain.db")


def _insert_active(
    wb: WikiBrain,
    *,
    record_id: str,
    record_class: str,
    title: str,
    content: str,
) -> None:
    """Insert a row without running store_record contradiction logic."""
    now = time.time()
    with wb._connect() as conn:
        conn.execute(
            """
            INSERT INTO brain_records (
                record_id, record_class, title, content, source,
                category, status, importance, confidence,
                tags, evidence_refs, metadata,
                created_at, updated_at, last_accessed, access_count
            ) VALUES (?, ?, ?, ?, ?, 'general', 'active', 0.5, 0.5, '[]', '[]', '{}', ?, ?, 0, 0)
            """,
            (record_id, record_class, title, content, "test", now, now),
        )


def _legacy_detect(
    wb: WikiBrain,
    *,
    content: str,
    title: str,
    record_class: str,
    exclude_record_id: str | None = None,
) -> dict[str, object] | None:
    """Pre-optimization reference implementation for parity checks."""
    with wb._connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM brain_records
            WHERE record_class = ?
              AND status = 'active'
            ORDER BY updated_at DESC
            LIMIT 25
            """,
            (record_class,),
        ).fetchall()
    for row in rows:
        if exclude_record_id and row["record_id"] == exclude_record_id:
            continue
        existing = wb._row_to_record(row)
        overlap = wb._similarity(title, existing.title)
        content_overlap = wb._similarity(content, existing.content)
        if overlap >= 0.78 and content_overlap < 0.55:
            return {"record_id": existing.record_id, "title": existing.title}
    return None


def test_detect_contradiction_finds_similar_title_dissimilar_content(tmp_path: Path) -> None:
    wb = _wiki_brain(tmp_path)
    _insert_active(
        wb,
        record_id="existing-1",
        record_class="fact",
        title="Deploy API v2 runbook",
        content="kubectl rollout restart deployment/api --namespace prod",
    )

    hit = wb.detect_contradiction(
        content="Weekly menu planning and grocery shopping checklist",
        title="Deploy API v2 runbook",
        record_class="fact",
    )

    assert hit is not None
    assert hit["record_id"] == "existing-1"
    assert hit["title"] == "Deploy API v2 runbook"


def test_detect_contradiction_returns_none_when_titles_differ(tmp_path: Path) -> None:
    wb = _wiki_brain(tmp_path)
    _insert_active(
        wb,
        record_id="existing-1",
        record_class="fact",
        title="Deploy API v2 runbook",
        content="kubectl rollout restart deployment/api",
    )

    assert (
        wb.detect_contradiction(
            content="kubectl rollout restart deployment/api",
            title="Unrelated database migration notes",
            record_class="fact",
        )
        is None
    )


def test_detect_contradiction_respects_exclude_record_id(tmp_path: Path) -> None:
    wb = _wiki_brain(tmp_path)
    _insert_active(
        wb,
        record_id="only-row",
        record_class="lesson",
        title="Shared lesson title",
        content="Original procedural steps for cache warmup",
    )

    assert (
        wb.detect_contradiction(
            content="Different steps that contradict the original",
            title="Shared lesson title",
            record_class="lesson",
            exclude_record_id="only-row",
        )
        is None
    )


def test_detect_contradiction_matches_legacy_implementation(tmp_path: Path) -> None:
    wb = _wiki_brain(tmp_path)
    for index in range(6):
        _insert_active(
            wb,
            record_id=f"row-{index}",
            record_class="fact",
            title=f"Topic cluster {index % 2}",
            content=f"Body text variant {index} with extra words",
        )

    probes = [
        ("Topic cluster 0", "Unrelated replacement content alpha"),
        ("Topic cluster 1", "Body text variant 3 with extra words"),
        ("No overlap title", "Body text variant 1 with extra words"),
    ]
    for title, content in probes:
        kwargs = dict(content=content, title=title, record_class="fact")
        assert wb.detect_contradiction(**kwargs) == _legacy_detect(wb, **kwargs)


def test_store_record_sets_supersedes_on_contradiction(tmp_path: Path) -> None:
    wb = _wiki_brain(tmp_path)
    _insert_active(
        wb,
        record_id="prior",
        record_class="fact",
        title="OAuth token refresh policy",
        content="Rotate refresh tokens every 30 days using the admin API",
    )

    stored = wb.store_record(
        BrainRecord(
            record_id="new-fact",
            record_class="fact",
            title="OAuth token refresh policy",
            content="Never rotate tokens; disable refresh for all clients",
            source="test",
        )
    )

    assert stored["supersedes_id"] == "prior"
