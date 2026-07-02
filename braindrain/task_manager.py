"""In-process task manager for long-running MCP tool executions."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class TaskRecord:
    task_id: str
    task_type: str
    status: str
    submitted_at: float
    started_at: float | None = None
    finished_at: float | None = None
    result: Any | None = None
    error: str | None = None


class TaskManager:
    """Track long-running tasks and expose polling state."""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._futures: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def submit(
        self,
        *,
        task_type: str,
        runner: Callable[[], Awaitable[Any]],
    ) -> TaskRecord:
        task_id = str(uuid.uuid4())
        record = TaskRecord(
            task_id=task_id,
            task_type=task_type,
            status="queued",
            submitted_at=time.time(),
        )
        async with self._lock:
            self._tasks[task_id] = record

        async def _run() -> None:
            record.status = "running"
            record.started_at = time.time()
            try:
                record.result = await runner()
                record.status = "completed"
            except Exception as exc:  # pragma: no cover - defensive runtime boundary
                record.error = str(exc)
                record.status = "failed"
            finally:
                record.finished_at = time.time()

        task = asyncio.create_task(_run())
        async with self._lock:
            self._futures[task_id] = task
        return record

    async def get(self, task_id: str) -> TaskRecord | None:
        async with self._lock:
            return self._tasks.get(task_id)

    async def as_dict(self, task_id: str) -> dict[str, Any]:
        record = await self.get(task_id)
        if record is None:
            return {"status": "not_found", "task_id": task_id}
        return {
            "task_id": record.task_id,
            "task_type": record.task_type,
            "status": record.status,
            "submitted_at": record.submitted_at,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
            "result": record.result if record.status == "completed" else None,
            "error": record.error,
        }
