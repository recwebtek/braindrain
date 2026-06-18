"""Self-contained HTML for MCP Apps (`ui://`) — no Vite, no Agent-Native."""

from __future__ import annotations

_BRIDGE_JS = r"""
const PROTOCOL_VERSION = "2025-11-25";
let hostContext = null;

function post(msg) {
  window.parent.postMessage(JSON.stringify(msg), "*");
}

function sendRequest(method, params) {
  const id = Math.floor(Math.random() * 1e9);
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("timeout: " + method)), 15000);
    function onMessage(event) {
      try {
        const data = typeof event.data === "string" ? JSON.parse(event.data) : event.data;
        if (data && data.id === id) {
          window.removeEventListener("message", onMessage);
          clearTimeout(timer);
          if (data.error) reject(data.error);
          else resolve(data.result);
        }
      } catch (_) { /* ignore non-json */ }
    }
    window.addEventListener("message", onMessage);
    post({ jsonrpc: "2.0", id, method, params });
  });
}

function applyTheme(ctx) {
  if (!ctx || !ctx.theme) return;
  const dark = ctx.theme === "dark";
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

function extractPayload(result) {
  if (!result) return null;
  if (result.structuredContent) return result.structuredContent;
  if (result.structured_content) return result.structured_content;
  return result;
}

window.addEventListener("message", (event) => {
  try {
    const data = typeof event.data === "string" ? JSON.parse(event.data) : event.data;
    if (!data || !data.method) return;
    if (data.method === "ui/notifications/host-context-changed") {
      hostContext = data.params || hostContext;
      applyTheme(hostContext);
    }
    if (data.method === "ui/notifications/tool-result") {
      renderDashboard(extractPayload(data.params));
    }
    if (data.method === "ui/notifications/tool-input") {
      const el = document.getElementById("status");
      if (el) el.textContent = "Loading…";
    }
  } catch (_) { /* ignore */ }
});

async function bootstrap() {
  try {
    const init = await sendRequest("ui/initialize", {
      protocolVersion: PROTOCOL_VERSION,
      appCapabilities: {},
      appInfo: { name: "braindrain-mcp-app", version: "1.0.0" },
    });
    hostContext = init || hostContext;
    applyTheme(hostContext);
    const status = document.getElementById("status");
    if (status) status.textContent = "Connected";
  } catch (err) {
    const status = document.getElementById("status");
    if (status) status.textContent = "Bridge: " + (err.message || String(err));
  }
}

document.addEventListener("DOMContentLoaded", bootstrap);
"""

_BASE_CSS = """
:root {
  --bg: #f8fafc;
  --panel: #ffffff;
  --text: #0f172a;
  --muted: #64748b;
  --border: #e2e8f0;
  --accent: #0284c7;
  --good: #16a34a;
  --warn: #d97706;
}
:root[data-theme="dark"] {
  --bg: #09090b;
  --panel: #18181b;
  --text: #fafafa;
  --muted: #a1a1aa;
  --border: #27272a;
  --accent: #38bdf8;
  --good: #22c55e;
  --warn: #f59e0b;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font: 13px/1.45 ui-sans-serif, system-ui, -apple-system, sans-serif;
  background: var(--bg);
  color: var(--text);
}
.wrap { padding: 12px 14px 16px; max-width: 960px; }
h1 { font-size: 15px; margin: 0 0 4px; font-weight: 600; }
.meta { color: var(--muted); font-size: 11px; margin-bottom: 12px; }
#status { color: var(--muted); font-size: 11px; margin-bottom: 8px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 8px; margin-bottom: 12px; }
.card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
}
.card .label { color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing: .04em; }
.card .value { font-size: 18px; font-weight: 600; margin-top: 4px; }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); }
th { color: var(--muted); font-weight: 500; font-size: 10px; text-transform: uppercase; }
tr:hover td { background: color-mix(in srgb, var(--accent) 6%, transparent); }
.pill { display: inline-block; padding: 1px 6px; border-radius: 999px; background: var(--border); font-size: 10px; }
.hint { color: var(--muted); font-size: 11px; margin-top: 10px; }
"""


