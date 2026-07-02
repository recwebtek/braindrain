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
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from braindrain.config import Config
from braindrain.mcp_stdio_client import StdioMCPClient
from braindrain.output_router import should_route
from braindrain.repo_stats import count_repo_files
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
    route_handle: str | None = None
    route_preview: str | None = None
    route_suggested_queries: list[str] | None = None
    error: str | None = None


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
    # network_mode: none ensures the sandbox has no internet access.
    runtime_configs = {"network_mode": "none"}

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


def _openai_compat_chat_completion(
    *,
    api_base: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    api_key: str = "",
) -> str | None:
    base = (api_base or "").rstrip("/")
    if not base:
        return None
    url = f"{base}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices:
        return None
    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        return None
    return content.strip()


def _step_tool_name(step: Any) -> str:
    if isinstance(step, dict):
        step_name = str(step.get("name", ""))
    else:
        step_name = str(step)
    return step_name.split(".")[0] if "." in step_name else step_name


def should_run_workflow_step(
    *, step: Any, workflow, args: dict[str, Any]
) -> tuple[bool, str | None]:
    """
    Gate optional workflow steps (distiller for large repos, heavy map when budget is low).
    """
    options = getattr(workflow, "options", None) or {}
    tool_name = _step_tool_name(step)
    path = str(args.get("path") or ".")

    distiller_threshold = options.get("distiller_when_file_count_gt")
    if tool_name == "ai_distiller" and distiller_threshold is not None:
        try:
            threshold = int(distiller_threshold)
        except (TypeError, ValueError):
            threshold = 0
        file_count = count_repo_files(path)
        if file_count <= threshold:
            return False, f"skipped: file_count={file_count} <= distiller_threshold={threshold}"

    heavy_tools = {"repo_mapper", "jcodemunch"}
    budget_gte = options.get("include_repo_mapper_when_token_budget_gte")
    if tool_name in heavy_tools and budget_gte is not None:
        try:
            gate = int(budget_gte)
        except (TypeError, ValueError):
            gate = 0
        budget = int(args.get("token_budget", getattr(workflow, "token_budget", 0)))
        if budget < gate:
            return False, f"skipped: token_budget={budget} < include_heavy_tools_gte={gate}"

    return True, None


