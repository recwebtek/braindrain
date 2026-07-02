"""Optional OpenTelemetry helpers for MCP tool spans."""

from __future__ import annotations

import os
from typing import Any

try:  # pragma: no cover - runtime optional dependency path
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode

    _OTEL_AVAILABLE = True
except Exception:  # pragma: no cover - graceful fallback
    trace = None
    Status = None
    StatusCode = None
    _OTEL_AVAILABLE = False


def otel_enabled() -> bool:
    if not _OTEL_AVAILABLE:
        return False
    flag = os.environ.get("BRAINDRAIN_OTEL_ENABLED", "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def emit_tool_span(
    *,
    tool_name: str,
    module: str,
    duration_ms: int,
    status: str,
    raw_tokens: int = 0,
    actual_tokens: int = 0,
    saved_tokens: int = 0,
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit a single OpenTelemetry span for a tool invocation."""
    if not otel_enabled():
        return

    tracer = trace.get_tracer("braindrain.mcp")
    with tracer.start_as_current_span(f"mcp.tool.{tool_name}") as span:
        span.set_attribute("mcp.tool.name", tool_name)
        span.set_attribute("mcp.tool.module", module)
        span.set_attribute("mcp.tool.duration_ms", duration_ms)
        span.set_attribute("mcp.tool.status", status)
        span.set_attribute("mcp.tool.tokens_in_raw_est", int(raw_tokens))
        span.set_attribute("mcp.tool.tokens_in_actual_est", int(actual_tokens))
        span.set_attribute("mcp.tool.tokens_saved_est", int(saved_tokens))
        for key, value in (extra or {}).items():
            if isinstance(value, (str, bool, int, float)):
                span.set_attribute(f"mcp.tool.{key}", value)
        if status != "ok":
            span.set_status(Status(StatusCode.ERROR, description="tool invocation failed"))
