# Changelog

All notable changes to this project are documented in this file.

The format is based on keeping a clear, user-facing history. Version in `VERSION` matches the release called out in `README.md`.

## Unreleased

### For users

- **Scriptlib modularization**: scriptlib now treats project-local `.scriptlib/` and shared `~/.braindrain/scriptlib` as distinct layers, with promotion-only flow into the shared personal catalog.
- **New scriptlib MCP tools**: added promote, update discovery/application, maintenance, and catalog status flows for local/shared script operations.
- **Librarian-first routing**: freestanding reusable scripts are now expected to go through librarian decision flow (`reuse`, `fork`, or `new`) before a fresh script is created.

### For contributors

- **Subagent templates**: single source tree `config/templates/agents/` deploys to `.cursor/agents/` and/or `.codex/agents/` depending on the resolved IDE set; duplicate `cursor-subagents/` and `codex-subagents/` template dirs were removed. Skills remain under `config/templates/cursor-skills/`. Added `daily-plan-auditor` agent and planning close-out guidance in Ruler `RULES.md`. Planning audit script moves `archived` plans into `<ide>/plans/.plan.archives/`. Tests: `tests/test_plan_auditor_master.py`.

## [1.0.3] — 2026-04-10

### For users

- You can opt into **scriptlib**: harvest and search reusable scripts, run them through MCP, and keep guidance in agent rules when scriptlib is enabled for a workspace.
- **prime_workspace** deploys Cursor/Codex subagent markdown into `.cursor/agents/` and `.codex/agents/` with optional `sync_subagents` and `codex_agent_targets`. (Older docs referred to split template trees; the repo now uses a single canonical tree — see Unreleased.)
- **Token checkpoint protocol** and optional `.braindrain/token-metrics.jsonl` schema `1.0` are documented in templates and README for consistent observability.

### For contributors

- Added librarian Cursor agent stub and `scriptlib-librarian` skill; `network_connectivity_check.py` for workspace connectivity checks.
- Tests: `tests/test_scriptlib.py` (scriptlib unit coverage).
- Merge branch combines token-stats rule updates, scriptlib stack, and learning-layer subagent deployment (resolved `workspace_primer.py` to keep both scriptlib seeding and subagent flows).
