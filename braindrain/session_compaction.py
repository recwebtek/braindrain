"""Structured session summary compaction (≤2 KB) for context-mode indexing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from braindrain.session import SessionSummary

COMPACT_MAX_BYTES = 2048


def _json_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _truncate_list(values: list[str], *, max_items: int, max_item_len: int) -> list[str]:
    trimmed = []
    for item in values[:max_items]:
        text = " ".join(str(item).split())
        if len(text) > max_item_len:
            text = text[: max_item_len - 3] + "..."
        trimmed.append(text)
    return trimmed


def build_compact_package(
    summary: SessionSummary, *, max_bytes: int = COMPACT_MAX_BYTES
) -> dict[str, Any]:
    """Build structured session package capped at max_bytes UTF-8 JSON."""
    package: dict[str, Any] = {
        "session_id": summary.session_id,
        "decisions": list(summary.key_decisions),
        "files_touched": list(summary.files_modified),
        "failures": list(summary.errors),
        "open_todos": list(summary.open_todos),
        "tools_used": dict(summary.tools_used),
        "events_count": int(summary.events_count),
        "token_total": int(summary.token_total),
    }
    if summary.end_time is not None:
        package["ended_at"] = summary.end_time

    list_keys = ("decisions", "files_touched", "failures", "open_todos")
    max_items = 64
    max_item_len = 240

    while _json_size(package) > max_bytes:
        if max_items <= 1 and max_item_len <= 40:
            # Cannot truncate further, must break to avoid infinite loop
            break
        max_items = max(1, max_items // 2)
        max_item_len = max(40, max_item_len - 40)
        for key in list_keys:
            package[key] = _truncate_list(
                package[key], max_items=max_items, max_item_len=max_item_len
            )
        tools = package.get("tools_used") or {}
        if isinstance(tools, dict) and len(tools) > max_items:
            top = sorted(tools.items(), key=lambda kv: kv[1], reverse=True)[:max_items]
            package["tools_used"] = dict(top)

    package["bytes"] = _json_size(package)
    package["truncated"] = _json_size(package) >= max_bytes - 32
    return package


def session_index_handle(session_id: str) -> str:
    digest = hashlib.sha256(session_id.encode("utf-8", errors="ignore")).hexdigest()
    return digest[:16]


def retrieval_hint(handle: str) -> str:
    return f"Call search_index with query handle:{handle} or session:{handle}."


IndexCallback = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any] | None]]


async def index_package_in_context_mode(
    client: Any,
    *,
    session_id: str,
    package: dict[str, Any],
) -> dict[str, Any]:
    """Index compact package into context-mode; return handle metadata."""
    handle = session_index_handle(session_id)
    source = f"session-summary:{session_id}"
    content_md = (
        f"# SessionSummary\n\n"
        f"- session_id: `{session_id}`\n"
        f"- handle: `{handle}`\n\n"
        f"```json\n{json.dumps(package, ensure_ascii=False, indent=2)}\n```\n"
    )
    index_result = await client.index_markdown(
        content_md=content_md,
        source=source,
        intent="session_compaction",
    )
    return {
        "handle": handle,
        "source": source,
        "indexed": True,
        "index_result": index_result,
        "retrieval_hint": retrieval_hint(handle),
    }
