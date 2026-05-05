"""Durable semantic/procedural/lesson memory store."""

from __future__ import annotations

import difflib
import json
import math
import sqlite3
import time
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BrainRecord:
    record_id: str
    record_class: str
    title: str
    content: str
    source: str
    category: str = "general"
    status: str = "active"
    importance: float = 0.5
    confidence: float = 0.5
    tags: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    supersedes_id: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0
    last_accessed: float = 0.0
    access_count: int = 0


class WikiBrain:
    """SQLite durable memory with FTS-backed retrieval and metrics."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        similarity_weight: float = 0.5,
        recency_weight: float = 0.3,
        importance_weight: float = 0.2,
        recency_half_life_days: float = 30.0,
        decay_half_life_days: float = 90.0,
        prune_threshold: float = 0.05,
        consolidation_similarity: float = 0.92,
    ) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.similarity_weight = similarity_weight
        self.recency_weight = recency_weight
        self.importance_weight = importance_weight
        self.recency_half_life_days = recency_half_life_days
        self.decay_half_life_days = decay_half_life_days
        self.prune_threshold = prune_threshold
        self.consolidation_similarity = consolidation_similarity
        self._fts_available = True
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # PRAGMA synchronous is connection-local and must be set on every connection.
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            # PRAGMA journal_mode=WAL is persistent and only needs to be set once.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS brain_records (
                    record_id TEXT PRIMARY KEY,
                    record_class TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    status TEXT NOT NULL DEFAULT 'active',
                    importance REAL NOT NULL DEFAULT 0.5,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    tags TEXT NOT NULL DEFAULT '[]',
                    evidence_refs TEXT NOT NULL DEFAULT '[]',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    supersedes_id TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_accessed REAL NOT NULL DEFAULT 0,
                    access_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_metrics (
                    metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    metric_type TEXT NOT NULL,
                    value REAL NOT NULL,
                    source TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    recorded_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_brain_records_class_status
                ON brain_records(record_class, status, updated_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_metrics_type_time
                ON memory_metrics(metric_type, recorded_at DESC)
                """
            )
            try:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS brain_records_fts
                    USING fts5(
                        record_id UNINDEXED,
                        title,
                        content,
                        tags,
                        record_class,
                        category,
                        status
                    )
                    """
                )
            except sqlite3.OperationalError:
                self._fts_available = False

    def store_record(self, record: BrainRecord) -> dict[str, Any]:
        # Avoid expensive asdict() in hot path
        now = time.time()
        if not record.record_id:
            record.record_id = str(uuid.uuid4())
        if not record.created_at:
            record.created_at = now
        record.updated_at = now

        contradiction = self.detect_contradiction(
            content=record.content,
            title=record.title,
            record_class=record.record_class,
            exclude_record_id=record.record_id,
        )
        if contradiction:
            record.supersedes_id = contradiction["record_id"]

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO brain_records (
                    record_id,
                    record_class,
                    title,
                    content,
                    source,
                    category,
                    status,
                    importance,
                    confidence,
                    tags,
                    evidence_refs,
                    metadata,
                    supersedes_id,
                    created_at,
                    updated_at,
                    last_accessed,
                    access_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.record_id,
                    record.record_class,
                    record.title,
                    record.content,
                    record.source,
                    record.category,
                    record.status,
                    record.importance,
                    record.confidence,
                    json.dumps(record.tags),
                    json.dumps(record.evidence_refs),
                    json.dumps(record.metadata),
                    record.supersedes_id,
                    record.created_at,
                    record.updated_at,
                    record.last_accessed,
                    record.access_count,
                ),
            )
            if record.supersedes_id:
                conn.execute(
                    """
                    UPDATE brain_records
                    SET status = 'superseded', updated_at = ?
                    WHERE record_id = ?
                    """,
                    (now, record.supersedes_id),
                )
            if self._fts_available:
                conn.execute(
                    """
                    INSERT INTO brain_records_fts (
                        rowid,
                        record_id,
                        title,
                        content,
                        tags,
                        record_class,
                        category,
                        status
                    )
                    VALUES (
                        (SELECT rowid FROM brain_records WHERE record_id = ?),
                        ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        record.record_id,
                        record.record_id,
                        record.title,
                        record.content,
                        " ".join(record.tags),
                        record.record_class,
                        record.category,
                        record.status,
                    ),
                )

        return {
            "record_id": record.record_id,
            "status": record.status,
            "supersedes_id": record.supersedes_id,
        }

    def store_fact(
        self,
        *,
        content: str,
        record_class: str = "semantic",
        title: str | None = None,
        source: str = "manual",
        category: str = "general",
        importance: float = 0.5,
        confidence: float = 0.5,
        tags: list[str] | None = None,
        evidence_refs: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = BrainRecord(
            record_id=str(uuid.uuid4()),
            record_class=record_class,
            title=title or content[:80],
            content=content,
            source=source,
            category=category,
            importance=importance,
            confidence=confidence,
            tags=tags or [],
            evidence_refs=evidence_refs or [],
            metadata=metadata or {},
        )
        return self.store_record(record)

    def query_records(
        self,
        *,
        query: str = "",
        record_class: str | None = None,
        limit: int = 10,
        include_superseded: bool = False,
    ) -> list[BrainRecord]:
        clauses: list[str] = []
        filter_params: list[Any] = []
        if record_class:
            clauses.append("r.record_class = ?")
            filter_params.append(record_class)
        if not include_superseded:
            clauses.append("r.status = 'active'")
        where = f"AND {' AND '.join(clauses)}" if clauses else ""

        with self._connect() as conn:
            if query and self._fts_available:
                rows = conn.execute(
                    f"""
                    SELECT r.*
                    FROM brain_records_fts f
                    JOIN brain_records r ON r.rowid = f.rowid
                    WHERE brain_records_fts MATCH ?
                    {where}
                    ORDER BY r.updated_at DESC
                    LIMIT ?
                    """,
                    (query, *filter_params, limit),
                ).fetchall()
            else:
                base_clauses = [clause.replace("r.", "") for clause in clauses]
                base_where = f"WHERE {' AND '.join(base_clauses)}" if base_clauses else ""
                rows = conn.execute(
                    f"""
                    SELECT *
                    FROM brain_records
                    {base_where}
                    ORDER BY updated_at DESC, created_at DESC
                    LIMIT ?
                    """,
                    (*filter_params, limit),
                ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def cognitive_recall(
        self,
        *,
        query: str,
        record_class: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        candidates = self.query_records(
            query=query,
            record_class=record_class,
            limit=max(limit * 4, 10),
            include_superseded=False,
        )
        now = time.time()
        ranked: list[dict[str, Any]] = []
        for record in candidates:
            similarity = self._similarity(query, f"{record.title} {record.content}")
            recency = self._recency_score(record.updated_at or record.created_at, now)
            importance = max(0.0, min(1.0, record.importance))
            score = (
                self.similarity_weight * similarity
                + self.recency_weight * recency
                + self.importance_weight * importance
            )
            ranked.append(
                {
                    "record": asdict(record),
                    "score": round(score, 6),
                    "signal_breakdown": {
                        "similarity": round(similarity, 6),
                        "recency": round(recency, 6),
                        "importance": round(importance, 6),
                    },
                }
            )
        ranked.sort(key=lambda item: item["score"], reverse=True)
        top = ranked[:limit]
        for item in top:
            self._mark_accessed(item["record"]["record_id"], now=now)
        return top

    def review_playbook(self, *, query: str = "", limit: int = 10) -> list[dict[str, Any]]:
        records = self.query_records(query=query, record_class="lesson", limit=limit)
        return [asdict(record) for record in records]

    def detect_contradiction(
        self,
        *,
        content: str,
        title: str,
        record_class: str,
        exclude_record_id: str | None = None,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
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
            existing = self._row_to_record(row)
            overlap = self._similarity(title, existing.title)
            content_overlap = self._similarity(content, existing.content)
            if overlap >= 0.78 and content_overlap < 0.55:
                return {"record_id": existing.record_id, "title": existing.title}
        return None

    def decay_records(self, *, now: float | None = None) -> dict[str, Any]:
        current = now or time.time()
        updated = 0
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT record_id, importance, updated_at, created_at
                FROM brain_records
                WHERE status = 'active'
                """
            ).fetchall()
            for row in rows:
                anchor = float(row["updated_at"] or row["created_at"])
                decayed = float(row["importance"]) * self._half_life(anchor, current, self.decay_half_life_days)
                conn.execute(
                    "UPDATE brain_records SET importance = ?, updated_at = ? WHERE record_id = ?",
                    (decayed, current, row["record_id"]),
                )
                updated += 1
        return {"updated_records": updated}

    def forget_below_threshold(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT record_id FROM brain_records
                WHERE importance < ? AND status = 'active'
                """,
                (self.prune_threshold,),
            ).fetchall()
            ids = [row["record_id"] for row in rows]
            if ids:
                conn.executemany(
                    "UPDATE brain_records SET status = 'forgotten' WHERE record_id = ?",
                    [(record_id,) for record_id in ids],
                )
        return {"forgotten_records": ids}

    def record_metric(
        self,
        metric_type: str,
        *,
        value: float = 1.0,
        source: str = "manual",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO memory_metrics (metric_type, value, source, metadata, recorded_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (metric_type, value, source, json.dumps(metadata or {}), now),
            )
        return {"metric_id": cursor.lastrowid, "recorded_at": now}

    def get_metrics_snapshot(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT metric_type, COUNT(*) AS events, SUM(value) AS total_value
                FROM memory_metrics
                GROUP BY metric_type
                ORDER BY metric_type ASC
                """
            ).fetchall()
            records = conn.execute(
                """
                SELECT record_class, status, COUNT(*) AS count
                FROM brain_records
                GROUP BY record_class, status
                ORDER BY record_class ASC, status ASC
                """
            ).fetchall()

        record_counts: dict[str, dict[str, int]] = defaultdict(dict)
        for row in records:
            record_counts[row["record_class"]][row["status"]] = int(row["count"])

        return {
            "metrics": {
                row["metric_type"]: {
                    "events": int(row["events"]),
                    "total_value": float(row["total_value"] or 0.0),
                }
                for row in rows
            },
            "record_counts": record_counts,
        }

    def _mark_accessed(self, record_id: str, *, now: float | None = None) -> None:
        current = now or time.time()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE brain_records
                SET last_accessed = ?, access_count = access_count + 1
                WHERE record_id = ?
                """,
                (current, record_id),
            )

    def _similarity(self, a: str, b: str) -> float:
        left = (a or "").strip().lower()
        right = (b or "").strip().lower()
        if not left or not right:
            return 0.0
        token_overlap = len(set(left.split()) & set(right.split()))
        token_denom = max(1, len(set(left.split())))
        lexical = difflib.SequenceMatcher(None, left, right).ratio()
        return min(1.0, 0.6 * lexical + 0.4 * (token_overlap / token_denom))

    def _half_life(self, anchor: float, now: float, half_life_days: float) -> float:
        delta_days = max(0.0, (now - anchor) / 86400.0)
        if half_life_days <= 0:
            return 1.0
        return math.pow(0.5, delta_days / half_life_days)

    def _recency_score(self, anchor: float, now: float) -> float:
        return self._half_life(anchor, now, self.recency_half_life_days)

    def _row_to_record(self, row: sqlite3.Row) -> BrainRecord:
        return BrainRecord(
            record_id=row["record_id"],
            record_class=row["record_class"],
            title=row["title"],
            content=row["content"],
            source=row["source"],
            category=row["category"],
            status=row["status"],
            importance=float(row["importance"]),
            confidence=float(row["confidence"]),
            tags=json.loads(row["tags"] or "[]"),
            evidence_refs=json.loads(row["evidence_refs"] or "[]"),
            metadata=json.loads(row["metadata"] or "{}"),
            supersedes_id=row["supersedes_id"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            last_accessed=float(row["last_accessed"] or 0.0),
            access_count=int(row["access_count"] or 0),
        )
