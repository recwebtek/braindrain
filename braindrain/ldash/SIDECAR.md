# LivingDash sidecar isolation

LivingDash is a **modular localhost sidecar**. It does not load or modify the Braindrain MCP stdio server.

## Boundaries

- **Launch:** `.cursor/commands/livingdash.md` or `LivingDashManager` only.
- **Code:** `braindrain/livingdash*.py`, `braindrain/ldash/`, and `config/hub_config.yaml` → `livingdash:` block.
- **Data:** Read-only access to workspace files, `.braindrain/`, and `~/.braindrain/` paths declared in config.
- **No changes to:** `braindrain/server.py`, `workspace_primer.py`, instrumentation, or observer write paths.

## Layout

| Path | Role |
|------|------|
| `braindrain/ldash/ui/` | React source + `dist/` build output (versioned) |
| `braindrain/ldash/config/` | Default `commands.json` / `services.json` templates |
| `braindrain/ldash/server/` | Optional `app.py` shim (package ships `livingdash_sidecar`) |
| `.braindrain/ldash/data/` | Per-project runtime: auth, snapshot, status, pid (gitignored) |
| `.braindrain/ldash/config/` | Per-project command/service overrides (gitignored) |

Legacy repo-root `.ldash/data/` is migrated into `.braindrain/ldash/data/` on first start.

## Configuration

See `livingdash:` in `config/hub_config.yaml` (host, port, `ui_dist`, `data_dir`, `read_paths`). This is separate from `cost_tracking.dashboard`.

## UI

Build: `cd braindrain/ldash/ui && npm install && npm run build`

After UI or collector changes: restart LivingDash (`/livingdash` or `LivingDashManager`), hard-refresh the browser, and click **Refresh workspace** once.

Security: install packages from `https://registry.npmjs.org` only; run `npm audit --audit-level=high` before release.

## Troubleshooting empty pages

- Confirm `/api/agents` returns data (not 401) in DevTools after login.
- Stale `snapshot.json` is auto-refreshed on start when `refresh_on_start` is true; use **Refresh workspace** if the sidecar was already running during a deploy.
- Rebuild UI dist if routes or pages look outdated.
