"""Observer layer for lightweight episodic event capture."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BrainEvent:
    timestamp: float
    session_id: str
    event_type: str
    tool_name: str | None = None
    files_touched: list[str] = field(default_factory=list)
    token_cost: int = 0
    duration_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class ObserverStore:
    """SQLite-backed event ring buffer."""

    def __init__(self, db_path: str | Path, *, max_events: int = 10_000) -> None:
        self.db_path = Path(db_path).expanduser()
        self.max_events = max_events
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for better write performance
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS brain_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    tool_name TEXT,
                    files_touched TEXT NOT NULL,
                    token_cost INTEGER NOT NULL DEFAULT 0,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    metadata TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_brain_events_session_time
                ON brain_events(session_id, timestamp DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_brain_events_type_time
                ON brain_events(event_type, timestamp DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_brain_events_timestamp
                ON brain_events(timestamp ASC)
                """
            )

    def record_event(self, event: BrainEvent) -> dict[str, Any]:
        payload = asdict(event)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO brain_events (
                    timestamp,
                    session_id,
                    event_type,
                    tool_name,
                    files_touched,
                    token_cost,
                    duration_ms,
                    metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["timestamp"],
                    payload["session_id"],
                    payload["event_type"],
                    payload["tool_name"],
                    json.dumps(payload["files_touched"]),
                    payload["token_cost"],
                    payload["duration_ms"],
                    json.dumps(payload["metadata"]),
                ),
            )
            pruned = self._prune_oldest(conn)
            return {"event_id": cursor.lastrowid, "pruned": pruned}

    def _prune_oldest(self, conn: sqlite3.Connection) -> int:
        """
        Prune the oldest events when the total exceeds the ring buffer size.
        Implements batch pruning (10% overflow threshold) to minimize DELETE frequency.
        """
        # Batch pruning threshold factor (e.g. 1.1 means wait for 10% overflow)
        PRUNE_THRESHOLD_FACTOR = 1.1

        row = conn.execute("SELECT COUNT(*) AS count FROM brain_events").fetchone()
        total = int(row["count"]) if row else 0

        # Only prune if we exceed the max_events by at least 10% overflow buffer
        threshold = self.max_events * PRUNE_THRESHOLD_FACTOR
        if total <= threshold:
            return 0

        overflow = total - self.max_events
        conn.execute(
            """
            DELETE FROM brain_events
            WHERE event_id IN (
                SELECT event_id FROM brain_events
                ORDER BY timestamp ASC, event_id ASC
                LIMIT ?
            )
            """,
            (overflow,),
        )
        return overflow

    def query_events(
        self,
        *,
        session_id: str | None = None,
        event_type: str | None = None,
        since: float | None = None,
        limit: int = 100,
    ) -> list[BrainEvent]:
        clauses: list[str] = []
        params: list[Any] = []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM brain_events
                {where}
                ORDER BY timestamp DESC, event_id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def get_event_stats(self, *, session_id: str | None = None) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        with self._connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS count FROM brain_events {where}", params
            ).fetchone()
            types = conn.execute(
                f"""
                SELECT event_type, COUNT(*) AS count
                FROM brain_events
                {where}
                GROUP BY event_type
                ORDER BY count DESC, event_type ASC
                """,
                params,
            ).fetchall()
            latest = conn.execute(
                f"""
                SELECT timestamp
                FROM brain_events
                {where}
                ORDER BY timestamp DESC, event_id DESC
                LIMIT 1
                """,
                params,
            ).fetchone()

        return {
            "session_id": session_id,
            "total_events": int(total["count"]) if total else 0,
            "by_type": {row["event_type"]: int(row["count"]) for row in types},
            "latest_timestamp": latest["timestamp"] if latest else None,
        }

    def _row_to_event(self, row: sqlite3.Row) -> BrainEvent:
        return BrainEvent(
            timestamp=float(row["timestamp"]),
            session_id=row["session_id"],
            event_type=row["event_type"],
            tool_name=row["tool_name"],
            files_touched=json.loads(row["files_touched"] or "[]"),
            token_cost=int(row["token_cost"] or 0),
            duration_ms=int(row["duration_ms"] or 0),
            metadata=json.loads(row["metadata"] or "{}"),
        )
