# AI Shell Plugin Runbook (Phase 1)

This document defines the operational and structural setup for the AI Shell plugin path used by Braindrain.

## Skill contract

For agent-agnostic usage protocol, call choreography, and tier policy, use:

- `bd-plugins/ai-shell/SKILL.md`

## Architecture

- Core host remains generic: `braindrain/plugin_host.py`
- Server MCP wrappers: `braindrain/server.py` (`ai_shell_run`, `ai_shell_state_sync`)
- Plugin package: `bd-plugins/ai-shell/plugin.py`
- macOS bridge helper: `bd-plugins/ai-shell/bridge.py`
- Policy source: `config/ai_shell_policy.yaml`
- Persistence backend: `braindrain/session.py` (`ai_shell_sessions`, `ai_shell_events`, `ai_shell_commands`)

## Plugin host contract

Every plugin must implement:

1. `discover()` -> metadata only, no side effects
2. `load(context)` -> runtime object
3. `runtime.register_tools(registry)` -> MCP passthrough tool registration
4. `runtime.healthcheck()` -> readiness probe
5. `runtime.shutdown()` -> deterministic cleanup

Versioning:

- plugin field: `plugin_api_version`
- current host compatibility window: `1.0` and `1.1`
- unsupported versions fail closed with deterministic load error

## Run path and config precedence

Resolution order:

1. environment variable
2. `config/hub_config.yaml`
3. fallback in code

Paths and mode:

- Plugin path:
  - env: `BRAINDRAIN_AI_SHELL_PLUGIN_PATH`
  - config: `plugins.ai_shell.path`
  - fallback: `bd-plugins/ai-shell/`
- Default mode:
  - env: `BRAINDRAIN_AI_SHELL_EXECUTION_MODE`
  - config: `ai_shell.execution_mode`
  - fallback: `hybrid`
- Socket path (bridge):
  - env: `BRAINDRAIN_AI_SHELL_SOCKET_PATH`
  - config: `ai_shell.socket_path`
  - fallback: `/tmp/braindrain-ai-shell.sock`

## Dev/prod environment notes

Braindrain server loads env files in this order without overriding existing env vars:

1. `.env.dev`
2. `.env.prod`
3. `.env`

Recommended:

- Use `.env.dev` for active plugin iteration and policy testing.
- Use `.env.prod` for stable operator defaults.
- Keep AI Shell variables explicit in both files so future agents inherit deterministic run behavior.

## Safety and policy

Policy is deterministic and gate-first:

1. normalize command input
2. validate parseability
3. enforce project-root boundary
4. evaluate deny rules
5. evaluate allowlist
6. resolve mode gate

Decision envelope fields:

- `policy_decision`: `allow_real_world | force_simulated | block`
- `policy_rule_id`
- `blocked_reason`: stable enum
- `decision_trace`: compact ordered checkpoints

Tier contract (balanced mode):

- Tier 1 (`always-allow`): `cd`, `pwd`, `ls`, `cat`, `echo`, `grep`, `rg`
- Tier 2 (`allow-with-constraints`): `python3`, `pytest`, `git` (read-safe subcommands by default)
- Tier 3 (`simulated-only`): unknown or high-risk/network/system mutation commands

## Agent-as-user reference flow

Canonical choreography for any agent:

1. `ai_shell_state_sync(session_id, project_id)`
2. `ai_shell_run(session_id, command, requested_mode, project_id)`
3. Apply `signals.cd` and `cwd_after` to local prompt state
4. If prompt drift or bridge mismatch, run `ai_shell_state_sync` again

Reference implementation lives in `bd-plugins/ai-shell/bridge.py` as `run_command_flow()`.

## Efficiency metrics

`ai_shell_commands` now records compact efficiency counters per command:

- `request_bytes`
- `response_bytes`
- `estimated_tokens`

MCP dashboard endpoint: `ai_shell_metrics(project_id, session_id=None)`

## Quickstart (MCP)

Use this sequence to get deterministic behavior:

1. `ai_shell_state_sync(session_id, project_id)` to fetch canonical cwd.
2. `ai_shell_run(session_id, command, requested_mode, project_id)` for one command.
3. If response includes `signals.cd`, update local cwd from `cwd_after`.
4. Call `ai_shell_metrics(project_id, session_id)` to inspect efficiency counters.

Example command set to feel the flow:

- `pwd` (Tier 1, expected real-world in `hybrid`)
- `cd bd-plugins` (updates canonical cwd and emits `signals.cd`)
- `git status` (Tier 2, allowed safe subcommand)
- `git push` (Tier 2 constrained path, blocked or simulated depending on mode)
- `curl https://example.com` (Tier 3 simulated-only or blocked)

## Operational notes

- Plugin tool loading happens at server runtime. If policy or plugin code changed and MCP behavior looks stale, restart the braindrain MCP server before validating.
- `ai_shell_state_sync` is the source of truth for cwd after any mismatch.
- `ai_shell_metrics` is intentionally compact for dashboards and agent decisions.

## Testing surface (Phase 1)

- `tests/test_plugin_host_contract.py`
- `tests/test_ai_shell_plugin.py`
- `tests/test_ai_shell_policy.py`
- `tests/test_ai_shell_macos_bridge.py`

Current expected command:

`python3 -m pytest tests/test_plugin_host_contract.py tests/test_ai_shell_plugin.py tests/test_ai_shell_policy.py tests/test_ai_shell_macos_bridge.py`
