# Coordinator Skill

## When to Apply
Apply this skill when acting as the coordinator agent — managing stages, routing tasks, and tracking progress across the task graph.

## Core Behaviour

### Reading the Task Graph
Parse `TASK-GRAPH.md` stages top to bottom. For each stage:
1. Identify all tasks and their `[TAG]` type
2. Build a dependency set — tasks with no blockers are immediately runnable
3. Tasks with `requires:` must wait for those to complete and return `success`

### Stage Advancement Rules
- A stage is complete when ALL its tasks are `success` or `skipped`
- A task is `skipped` only if the coordinator determines it's not applicable (e.g. no blog content — skip `[EMBED]` blog schema task)
- Never skip `[GITOPS]` commit tasks
- Never skip `[TESTOPS]` tasks if tests exist

### Parallel Execution

**Hard cap:** at most **3** concurrent Task/subagent dispatches (prefer **2** when token pressure is high). Queue additional runnable tasks; do not launch a fourth parallel agent.

Before any subagent batch (one or more dispatches in the same coordinator turn):

1. `get_token_dashboard()` — baseline snapshot
2. `record_token_checkpoint(phase="pre_high_cost", task="<stage-id>", note="subagent batch", context_tags=["subagent"])`

After the batch completes (all launched agents returned):

1. `get_token_dashboard()` — compare delta
2. `record_token_checkpoint(phase="post_high_cost", task="<stage-id>", note="subagent batch done", context_tags=["subagent"])`
3. On stage close: `get_token_stats()` once per stage

Run these in parallel when possible (within the cap above):

- `[RESEARCH]` tasks (always background-safe)
- `[EMBED]` tasks (read-only)
- `[TESTOPS]` tasks (read-only, `is_background: true`)

Never parallelize:

- Two `[GITOPS]` tasks on the same branch
- Two `[BUILD]` tasks writing to the same file

### Subagent model tiers (cost)

Align Task `model` with `config/hub_config.yaml` — prefer cheaper tiers for read-only work:

| Agent | Preferred model | Notes |
|-------|-----------------|-------|
| `testops` | `gemini-3-flash-preview` | Test/lint runs only; read-mostly |
| `toolcall` | `fast` (or host default fast tier) | Mechanical file/API work |
| `research` | `fast` | Docs and lookup |
| `embedding` | `fast` | LLMs.txt / JSON-LD / index maintenance |
| `librarian` | `composer-2` | Scriptlib reasoning |
| `gitops` | `composer-2` | Branch/commit/merge policy |
| `coordinator` | `composer-2` | Orchestration loop |

When `models.tier_local` (LM Studio / `qwen3:4b`) is available, use it for **plan-only** or classification side work — not for `[BUILD]` or `[GITOPS]`.

Pass large subagent stdout through `route_output()`; retrieve with `search_index()` instead of pasting into coordinator context.

### Handoff Protocol
When delegating to a sub-agent, pass:
```json
{
  "taskId": "T00X",
  "instruction": "precise one-paragraph task description",
  "context": ["relevant file paths"],
  "constraints": ["any hard rules for this task"],
  "expectedOutput": "what success looks like"
}
```

### Checkpoint Format
After each task, update `PROGRESS.md` immediately — do not batch updates.

## Escalation Script
When escalating to user:
> "Task [T00X] has failed [N] times. Last error: [error]. I need your input before continuing. Options: (1) retry with modified approach, (2) skip and continue, (3) revise architect plan."
