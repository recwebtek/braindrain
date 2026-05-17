"""Shared MCP tool instrumentation: telemetry + observer bridge."""

from __future__ import annotations

import functools
import hashlib
import inspect
import json
import os
import time
from typing import Any, Callable, Optional, Protocol

from braindrain.observer import BrainEvent, ObserverStore
from braindrain.telemetry import TelemetrySession, estimate_tokens


class TokenEstimator(Protocol):
    def estimate(self, text: str) -> int: ...


def hash_args(payload: Any) -> str:
    """Stable SHA256 of sorted JSON for observer privacy (no raw prompts)."""
    try:
        normalized = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        normalized = repr(payload)
    return hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()


def _default_session_id() -> str:
    return os.environ.get("BRAINDRAIN_SESSION_ID", "mcp-default")


def _serialize_for_tokens(value: Any, *, max_chars: int = 200_000) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    elif isinstance(value, (bytes, bytearray)):
        text = value.decode("utf-8", errors="ignore")
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(value)
    if len(text) > max_chars:
        return text[:max_chars]
    return text


def _extract_raw_text(fn: Callable[..., Any], args: tuple, kwargs: dict) -> str:
    if "text" in kwargs and isinstance(kwargs["text"], str):
        return kwargs["text"]
    if "query" in kwargs and isinstance(kwargs["query"], str):
        return kwargs["query"]
    sig = inspect.signature(fn)
    params = list(sig.parameters.keys())
    for idx, name in enumerate(params):
        if idx >= len(args):
            break
        if name in {"text", "query", "path"} and isinstance(args[idx], str):
            return args[idx]
    return _serialize_for_tokens({"args": args, "kwargs": kwargs})


def _result_instrumented(result: Any) -> bool:
    if isinstance(result, dict):
        meta = result.get("meta")
        if isinstance(meta, dict) and meta.get("_instrumented"):
            return True
        if result.get("_instrumented"):
            return True
    return False


def record_tool_io(
    telemetry: TelemetrySession,
    *,
    tool_name: str,
    raw_text: str,
    actual_text: str,
    module: str = "tool_gate",
    meta: Optional[dict[str, Any]] = None,
    observer_store: Optional[ObserverStore] = None,
    session_id: Optional[str] = None,
    duration_ms: int = 0,
    hash_tool_args: bool = True,
    args_hash_payload: Any = None,
) -> dict[str, Any]:
    """Record telemetry and optional observer tool_call event."""
    event_meta = dict(meta or {})
    event_meta["_instrumented"] = True

    event = telemetry.record(
        tool_name=tool_name,
        raw_text=raw_text,
        actual_text=actual_text,
        module=module,
        meta=event_meta,
    )
    raw_tokens = int(event.get("tokens_in_raw_est", 0))
    actual_tokens = int(event.get("tokens_in_actual_est", 0))
    saved_tokens = int(event.get("tokens_saved_est", 0))

    if observer_store is not None:
        obs_meta: dict[str, Any] = {
            "module": module,
            "tokens_in_raw_est": raw_tokens,
            "tokens_in_actual_est": actual_tokens,
            "tokens_saved_est": saved_tokens,
        }
        if hash_tool_args and args_hash_payload is not None:
            obs_meta["args_hash"] = hash_args(args_hash_payload)

        observer_store.record_event(
            BrainEvent(
                timestamp=time.time(),
                session_id=session_id or _default_session_id(),
                event_type="tool_call",
                tool_name=tool_name,
                token_cost=raw_tokens + actual_tokens,
                duration_ms=duration_ms,
                metadata=obs_meta,
            )
        )

    return {
        "raw_tokens": raw_tokens,
        "actual_tokens": actual_tokens,
        "saved_tokens": saved_tokens,
    }


def make_observe_mcp_tool(
    *,
    telemetry: TelemetrySession,
    observer_enabled: Callable[[], bool],
    observer_store_getter: Callable[[], ObserverStore],
    hash_args_enabled: Callable[[], bool],
    wrap_tool: Callable[[str], bool],
    module_for: Optional[Callable[[str], str]] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Factory for the MCP tool observer decorator."""

    def _module(tool_name: str) -> str:
        if module_for is not None:
            return module_for(tool_name)
        if tool_name in {"route_output", "search_index"}:
            return "output_sandbox"
        if tool_name in {"search_tools", "get_available_tools"}:
            return "tool_gate"
        if tool_name.startswith("scriptlib_"):
            return "tool_gate"
        return "tool_gate"

    def observe_mcp_tool(fn: Callable[..., Any]) -> Callable[..., Any]:
        tool_name = fn.__name__

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not observer_enabled() or not wrap_tool(tool_name):
                return await fn(*args, **kwargs)

            start = time.perf_counter()
            result = await fn(*args, **kwargs)
            if _result_instrumented(result):
                return result

            duration_ms = int((time.perf_counter() - start) * 1000)
            raw_text = _extract_raw_text(fn, args, kwargs)
            actual_text = _serialize_for_tokens(result)

            record_tool_io(
                telemetry,
                tool_name=tool_name,
                raw_text=raw_text,
                actual_text=actual_text,
                module=_module(tool_name),
                meta={"duration_ms": duration_ms},
                observer_store=observer_store_getter(),
                duration_ms=duration_ms,
                hash_tool_args=hash_args_enabled(),
                args_hash_payload={"args": args, "kwargs": kwargs},
            )

            if tool_name == "get_env_context" and isinstance(result, dict) and result.get("cached"):
                summary = result.get("summary") or {}
                telemetry.record_cache_hit(
                    tool_name=tool_name,
                    payload_hash=hash_args(summary),
                )

            return result

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not observer_enabled() or not wrap_tool(tool_name):
                return fn(*args, **kwargs)

            start = time.perf_counter()
            result = fn(*args, **kwargs)
            if _result_instrumented(result):
                return result

            duration_ms = int((time.perf_counter() - start) * 1000)
            raw_text = _extract_raw_text(fn, args, kwargs)
            actual_text = _serialize_for_tokens(result)

            record_tool_io(
                telemetry,
                tool_name=tool_name,
                raw_text=raw_text,
                actual_text=actual_text,
                module=_module(tool_name),
                meta={"duration_ms": duration_ms},
                observer_store=observer_store_getter(),
                duration_ms=duration_ms,
                hash_tool_args=hash_args_enabled(),
                args_hash_payload={"args": args, "kwargs": kwargs},
            )

            if tool_name == "get_env_context" and isinstance(result, dict) and result.get("cached"):
                summary = result.get("summary") or {}
                telemetry.record_cache_hit(
                    tool_name=tool_name,
                    payload_hash=hash_args(summary),
                )

            return result

        if inspect.iscoroutinefunction(fn):
            return async_wrapper
        return sync_wrapper

    return observe_mcp_tool
