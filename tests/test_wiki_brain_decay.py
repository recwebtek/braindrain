"""Regression tests for WikiBrain decay and pruning optimizations."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from braindrain.wiki_brain import WikiBrain


def _wiki_brain(
    tmp_path: Path, *, half_life_days: float = 90.0, prune_threshold: float = 0.05
) -> WikiBrain:
    return WikiBrain(
        tmp_path / "brain.db",
        decay_half_life_days=half_life_days,
        prune_threshold=prune_threshold,
    )


def _insert_active(
    wb: WikiBrain,
    *,
    record_id: str,
    importance: float,
    updated_at: float,
    created_at: float | None = None,
) -> None:
    anchor = created_at if created_at is not None else updated_at
    with wb._connect() as conn:
        conn.execute(
            """
            INSERT INTO brain_records (
                record_id, record_class, title, content, source,
                category, status, importance, confidence,
                tags, evidence_refs, metadata,
                created_at, updated_at, last_accessed, access_count
            ) VALUES (?, 'fact', ?, ?, 'test', 'general', 'active', ?, 0.5, '[]', '[]', '{}', ?, ?, 0, 0)
            """,
            (
                record_id,
                f"title-{record_id}",
                f"content-{record_id}",
                importance,
                anchor,
                updated_at,
            ),
        )


def _expected_importance(
    wb: WikiBrain,
    *,
    importance: float,
    anchor: float,
    now: float,
) -> float:
    return importance * wb._half_life(anchor, now, wb.decay_half_life_days)


def test_decay_records_matches_half_life_formula(tmp_path: Path) -> None:
    wb = _wiki_brain(tmp_path, half_life_days=30.0)
    now = time.time()
    anchors = {
        "recent": now - 2 * 86400,
        "stale": now - 45 * 86400,
        "zero-updated": now - 10 * 86400,
    }
    _insert_active(wb, record_id="recent", importance=1.0, updated_at=anchors["recent"])
    _insert_active(wb, record_id="stale", importance=0.8, updated_at=anchors["stale"])
    _insert_active(
        wb,
        record_id="zero-updated",
        importance=0.6,
        updated_at=0.0,
        created_at=anchors["zero-updated"],
    )

    result = wb.decay_records(now=now)
    assert result["updated_records"] == 3

    with wb._connect() as conn:
        rows = {
            row["record_id"]: row
            for row in conn.execute(
                "SELECT record_id, importance, updated_at FROM brain_records"
            ).fetchall()
        }

    for record_id, anchor in anchors.items():
        expected = _expected_importance(
            wb,
            importance={"recent": 1.0, "stale": 0.8, "zero-updated": 0.6}[record_id],
            anchor=anchor if record_id != "zero-updated" else anchors["zero-updated"],
            now=now,
        )
        assert rows[record_id]["importance"] == pytest.approx(expected, rel=1e-6)
        assert rows[record_id]["updated_at"] == pytest.approx(now, rel=1e-6)


def test_decay_records_zero_half_life_only_refreshes_timestamps(tmp_path: Path) -> None:
    wb = _wiki_brain(tmp_path, half_life_days=0.0)
    now = time.time()
    _insert_active(wb, record_id="keep", importance=0.42, updated_at=now - 1000)

    result = wb.decay_records(now=now)
    assert result["updated_records"] == 1

    with wb._connect() as conn:
        row = conn.execute(
            "SELECT importance, updated_at FROM brain_records WHERE record_id = 'keep'"
        ).fetchone()
    assert row["importance"] == 0.42
    assert row["updated_at"] == pytest.approx(now, rel=1e-6)


def test_forget_below_threshold_marks_only_low_importance_records(tmp_path: Path) -> None:
    wb = _wiki_brain(tmp_path, prune_threshold=0.1)
    _insert_active(wb, record_id="keep", importance=0.5, updated_at=time.time())
    _insert_active(wb, record_id="drop-a", importance=0.04, updated_at=time.time())
    _insert_active(wb, record_id="drop-b", importance=0.09, updated_at=time.time())

    result = wb.forget_below_threshold()
    assert set(result["forgotten_records"]) == {"drop-a", "drop-b"}

    with wb._connect() as conn:
        statuses = {
            row["record_id"]: row["status"]
            for row in conn.execute("SELECT record_id, status FROM brain_records").fetchall()
        }
    assert statuses["keep"] == "active"
    assert statuses["drop-a"] == "forgotten"
    assert statuses["drop-b"] == "forgotten"


def test_salience_gate_rejects_low_signal_records(tmp_path: Path) -> None:
    wb = WikiBrain(tmp_path / "brain.db", salience_threshold=0.75)
    out = wb.store_fact(
        content="tiny",
        importance=0.1,
        confidence=0.1,
    )
    assert out["status"] == "rejected_low_salience"


def test_max_active_records_enforces_bounded_store(tmp_path: Path) -> None:
    wb = WikiBrain(tmp_path / "brain.db", max_active_records=2)
    wb.store_fact(content="A", importance=0.8, confidence=0.8)
    wb.store_fact(content="B", importance=0.7, confidence=0.7)
    wb.store_fact(content="C", importance=0.6, confidence=0.6)
    with wb._connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM brain_records WHERE status = 'active'"
        ).fetchone()
    assert int(row["count"]) == 2


def test_associative_edges_written_when_enabled(tmp_path: Path) -> None:
    wb = WikiBrain(
        tmp_path / "brain.db",
        associative_edges_enabled=True,
        edge_similarity_threshold=0.5,
    )
    wb.store_fact(content="deploy api runbook", title="Deploy API", importance=0.8, confidence=0.8)
    wb.store_fact(content="deploy api checklist", title="Deploy API", importance=0.8, confidence=0.8)
    with wb._connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM brain_record_edges").fetchone()
    assert int(row["count"]) >= 1


def test_hybrid_recall_falls_back_without_embeddings_provider(tmp_path: Path) -> None:
    wb = WikiBrain(
        tmp_path / "brain.db",
        hybrid_embeddings_enabled=True,
        embeddings_cfg={},
    )
    wb.store_fact(content="OAuth refresh tokens policy", importance=0.9, confidence=0.9)
    wb.store_fact(content="Database migration checklist", importance=0.6, confidence=0.7)
    out = wb.cognitive_recall(query="OAuth policy", limit=2)
    assert len(out) >= 1
    assert "score" in out[0]
