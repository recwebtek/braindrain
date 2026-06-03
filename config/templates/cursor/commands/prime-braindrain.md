# Prime BRAINDRAIN (Cursor orchestration)

Prime this workspace for Cursor multi-agent planning: rules, subagents, hooks, skills, and operational scripts (`daily_plan_audit.py`, `plan_build_guard.py`).

**Deploy contract:** `cursor-orchestration` copies hub `scripts/daily_plan_audit.py` + `plan_branch_utils.py` and all `config/templates/agents/*.md` (including `daily-plan-auditor`) into the project. Plan files under `.cursor/plans/` stay machine-local (gitignored); the auditor updates plan `branch:` frontmatter and `.braindrain/plan-reports/` on each run. Hub script/agent upgrades apply on re-prime via content-hash markers (no `sync_templates` required for scripts/agents).

## MCP (preferred)

```
prime_workspace(
  path=".",
  agents=["cursor"],
  bundle="cursor-orchestration",
  sync_subagents=true,
)
```

Use `sync_templates=true` when refreshing Cursor hooks or slash commands from hub templates.

Or:

```
run_workflow("prime_cursor_orchestration", { "path": ".", "dry_run": false })
```

## Shell (auditor after prime)

```bash
python3 scripts/daily_plan_audit.py --repo-root . --trigger "post-prime"
```

Verify `.braindrain/primed.json` includes `braindrain_hub_root`, `scripts/daily_plan_audit.py` exists locally, and `.cursor/agents/daily-plan-auditor.md` is present. Run `/masterplan` after editing plans.
