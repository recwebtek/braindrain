# masterplan

Run planning close-out for this workspace: refresh `.braindrain/plan-reports/` from local `*.plan.md` files (never committed).

## Prerequisites

- Workspace primed with `bundle="cursor-orchestration"` so `scripts/daily_plan_audit.py` and `.cursor/agents/daily-plan-auditor.md` are deployed from the hub (re-prime after hub upgrades — script hash auto-upgrades on prime).
- `gh` available if you want PR columns in `master-plan.md`.

## Execute

From repo root:

```bash
# read-only (default)
python3 scripts/daily_plan_audit.py --repo-root . --trigger "manual-masterplan-command"

# after you confirm the READY_TO_ARCHIVE list in next-actions.md
python3 scripts/daily_plan_audit.py --repo-root . --trigger "manual-masterplan-command" \
  --apply-disposition-sync --apply-archive

# optional: write high-confidence overlap relations to plan frontmatter
python3 scripts/daily_plan_audit.py --repo-root . --trigger "manual-masterplan-command" \
  --apply-overlap-relations

# optional: write goal_tags from alignment scoring
python3 scripts/daily_plan_audit.py --repo-root . --trigger "manual-masterplan-command" \
  --apply-goal-tags
```

Defaults for overlap threshold and apply flags can also live in `config/hub_config.yaml` under `planning_auditor:` (CLI overrides YAML for one-off runs).

Write-back flags (`--apply-disposition-sync`, `--apply-archive`, `--apply-overlap-relations`, `--apply-goal-tags`) are **human + CLI only**. The daily-plan-auditor subagent and stop hook never pass them unless you explicitly request apply in the same turn.

## What the auditor does (machine-local plans)

- Scans IDE `plans/` trees (e.g. `.cursor/plans/*.plan.md`); plans stay gitignored.
- Reconciles each plan's `branch:` with **git refs** and **`gh pr list --head`** (user-created branches win over stale auto-slugs).
- Writes corrected `branch:` into plan frontmatter when the resolved branch has a PR or exists in git.
- Regenerates `master-plan.md`, `next-actions.md`, `plan-task-board.md`, `overlap-relations.md`, `latest.md`.
- Adds **Overlap clusters** and **Goal alignment** sections to `master-plan.md` when overlaps or goal sources exist.

## Report back

Summarize: plan count, drift vs `_master.plan.md`, top items from `next-actions.md`, overlap clusters (if any), low goal-alignment plans, and any branch/PR corrections applied to plan frontmatter.
