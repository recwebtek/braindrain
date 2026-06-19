"""Self-contained HTML for MCP Apps (`ui://`) — no Vite, no Agent-Native."""

from __future__ import annotations

_BRIDGE_JS = r"""
const PROTOCOL_VERSION = "2026-01-26";
const state = { initialized: false, nextId: 1, hostContext: null, pendingToolResult: null };
const pendingRequests = new Map();
let lastInbound = "";

function parseMessage(raw) {
  if (!raw) return null;
  if (typeof raw === "string") {
    try { raw = JSON.parse(raw); } catch (_) { return null; }
  }
  if (raw && typeof raw === "object") {
    if (raw.jsonrpc === "2.0") return raw;
    if (raw.data && raw.data.jsonrpc === "2.0") return raw.data;
    if (raw.payload && raw.payload.jsonrpc === "2.0") return raw.payload;
  }
  return null;
}

function postToHost(msg) {
  const targets = [];
  try {
    if (window.parent && window.parent !== window) targets.push(window.parent);
  } catch (_) {}
  try {
    if (window.top && window.top !== window && targets.indexOf(window.top) === -1) {
      targets.push(window.top);
    }
  } catch (_) {}
  for (let i = 0; i < targets.length; i++) {
    targets[i].postMessage(msg, "*");
  }
}

function sendNotification(method, params) {
  postToHost({ jsonrpc: "2.0", method: method, params: params || {} });
}

function sendRequest(method, params, timeoutMs) {
  const id = state.nextId++;
  const key = String(id);
  return new Promise(function(resolve, reject) {
    const timer = setTimeout(function() {
      pendingRequests.delete(key);
      reject(new Error("timeout: " + method + (lastInbound ? " (last: " + lastInbound + ")" : "")));
    }, timeoutMs || 15000);
    pendingRequests.set(key, {
      resolve: function(result) { clearTimeout(timer); resolve(result); },
      reject: function(err) { clearTimeout(timer); reject(err); }
    });
    postToHost({ jsonrpc: "2.0", id: id, method: method, params: params });
  });
}

function applyTheme(ctx) {
  if (!ctx) return;
  const theme = ctx.theme || (ctx.hostContext && ctx.hostContext.theme);
  if (!theme) return;
  document.documentElement.dataset.theme = theme === "dark" ? "dark" : "light";
}

function extractData(response) {
  if (!response || typeof response !== "object") return null;
  if (response.structuredContent && typeof response.structuredContent === "object") {
    return response.structuredContent;
  }
  if (response.structured_content && typeof response.structured_content === "object") {
    return response.structured_content;
  }
  if (response.content && Array.isArray(response.content)) {
    for (let i = 0; i < response.content.length; i++) {
      const item = response.content[i];
      if (item && item.type === "text" && typeof item.text === "string") {
        try {
          const parsed = JSON.parse(item.text);
          if (parsed && typeof parsed === "object") return parsed;
        } catch (_) {}
      }
    }
  }
  if (response.result && typeof response.result === "object") {
    return extractData(response.result);
  }
  return response;
}

function handleToolResult(params) {
  const payload = extractData(params);
  if (typeof renderDashboard === "function" && payload) {
    renderDashboard(payload);
  }
  const status = document.getElementById("status");
  if (status && (status.textContent === "Initializing…" || status.textContent.indexOf("Bridge:") === 0)) {
    status.textContent = state.initialized ? "Connected" : "Connected (data only)";
  }
}

function finishInitialize(init) {
  state.hostContext = (init && init.hostContext) || init || null;
  applyTheme(state.hostContext);
  sendNotification("ui/notifications/initialized");
  state.initialized = true;
  if (state.pendingToolResult) {
    const queued = state.pendingToolResult;
    state.pendingToolResult = null;
    handleToolResult(queued);
  }
  const status = document.getElementById("status");
  if (status && status.textContent === "Initializing…") {
    status.textContent = "Connected";
  }
  setupSizeReporting();
}

window.addEventListener("message", function(event) {
  const msg = parseMessage(event.data);
  if (!msg || msg.jsonrpc !== "2.0") return;

  if (msg.id != null && pendingRequests.has(String(msg.id))) {
    lastInbound = "response id=" + String(msg.id);
    const pending = pendingRequests.get(String(msg.id));
    pendingRequests.delete(String(msg.id));
    if (msg.error) pending.reject(msg.error);
    else pending.resolve(msg.result);
    return;
  }

  if (!msg.method) return;
  lastInbound = msg.method;

  if (msg.method === "ui/notifications/host-context-changed") {
    state.hostContext = Object.assign({}, state.hostContext || {}, msg.params || {});
    applyTheme(state.hostContext);
    return;
  }
  if (msg.method === "ui/notifications/tool-result") {
    if (!state.initialized) state.pendingToolResult = msg.params;
    else handleToolResult(msg.params);
    return;
  }
  if (msg.method === "ui/notifications/tool-input") {
    const el = document.getElementById("status");
    if (el) el.textContent = "Loading…";
  }
});

function setupSizeReporting() {
  let lastW = 0;
  let lastH = 0;
  let scheduled = false;
  function report() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(function() {
      scheduled = false;
      const html = document.documentElement;
      const prev = html.style.height;
      html.style.height = "max-content";
      const height = Math.ceil(html.getBoundingClientRect().height);
      html.style.height = prev;
      const width = Math.ceil(window.innerWidth);
      if (width === lastW && height === lastH) return;
      lastW = width;
      lastH = height;
      sendNotification("ui/notifications/size-changed", { width: width, height: height });
    });
  }
  report();
  if (typeof ResizeObserver !== "undefined") {
    const ro = new ResizeObserver(report);
    ro.observe(document.documentElement);
    ro.observe(document.body);
  }
}

async function callTool(name, args) {
  try {
    const result = await sendRequest("tools/call", { name: name, arguments: args || {} }, 120000);
    if (result && result.isError) {
      const msg = (result.content && result.content[0] && result.content[0].text) || "Tool call failed";
      throw new Error(msg);
    }
    return extractData(result);
  } catch (err) {
    if (err && typeof err === "object" && err.message) throw err;
    if (err && typeof err === "object" && err.code === -32602) {
      throw new Error(err.message || "Invalid tool call");
    }
    throw err;
  }
}

function sendChatMessage(text) {
  sendNotification("ui/message", { message: text });
}

async function bootstrap() {
  const status = document.getElementById("status");
  const initParams = {
    protocolVersion: PROTOCOL_VERSION,
    appCapabilities: { availableDisplayModes: ["inline"] },
    appInfo: { name: "braindrain-mcp-app", version: "1.0.0" }
  };
  const versions = [PROTOCOL_VERSION, "2025-06-18"];
  for (let i = 0; i < versions.length; i++) {
    initParams.protocolVersion = versions[i];
    try {
      const init = await sendRequest("ui/initialize", initParams, i === 0 ? 8000 : 7000);
      finishInitialize(init);
      return;
    } catch (err) {
      if (i === versions.length - 1 && status) {
        if (state.pendingToolResult) {
          handleToolResult(state.pendingToolResult);
          state.pendingToolResult = null;
          status.textContent = "Connected (no handshake)";
          return;
        }
        status.textContent = "Bridge: " + (err.message || String(err));
      }
    }
  }
}

bootstrap();
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
.pill.blocked { background: color-mix(in srgb, var(--warn) 25%, var(--border)); color: var(--warn); }
.pill.progress { background: color-mix(in srgb, var(--accent) 20%, var(--border)); color: var(--accent); }
.pill.outstanding { background: var(--border); color: var(--muted); }
.plan-card { border: 1px solid var(--border); border-radius: 10px; margin-bottom: 10px; background: var(--panel); overflow: hidden; }
.plan-card > summary { list-style: none; cursor: pointer; padding: 10px 12px; border-bottom: 1px solid transparent; }
.plan-card > summary::-webkit-details-marker { display: none; }
.plan-card[open] > summary { border-bottom-color: var(--border); }
.plan-card > summary:hover { background: color-mix(in srgb, var(--accent) 4%, transparent); }
.plan-head { padding: 0; border-bottom: none; }
.plan-title { font-size: 13px; font-weight: 600; margin: 0 0 6px; display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.plan-title-text { flex: 1 1 auto; min-width: 0; }
.progress-pill { font-size: 10px; font-weight: 500; color: var(--muted); white-space: nowrap; }
.progress-bar { height: 4px; background: var(--border); border-radius: 999px; overflow: hidden; margin: 0 0 8px; }
.progress-bar > span { display: block; height: 100%; background: var(--good); border-radius: 999px; }
.plan-meta { display: flex; flex-wrap: wrap; gap: 6px; font-size: 10px; color: var(--muted); align-items: center; }
.plan-meta code { font-size: 10px; background: var(--bg); padding: 1px 4px; border-radius: 4px; }
.plan-meta a { color: var(--accent); text-decoration: none; }
.plan-meta a:hover { text-decoration: underline; }
.plan-body { padding: 10px 12px 12px; }
.section-title { font-size: 10px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); margin: 10px 0 6px; }
.section-title:first-child { margin-top: 0; }
.plan-overview { font-size: 11px; color: var(--muted); line-height: 1.45; margin-bottom: 8px; }
.plan-items, .todo-list { list-style: none; margin: 0; padding: 0; }
.plan-items li, .todo-list li { padding: 6px 0; border-bottom: 1px solid color-mix(in srgb, var(--border) 70%, transparent); font-size: 12px; }
.plan-items li:last-child, .todo-list li:last-child { border-bottom: none; }
.item-text, .todo-text { display: block; margin-top: 3px; line-height: 1.35; }
.item-gaps, .todo-id { color: var(--muted); font-size: 10px; margin-top: 2px; }
.pill.completed { background: color-mix(in srgb, var(--good) 20%, var(--border)); color: var(--good); }
.pill.cancelled { background: var(--border); color: var(--muted); text-decoration: line-through; }
.pill.todo-pending { background: var(--border); color: var(--muted); }
.pill.todo-progress { background: color-mix(in srgb, var(--accent) 20%, var(--border)); color: var(--accent); }
.rollup { font-size: 10px; color: var(--muted); }
.summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 8px; margin-bottom: 12px; }
.hint { color: var(--muted); font-size: 11px; margin-top: 10px; }
.next-actions { margin: 0 0 12px; padding-left: 18px; font-size: 11px; color: var(--muted); }
.next-actions li { margin: 4px 0; }
.toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 10px; }
.toolbar label { font-size: 11px; color: var(--muted); display: inline-flex; align-items: center; gap: 4px; }
.toolbar select, .toolbar button { font-size: 11px; border: 1px solid var(--border); background: var(--panel); color: var(--text); border-radius: 6px; padding: 4px 6px; }
.toolbar button { cursor: pointer; }
.toolbar button:disabled { opacity: 0.45; cursor: not-allowed; }
.plan-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid var(--border); }
.plan-actions button { font-size: 10px; border: 1px solid var(--border); background: var(--bg); color: var(--text); border-radius: 6px; padding: 4px 8px; cursor: pointer; }
.plan-actions button.danger { border-color: color-mix(in srgb, var(--warn) 40%, var(--border)); color: var(--warn); }
.plan-actions button:disabled { opacity: 0.45; cursor: not-allowed; }
.action-result { font-size: 10px; color: var(--muted); margin-top: 6px; line-height: 1.4; }
.action-result.ok { color: var(--good); }
.action-result.err { color: var(--warn); }
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
  <script>{render_js}</script>
  <script>{_BRIDGE_JS}</script>
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
function esc(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function statusClass(status) {
  if (status === "Blocked") return "blocked";
  if (status === "In Progress") return "progress";
  return "outstanding";
}

function todoStatusClass(status) {
  const s = (status || "pending").toLowerCase();
  if (s === "completed") return "completed";
  if (s === "in_progress") return "todo-progress";
  if (s === "cancelled") return "cancelled";
  return "todo-pending";
}

function todoStatusLabel(status) {
  const s = (status || "pending").toLowerCase();
  if (s === "completed") return "Done";
  if (s === "in_progress") return "Active";
  if (s === "cancelled") return "Cancelled";
  return "Pending";
}

function progressPct(summary) {
  if (!summary || !summary.total) return 0;
  const done = (summary.completed || 0) + (summary.cancelled || 0);
  return Math.round((done / summary.total) * 100);
}

function renderPrLink(pr) {
  if (!pr || !pr.label) return "";
  if (pr.url) {
    return `<a href="${esc(pr.url)}" target="_blank" rel="noopener">${esc(pr.label)}</a>`;
  }
  return esc(pr.label);
}

function gateEnabled(gates, key) {
  const g = gates && gates[key];
  return !!(g && g.enabled);
}

function gateReason(gates, key) {
  const g = gates && gates[key];
  return (g && g.reason) ? g.reason : "";
}

function renderActionButtons(group) {
  const gates = group.action_gates || {};
  const src = group.source || "";
  function btn(action, label, enabled, extraClass) {
    const dis = enabled ? "" : " disabled";
    const title = enabled ? "" : ` title="${esc(gateReason(gates, action))}"`;
    const cls = extraClass ? ` ${extraClass}` : "";
    return `<button type="button" class="plan-action${cls}" data-action="${esc(action)}" data-source="${esc(src)}"${dis}${title}>${esc(label)}</button>`;
  }
  return `<div class="plan-actions" data-source="${esc(src)}">
    ${btn("audit", "Recheck", gateEnabled(gates, "audit"))}
    ${btn("apply_sync", "Apply sync", gateEnabled(gates, "apply_sync"))}
    ${btn("research", "Research", gateEnabled(gates, "research"))}
    ${btn("merge_ready", "Merge-ready", gateEnabled(gates, "merge_ready"))}
    ${btn("archive", "Archive", gateEnabled(gates, "archive"))}
    ${btn("cancel_plan", "Cancel plan", gateEnabled(gates, "cancel_plan"), "danger")}
    ${btn("continue", "Continue", gateEnabled(gates, "continue"))}
    <div class="action-result" data-result="${esc(src)}"></div>
  </div>`;
}

function renderDashboard(raw) {
  const payload = raw && raw.dashboard ? raw.dashboard : raw;
  const root = document.getElementById("root");
  const status = document.getElementById("status");
  if (!payload) {
    root.innerHTML = "<p class='hint'>No plan board data.</p>";
    return;
  }
  if (status) status.textContent = "Updated " + (payload.generated_at || "");

  const groups = payload.plan_groups || [];
  const summary = payload.summary || {};
  if (!groups.length) {
    root.innerHTML = "<p class='hint'>" + esc(payload.hint || "Plan board empty.") + "</p>";
    return;
  }

  let summaryHtml = `
    <div class="summary-grid">
      <div class="card"><div class="label">Plans</div><div class="value">${summary.plan_count || groups.length}</div></div>
      <div class="card"><div class="label">Open items</div><div class="value">${summary.item_count || 0}</div></div>
      <div class="card"><div class="label">Blocked</div><div class="value">${summary.blocked_items || 0}</div></div>
      <div class="card"><div class="label">Outstanding</div><div class="value">${summary.outstanding_items || 0}</div></div>
    </div>`;

  let totalTodos = groups.reduce(function(acc, g) {
    return acc + ((g.todo_summary && g.todo_summary.total) || 0);
  }, 0);
  const doneTodos = groups.reduce(function(acc, g) {
    const ts = g.todo_summary || {};
    return acc + (ts.completed || 0) + (ts.cancelled || 0);
  }, 0);
  if (totalTodos > 0) {
    summaryHtml += `<p class="hint">Frontmatter todos: ${doneTodos}/${totalTodos} complete (${progressPct({total: totalTodos, completed: doneTodos, cancelled: 0})}%)</p>`;
  }

  let nextHtml = "";
  const actions = payload.next_actions || [];
  if (actions.length) {
    nextHtml = "<ul class='next-actions'><li>" + actions.map(esc).join("</li><li>") + "</li></ul>";
  }

  const dispositionOptions = Array.from(new Set(groups.map(function(g) { return g.disposition || "—"; }))).sort();
  let controlsHtml = `
    <div class="toolbar">
      <label>Disposition
        <select id="disp-filter">
          <option value="">All</option>
          ${dispositionOptions.map(function(d) { return `<option value="${esc(d)}">${esc(d)}</option>`; }).join("")}
        </select>
      </label>
      <label><input type="checkbox" id="pr-only" /> PR only</label>
      <button id="expand-all" type="button">Expand all</button>
      <button id="collapse-all" type="button">Collapse all</button>
      <span class="hint" id="filter-count"></span>
    </div>`;

  const allCards = groups.map(function(group, idx) {
    const counts = group.status_counts || {};
    const ts = group.todo_summary || {};
    const pct = progressPct(ts);
    const todoLabel = ts.total ? `${(ts.completed || 0) + (ts.cancelled || 0)}/${ts.total} todos` : `${counts.Outstanding || 0} open items`;
    const rollups = group.item_rollups || null;
    const rollupText = rollups
      ? `Items ${rollups.implemented}/${rollups.active}/${rollups.blocked}/${rollups.outstanding}/${rollups.unknown} (impl/active/blk/out/unk)`
      : `${counts.Outstanding || 0} out · ${counts["In Progress"] || 0} active · ${counts.Blocked || 0} blocked`;

    const boardItems = (group.items || []).map(function(item) {
      return `<li>
        <span class="pill ${statusClass(item.status)}">${esc(item.status)}</span>
        <span class="item-text">${esc(item.item)}</span>
        ${item.gaps && item.gaps !== "—" ? `<div class="item-gaps">Gaps: ${esc(item.gaps)}</div>` : ""}
      </li>`;
    }).join("");

    const fmTodos = (group.todos || []).map(function(todo) {
      return `<li>
        <span class="pill ${todoStatusClass(todo.status)}">${todoStatusLabel(todo.status)}</span>
        <span class="todo-text">${esc(todo.content)}</span>
        ${todo.id ? `<div class="todo-id">${esc(todo.id)}</div>` : ""}
      </li>`;
    }).join("");

    const src = group.source || "";
    const srcShort = src.split("/").pop() || src;
    const openAttr = idx < 2 ? " open" : "";

    let body = "";
    if (group.overview) {
      body += `<div class="plan-overview">${esc(group.overview)}</div>`;
    }
    if (fmTodos) {
      body += `<div class="section-title">Plan todos (frontmatter)</div><ul class="todo-list">${fmTodos}</ul>`;
    }
    if (boardItems) {
      body += `<div class="section-title">Task board items</div><ul class="plan-items">${boardItems}</ul>`;
    }
    if (!body) {
      body = "<p class='hint'>No todo detail available.</p>";
    }
    body = renderActionButtons(group) + body;

    return `<details class="plan-card" data-disposition="${esc(group.disposition || "—")}" data-has-pr="${group.pr ? "1" : "0"}" data-source="${esc(src)}"${openAttr}>
      <summary>
        <div class="plan-title">
          <span class="plan-title-text">#${esc(group.seq)} — ${esc(group.plan)}</span>
          <span class="progress-pill">${esc(todoLabel)} · ${pct}%</span>
        </div>
        <div class="progress-bar"><span style="width:${pct}%"></span></div>
        <div class="plan-meta">
          <span class="pill">${esc(group.disposition || "—")}</span>
          <span class="pill progress">${esc(group.next_verb || "—")}</span>
          <span>Owner: ${esc(group.owner)}</span>
          <span>Priority: ${esc(group.priority)}</span>
          <span>Branch: <code>${esc(group.branch)}</code></span>
          ${group.pr ? `<span>PR: ${renderPrLink(group.pr)}</span>` : ""}
          ${group.parent ? `<span>Parent: ${esc(group.parent)}</span>` : ""}
        </div>
        <div class="rollup">${esc(rollupText)} · ${esc(srcShort)}</div>
      </summary>
      <div class="plan-body">${body}</div>
    </details>`;
  });

  root.innerHTML = summaryHtml + nextHtml + controlsHtml + allCards.join("");

  const boardState = {
    projectRoot: payload.project_root || ".",
    audits: {}
  };

  async function pollPlanAction(extra) {
    const params = Object.assign({ path: boardState.projectRoot }, extra || {});
    return callTool("poll_plan_board", params);
  }

  async function refreshBoard() {
    try {
      const data = await pollPlanAction({});
      if (data) renderDashboard(data);
    } catch (err) {
      const status = document.getElementById("status");
      if (status) status.textContent = "Refresh failed: " + (err.message || String(err));
    }
  }

  function applyActionPayload(data, source) {
    if (!data) return null;
    const result = data.action_result || null;
    if (data.action_result && data.action === "audit" && source) {
      boardState.audits[source] = data.action_result;
    }
    if (data.plan_groups) renderDashboard(data);
    return result;
  }

  async function runPlanAction(action, source, resultEl) {
    const path = boardState.projectRoot;
    resultEl.className = "action-result";
    resultEl.textContent = "Working…";
    try {
      if (action === "research") {
        const data = await pollPlanAction({ action: "research", source: source });
        const handoff = applyActionPayload(data, source) || data;
        const msg = (handoff && handoff.message) || ("Research plan " + source);
        sendChatMessage(msg);
        resultEl.className = "action-result ok";
        resultEl.textContent = "Research prompt sent to chat.";
        return;
      }
      if (action === "audit") {
        const data = await pollPlanAction({ action: "audit", source: source, dry_run: true });
        const audit = applyActionPayload(data, source);
        const count = (audit && audit.proposals && audit.proposals.length) || 0;
        resultEl.className = "action-result ok";
        resultEl.textContent = (audit && audit.summary) || (count + " proposal(s)");
        return;
      }
      if (action === "apply_sync") {
        const audit = boardState.audits[source];
        if (!audit || !audit.proposals || !audit.proposals.length) {
          resultEl.className = "action-result err";
          resultEl.textContent = "Run Recheck first.";
          return;
        }
        if (!window.confirm("Apply " + audit.proposals.length + " todo sync proposal(s)?")) {
          resultEl.textContent = "Cancelled.";
          return;
        }
        const data = await pollPlanAction({
          action: "apply_sync",
          source: source,
          proposals: audit.proposals,
          confirm: true
        });
        const applied = applyActionPayload(data, source);
        if (applied && applied.ok) {
          resultEl.className = "action-result ok";
          resultEl.textContent = "Applied: " + (applied.applied || []).join(", ");
          delete boardState.audits[source];
        } else {
          resultEl.className = "action-result err";
          resultEl.textContent = (applied && applied.reason) || "Apply failed";
        }
        return;
      }
      if (action === "merge_ready") {
        if (!window.confirm("Mark plan merge-ready?")) {
          resultEl.textContent = "Cancelled.";
          return;
        }
        const data = await pollPlanAction({ action: "merge_ready", source: source, confirm: true });
        const res = applyActionPayload(data, source);
        if (res && res.ok) {
          resultEl.className = "action-result ok";
          resultEl.textContent = "Marked merge-ready.";
        } else {
          resultEl.className = "action-result err";
          resultEl.textContent = (res && res.reason) || "Failed";
        }
        return;
      }
      if (action === "archive") {
        if (!window.confirm("Archive this plan?")) {
          resultEl.textContent = "Cancelled.";
          return;
        }
        const data = await pollPlanAction({ action: "archive", source: source, confirm: true });
        const res = applyActionPayload(data, source);
        if (res && res.ok) {
          resultEl.className = "action-result ok";
          resultEl.textContent = "Archived to " + (res.archived_to || "archive");
        } else {
          resultEl.className = "action-result err";
          resultEl.textContent = (res && res.reason) || "Failed";
        }
        return;
      }
      if (action === "cancel_plan") {
        const note = window.prompt(
          "Cancellation note (shown in plan overview):",
          "Outdated idea — superseded / no longer pursuing"
        );
        if (note === null) {
          resultEl.textContent = "Cancelled.";
          return;
        }
        if (!window.confirm("Cancel plan, mark todos cancelled, and move to archive?")) {
          resultEl.textContent = "Cancelled.";
          return;
        }
        const data = await pollPlanAction({
          action: "cancel_plan",
          source: source,
          confirm: true,
          cancel_note: note
        });
        const res = applyActionPayload(data, source);
        if (res && res.ok) {
          resultEl.className = "action-result ok";
          resultEl.textContent = "Cancelled → " + (res.archived_to || "archive");
        } else {
          resultEl.className = "action-result err";
          resultEl.textContent = (res && res.reason) || "Failed";
        }
        return;
      }
      if (action === "continue") {
        if (!window.confirm("Queue continue build for this plan?")) {
          resultEl.textContent = "Cancelled.";
          return;
        }
        const data = await pollPlanAction({ action: "continue", source: source, confirm: true });
        const res = applyActionPayload(data, source);
        if (res && res.ok) {
          sendChatMessage(res.handoff_message || ("Continue " + source));
          resultEl.className = "action-result ok";
          resultEl.textContent = "Queued branch " + (res.branch || "");
        } else {
          resultEl.className = "action-result err";
          resultEl.textContent = (res && res.reason) || "Failed";
        }
        return;
      }
    } catch (err) {
      resultEl.className = "action-result err";
      resultEl.textContent = err.message || String(err);
    }
  }

  root.querySelectorAll(".plan-action").forEach(function(button) {
    button.addEventListener("click", function() {
      if (button.disabled) return;
      const action = button.getAttribute("data-action");
      const source = button.getAttribute("data-source") || "";
      const wrap = button.closest(".plan-actions");
      const resultEl = wrap ? wrap.querySelector(".action-result") : null;
      if (action && source && resultEl) runPlanAction(action, source, resultEl);
    });
  });

  function updateFilters() {
    const disp = document.getElementById("disp-filter");
    const prOnly = document.getElementById("pr-only");
    const wantedDisp = disp ? disp.value : "";
    const onlyPr = prOnly ? !!prOnly.checked : false;
    let shown = 0;
    const cards = root.querySelectorAll(".plan-card");
    cards.forEach(function(card) {
      const matchesDisp = !wantedDisp || card.getAttribute("data-disposition") === wantedDisp;
      const matchesPr = !onlyPr || card.getAttribute("data-has-pr") === "1";
      const visible = matchesDisp && matchesPr;
      card.style.display = visible ? "" : "none";
      if (visible) shown += 1;
    });
    const count = document.getElementById("filter-count");
    if (count) count.textContent = `${shown}/${groups.length} shown`;
  }

  const dispEl = document.getElementById("disp-filter");
  const prEl = document.getElementById("pr-only");
  if (dispEl) dispEl.addEventListener("change", updateFilters);
  if (prEl) prEl.addEventListener("change", updateFilters);
  updateFilters();

  const expandBtn = document.getElementById("expand-all");
  const collapseBtn = document.getElementById("collapse-all");
  if (expandBtn) {
    expandBtn.addEventListener("click", function() {
      root.querySelectorAll(".plan-card").forEach(function(card) {
        if (card.style.display !== "none") card.setAttribute("open", "open");
      });
    });
  }
  if (collapseBtn) {
    collapseBtn.addEventListener("click", function() {
      root.querySelectorAll(".plan-card").forEach(function(card) {
        card.removeAttribute("open");
      });
    });
  }
}
"""


def token_dashboard_html() -> str:
    return _html_page("Braindrain Token Dashboard", _TOKEN_RENDER_JS)


def plan_board_html() -> str:
    return _html_page("Braindrain Plan Board", _PLAN_RENDER_JS)
