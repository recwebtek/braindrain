"""SIGINT map MCP App — vanilla SVG force-directed operational topology."""

from __future__ import annotations

from braindrain.mcp_apps.html import _BASE_CSS, _BRIDGE_JS

_SIGINT_CSS = """
.sigint-layout { display: grid; grid-template-columns: 1fr 220px; gap: 10px; align-items: start; }
@media (max-width: 640px) { .sigint-layout { grid-template-columns: 1fr; } }
.sigint-graph-wrap {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  min-height: 320px;
}
#sigint-svg { width: 100%; height: 340px; display: block; cursor: grab; }
#sigint-svg:active { cursor: grabbing; }
.sigint-edge { stroke: var(--muted); stroke-width: 1.2; fill: none; opacity: 0.55; }
.sigint-edge.dashed { stroke-dasharray: 4 3; opacity: 0.35; }
.sigint-edge.pulse { animation: edge-pulse 1.2s ease-out 1; }
@keyframes edge-pulse { from { stroke-width: 3; opacity: 1; } to { stroke-width: 1.2; opacity: 0.55; } }
.sigint-node circle { stroke: var(--border); stroke-width: 1.5; cursor: pointer; }
.sigint-node.selected circle { stroke: var(--accent); stroke-width: 2.5; }
.sigint-node text { font-size: 9px; fill: var(--text); pointer-events: none; text-anchor: middle; }
.sigint-inspector {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 11px;
  max-height: 380px;
  overflow-y: auto;
}
.sigint-inspector h2 { font-size: 11px; margin: 0 0 8px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); font-weight: 600; }
.sigint-inspector .node-type { font-size: 10px; color: var(--muted); margin-bottom: 6px; }
.sigint-inspector .node-label { font-size: 13px; font-weight: 600; margin-bottom: 8px; word-break: break-word; }
.sigint-inspector dl { margin: 0; }
.sigint-inspector dt { color: var(--muted); font-size: 9px; text-transform: uppercase; margin-top: 6px; }
.sigint-inspector dd { margin: 2px 0 0; font-size: 10px; word-break: break-word; }
.sigint-log { margin-top: 10px; border-top: 1px solid var(--border); padding-top: 8px; }
.sigint-log-item { font-size: 10px; color: var(--muted); padding: 3px 0; border-bottom: 1px solid color-mix(in srgb, var(--border) 60%, transparent); }
.sigint-legend { font-size: 10px; color: var(--muted); margin-top: 8px; line-height: 1.4; }
.sigint-stats { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.sigint-stat { font-size: 10px; padding: 2px 6px; border-radius: 999px; background: var(--border); color: var(--muted); }
"""

