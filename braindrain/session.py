"""Session and episode tracking for memory promotion."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SessionSummary:
    session_id: str
    start_time: float
    end_time: float | None = None
    events_count: int = 0
    tools_used: dict[str, int] = field(default_factory=dict)
    files_modified: list[str] = field(default_factory=list)
    key_decisions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    token_total: int = 0
    updated_at: float = 0.0


@dataclass
class EpisodeRecord:
    episode_id: str
    session_id: str
    problem: str
    context: str
    action: str
    outcome: str
    evidence_refs: list[str] = field(default_factory=list)
    local_critique: str = ""
    global_reflection: str = ""
    confidence: float = 0.5
    tags: list[str] = field(default_factory=list)
    created_at: float = 0.0
    promoted_lesson_id: str | None = None


class SessionStore:
    """Tracks session summaries and grounded episodes."""

    def __init__(self, db_path: str | Path, *, inactivity_timeout_minutes: int = 30) -> None:
        self.db_path = Path(db_path).expanduser()
        self.inactivity_timeout_minutes = inactivity_timeout_minutes
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_summaries (
                    session_id TEXT PRIMARY KEY,
                    start_time REAL NOT NULL,
                    end_time REAL,
                    events_count INTEGER NOT NULL DEFAULT 0,
                    tools_used TEXT NOT NULL DEFAULT '{}',
                    files_modified TEXT NOT NULL DEFAULT '[]',
                    key_decisions TEXT NOT NULL DEFAULT '[]',
                    errors TEXT NOT NULL DEFAULT '[]',
                    token_total INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS episode_records (
                    episode_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    problem TEXT NOT NULL,
                    context TEXT NOT NULL,
                    action TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    evidence_refs TEXT NOT NULL DEFAULT '[]',
                    local_critique TEXT NOT NULL DEFAULT '',
                    global_reflection TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    tags TEXT NOT NULL DEFAULT '[]',
                    created_at REAL NOT NULL,
                    promoted_lesson_id TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_session_summaries_updated_at
                ON session_summaries(updated_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_episode_records_session_time
                ON episode_records(session_id, created_at DESC)
                """
            )

    def touch_session(
        self,
        session_id: str,
        *,
        tool_name: str | None = None,
        files_modified: list[str] | None = None,
        key_decision: str | None = None,
        error: str | None = None,
        token_delta: int = 0,
        timestamp: float | None = None,
    ) -> SessionSummary:
        now = timestamp or time.time()
        existing = self.get_session_summary(session_id=session_id)
        if existing is None:
            existing = SessionSummary(
                session_id=session_id,
                start_time=now,
                updated_at=now,
            )

        existing.events_count += 1
        existing.updated_at = now
        if tool_name:
            existing.tools_used[tool_name] = existing.tools_used.get(tool_name, 0) + 1
        if files_modified:
            existing.files_modified = sorted(set(existing.files_modified).union(files_modified))
        if key_decision and key_decision not in existing.key_decisions:
            existing.key_decisions.append(key_decision)
        if error and error not in existing.errors:
            existing.errors.append(error)
        existing.token_total += token_delta
        self.upsert_session(existing)
        return existing

    def upsert_session(self, summary: SessionSummary) -> None:
        payload = asdict(summary)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO session_summaries (
                    session_id,
                    start_time,
                    end_time,
                    events_count,
                    tools_used,
                    files_modified,
                    key_decisions,
                    errors,
                    token_total,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    start_time = excluded.start_time,
                    end_time = excluded.end_time,
                    events_count = excluded.events_count,
                    tools_used = excluded.tools_used,
                    files_modified = excluded.files_modified,
                    key_decisions = excluded.key_decisions,
                    errors = excluded.errors,
                    token_total = excluded.token_total,
                    updated_at = excluded.updated_at
                """,
                (
                    payload["session_id"],
                    payload["start_time"],
                    payload["end_time"],
                    payload["events_count"],
                    json.dumps(payload["tools_used"]),
                    json.dumps(payload["files_modified"]),
                    json.dumps(payload["key_decisions"]),
                    json.dumps(payload["errors"]),
                    payload["token_total"],
                    payload["updated_at"],
                ),
            )

    def finalize_session(self, session_id: str, *, timestamp: float | None = None) -> SessionSummary | None:
        summary = self.get_session_summary(session_id=session_id)
        if summary is None:
            return None
        done_at = timestamp or time.time()
        summary.end_time = done_at
        summary.updated_at = done_at
        self.upsert_session(summary)
        return summary

    def get_session_summary(self, session_id: str | None = None) -> SessionSummary | None:
        with self._connect() as conn:
            if session_id:
                row = conn.execute(
                    "SELECT * FROM session_summaries WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT * FROM session_summaries
                    ORDER BY updated_at DESC, start_time DESC
                    LIMIT 1
                    """
                ).fetchone()
        return self._row_to_session(row) if row else None

    def list_recent_sessions(self, *, limit: int = 10) -> list[SessionSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM session_summaries
                ORDER BY updated_at DESC, start_time DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_session(row) for row in rows]

    def should_dream(self, *, quiet_minutes: int | None = None, now: float | None = None) -> bool:
        quiet = quiet_minutes if quiet_minutes is not None else self.inactivity_timeout_minutes
        current = now or time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(updated_at) AS latest_activity FROM session_summaries"
            ).fetchone()
        latest = float(row["latest_activity"]) if row and row["latest_activity"] else 0.0
        if latest == 0.0:
            return True
        return (current - latest) >= quiet * 60

    def record_episode(self, episode: EpisodeRecord) -> dict[str, Any]:
        payload = asdict(episode)
        if not payload["episode_id"]:
            payload["episode_id"] = str(uuid.uuid4())
        if not payload["created_at"]:
            payload["created_at"] = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO episode_records (
                    episode_id,
                    session_id,
                    problem,
                    context,
                    action,
                    outcome,
                    evidence_refs,
                    local_critique,
                    global_reflection,
                    confidence,
                    tags,
                    created_at,
                    promoted_lesson_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["episode_id"],
                    payload["session_id"],
                    payload["problem"],
                    payload["context"],
                    payload["action"],
                    payload["outcome"],
                    json.dumps(payload["evidence_refs"]),
                    payload["local_critique"],
                    payload["global_reflection"],
                    payload["confidence"],
                    json.dumps(payload["tags"]),
                    payload["created_at"],
                    payload["promoted_lesson_id"],
                ),
            )
        return {"episode_id": payload["episode_id"]}

    def mark_episode_promoted(self, episode_id: str, lesson_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE episode_records
                SET promoted_lesson_id = ?
                WHERE episode_id = ?
                """,
                (lesson_id, episode_id),
            )

    def list_episodes(self, *, session_id: str | None = None, limit: int = 20) -> list[EpisodeRecord]:
        with self._connect() as conn:
            if session_id:
                rows = conn.execute(
                    """
                    SELECT * FROM episode_records
                    WHERE session_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (session_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM episode_records
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [self._row_to_episode(row) for row in rows]

    def _row_to_session(self, row: sqlite3.Row) -> SessionSummary:
        return SessionSummary(
            session_id=row["session_id"],
            start_time=float(row["start_time"]),
            end_time=float(row["end_time"]) if row["end_time"] is not None else None,
            events_count=int(row["events_count"] or 0),
            tools_used=json.loads(row["tools_used"] or "{}"),
            files_modified=json.loads(row["files_modified"] or "[]"),
            key_decisions=json.loads(row["key_decisions"] or "[]"),
            errors=json.loads(row["errors"] or "[]"),
            token_total=int(row["token_total"] or 0),
            updated_at=float(row["updated_at"]),
        )

    def _row_to_episode(self, row: sqlite3.Row) -> EpisodeRecord:
        return EpisodeRecord(
            episode_id=row["episode_id"],
            session_id=row["session_id"],
            problem=row["problem"],
            context=row["context"],
            action=row["action"],
            outcome=row["outcome"],
            evidence_refs=json.loads(row["evidence_refs"] or "[]"),
            local_critique=row["local_critique"] or "",
            global_reflection=row["global_reflection"] or "",
            confidence=float(row["confidence"] or 0.5),
            tags=json.loads(row["tags"] or "[]"),
            created_at=float(row["created_at"]),
            promoted_lesson_id=row["promoted_lesson_id"],
        )