class WorkflowEngine:
    def __init__(
        self, *, config: Config, telemetry: TelemetrySession, context_mode_client_getter
    ) -> None:
        self._config = config
        self._telemetry = telemetry
        self._get_context_mode_client = context_mode_client_getter

    def _should_use_model_tiers(self) -> bool:
        return bool(self._config.get("modules.workflow_engine.use_model_tiers", False))

    def _model_tier_summary(self, *, workflow, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self._should_use_model_tiers():
            return None
        models = getattr(self._config.data, "models", {}) or {}
        tier = models.get(str(workflow.model))
        if tier is None:
            return None

        summary_obj = _summary_object_from_payload(payload)
        system_prompt = (
            "You summarize workflow execution for operators. Keep JSON shape with keys "
            "`workflow`, `generated_at`, `steps` and concise step diagnostics."
        )
        user_prompt = _safe_json_dumps(summary_obj)
        api_key = ""
        if getattr(tier, "provider", "") not in {"lm_studio", "ollama"}:
            api_key = os.environ.get("OPENAI_API_KEY", "")
        content = _openai_compat_chat_completion(
            api_base=str(getattr(tier, "api_base", "") or ""),
            model=str(getattr(tier, "model", "") or ""),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=min(int(getattr(tier, "max_tokens", 2048) or 2048), 1200),
            api_key=api_key,
        )
        if not content:
            return None
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return {
                    "mode": "model_tier",
                    "provider": str(getattr(tier, "provider", "")),
                    "model": str(getattr(tier, "model", "")),
                    "summary": content,
                    "result": parsed,
                }
        except json.JSONDecodeError:
            pass
        return {
            "mode": "model_tier_text",
            "provider": str(getattr(tier, "provider", "")),
            "model": str(getattr(tier, "model", "")),
            "summary": content,
            "result": {
                "workflow": payload.get("workflow"),
                "generated_at": payload.get("generated_at"),
                "text": content,
            },
        }

    async def _maybe_route(
        self, *, tool_name: str, step: str, output_obj: Any, intent: str
    ) -> tuple[bool, dict[str, Any]]:
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
        index_result = await client.index_markdown(
            content_md=md, source=f"workflow:{intent}", intent=intent
        )
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
            return {
                "error": f"Workflow '{name}' not found",
                "available": [w.name for w in self._config.workflows],
            }

        steps_out: list[StepResult] = []

        requested_role = str(args.get("role", "")).strip()
        if wf.required_roles and requested_role and requested_role not in wf.required_roles:
            return {
                "workflow": name,
                "status": "role_not_allowed",
                "required_roles": wf.required_roles,
                "provided_role": requested_role,
            }

        # Execute steps sequentially (simple, deterministic)
        for step in wf.steps:
            run_step, skip_reason = should_run_workflow_step(step=step, workflow=wf, args=args)
            if not run_step:
                steps_out.append(
                    StepResult(
                        step=step,
                        ok=True,
                        started_at=datetime.now().isoformat(),
                        finished_at=datetime.now().isoformat(),
                        output={"skipped": True, "reason": skip_reason},
                        routed=False,
                    )
                )
                continue

            started = datetime.now().isoformat()
            ok = True
            step_args = dict(args)
            if isinstance(step, dict):
                step_name = str(step.get("name", ""))
                tool_name = step_name.split(".")[0] if "." in step_name else step_name
                method = step_name.split(".")[1] if "." in step_name else step_name
                override_args = step.get("args", {})
                if isinstance(override_args, dict):
                    step_args.update(override_args)
            else:
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
                output_obj = await client.call_tool(method, step_args)
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

        sandbox_summary = _summarize_in_sandbox(
            payload=raw_payload, max_chars=min(8000, wf.token_budget * 4)
        )
        model_summary = self._model_tier_summary(workflow=wf, payload=raw_payload)
        final_summary = model_summary or sandbox_summary

        # Telemetry attribution: raw vs returned (estimated)
        raw_text = _safe_json_dumps(raw_payload)
        actual_text = _safe_json_dumps(final_summary)
        self._telemetry.record(
            tool_name="run_workflow",
            raw_text=raw_text,
            actual_text=actual_text,
            module="workflow_engine",
            meta={
                "workflow": name,
                "steps": wf.steps,
                "sandbox_mode": sandbox_summary.get("mode"),
                "model_summary_mode": (model_summary or {}).get("mode") if model_summary else None,
            },
        )

        return {
            "workflow": name,
            "token_budget": wf.token_budget,
            "sandbox": {
                "enabled": True,
                "mode": sandbox_summary.get("mode"),
                "bytes_in": sandbox_summary.get("bytes_in"),
            },
            "model_summary": {
                "enabled": bool(model_summary),
                "mode": (model_summary or {}).get("mode"),
                "provider": (model_summary or {}).get("provider"),
                "model": (model_summary or {}).get("model"),
            },
            "result": json.loads(final_summary["summary"])
            if final_summary.get("summary", "").startswith("{")
            else final_summary.get("result", final_summary),
        }

    def plan(self, *, name: str, args: dict[str, Any]) -> dict[str, Any]:
        wf = self._config.get_workflow(name)
        if not wf:
            return {
                "error": f"Workflow '{name}' not found",
                "available": [w.name for w in self._config.workflows],
            }

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
- Docker sandbox is used for intermediate processing/summarization (network: none).
"""
        return {
            "workflow": name,
            "token_budget": wf.token_budget,
            "plan_markdown": md,
            "plan_before_run": wf.plan_before_run,
        }
