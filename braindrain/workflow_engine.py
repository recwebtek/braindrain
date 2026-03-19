"""Workflow engine (Phase 3).

Executes configured workflows by calling downstream MCP tools step-by-step.
Intermediate step outputs are kept out of chat context by routing large blobs
through context-mode (FTS5) and returning handles/previews instead.

Execution includes a Docker-backed sandbox stage (llm-sandbox) for processing
and summarizing step outputs into a token/size budget without leaking the full
intermediate payload back to the caller.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from braindrain.config import Config
from braindrain.mcp_stdio_client import StdioMCPClient
from braindrain.output_router import should_route
from braindrain.telemetry import TelemetrySession

try:
    from llm_sandbox import ArtifactSandboxSession

    LLM_SANDBOX_AVAILABLE = True
except Exception:  # pragma: no cover
    ArtifactSandboxSession = None
    LLM_SANDBOX_AVAILABLE = False


@dataclass(frozen=True)
class StepResult:
    step: str
    ok: bool
    started_at: str
    finished_at: str
    output: Any
    routed: bool
    route_handle: Optional[str] = None
    route_preview: Optional[str] = None
    route_suggested_queries: Optional[list[str]] = None
    error: Optional[str] = None


def _estimate_tokens(text: str) -> int:
    # same heuristic used elsewhere (directional only)
    return max(0, len(text) // 4)


def _safe_json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _summary_object_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    steps = payload.get("steps") or []
    summary_steps: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        summary_steps.append(
            {
                "step": step.get("step"),
                "ok": step.get("ok"),
                "routed": step.get("routed"),
                "handle": step.get("route_handle"),
                "preview": step.get("route_preview"),
                "suggested_queries": step.get("route_suggested_queries"),
                "error": step.get("error"),
            }
        )
    return {
        "workflow": payload.get("workflow"),
        "generated_at": payload.get("generated_at"),
        "steps": summary_steps,
    }


def _bounded_summary_json(payload: dict[str, Any], max_chars: int) -> str:
    obj = _summary_object_from_payload(payload)

    def dump() -> str:
        return json.dumps(obj, ensure_ascii=False)

    out = dump()
    if len(out) <= max_chars:
        return out

    for step in obj.get("steps", []):
        if isinstance(step, dict) and isinstance(step.get("preview"), str):
            step["preview"] = step["preview"][:200] + "\n…(truncated)…"
        if isinstance(step, dict) and isinstance(step.get("suggested_queries"), list):
            step["suggested_queries"] = step["suggested_queries"][:3]

    out = dump()
    if len(out) <= max_chars:
        return out

    for step in obj.get("steps", []):
        if isinstance(step, dict):
            step.pop("preview", None)

    out = dump()
    return out[:max_chars]


def _summarize_in_sandbox(*, payload: dict[str, Any], max_chars: int = 8000) -> dict[str, Any]:
    """
    Use llm-sandbox (Docker) to produce a size-bounded summary.

    This intentionally does NOT call an LLM; it just runs deterministic Python
    code in an isolated container so later phases can swap in true PTC/LLM
    summarization without changing the workflow engine API surface.
    """
    if not LLM_SANDBOX_AVAILABLE:
        # Fallback: deterministic local summary (still size bounded)
        raw = _safe_json_dumps(payload)
        summary = _bounded_summary_json(payload, max_chars=max_chars)
        return {
            "mode": "local_fallback",
            "bytes_in": len(raw.encode("utf-8", errors="ignore")),
            "bytes_out": len(summary.encode("utf-8", errors="ignore")),
            "summary": summary,
        }

    if os.environ.get("BRAINDRAIN_DISABLE_DOCKER_SANDBOX") in {"1", "true", "TRUE", "yes", "YES"}:
        raw = _safe_json_dumps(payload)
        summary = _bounded_summary_json(payload, max_chars=max_chars)
        return {
            "mode": "local_fallback_disabled_docker",
            "bytes_in": len(raw.encode("utf-8", errors="ignore")),
            "bytes_out": len(summary.encode("utf-8", errors="ignore")),
            "summary": summary,
        }

    raw = _safe_json_dumps(payload)
    # Keep runtime configs tight; no user-provided overrides here.
    runtime_configs = {"network_mode": "bridge"}

    # If Docker isn't available, don't hang: fallback quickly.
    try:
        import docker  # type: ignore

        docker.from_env(timeout=2).ping()
    except Exception:
        summary = _bounded_summary_json(payload, max_chars=max_chars)
        return {
            "mode": "local_fallback_no_docker",
            "bytes_in": len(raw.encode("utf-8", errors="ignore")),
            "bytes_out": len(summary.encode("utf-8", errors="ignore")),
            "summary": summary,
        }

    code = f"""
