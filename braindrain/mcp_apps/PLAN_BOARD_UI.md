# MCP Apps — Plan Board UI

Interactive plan task board rendered inline in Cursor chat via MCP Apps (`ui://`). Vanilla HTML + Python data loaders in `braindrain/mcp_apps/` — no Vite/React stack.

## Quick start

1. **Restart** the braindrain MCP connection after code changes (`braindrain/mcp_apps/` or server registration).
2. In chat, invoke **`show_plan_board`** (or ask the agent to open the plan board).
3. Data comes from `.braindrain/plan-reports/` — run **`/masterplan`** or `python3 scripts/daily_plan_audit.py` when the board is empty or stale.

Default project root is the braindrain server workspace (`show_plan_board` / `poll_plan_board` use the hub install root unless you pass `path`).

## Architecture

| Piece | Role |
| ----- | ---- |
| `show_plan_board` | Opens the inline MCP App; returns structured payload + UI resource |
| `poll_plan_board` | **Iframe-safe router** — refresh board and all write actions (audit, sync, archive, disposition, etc.) |
| `braindrain/mcp_apps/html.py` | Self-contained UI (bridge JS, filters, modals, action buttons) |
| `braindrain/mcp_apps/data.py` | Loads `plan-task-board.md`, master-plan tables, archived plans |
| `braindrain/mcp_apps/plan_enrich.py` | Merges frontmatter todos, PR links, timestamps, disposition metadata |
| `braindrain/mcp_apps/plan_actions.py` | Action implementations dispatched by `poll_plan_board` |
| `braindrain/mcp_apps/plan_gates.py` | Per-button enable/disable rules |

**Important:** The plan board iframe can only call tools the host proxies. All buttons route through **`poll_plan_board`** with an `action` parameter — not separate MCP tools like `audit_plan_implementation` (those exist for schema/catalog but fail inside the sandbox).

## Toolbar (global filters)

| Control | Behavior |
| ------- | -------- |
| **Run /masterplan** | Runs `daily_plan_audit.py --trigger manual-masterplan-command`; glows after write actions until run |
| **Disposition** | Filter cards by disposition (independent of per-card disposition dropdown) |
| **Updated** | Filter by plan `last_modified_at` / file mtime: This week, This month, Last month |
| **Show archived** | Off by default; loads archived cards from `*/plans/.plan.archives/` when checked |
| **PR only** | Show only plans with a linked PR |
| **Expand all / Collapse all** | Toggle visible card `<details>` |

Archived plans also appear when the disposition filter is **archived** or **scratched**, even if **Show archived** is unchecked.

## Plan card

Each card is one plan (grouped from `plan-task-board.md`, not one row per todo).

### Header meta

- Progress bar from frontmatter **todo_summary** (completed + cancelled / total).
- **Disposition dropdown** — sets `disposition:` in plan frontmatter (auditor vocabulary). Confirm dialog → write → refresh. Run `/masterplan` to sync the task board and master index.
- **Next verb** pill (IMPLEMENT, MERGE, etc.) from auditor disposition tables.
- Owner, priority, branch, PR, parent, **timestamp tags** (`updated …`, `created …`, optional `model …`).
- **Current month** updated tags are highlighted yellow.

Valid disposition values: `active`, `meta`, `research-needed`, `replan-needed`, `merge-ready`, `needs-fix`, `backlogged`, `scratched`, `implemented`, `archived`.

### Rollup line

- Task-board item counts.
- **Open in Cursor** — see [Opening plans in the editor](#opening-plans-in-the-editor).
- Clickable **filename** (same open behavior).

### Action buttons

| Button | Action key | Notes |
| ------ | ---------- | ----- |
| Recheck | `audit` | Read-only: compares todos vs repo paths; does **not** re-render the whole board |
| Apply sync | `apply_sync` | Writes Recheck proposals to frontmatter todos (`confirm=true`) |
| Research | `research` | Sends research handoff via `ui/message` |
| Merge-ready | `merge_ready` | Gated: active, all todos done, PR linked |
| Archive | `archive` | Moves file to `.plan.archives/`; branch/PR are **not** deleted |
| Cancel plan | `cancel_plan` | Scratches disposition, cancels todos, moves to archive |
| Continue | `continue` | Gitops queue + chat handoff |

Archive and Cancel are available even when a branch or PR exists (only the plan file moves / is scratched).

Archived cards (loaded from `.plan.archives/`) show an **Archived** badge instead of action buttons.

## Recheck (audit)

Recheck scans each pending frontmatter todo against the repo:

- Paths in backticks, path-ish text, and file extensions (same family as `/masterplan`).
- Plan body sections that mention the todo id.
- Keyword → known file hints (e.g. schema snapshot fixture).
- Branch diff evidence when the plan has a `branch:` frontmatter field.

Proposals suggest marking todos **completed** when evidence files exist. Use **Apply sync** after Recheck to update frontmatter.

## Opening plans in the editor

The MCP App runs in a **sandboxed iframe**. It cannot open local files directly (`cursor://` links and plain anchors are blocked).

**Open in Cursor** or the filename button:

1. Copies the absolute path to the clipboard.
2. Opens a dialog with `@.cursor/plans/…` chat reference and full path.
3. **Send to chat** — injects a message with an `@` file link; click it in chat to open in the editor.
4. **Try deep link** — optional `cursor://` / `vscode://` via host `ui/open-link` (often blocked).
5. **⌘P** — paste the copied absolute path.

Cursor **Simple Browser** (`Browser Tab`) only supports http/https URLs, not local `.plan.md` files.

## iframe limitations (by design)

| Blocked in iframe | Workaround used |
| ----------------- | --------------- |
| `window.confirm` / `prompt` | Inline HTML modals (`planDialogConfirm`, `planDialogCancelPlan`) |
| Separate MCP tool calls | Single router: `poll_plan_board` + `action` |
| `cursor://` / `file://` navigation | Dialog + `ui/message` @ file + clipboard + `ui/open-link` fallback |

## Related tools

App-only helpers (registered for catalog; iframe uses `poll_plan_board` instead):

- `audit_plan_implementation`, `apply_plan_todo_sync`, `mark_plan_merge_ready`, `archive_plan`, `enqueue_plan_continue`, `plan_board_handoff`

Token dashboard sibling: **`show_token_dashboard`** (`ui://braindrain/token-dashboard`).

## Tests

```bash
uv run pytest tests/test_mcp_apps.py -q
```

After changing `@mcp.tool()` signatures for plan board tools:

```bash
uv run python scripts/regenerate_mcp_tool_schemas_snapshot.py
uv run pytest tests/test_mcp_tool_schemas.py -q
```

## File map

```
braindrain/mcp_apps/
├── html.py           # UI + bridge JS
├── data.py           # Payload builder
├── plan_enrich.py    # Frontmatter + master-plan merge
├── plan_actions.py   # Actions + poll_plan_board dispatch
├── plan_gates.py     # Button gating
├── plan_paths.py     # Resolve .cursor/plans vs plans/
└── register.py       # Tool + resource registration
```
