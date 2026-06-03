---
name: braindrain-hub-pr
description: >-
  Contribute bug fixes and features to the Braindrain MCP hub repo (BRAIN_MCP_HUB)
  with correct repo boundaries, branch hygiene, tests, and PR workflow. Use when
  fixing prime_workspace, MCP tools, templates, Livingdash, plan auditor, or when
  the user says "fix braindrain", "hub PR", "braindrain mcp change", or a consumer
  prime needs a durable hub fix — not ad-hoc edits only in a consumer repo.
---

# Braindrain hub contributor

Guide for changing **BRAIN_MCP_HUB** (the MCP server / primer / templates), then shipping via **PR → review → merge**, and only then updating consumer repos via `prime_workspace`.

## Repo map (do not confuse)

| Repo | Role | Commit here? |
|------|------|----------------|
| **BRAIN_MCP_HUB** | Source of truth: `braindrain/`, `config/templates/`, `scripts/daily_plan_audit.py`, bundles | **Yes** — all durable fixes |
| **Consumer** (STACKCRAFT, etc.) | Primed artifacts: `.cursor/`, vendored scripts, `.braindrain/` | **Optional** — local prime only until hub merges |

**Rule:** If the fix belongs in `prime_workspace`, templates, or MCP tools → edit the **hub**, not only the consumer.

## Before you touch the hub

1. Confirm hub path (typical): `/Volumes/devnvme/Development/BRAIN_MCP_HUB`
2. `cd` to hub root — **never** apply hub template edits from a consumer workspace without switching directory
3. `git fetch origin` and note current branch
4. Ask user if an open feature branch (e.g. `codex/livingdash`) must stay isolated

## Branch strategy

### Default (hub fix / bug / prime feature)

```bash
cd /path/to/BRAIN_MCP_HUB
git fetch origin
git switch -c fix/<short-topic> origin/main
```

One concern per branch. PR base: **`main`**.

### When user already has a long-lived branch

- **Do not** mix unrelated work (e.g. Livingdash sidecar + unrelated templates) on one branch
- **Do not** use `git stash push --keep-index` when staged and unstaged changes are different features
- Prefer: stash **everything** (`git stash push -u`) or commit feature A, then branch from `main` for feature B

### Consumer-only hotfix (temporary)

Allowed only if user explicitly wants a **stopgap** before hub merge:

- Copy vendored files into consumer; document *"Replace after hub PR merges and re-prime"*
- Still open a hub PR for the real fix

## What lives where (hub)

| Change type | Hub paths |
|-------------|-----------|
| Cursor skills | `config/templates/cursor-skills/<name>/SKILL.md` → `.cursor/skills/<name>/SKILL.md` |
| Slash commands | `config/templates/cursor/commands/*.md` → `.cursor/commands/` via `deploy_cursor_commands` in `prime_workspace` (e.g. `brainlog.md`, `prime-braindrain.md`) |
| Subagents | `config/templates/agents/*.md` |
| Primer logic | `braindrain/workspace_primer.py` |
| Tests | `tests/test_*.py` |

Register new skills in `config/bundles/*.yaml` under `skills:` so `prime_workspace` deploys them.

## Implementation checklist

```
- [ ] Working directory is BRAIN_MCP_HUB root
- [ ] Branch from origin/main, name fix/<topic> or docs/<topic>
- [ ] Smallest diff; no unrelated files
- [ ] Tests run (see below)
- [ ] Commit with conventional message
- [ ] Push + open PR (gh)
- [ ] Tell user: reload braindrain MCP after merge
- [ ] Consumer: re-run prime_workspace
```

## Slash command: `/brainlog`

- **Template:** `config/templates/cursor/commands/brainlog.md`
- **When:** end of a largely completed chat/task (not session start).
- **Does:** MCP-driven L1 `touch_session(end_session=true)`, token `record_token_checkpoint(phase="end")`, L2 `evaluate_memory_candidate` / optional `store_fact` or `record_episode`, L3 `get_dream_status` / optional `run_dream`, plus checklist for `.braindrain/*.md` updates.
- **Requires:** memory sections in `config/hub_config.yaml` (`sessions`, `wiki_brain`, `lessons`, `dreaming`, `memory_learning`) — wired by the memory config plan.

After adding or changing command templates, run `prime_workspace` on a consumer (or hub) with Cursor in scope; use `sync_templates=true` to refresh an existing `.cursor/commands/brainlog.md`.

## Tests (hub)

From hub root, with Python + `pyyaml`:

```bash
python3 -m pytest tests/test_workspace_primer_hooks.py -q
```

## PR workflow

```bash
git push -u origin HEAD
gh pr create --base main --title "docs(skills): braindrain hub PR contributor skill" --body "$(cat <<'EOF'
## Summary
- …

## Test plan
- [ ] pytest tests/test_workspace_primer_hooks.py
- [ ] prime_workspace on hub repo installs `.cursor/skills/braindrain-hub-pr/`

EOF
)"
```

## After merge

1. Reload braindrain MCP in Cursor
2. Re-run `prime_workspace` on consumer repos
3. Invoke skill: `/braindrain-hub-pr` or ask agent to follow `braindrain-hub-pr` skill

## Anti-patterns

| Don't | Do instead |
|-------|------------|
| Edit hub while fixing a consumer without a branch | Hub branch + PR, then prime consumer |
| Mix Livingdash + unrelated templates on one branch | Separate PRs from `main` |
| `stash --keep-index` with mixed features | `stash push -u` or separate branches |
| Large diff paste to hub agent | Branch name + PR URL |

## Handoff blurb

```markdown
Hub change on branch `<branch>` (from main). Not on unrelated feature branches.
PR: <url>
Touches: <files>
Tests: <commands>
After merge: reload MCP + prime_workspace on <consumer>.
```
