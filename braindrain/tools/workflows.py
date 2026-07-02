"""Workflow tool implementations extracted from server.py."""

from __future__ import annotations


async def list_workflows_impl(config) -> dict:
    return config.get_workflow_catalog()


async def run_workflow_impl(
    config,
    telemetry,
    get_workflow_engine,
    init_project_memory_fn,
    prime_workspace_fn,
    name: str,
    args: dict | None = None,
) -> dict:
    if args is None:
        args = {}

    if name == "init_project_memory":
        return init_project_memory_fn(
            path=args.get("path", "."),
            dry_run=bool(args.get("dry_run", False)),
        )

    if name == "prime_cursor_orchestration":
        return await prime_workspace_fn(
            path=args.get("path", "."),
            agents=args.get("agents") or ["cursor"],
            dry_run=bool(args.get("dry_run", False)),
            sync_templates=bool(args.get("sync_templates", True)),
            sync_subagents=bool(args.get("sync_subagents", True)),
            bundle=args.get("bundle") or "cursor-orchestration",
            compact_mcp_response=bool(args.get("compact_mcp_response", True)),
        )

    workflow = config.get_workflow(name)
    if not workflow:
        return {
            "error": f"Workflow '{name}' not found",
            "available": [wf.name for wf in config.workflows],
        }

    engine = get_workflow_engine()
    if engine is None:
        return {
            "workflow": name,
            "status": "workflow_engine_disabled",
            "message": "Enable modules.workflow_engine.enabled in config/hub_config.yaml",
            "token_budget": workflow.token_budget,
        }

    try:
        return await engine.run(name=name, args=args)
    except Exception as e:
        telemetry.log_error(f"Workflow '{name}' failed: {e}", context={"name": name, "args": args})
        return {"error": str(e), "workflow": name}


async def plan_workflow_impl(
    config, get_workflow_engine, name: str, args: dict | None = None
) -> dict:
    if args is None:
        args = {}

    if name == "prime_cursor_orchestration":
        return {
            "workflow": name,
            "status": "plan_ready",
            "plan": {
                "workflow": name,
                "token_budget": 800,
                "steps": ["braindrain.prime_workspace"],
                "args": {
                    "path": args.get("path", "."),
                    "agents": args.get("agents") or ["cursor"],
                    "bundle": args.get("bundle") or "cursor-orchestration",
                    "sync_templates": bool(args.get("sync_templates", True)),
                    "sync_subagents": bool(args.get("sync_subagents", True)),
                    "dry_run": bool(args.get("dry_run", False)),
                },
            },
            "notes": [
                "Deploys cursor-orchestration bundle: agents, hooks, skills, scripts.",
                "Use run_workflow('prime_cursor_orchestration') or prime_workspace with bundle=cursor-orchestration.",
            ],
        }

    if name == "init_project_memory":
        return {
            "workflow": name,
            "status": "plan_ready",
            "plan": {
                "workflow": name,
                "token_budget": 500,
                "steps": ["braindrain.init_project_memory"],
                "args": {
                    "path": args.get("path", "."),
                    "dry_run": bool(args.get("dry_run", False)),
                },
            },
            "notes": [
                "Idempotent memory bootstrap.",
                "Creates .braindrain/AGENT_MEMORY.md and .cursor/hooks/state/continual-learning-index.json when missing.",
                "Migrates .devdocs/AGENT_MEMORY.md to .braindrain/ if the legacy path exists.",
            ],
        }

    workflow = config.get_workflow(name)
    if not workflow:
        return {
            "error": f"Workflow '{name}' not found",
            "available": [wf.name for wf in config.workflows],
        }

    engine = get_workflow_engine()
    if engine is None:
        return {
            "workflow": name,
            "status": "workflow_engine_disabled",
            "message": "Enable modules.workflow_engine.enabled in config/hub_config.yaml to run workflows",
            "plan": {
                "workflow": name,
                "token_budget": workflow.token_budget,
                "steps": workflow.steps,
                "args": args,
            },
        }

    return engine.plan(name=name, args=args)
