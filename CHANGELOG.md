# Changelog

All notable changes to this project are documented in this file.

The format is based on keeping a clear, user-facing history. Version in `VERSION` matches the release called out in `README.md`.

## [1.0.3] — 2026-04-10

### For users

- You can opt into **scriptlib**: harvest and search reusable scripts, run them through MCP, and keep guidance in agent rules when scriptlib is enabled for a workspace.
- **prime_workspace** now deploys **Cursor and Codex subagent templates** from `config/templates/cursor-subagents/` and `config/templates/codex-subagents/`, with optional `sync_subagents` and `codex_agent_targets` for Codex layout.
- **Token checkpoint protocol** and optional `.braindrain/token-metrics.jsonl` schema `1.0` are documented in templates and README for consistent observability.

### For contributors

- Added librarian Cursor agent stub and `scriptlib-librarian` skill; `network_connectivity_check.py` for workspace connectivity checks.
- Tests: `tests/test_scriptlib.py` (scriptlib unit coverage).
- Merge branch combines token-stats rule updates, scriptlib stack, and learning-layer subagent deployment (resolved `workspace_primer.py` to keep both scriptlib seeding and subagent flows).
