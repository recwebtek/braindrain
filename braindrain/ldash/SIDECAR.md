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
| `braindrain/ldash/ui-nexus/` | Variant A (NEXUS) graph-first cockpit |
| `braindrain/ldash/ui-pilot/` | Variant B (PILOT) keyboard command deck |
| `braindrain/ldash/ui-grid/` | Variant C (GRID) dense analyst cockpit |
| `braindrain/ldash/ui-shared/` | Shared API contracts/client/hooks/tokens for all variants |
| `braindrain/ldash/config/` | Default `commands.json` / `services.json` templates |
| `braindrain/ldash/server/` | Optional `app.py` shim (package ships `livingdash_sidecar`) |
| `.braindrain/ldash/data/` | Per-project runtime: auth, snapshot, status, pid (gitignored) |
| `.braindrain/ldash/config/` | Per-project command/service overrides (gitignored) |

Legacy repo-root `.ldash/data/` is migrated into `.braindrain/ldash/data/` on first start.

## Configuration

See `livingdash:` in `config/hub_config.yaml` (host, port, `ui_dist`, `data_dir`, `read_paths`). This is separate from `cost_tracking.dashboard`.

## UI

Build: `cd braindrain/ldash/ui && npm install && npm run build`

Variant builds:

- `cd braindrain/ldash/ui-nexus && npm install && npm run build`
- `cd braindrain/ldash/ui-pilot && npm install && npm run build`
- `cd braindrain/ldash/ui-grid && npm install && npm run build`

Select the active variant through `config/hub_config.yaml`:

```yaml
livingdash:
  ui_dist: "braindrain/ldash/ui-nexus/dist" # or ui-pilot/dist or ui-grid/dist
```

If `ui_dist` is null, LivingDash serves the default `braindrain/ldash/ui/dist`.

After UI or collector changes: restart LivingDash (`/livingdash` or `LivingDashManager`), hard-refresh the browser, and click **Refresh workspace** once.

Security: install packages from `https://registry.npmjs.org` only; run `npm audit --audit-level=high` before release.

## Troubleshooting empty pages

- Confirm `/api/agents` returns data (not 401) in DevTools after login.
- Stale `snapshot.json` is auto-refreshed on start when `refresh_on_start` is true; use **Refresh workspace** if the sidecar was already running during a deploy.
- Rebuild UI dist if routes or pages look outdated.