def _html_page(title: str, render_js: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>{_BASE_CSS}</style>
</head>
<body>
  <div class="wrap">
    <h1>{title}</h1>
    <div id="status">Initializing…</div>
    <div id="root"></div>
  </div>
  <script>{_BRIDGE_JS}</script>
  <script>{render_js}</script>
</body>
</html>
"""


_TOKEN_RENDER_JS = r"""
function fmt(n) {
  if (n == null) return "—";
  if (typeof n === "number") return n.toLocaleString();
  return String(n);
}

function renderDashboard(raw) {
  const payload = raw && raw.dashboard ? raw.dashboard : raw;
  const root = document.getElementById("root");
  const status = document.getElementById("status");
  if (!payload || !payload.snapshot) {
    root.innerHTML = "<p class='hint'>No dashboard data yet.</p>";
    if (status) status.textContent = "No data";
    return;
  }
  const s = payload.snapshot;
  const tools = payload.tools || [];
  const checkpoints = payload.checkpoints || [];
  if (status) status.textContent = "Updated " + (payload.generated_at || "");

  let toolsHtml = tools.slice(0, 12).map(t => `
    <tr>
      <td>${t.name}</td>
      <td>${fmt(t.calls)}</td>
      <td>${fmt(t.saved_tokens)}</td>
      <td>${fmt(t.saved_pct)}%</td>
    </tr>`).join("");

  let cpHtml = checkpoints.slice(-8).reverse().map(c => `
    <tr>
      <td>${c.phase || ""}</td>
      <td>${c.task || ""}</td>
      <td>${(c.totals && c.totals.saved_tokens) != null ? c.totals.saved_tokens : "—"}</td>
      <td><span class="pill">${(c.context_tags || []).join(", ")}</span></td>
    </tr>`).join("");

  root.innerHTML = `
    <div class="grid">
      <div class="card"><div class="label">Saved (est.)</div><div class="value">${fmt(s.tokens_saved_est)}</div></div>
      <div class="card"><div class="label">Saved %</div><div class="value">${fmt(s.saved_pct_est)}%</div></div>
      <div class="card"><div class="label">Raw in</div><div class="value">${fmt(s.tokens_in_raw_est)}</div></div>
      <div class="card"><div class="label">Actual in</div><div class="value">${fmt(s.tokens_in_actual_est)}</div></div>
      <div class="card"><div class="label">Cost avoided</div><div class="value">$${fmt(s.cost_avoided_usd)}</div></div>
      <div class="card"><div class="label">Uptime</div><div class="value">${fmt(s.uptime_seconds)}s</div></div>
    </div>
    <h2 style="font-size:13px;margin:14px 0 6px">Per-tool</h2>
    <table><thead><tr><th>Tool</th><th>Calls</th><th>Saved</th><th>%</th></tr></thead><tbody>${toolsHtml || "<tr><td colspan=4 class='hint'>No tool calls this session</td></tr>"}</tbody></table>
    <h2 style="font-size:13px;margin:14px 0 6px">Recent checkpoints</h2>
    <table><thead><tr><th>Phase</th><th>Task</th><th>Saved</th><th>Tags</th></tr></thead><tbody>${cpHtml || "<tr><td colspan=4 class='hint'>No checkpoints file yet</td></tr>"}</tbody></table>
    <p class="hint">Session log: ${payload.session_log || "—"}</p>`;
}
"""

_PLAN_RENDER_JS = r"""
function renderDashboard(raw) {
  const payload = raw && raw.dashboard ? raw.dashboard : raw;
  const root = document.getElementById("root");
  const status = document.getElementById("status");
  if (!payload) {
    root.innerHTML = "<p class='hint'>No plan board data.</p>";
    return;
  }
  if (status) status.textContent = "Updated " + (payload.generated_at || "");
  const rows = payload.board_rows || [];
  if (!rows.length) {
    root.innerHTML = `<p class='hint'>${payload.hint || "Plan board empty."}</p>
      <p class='hint'>Reports: ${payload.reports_dir || ""}</p>`;
    return;
  }
  const body = rows.map(r => `
    <tr>
      <td>${r.seq}</td>
      <td>${r.plan}</td>
      <td>${r.ide || ""}</td>
      <td>${r.status || ""}</td>
      <td>${r.owner || ""}</td>
    </tr>`).join("");
  root.innerHTML = `
    <table>
      <thead><tr><th>Seq</th><th>Plan</th><th>IDE</th><th>Status</th><th>Owner</th></tr></thead>
      <tbody>${body}</tbody>
    </table>
    <p class="hint">Source: ${payload.board_path || ""}</p>`;
}
"""


def token_dashboard_html() -> str:
    return _html_page("Braindrain Token Dashboard", _TOKEN_RENDER_JS)


def plan_board_html() -> str:
    return _html_page("Braindrain Plan Board", _PLAN_RENDER_JS)
