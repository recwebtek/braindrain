# metaplan-closeout

Split a **meta** umbrella plan (`disposition: meta`) into child `.cursor/plans/*.plan.md` files and wire `_master.plan.md`.

## Prerequisites

- Meta plan lives under `.cursor/plans/` (not `QA-Logs/` or other paths).
- Meta frontmatter includes `children_spec:` with `id`, `file`, `name`, `branch`, and `section` per child.
- Meta todos use `split-<id>` and flip to `completed` only when the child file exists.

## Phase 1 — skeletons + master wiring (script)

Replace `PATH/TO/meta.plan.md` with the meta plan file:

```bash
python3 scripts/plan_meta_closeout.py --meta PATH/TO/meta.plan.md --repo-root .
```

Add `--dry-run` to preview without writes. Add `--no-run-auditor` to skip the auditor invoke.

The script:

1. Validates `disposition: meta` and `children_spec`
2. Writes child plan skeletons under `.cursor/plans/` (skips existing unless `--force`)
3. Marks matching `split-*` todos `completed` on the meta plan
4. Appends child links under `_master.plan.md` → `## active`
5. Invokes `daily_plan_audit.py --trigger "meta-closeout"` by default

## Phase 2 — agent body extraction (only if `body_pending` in JSON)

When the script reports `body_pending: [...]`:

- For each listed child: copy the parent `section:` slice from the meta plan body into the child plan
- Replace placeholder `impl-*` todos with concrete implementation todos from that section
- Do **not** edit Ruler/protocol files

## Guardrails

- **Do not** run `plan_build_guard.py` on the meta plan — it returns `meta_plan_no_build`
- After phase 1 + phase 2 complete → **always** run `/masterplan`
- Start a **new chat** before Plan Build on the first child plan

## Then

```bash
# refresh build queue with new children
/masterplan

# build ONE child (not the meta plan)
python3 scripts/plan_build_guard.py --plan .cursor/plans/CHILD.plan.md --repo-root .
```