_SIGINT_RENDER_JS = r"""
const POLL_MS = 8000;
let pollTimer = null;
let graphState = { nodes: [], edges: [], positions: {}, selectedId: null, newestEdgeTs: 0 };

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function nodeRadius(type) {
  if (type === "session") return 18;
  if (type === "braindrain_hub") return 16;
  if (type === "plan") return 13;
  return 11;
}

function initPositions(nodes, width, height) {
  const cx = width / 2;
  const cy = height / 2;
  const positions = {};
  nodes.forEach(function(n, i) {
    if (n.type === "session") {
      positions[n.id] = { x: cx, y: cy, vx: 0, vy: 0 };
    } else {
      const angle = (i / Math.max(nodes.length, 1)) * Math.PI * 2;
      const r = 80 + (i % 5) * 22;
      positions[n.id] = { x: cx + Math.cos(angle) * r, y: cy + Math.sin(angle) * r, vx: 0, vy: 0 };
    }
  });
  return positions;
}

function runForceLayout(nodes, edges, positions, width, height, ticks) {
  const repulsion = 2800;
  const attraction = 0.012;
  const centerPull = 0.003;
  const cx = width / 2;
  const cy = height / 2;
  const nodeById = {};
  nodes.forEach(function(n) { nodeById[n.id] = n; });

  for (let t = 0; t < (ticks || 80); t++) {
    nodes.forEach(function(a) {
      const pa = positions[a.id];
      if (!pa) return;
      nodes.forEach(function(b) {
        if (a.id === b.id) return;
        const pb = positions[b.id];
        if (!pb) return;
        let dx = pa.x - pb.x;
        let dy = pa.y - pb.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const force = repulsion / (dist * dist);
        pa.vx += (dx / dist) * force;
        pa.vy += (dy / dist) * force;
      });
    });

    edges.forEach(function(e) {
      const ps = positions[e.source];
      const pt = positions[e.target];
      if (!ps || !pt) return;
      const dx = pt.x - ps.x;
      const dy = pt.y - ps.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const w = (e.weight || 1) * attraction;
      ps.vx += dx * w;
      ps.vy += dy * w;
      pt.vx -= dx * w;
      pt.vy -= dy * w;
    });

    nodes.forEach(function(n) {
      const p = positions[n.id];
      if (!p) return;
      if (n.type === "session") {
        p.vx += (cx - p.x) * centerPull * 3;
        p.vy += (cy - p.y) * centerPull * 3;
      } else {
        p.vx += (cx - p.x) * centerPull;
        p.vy += (cy - p.y) * centerPull;
      }
      p.vx *= 0.85;
      p.vy *= 0.85;
      p.x += p.vx;
      p.y += p.vy;
      const pad = 24;
      p.x = Math.max(pad, Math.min(width - pad, p.x));
      p.y = Math.max(pad, Math.min(height - pad, p.y));
    });
  }
  return positions;
}

function renderGraphSvg(payload) {
  const nodes = payload.nodes || [];
  const edges = payload.edges || [];
  const width = 640;
  const height = 340;
  if (!graphState.positions || Object.keys(graphState.positions).length !== nodes.length) {
    graphState.positions = initPositions(nodes, width, height);
  }
  graphState.positions = runForceLayout(nodes, edges, graphState.positions, width, height, 60);
  graphState.nodes = nodes;
  graphState.edges = edges;

  let newestTs = 0;
  edges.forEach(function(e) { if (e.ts && e.ts > newestTs) newestTs = e.ts; });
  const pulseNew = newestTs > graphState.newestEdgeTs;
  graphState.newestEdgeTs = newestTs;

  let edgesHtml = edges.map(function(e) {
    const ps = graphState.positions[e.source];
    const pt = graphState.positions[e.target];
    if (!ps || !pt) return "";
    const cls = "sigint-edge" + (e.dashed ? " dashed" : "") + (pulseNew && e.ts === newestTs ? " pulse" : "");
    return '<line class="' + cls + '" x1="' + ps.x + '" y1="' + ps.y + '" x2="' + pt.x + '" y2="' + pt.y + '" />';
  }).join("");

  let nodesHtml = nodes.map(function(n) {
    const p = graphState.positions[n.id];
    if (!p) return "";
    const r = nodeRadius(n.type);
    const sel = graphState.selectedId === n.id ? " selected" : "";
    const label = n.label && n.label.length > 14 ? n.label.slice(0, 12) + "…" : (n.label || n.id);
    return '<g class="sigint-node' + sel + '" data-id="' + esc(n.id) + '" transform="translate(' + p.x + ',' + p.y + ')">' +
      '<circle r="' + r + '" fill="' + esc(n.color || "#94a3b8") + '" />' +
      '<text dy="' + (r + 12) + '">' + esc(label) + '</text></g>';
  }).join("");

  return '<svg id="sigint-svg" viewBox="0 0 ' + width + ' ' + height + '" xmlns="http://www.w3.org/2000/svg">' +
    '<g class="sigint-edges">' + edgesHtml + '</g>' +
    '<g class="sigint-nodes">' + nodesHtml + '</g></svg>';
}

function renderInspector(payload) {
  const panel = document.getElementById("sigint-inspector");
  if (!panel) return;
  const nodes = payload.nodes || [];
  const selected = nodes.find(function(n) { return n.id === graphState.selectedId; });
  if (!selected) {
    panel.innerHTML = '<h2>Inspector</h2><p class="hint">Click a node to inspect metadata and related events.</p>';
    return;
  }
  let metaHtml = "";
  const meta = selected.meta || {};
  Object.keys(meta).forEach(function(k) {
    metaHtml += "<dt>" + esc(k) + "</dt><dd>" + esc(meta[k]) + "</dd>";
  });
  const log = (payload.log || []).filter(function(ev) {
    if (selected.type === "braindrain_tool") return ev.tool_name === selected.label;
    if (selected.type === "hook") return ev.event_type === "session_end";
    return true;
  }).slice(-5);
  let logHtml = log.map(function(ev) {
    const ts = ev.timestamp ? new Date(ev.timestamp * 1000).toLocaleTimeString() : "";
    return '<div class="sigint-log-item">' + esc(ts) + " " + esc(ev.event_type) +
      (ev.tool_name ? " · " + esc(ev.tool_name) : "") + "</div>";
  }).join("");
  panel.innerHTML =
    "<h2>Inspector</h2>" +
    '<div class="node-type">' + esc(selected.type) + " · " + esc(selected.status || "") + "</div>" +
    '<div class="node-label">' + esc(selected.label) + "</div>" +
    "<dl>" + metaHtml + "</dl>" +
    (logHtml ? '<div class="sigint-log"><h2>Related events</h2>' + logHtml + "</div>" : "");
}

function bindGraphClicks() {
  const svg = document.getElementById("sigint-svg");
  if (!svg) return;
  svg.querySelectorAll(".sigint-node").forEach(function(g) {
    g.addEventListener("click", function() {
      graphState.selectedId = g.getAttribute("data-id");
      bindGraphClicks();
      renderInspector(window.__sigintPayload || {});
    });
  });
}

function renderLogStrip(payload) {
  const el = document.getElementById("sigint-log-strip");
  if (!el) return;
  const log = payload.log || [];
  if (!log.length) {
    el.innerHTML = "<p class='hint'>" + esc(payload.hint || "No events in log.") + "</p>";
    return;
  }
  el.innerHTML = log.slice().reverse().map(function(ev) {
    const ts = ev.timestamp ? new Date(ev.timestamp * 1000).toLocaleTimeString() : "";
    return '<div class="sigint-log-item">' + esc(ts) + " · " + esc(ev.event_type) +
      (ev.tool_name ? " · " + esc(ev.tool_name) : "") + "</div>";
  }).join("");
}

function renderDashboard(raw) {
  const payload = raw;
  window.__sigintPayload = payload;
  const root = document.getElementById("root");
  const status = document.getElementById("status");
  if (!payload || !payload.nodes) {
    root.innerHTML = "<p class='hint'>No SIGINT map data yet.</p>";
    if (status) status.textContent = "No data";
    return;
  }
  if (status) status.textContent = "Updated " + (payload.generated_at || "") + " · session " + (payload.session_id || "").slice(0, 20);

  const stats = payload.stats || {};
  const legend = payload.legend || {};
  root.innerHTML =
    '<div class="sigint-stats">' +
    ["events", "tools", "plans", "external_mcps", "subagents"].map(function(k) {
      if (stats[k] == null) return "";
      return '<span class="sigint-stat">' + esc(k) + ": " + esc(stats[k]) + "</span>";
    }).join("") +
    "</div>" +
    '<div class="sigint-layout">' +
    '<div class="sigint-graph-wrap" id="sigint-graph">' + renderGraphSvg(payload) + "</div>" +
    '<div class="sigint-inspector" id="sigint-inspector"></div></div>' +
    '<div class="sigint-log" id="sigint-log-strip"></div>' +
    '<p class="sigint-legend">' +
    esc(legend.subagent_gap || "") + " " + esc(legend.external_mcp_edges || "") +
    "</p>";

  if (!graphState.selectedId && payload.nodes.length) {
    const session = payload.nodes.find(function(n) { return n.type === "session"; });
    graphState.selectedId = session ? session.id : payload.nodes[0].id;
  }
  bindGraphClicks();
  renderInspector(payload);
  renderLogStrip(payload);
}

async function pollSigintMap() {
  try {
    const data = await callTool("poll_sigint_map", {});
    if (data) renderDashboard(data);
  } catch (err) {
    const status = document.getElementById("status");
    if (status) status.textContent = "Poll failed: " + (err.message || String(err));
  }
}

function startPollLoop() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(pollSigintMap, POLL_MS);
}

startPollLoop();
"""


def sigint_map_html() -> str:
    """Return self-contained HTML for the SIGINT operational topology map."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Braindrain SIGINT Map</title>
  <style>{_BASE_CSS}{_SIGINT_CSS}</style>
</head>
<body>
  <div class="wrap">
    <h1>Braindrain SIGINT Map</h1>
    <div id="status">Initializing…</div>
    <div id="root"></div>
  </div>
  <script>{_SIGINT_RENDER_JS}</script>
  <script>{_BRIDGE_JS}</script>
</body>
</html>
"""
