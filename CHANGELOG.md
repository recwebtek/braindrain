# Changelog

All notable changes to this project are documented in this file.

The format is based on keeping a clear, user-facing history. Version in `VERSION` matches the release called out in `README.md`.

## Unreleased

### For users

- **CI badge**: GitHub Actions runs ruff + pytest on push and pull requests (see README Contributing section).
- **`braindrain-hub-pr` skill**: `prime_workspace` deploys bundle-listed Cursor skills from `config/templates/cursor-skills/` (included in `core` and `full` bundles). Documents hub-vs-consumer PR workflow in `docs/skill-braindrain-hub-pr.md`.
- **Scriptlib modularization**: scriptlib now treats project-local `.scriptlib/` and shared `~/.braindrain/scriptlib` as distinct layers, with promotion-only flow into the shared personal catalog.
- **New scriptlib MCP tools**: added promote, update discovery/application, maintenance, and catalog status flows for local/shared script operations.
- **Librarian-first routing**: freestanding reusable scripts are now expected to go through librarian decision flow (`reuse`, `fork`, or `new`) before a fresh script is created.
- **Model provenance controls**: added `provenance` config toggles for chat footer scope, plan metadata stamping, and subagent model tracing (`.braindrain/plan-reports/model-trace.jsonl`), plus audit report frontmatter fields for model/date/cursor mode attribution.
- **Cursor stop hook stability**: `on-stop-observe.sh` is now output-silent by default so Cursor stop-hook JSON parsing is not broken by plain-text stdout.

### For contributors

- **CI foundation (P0-1)**: `.github/workflows/ci.yml` matrix (Python 3.11 / 3.12 / 3.14 × Ubuntu / macOS); `uv.lock` for reproducible installs; ruff lint+format in `pyproject.toml`; `.pre-commit-config.yaml` (ruff, trailing whitespace, EOF fixer, gitleaks). Use `uv sync --group dev` locally. `pytest` marker `local_only` skips machine-dependent tests in CI.
- **`deploy_cursor_skill_templates`**: `braindrain/workspace_primer.py` copies `config/templates/cursor-skills/<id>/SKILL.md` → `.cursor/skills/<id>/SKILL.md` per bundle `skills:` list. Tests in `tests/test_workspace_primer_hooks.py`.
- **Subagent templates**: single source tree `config/templates/agents/` deploys to `.cursor/agents/` and/or `.codex/agents/` depending on the resolved IDE set; duplicate `cursor-subagents/` and `codex-subagents/` template dirs were removed. Skills remain under `config/templates/cursor-skills/`. Added `daily-plan-auditor` agent and planning close-out guidance in Ruler `RULES.md`. Planning audit script moves `archived` plans into `<ide>/plans/.plan.archives/`. Tests: `tests/test_plan_auditor_master.py`.
- Added provenance-aware runtime/tooling paths in `braindrain/server.py`, `braindrain/config.py`, `braindrain/types.py`, and `scripts/daily_plan_audit.py`, with tests in `tests/test_plan_auditor_master.py` and `tests/test_provenance_config.py`.

## [1.0.3] — 2026-04-10

### For users

- You can opt into **scriptlib**: harvest and search reusable scripts, run them through MCP, and keep guidance in agent rules when scriptlib is enabled for a workspace.
- **prime_workspace** deploys Cursor/Codex subagent markdown into `.cursor/agents/` and `.codex/agents/` with optional `sync_subagents` and `codex_agent_targets`. (Older docs referred to split template trees; the repo now uses a single canonical tree — see Unreleased.)
- **Token checkpoint protocol** and optional `.braindrain/token-metrics.jsonl` schema `1.0` are documented in templates and README for consistent observability.

### For contributors

- Added librarian Cursor agent stub and `scriptlib-librarian` skill; `network_connectivity_check.py` for workspace connectivity checks.
- Tests: `tests/test_scriptlib.py` (scriptlib unit coverage).
- Merge branch combines token-stats rule updates, scriptlib stack, and learning-layer subagent deployment (resolved `workspace_primer.py` to keep both scriptlib seeding and subagent flows).
