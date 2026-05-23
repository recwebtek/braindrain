# Prime BRAINDRAIN (Cursor orchestration)

Prime this workspace for Cursor multi-agent planning: rules, subagents, hooks, skills, and operational scripts (`daily_plan_audit.py`, `plan_build_guard.py`).

## MCP (preferred)

```
prime_workspace(
  path=".",
  agents=["cursor"],
  bundle="cursor-orchestration",
  sync_templates=true,
  sync_subagents=true,
)
```

Or:

```
run_workflow("prime_cursor_orchestration", { "path": ".", "dry_run": false })
```

## Shell (auditor after prime)

```bash
python3 scripts/daily_plan_audit.py --repo-root . --trigger "post-prime"
```

Verify `.braindrain/primed.json` includes `braindrain_hub_root` and `scripts/daily_plan_audit.py` exists locally.
