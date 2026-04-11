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

## Tool Use

- `scriptlib_enable` — opt the workspace into scriptlib
- `scriptlib_harvest_workspace` — copy scripts from `tests/`, `scripts/`, and other supported locations
- `scriptlib_search` — find reusable candidates
- `scriptlib_describe` — inspect metadata, history, and run mode
- `scriptlib_run` — execute with `wrapped`, `source_context`, or `native_copy`
- `scriptlib_fork` — create a safe new version for changes
- `scriptlib_record_result` — update score, mistakes, and validation state
- `scriptlib_refresh_index` — rebuild the catalog after manual edits

## Rules

- Search first, write later.
- For repo-relative tests or helpers, assume `wrapped` or `source_context` until proven self-contained.
- Do not mark `native_copy` unless validation proved the copied script runs cleanly from the library artifact itself.
- Record failures with short, concrete notes so the library gets smarter over time.

## Handoff Expectations

When reporting back to another agent or the user, include:

```json
{
  "scriptId": "",
  "executionMode": "",
  "whySelected": "",
  "reuseDecision": "reuse|fork|new",
  "riskLevel": "",
  "nextAction": ""
}
```