import json

raw = {json.dumps(raw)}
max_chars = {int(max_chars)}

# Parse payload if possible; otherwise treat as text.
try:
    obj = json.loads(raw)
except Exception:
    obj = {{"raw": raw}}

def truncate_str(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    return s[:n] + "\\n…(truncated)…"

# Produce a stable, bounded summary structure.
summary = {{
    "workflow": obj.get("workflow"),
    "generated_at": obj.get("generated_at"),
    "steps": [],
}}

steps = obj.get("steps") or []
for step in steps:
    entry = {{
        "step": step.get("step"),
        "ok": step.get("ok"),
        "routed": step.get("routed"),
        "handle": step.get("route_handle"),
        "preview": step.get("route_preview"),
        "suggested_queries": step.get("route_suggested_queries"),
        "error": step.get("error"),
    }}
    summary["steps"].append(entry)

out = json.dumps(summary, ensure_ascii=False)
out = truncate_str(out, max_chars)
print(out)
"""

    with ArtifactSandboxSession(backend="docker", runtime_configs=runtime_configs) as session:
        result = session.run(code)
        out = (result.output or "").strip()
        return {
            "mode": "llm_sandbox_docker",
            "bytes_in": len(raw.encode("utf-8", errors="ignore")),
            "bytes_out": len(out.encode("utf-8", errors="ignore")),
            "summary": out,
        }


class WorkflowEngine:
    def __init__(self, *, config: Config, telemetry: TelemetrySession, context_mode_client_getter) -> None:
        self._config = config
        self._telemetry = telemetry
        self._get_context_mode_client = context_mode_client_getter

    async def _maybe_route(self, *, tool_name: str, step: str, output_obj: Any, intent: str) -> tuple[bool, dict[str, Any]]:
        """
        Route large outputs through context-mode, returning a small envelope.
        """
        text = _safe_json_dumps(output_obj)
        if not should_route(text, min_chars=5000):
            return False, {"output": output_obj}

        client = self._get_context_mode_client()
        if client is None:
            # can't route; return preview only
            return True, {
                "output_preview": text[:400],
                "error": "context_mode not configured; cannot index",
            }

        # Reuse existing markdown routing format used elsewhere (keep consistent)
        md = f"""# Workflow step output

- workflow: `{intent}`
- tool: `{tool_name}`
- step: `{step}`

```json
{text}
```
"""
        index_result = await client.index_markdown(content_md=md, source=f"workflow:{intent}", intent=intent)
        handle = f"{intent}:{tool_name}:{step}:{datetime.now().strftime('%Y%m%d%H%M%S')}"
        suggested_queries = [
            f"{intent} {tool_name} {step}",
            f"{tool_name} {step} error",
            f"{tool_name} {step} result",
        ]
        return True, {
            "route_handle": handle,
            "route_preview": text[:400],
            "route_suggested_queries": suggested_queries,
            "context_mode": {"indexed_via": "ctx_index", "index_result": index_result},
        }

    async def run(self, *, name: str, args: dict[str, Any]) -> dict[str, Any]:
        wf = self._config.get_workflow(name)
        if not wf:
            return {"error": f"Workflow '{name}' not found", "available": [w.name for w in self._config.workflows]}

        steps_out: list[StepResult] = []

        # Execute steps sequentially (simple, deterministic)
        for step in wf.steps:
            started = datetime.now().isoformat()
            ok = True
            tool_name = step.split(".")[0] if "." in step else step
            method = step.split(".")[1] if "." in step else step

            tool = self._config.get_tool(tool_name)
            if not tool or not tool.command:
                finished = datetime.now().isoformat()
                steps_out.append(
                    StepResult(
                        step=step,
                        ok=False,
                        started_at=started,
                        finished_at=finished,
                        output=None,
                        routed=False,
                        error=f"Tool '{tool_name}' not configured",
                    )
                )
                continue

            try:
                client = StdioMCPClient(tool.command)
                output_obj = await client.call_tool(method, args)
            except Exception as e:  # pragma: no cover
                ok = False
                output_obj = None
                err = str(e)
            else:
                err = None

            routed = False
            route_handle = None
            route_preview = None
            route_suggested_queries = None

            if ok and output_obj is not None:
                routed, envelope = await self._maybe_route(
                    tool_name=tool_name, step=step, output_obj=output_obj, intent=name
                )
                if routed and "route_handle" in envelope:
                    route_handle = envelope.get("route_handle")
                    route_preview = envelope.get("route_preview")
                    route_suggested_queries = envelope.get("route_suggested_queries")
                    output_obj = envelope

            finished = datetime.now().isoformat()
            steps_out.append(
                StepResult(
                    step=step,
                    ok=ok,
                    started_at=started,
                    finished_at=finished,
                    output=output_obj,
                    routed=routed,
                    route_handle=route_handle,
                    route_preview=route_preview,
                    route_suggested_queries=route_suggested_queries,
                    error=err,
                )
            )

        raw_payload = {
            "workflow": name,
            "generated_at": datetime.now().isoformat(),
            "args": args,
            "steps": [json.loads(_safe_json_dumps(s.__dict__)) for s in steps_out],
        }

        sandbox_summary = _summarize_in_sandbox(payload=raw_payload, max_chars=min(8000, wf.token_budget * 4))

        # Telemetry attribution: raw vs returned (estimated)
        raw_text = _safe_json_dumps(raw_payload)
        actual_text = _safe_json_dumps(sandbox_summary)
        self._telemetry.record(
            tool_name="run_workflow",
            raw_text=raw_text,
            actual_text=actual_text,
            module="workflow_engine",
            meta={"workflow": name, "steps": wf.steps, "sandbox_mode": sandbox_summary.get("mode")},
        )

        return {
            "workflow": name,
            "token_budget": wf.token_budget,
            "sandbox": {"enabled": True, "mode": sandbox_summary.get("mode"), "bytes_in": sandbox_summary.get("bytes_in")},
            "result": json.loads(sandbox_summary["summary"]) if sandbox_summary.get("summary", "").startswith("{") else sandbox_summary,
        }

    def plan(self, *, name: str, args: dict[str, Any]) -> dict[str, Any]:
        wf = self._config.get_workflow(name)
        if not wf:
            return {"error": f"Workflow '{name}' not found", "available": [w.name for w in self._config.workflows]}

        md = f"""# Workflow plan: `{name}`

## Inputs

```json
{json.dumps(args or {{}}, indent=2, ensure_ascii=False)}
```

## Steps
{chr(10).join([f"- `{s}`" for s in wf.steps])}

## Output routing
- Large step outputs will be routed through **context-mode** (FTS5) and returned as handles + previews.

## Token budget
- `token_budget`: **{wf.token_budget}** (used as a size cap for the final summary payload)

## Safety
- Docker sandbox is used for intermediate processing/summarization (network: bridge).
"""
        return {
            "workflow": name,
            "token_budget": wf.token_budget,
            "plan_markdown": md,
            "plan_before_run": wf.plan_before_run,
        }

