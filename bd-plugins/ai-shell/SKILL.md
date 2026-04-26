# AI Shell Skill Contract

This skill defines how any agent should use `ai_shell_state_sync` and `ai_shell_run` safely and consistently.

## Purpose

Use AI Shell as a bounded shell execution capability with deterministic policy gates and canonical working-directory state.

## Tool Contract

### `ai_shell_state_sync`

Inputs:
- `session_id` (required)
- `project_id` (optional, default `default`)

Output guarantees:
- Returns canonical `cwd_after` for the `(session_id, project_id)` tuple.
- Returns `mode_default`.

### `ai_shell_run`

Inputs:
- `session_id` (required)
- `command` (required)
- `cwd` (optional, only used to seed a new session)
- `requested_mode` (optional: `simulated`, `hybrid`, `real_world`)
- `project_id` (optional, default `default`)

Output guarantees:
- Returns `mode_used`, `cwd_after`, `safety`, and `output_text`.
- For `cd`, returns `signals.cd` and token-minimal output marker `__CD__:<path>`.

## Command Tier Policy

### Tier 1: `always-allow`
- Commands: `cd`, `pwd`, `ls`, `cat`, `echo`, `grep`, `rg`
- Rules: repo-root boundary, no interactive TTY flags.

### Tier 2: `allow-with-constraints`
- Commands: `python3`, `pytest`, `git`
- Rules:
  - `python3`: script/module style execution only in repo context.
  - `pytest`: bounded invocations preferred.
  - `git`: read-safe subcommands by default (`status`, `diff`, `log`, `show`, `branch`, `rev-parse`, `remote`, `ls-files`).

### Tier 3: `simulated-only`
- Unknown commands and high-risk classes (`curl`, `wget`, `rm`, `sudo`, `ssh`, `scp`, `reboot`, `shutdown`, `dd`, `mkfs`).
- Never execute real-world in this tier for this phase.

## Canonical Agent Flow

1. `ai_shell_state_sync(session_id, project_id)` before command bursts or after handoff.
2. `ai_shell_run(...)` for one command.
3. If response has `signals.cd`, update local prompt/model state from `cwd_after`.
4. If bridge reports mismatch/stale prompt, call `ai_shell_state_sync(...)` again.

## Error and Safety Handling

- If `safety.policy_decision == block`, show `blocked_reason` and do not retry blindly.
- If `policy_decision == force_simulated`, proceed with simulated output, do not escalate to `real_world` automatically.
- Treat `outside_project_root`, `interactive_tty`, `destructive_command`, and `network_blocked` as hard safety stops.

## Multi-Agent Handoff Rules

- Reuse shared `session_id` and `project_id` for continuity.
- New agent must call `ai_shell_state_sync` first before issuing any run call.
- Do not infer cwd from memory if sync says otherwise.

