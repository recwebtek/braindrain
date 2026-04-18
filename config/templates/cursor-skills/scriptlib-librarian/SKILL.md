# Scriptlib Librarian Skill

## When to Apply
Apply when an agent needs to find, reuse, adapt, catalog, score, or run scripts through scriptlib.

## Core Workflow

1. Check whether scriptlib is enabled for the workspace.
2. Search scriptlib before planning any new script creation.
3. If a close match exists, prefer:
   - reuse as-is
   - fork into a new version
   - record why it failed before rewriting
4. If the workspace has useful scripts outside scriptlib, harvest them first.
5. Run path-sensitive scripts through scriptlib so the original workspace context is restored.
6. Promote validated reusable scripts into the shared personal library only with explicit approval.
7. Use maintenance routines to surface duplicate scripts, stale pins, ignored junk dirs, and promotion candidates.

## Tool Use

- `scriptlib_enable` — opt the workspace into scriptlib
- `scriptlib_harvest_workspace` — copy scripts from `tests/`, `scripts/`, and other supported locations
- `scriptlib_search` — find reusable candidates
- `scriptlib_describe` — inspect metadata, history, and run mode
- `scriptlib_run` — execute with `wrapped`, `source_context`, or `native_copy`
- `scriptlib_fork` — create a safe new version for changes
- `scriptlib_promote` — publish a validated local script into the shared personal library
- `scriptlib_list_updates` — list pinned shared scripts with available updates
- `scriptlib_apply_update` — pin or upgrade a shared script artifact for the current workspace
- `scriptlib_run_maintenance` — refresh indexes and surface duplicates, updates, and promotion candidates
- `scriptlib_catalog_status` — inspect local/shared catalog state and shared pins
- `scriptlib_record_result` — update score, mistakes, and validation state
- `scriptlib_refresh_index` — rebuild the catalog after manual edits

## Rules

- Search first, write later.
- A freestanding reusable script must not be written until librarian returns a structured `reuseDecision`.
- For repo-relative tests or helpers, assume `wrapped` or `source_context` until proven self-contained.
- Do not mark `native_copy` unless validation proved the copied script runs cleanly from the library artifact itself.
- Record failures with short, concrete notes so the library gets smarter over time.
- Promotion into the shared personal library requires explicit approval.
- Shared artifact upgrades require explicit approval.
- Librarian may maintain ignore rules and catalog health without mutating the shared trust surface.

## Handoff Expectations

When reporting back to another agent or the user, include:

```json
{
  "scriptId": "",
  "executionMode": "",
  "whySelected": "",
  "reuseDecision": "reuse|fork|new",
  "approvalRequired": [],
  "riskLevel": "",
  "nextAction": ""
}
```
