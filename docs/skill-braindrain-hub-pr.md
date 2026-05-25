# Skill: braindrain-hub-pr

Contributor workflow for **BRAIN_MCP_HUB** — branch hygiene, tests, and PRs before changing consumer repos.

## Canonical source

| Path | Purpose |
|------|---------|
| `config/templates/cursor-skills/braindrain-hub-pr/SKILL.md` | Template deployed by `prime_workspace` |
| `.cursor/skills/braindrain-hub-pr/SKILL.md` | Installed copy (gitignored at repo root; created by prime) |

Personal copy (optional): `~/.cursor/skills/braindrain-hub-pr/SKILL.md`

## When to use

- Fixing `prime_workspace`, MCP tools, templates, or hub scripts
- A consumer prime surfaced a bug that belongs in the hub
- User says: "hub PR", "fix braindrain mcp", "braindrain-hub-pr"

## Bundle deployment

Listed in:

- `config/bundles/core.yaml` → `skills: [braindrain-hub-pr]`
- `config/bundles/full.yaml` → same skill id appended

After merge, prime the hub repo itself to install the skill locally:

```text
prime_workspace(path=".", agents=["cursor"], bundle="core")
```

Or use bundle `full` for the full skill set.

## Related PRs

| Branch | Topic |
|--------|--------|
| `docs/skill-braindrain-hub-pr` | This skill + `deploy_cursor_skill_templates` |
| `feat/cursor-plan-slash-commands` | Plan slash commands + audit script deploy (separate) |
| `codex/livingdash` | Livingdash sidecar (separate; do not mix) |

## Maintainer notes

- Edit the template under `config/templates/cursor-skills/`, not generated `.cursor/skills/` in gitignored trees.
- Re-prime consumer projects after hub releases; reload MCP after server changes.
