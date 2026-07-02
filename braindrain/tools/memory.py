"""Memory/provenance tool implementations extracted from server.py."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from braindrain.context_mode_client import MCPProtocolError
from braindrain.observer import BrainEvent
from braindrain.session import EpisodeRecord
from braindrain.session_compaction import (
    build_compact_package,
    index_package_in_context_mode,
    retrieval_hint,
    session_index_handle,
)


def get_provenance_settings_impl(
    provenance_settings_fn, effective_model_name_fn, effective_cursor_mode_fn
) -> dict:
    return {
        "provenance": provenance_settings_fn(),
        "effective_model": effective_model_name_fn(),
        "cursor_mode": effective_cursor_mode_fn(),
        "timestamp": datetime.now().isoformat(),
    }


def record_model_trace_event_impl(
    provenance_settings_fn,
    effective_model_name_fn,
    effective_cursor_mode_fn,
    telemetry,
    actor: str,
    model_name: str = "",
    event: str = "run",
    source: str = "manual",
    metadata: dict | None = None,
) -> dict:
    settings = provenance_settings_fn()
    trace_cfg = settings.get("subagent_trace", {}) if isinstance(settings, dict) else {}
    enabled = bool(trace_cfg.get("enabled", True)) and bool(settings.get("enabled", True))
    if not enabled:
        return {
            "ok": True,
            "status": "disabled",
            "message": "provenance.subagent_trace is disabled",
        }
    trace_path = Path(str(trace_cfg.get("path") or ".braindrain/plan-reports/model-trace.jsonl"))
    if not trace_path.is_absolute():
        trace_path = Path.cwd() / trace_path
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    payload = {
        "timestamp": now.isoformat(),
        "date": now.strftime(str(settings.get("date_format", "%Y-%m-%d"))),
        "actor": actor,
        "event": event,
        "source": source,
        "model_name": effective_model_name_fn(model_name),
        "cursor_mode": effective_cursor_mode_fn(),
        "metadata": metadata or {},
    }
    sanitized_payload = telemetry.sanitize(payload)
    with open(trace_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(sanitized_payload, ensure_ascii=False) + "\n")
    return {"ok": True, "trace_path": str(trace_path), "event": sanitized_payload}


async def touch_session_impl(
    get_session_store,
    get_context_mode_client,
    get_observer_store,
    session_id: str,
    tool_name: str | None = None,
    files_modified: list[str] | None = None,
    key_decision: str | None = None,
    error: str | None = None,
    open_todos: list[str] | None = None,
    token_delta: int = 0,
    timestamp: float | None = None,
    end_session: bool = False,
    index_in_context_mode: bool = True,
) -> dict:
    store = get_session_store()
    summary = store.touch_session(
        session_id=session_id,
        tool_name=tool_name,
        files_modified=files_modified,
        key_decision=key_decision,
        error=error,
        open_todos=open_todos,
        token_delta=token_delta,
        timestamp=timestamp,
    )
    if not end_session:
        return summary.__dict__
    package = build_compact_package(summary)
    handle = session_index_handle(session_id)
    index_meta: dict | None = None
    if index_in_context_mode:
        client = get_context_mode_client()
        if client is not None:
            try:
                index_meta = await index_package_in_context_mode(
                    client, session_id=session_id, package=package
                )
                handle = str(index_meta.get("handle") or handle)
            except MCPProtocolError as exc:
                index_meta = {"indexed": False, "error": str(exc), "handle": handle}
    finalized = store.end_session(
        session_id, compact_package=package, context_index_handle=handle, timestamp=timestamp
    )
    get_observer_store().record_event(
        BrainEvent(
            timestamp=timestamp or time.time(),
            session_id=session_id,
            event_type="session_end",
            tool_name=None,
            token_cost=int(package.get("token_total", 0) or 0),
            duration_ms=0,
            metadata={
                "bytes": package.get("bytes"),
                "context_index_handle": handle,
                "indexed": bool(index_meta and index_meta.get("indexed")),
            },
        )
    )
    response = finalized.__dict__ if finalized else summary.__dict__
    response["compact_package"] = package
    response["context_index_handle"] = handle
    response["retrieval_hint"] = retrieval_hint(handle)
    if index_meta is not None:
        response["context_mode"] = index_meta
    return response


def record_episode_impl(
    get_session_store,
    session_id: str,
    problem: str,
    context: str,
    action: str,
    outcome: str,
    evidence_refs: list[str] | None = None,
    local_critique: str = "",
    global_reflection: str = "",
    confidence: float = 0.5,
    tags: list[str] | None = None,
    episode_id: str = "",
) -> dict:
    episode = EpisodeRecord(
        episode_id=episode_id,
        session_id=session_id,
        problem=problem,
        context=context,
        action=action,
        outcome=outcome,
        evidence_refs=evidence_refs or [],
        local_critique=local_critique,
        global_reflection=global_reflection,
        confidence=confidence,
        tags=tags or [],
    )
    return get_session_store().record_episode(episode)
