# Build plan (branch guard first)

When implementing from a `*.plan.md`, **run the branch guard before any file edits**.

## Required first command

Replace `PATH/TO/plan.plan.md` with the active plan file:

```bash
python3 scripts/plan_build_guard.py --plan PATH/TO/plan.plan.md --repo-root .
```

This creates the plan branch if missing and checks out that branch (stash + switch when the tree is dirty).

If the guard JSON reports `"error": "meta_plan_no_build"`:

- **Stop** — do not implement on the meta plan
- Run `/metaplan-closeout` on the meta plan, finish phase 2 body extraction if needed
- Run `/masterplan`, then Plan Build on a **child** plan file

## Then implement

Proceed with Plan Build / implementation only after the guard JSON reports `"ok": true`.

If `branch:` is missing from the plan, run the daily auditor first:

```bash
python3 scripts/daily_plan_audit.py --repo-root . --trigger "pre-build"
```
