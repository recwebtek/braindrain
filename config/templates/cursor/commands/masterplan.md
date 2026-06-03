# masterplan

Run planning close-out for this workspace: refresh `.braindrain/plan-reports/` from local `*.plan.md` files (never committed).

## Prerequisites

- Workspace primed with `bundle="cursor-orchestration"` so `scripts/daily_plan_audit.py` and `.cursor/agents/daily-plan-auditor.md` are deployed from the hub (re-prime after hub upgrades — script hash auto-upgrades on prime).
- `gh` available if you want PR columns in `master-plan.md`.

## Execute

From repo root:

```bash
python3 scripts/daily_plan_audit.py --repo-root . --trigger "manual-masterplan-command"
```

## What the auditor does (machine-local plans)

- Scans IDE `plans/` trees (e.g. `.cursor/plans/*.plan.md`); plans stay gitignored.
- Reconciles each plan's `branch:` with **git refs** and **`gh pr list --head`** (user-created branches win over stale auto-slugs).
- Writes corrected `branch:` into plan frontmatter when the resolved branch has a PR or exists in git.
- Regenerates `master-plan.md`, `next-actions.md`, `plan-task-board.md`, `latest.md`.

## Report back

Summarize: plan count, drift vs `_master.plan.md`, top items from `next-actions.md`, and any branch/PR corrections applied to plan frontmatter.
