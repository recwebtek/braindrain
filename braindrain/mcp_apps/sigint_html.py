"""SIGINT map MCP App — vanilla SVG orbital-tree operational topology."""

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
  min-height: 380px;
  position: relative;
}
#sigint-svg { width: 100%; height: 420px; display: block; touch-action: none; }
#sigint-svg.pan-ready { cursor: grab; }
#sigint-svg.panning { cursor: grabbing; }
.sigint-zoom-bar {
  position: absolute; top: 8px; right: 8px; z-index: 2;
  display: flex; align-items: center; gap: 4px;
  background: color-mix(in srgb, var(--panel) 88%, transparent);
  border: 1px solid var(--border); border-radius: 8px; padding: 3px;
}
.sigint-zoom-btn {
  font-size: 12px; line-height: 1; min-width: 26px; height: 26px;
  border: 1px solid var(--border); border-radius: 6px;
  background: var(--panel); color: var(--text); cursor: pointer; padding: 0 6px;
}
.sigint-zoom-btn:hover { border-color: var(--accent); }
.sigint-zoom-level { font-size: 10px; color: var(--muted); min-width: 38px; text-align: center; }
.sigint-zoom-hint {
  position: absolute; left: 10px; bottom: 8px; z-index: 2;
  font-size: 9px; color: var(--muted); pointer-events: none;
}
.sigint-sector-label {
  font-size: 10px; fill: var(--muted); font-weight: 600;
  text-transform: uppercase; letter-spacing: .06em; opacity: 0.7;
  pointer-events: none;
}
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
.sigint-filters { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 8px; align-items: center; }
.sigint-filters-label { font-size: 9px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); margin-right: 4px; }
.sigint-filter {
  font-size: 10px; padding: 3px 8px; border-radius: 999px; border: 1px solid var(--border);
  background: var(--panel); color: var(--muted); cursor: pointer; user-select: none;
  display: inline-flex; align-items: center; gap: 5px; transition: opacity .15s, border-color .15s;
}
.sigint-filter::before {
  content: ""; width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0;
  background: var(--swatch, #94a3b8);
}
.sigint-filter.on { color: var(--text); border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); }
.sigint-filter.off { opacity: 0.45; text-decoration: line-through; }
.sigint-filter.off::before { opacity: 0.35; }
"""

_SIGINT_RENDER_JS = r"""
const POLL_MS = 8000;
let pollTimer = null;
const NODE_TYPES = [
  "session", "braindrain_hub", "braindrain_tool", "hook",
  "subagent", "plan", "external_mcp"
];
const TYPE_LABELS = {
  session: "Session",
  braindrain_hub: "Hub",
  braindrain_tool: "Tools",
  hook: "Hooks",
  subagent: "Subagents",
  plan: "Plans",
  external_mcp: "External MCP"
};
const TYPE_COLORS = {
  session: "#3b82f6",
  braindrain_hub: "#8b5cf6",
  braindrain_tool: "#a78bfa",
  hook: "#ef4444",
  subagent: "#f59e0b",
  plan: "#10b981",
  external_mcp: "#64748b"
};
const GRAPH_W = 960;
const GRAPH_H = 520;
const RING_RADIUS = {
  session: 0,
  braindrain_hub: 56,
  braindrain_tool: 120,
  hook: 168,
  subagent: 168,
  plan: 220,
  external_mcp: 268
};
const TYPE_SECTOR = {
  braindrain_hub: -Math.PI / 2,
  braindrain_tool: Math.PI / 5,
  hook: (Math.PI * 4) / 5,
  subagent: Math.PI,
  plan: (Math.PI * 5) / 6,
  external_mcp: -Math.PI / 5
};
const SECTOR_WIDTH = {
  braindrain_hub: 0.2,
  braindrain_tool: Math.PI / 2.2,
  hook: Math.PI / 2.5,
  subagent: Math.PI / 2.5,
  plan: Math.PI * 1.05,
  external_mcp: Math.PI * 1.05
};
const SECTOR_LABELS = {
  braindrain_tool: "Tools",
  plan: "Plans",
  external_mcp: "External MCP",
  hook: "Hooks",
  subagent: "Subagents"
};

let graphState = {
  nodes: [],
  edges: [],
  selectedId: null,
  newestEdgeTs: 0,
  typeFilters: {},
  shellReady: false,
  viewport: { scale: 1, tx: 0, ty: 0 },
  zoomBound: false
};

NODE_TYPES.forEach(function(t) { graphState.typeFilters[t] = true; });

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

function stableHash01(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 4294967296;
}

function orbitalPosition(node, cx, cy, siblingsByType) {
  if (node.type === "session") return { x: cx, y: cy };
  const siblings = siblingsByType[node.type] || [node];
  const count = siblings.length;
  const idx = siblings.findIndex(function(s) { return s.id === node.id; });
  const baseR = RING_RADIUS[node.type] || 140;
  const sectorCenter = TYPE_SECTOR[node.type] != null ? TYPE_SECTOR[node.type] : 0;
  const sectorWidth = SECTOR_WIDTH[node.type] || Math.min(Math.PI * 1.2, count * 0.22 + 0.35);
  let angle;
  if (count === 1) {
    angle = sectorCenter;
  } else {
    const t = idx / (count - 1);
    angle = sectorCenter - sectorWidth / 2 + t * sectorWidth;
  }
  const ringLane = count > 8 ? Math.floor(stableHash01(node.id + ":lane") * 2) : 0;
  const r = baseR + ringLane * 34;
  return { x: cx + Math.cos(angle) * r, y: cy + Math.sin(angle) * r };
}

function computeLayout(nodes) {
  const cx = GRAPH_W / 2;
  const cy = GRAPH_H / 2;
  const siblingsByType = {};
  nodes.forEach(function(n) {
    if (!siblingsByType[n.type]) siblingsByType[n.type] = [];
    siblingsByType[n.type].push(n);
  });
  Object.keys(siblingsByType).forEach(function(t) {
    siblingsByType[t].sort(function(a, b) { return a.id.localeCompare(b.id); });
  });
  const positions = {};
  nodes.forEach(function(n) {
    positions[n.id] = orbitalPosition(n, cx, cy, siblingsByType);
  });
  return positions;
}

function isTypeVisible(type) {
  return graphState.typeFilters[type] !== false;
}

function filterNodes(nodes) {
  return (nodes || []).filter(function(n) { return isTypeVisible(n.type); });
}

function filterEdges(edges, visibleIds) {
  return (edges || []).filter(function(e) {
    return visibleIds.has(e.source) && visibleIds.has(e.target);
  });
}

function buildGraphContent(payload) {
  const allNodes = payload.nodes || [];
  const allEdges = payload.edges || [];
  const nodes = filterNodes(allNodes);
  const visibleIds = new Set(nodes.map(function(n) { return n.id; }));
  const edges = filterEdges(allEdges, visibleIds);
  const positions = computeLayout(nodes);
  graphState.nodes = nodes;
  graphState.edges = edges;

  let newestTs = 0;
  edges.forEach(function(e) { if (e.ts && e.ts > newestTs) newestTs = e.ts; });
  const pulseNew = newestTs > graphState.newestEdgeTs;
  graphState.newestEdgeTs = newestTs;

  const cx = GRAPH_W / 2;
  const cy = GRAPH_H / 2;

  let edgesHtml = edges.map(function(e) {
    const ps = positions[e.source];
    const pt = positions[e.target];
    if (!ps || !pt) return "";
    const cls = "sigint-edge" + (e.dashed ? " dashed" : "") + (pulseNew && e.ts === newestTs ? " pulse" : "");
    return '<line class="' + cls + '" x1="' + ps.x + '" y1="' + ps.y + '" x2="' + pt.x + '" y2="' + pt.y + '" />';
  }).join("");

  let nodesHtml = nodes.map(function(n) {
    const p = positions[n.id];
    if (!p) return "";
    const r = nodeRadius(n.type);
    const sel = graphState.selectedId === n.id ? " selected" : "";
    const label = n.label && n.label.length > 18 ? n.label.slice(0, 16) + "…" : (n.label || n.id);
    return '<g class="sigint-node' + sel + '" data-id="' + esc(n.id) + '" transform="translate(' + p.x + ',' + p.y + ')">' +
      '<circle r="' + r + '" fill="' + esc(n.color || "#94a3b8") + '" />' +
      '<text dy="' + (r + 12) + '">' + esc(label) + '</text></g>';
  }).join("");

  const ringsHtml = NODE_TYPES.filter(function(t) { return t !== "session" && RING_RADIUS[t] && isTypeVisible(t); }).map(function(t) {
    const rr = RING_RADIUS[t];
    return '<circle class="sigint-ring" cx="' + cx + '" cy="' + cy +
      '" r="' + rr + '" fill="none" stroke="var(--border)" stroke-width="0.6" opacity="0.28" />';
  }).join("");

  const labelsHtml = Object.keys(SECTOR_LABELS).filter(function(t) {
    return isTypeVisible(t) && nodes.some(function(n) { return n.type === t; });
  }).map(function(t) {
    const sectorCenter = TYPE_SECTOR[t] || 0;
    const rr = (RING_RADIUS[t] || 140) + 22;
    const lx = cx + Math.cos(sectorCenter) * rr;
    const ly = cy + Math.sin(sectorCenter) * rr;
    return '<text class="sigint-sector-label" x="' + lx + '" y="' + ly + '" text-anchor="middle">' +
      esc(SECTOR_LABELS[t]) + "</text>";
  }).join("");

  return {
    positions: positions,
    viewportHtml:
      '<g class="sigint-rings">' + ringsHtml + "</g>" +
      '<g class="sigint-sector-labels">' + labelsHtml + "</g>" +
      '<g class="sigint-edges">' + edgesHtml + "</g>" +
      '<g class="sigint-nodes">' + nodesHtml + "</g>"
  };
}

function applyViewportTransform() {
  const vp = document.getElementById("sigint-viewport");
  if (!vp) return;
  const v = graphState.viewport;
  vp.setAttribute("transform", "translate(" + v.tx + "," + v.ty + ") scale(" + v.scale + ")");
  const level = document.getElementById("sigint-zoom-level");
  if (level) level.textContent = Math.round(v.scale * 100) + "%";
}

function clampScale(s) {
  return Math.max(0.35, Math.min(4.5, s));
}

function zoomAt(factor, clientX, clientY) {
  const svg = document.getElementById("sigint-svg");
  if (!svg) return;
  const rect = svg.getBoundingClientRect();
  const v = graphState.viewport;
  const oldScale = v.scale;
  const newScale = clampScale(oldScale * factor);
  if (newScale === oldScale) return;
  const px = clientX != null ? clientX - rect.left : rect.width / 2;
  const py = clientY != null ? clientY - rect.top : rect.height / 2;
  const sx = (px / rect.width) * GRAPH_W;
  const sy = (py / rect.height) * GRAPH_H;
  v.tx = sx - (sx - v.tx) * (newScale / oldScale);
  v.ty = sy - (sy - v.ty) * (newScale / oldScale);
  v.scale = newScale;
  applyViewportTransform();
}

function resetViewport(fit) {
  if (fit && graphState.nodes.length) {
    const positions = computeLayout(graphState.nodes);
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    graphState.nodes.forEach(function(n) {
      const p = positions[n.id];
      if (!p) return;
      const pad = 36;
      minX = Math.min(minX, p.x - pad);
      minY = Math.min(minY, p.y - pad);
      maxX = Math.max(maxX, p.x + pad);
      maxY = Math.max(maxY, p.y + pad);
    });
    const bw = Math.max(maxX - minX, 80);
    const bh = Math.max(maxY - minY, 80);
    const scaleX = GRAPH_W / bw;
    const scaleY = GRAPH_H / bh;
    const scale = clampScale(Math.min(scaleX, scaleY) * 0.92);
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    graphState.viewport = {
      scale: scale,
      tx: GRAPH_W / 2 - cx * scale,
      ty: GRAPH_H / 2 - cy * scale
    };
  } else {
    graphState.viewport = { scale: 1, tx: 0, ty: 0 };
  }
  applyViewportTransform();
}

function focusNode(nodeId) {
  const positions = computeLayout(graphState.nodes);
  const p = positions[nodeId];
  if (!p) return;
  graphState.viewport.scale = clampScale(1.8);
  graphState.viewport.tx = GRAPH_W / 2 - p.x * graphState.viewport.scale;
  graphState.viewport.ty = GRAPH_H / 2 - p.y * graphState.viewport.scale;
  applyViewportTransform();
}

function bindZoomPan() {
  if (graphState.zoomBound) return;
  const svg = document.getElementById("sigint-svg");
  if (!svg) return;
  graphState.zoomBound = true;
  svg.classList.add("pan-ready");

  let panning = false;
  let panStart = { x: 0, y: 0, tx: 0, ty: 0 };

  svg.addEventListener("wheel", function(ev) {
    ev.preventDefault();
    const factor = ev.deltaY < 0 ? 1.12 : 1 / 1.12;
    zoomAt(factor, ev.clientX, ev.clientY);
  }, { passive: false });

  svg.addEventListener("mousedown", function(ev) {
    if (ev.button !== 0) return;
    if (ev.target.closest && ev.target.closest(".sigint-node")) return;
    panning = true;
    svg.classList.add("panning");
    panStart = {
      x: ev.clientX,
      y: ev.clientY,
      tx: graphState.viewport.tx,
      ty: graphState.viewport.ty
    };
  });

  window.addEventListener("mousemove", function(ev) {
    if (!panning) return;
    const rect = svg.getBoundingClientRect();
    const dx = (ev.clientX - panStart.x) * (GRAPH_W / rect.width);
    const dy = (ev.clientY - panStart.y) * (GRAPH_H / rect.height);
    graphState.viewport.tx = panStart.tx + dx;
    graphState.viewport.ty = panStart.ty + dy;
    applyViewportTransform();
  });

  window.addEventListener("mouseup", function() {
    if (!panning) return;
    panning = false;
    svg.classList.remove("panning");
  });

  const zoomIn = document.getElementById("sigint-zoom-in");
  const zoomOut = document.getElementById("sigint-zoom-out");
  const zoomReset = document.getElementById("sigint-zoom-reset");
  const zoomFit = document.getElementById("sigint-zoom-fit");
  if (zoomIn) zoomIn.addEventListener("click", function() { zoomAt(1.2); });
  if (zoomOut) zoomOut.addEventListener("click", function() { zoomAt(1 / 1.2); });
  if (zoomReset) zoomReset.addEventListener("click", function() { resetViewport(false); });
  if (zoomFit) zoomFit.addEventListener("click", function() { resetViewport(true); });
}

function graphShellHtml(contentHtml) {
  return '<div class="sigint-zoom-bar">' +
    '<button type="button" class="sigint-zoom-btn" id="sigint-zoom-out" title="Zoom out">−</button>' +
    '<span class="sigint-zoom-level" id="sigint-zoom-level">100%</span>' +
    '<button type="button" class="sigint-zoom-btn" id="sigint-zoom-in" title="Zoom in">+</button>' +
    '<button type="button" class="sigint-zoom-btn" id="sigint-zoom-fit" title="Fit all">Fit</button>' +
    '<button type="button" class="sigint-zoom-btn" id="sigint-zoom-reset" title="Reset view">1:1</button>' +
    "</div>" +
    '<div class="sigint-zoom-hint">Scroll to zoom · drag background to pan · double-click node to focus</div>' +
    '<svg id="sigint-svg" viewBox="0 0 ' + GRAPH_W + " " + GRAPH_H + '" xmlns="http://www.w3.org/2000/svg">' +
    '<g id="sigint-viewport">' + contentHtml + "</g></svg>";
}

function mountGraph(payload, opts) {
  opts = opts || {};
  const content = buildGraphContent(payload);
  const graphEl = document.getElementById("sigint-graph");
  if (!graphEl) return;
  const existing = document.getElementById("sigint-viewport");
  if (existing && graphState.zoomBound) {
    existing.innerHTML = content.viewportHtml;
    if (opts.autoFit) resetViewport(true);
    else applyViewportTransform();
  } else {
    graphState.zoomBound = false;
    graphEl.innerHTML = graphShellHtml(content.viewportHtml);
    bindZoomPan();
    if (opts.autoFit) resetViewport(true);
    else applyViewportTransform();
  }
}

function typeCounts(nodes) {
  const counts = {};
  (nodes || []).forEach(function(n) {
    counts[n.type] = (counts[n.type] || 0) + 1;
  });
  return counts;
}

function renderFilters(payload) {
  const el = document.getElementById("sigint-filters");
  if (!el) return;
  const counts = typeCounts(payload.nodes || []);
  el.innerHTML = '<span class="sigint-filters-label">Show</span>' +
    NODE_TYPES.map(function(t) {
      const n = counts[t] || 0;
      if (!n && t !== "session" && t !== "braindrain_hub") return "";
      const on = isTypeVisible(t);
      const color = TYPE_COLORS[t] || "#94a3b8";
      return '<button type="button" class="sigint-filter ' + (on ? "on" : "off") +
        '" data-type="' + esc(t) + '" style="--swatch:' + color + '">' +
        esc(TYPE_LABELS[t] || t) + (n ? " (" + n + ")" : "") + "</button>";
    }).join("");
  el.querySelectorAll(".sigint-filter").forEach(function(btn) {
    const type = btn.getAttribute("data-type");
    btn.style.setProperty("--swatch", TYPE_COLORS[type] || "#94a3b8");
    btn.addEventListener("click", function() {
      graphState.typeFilters[type] = !isTypeVisible(type);
      if (window.__sigintPayload) mountGraph(window.__sigintPayload);
      renderFilters(window.__sigintPayload || {});
      renderInspector(window.__sigintPayload || {});
      bindGraphClicks();
    });
  });
}

function renderInspector(payload) {
  const panel = document.getElementById("sigint-inspector");
  if (!panel) return;
  const nodes = filterNodes(payload.nodes || []);
  const selected = nodes.find(function(n) { return n.id === graphState.selectedId; });
  if (!selected) {
    const allNodes = payload.nodes || [];
    const hiddenSelected = allNodes.find(function(n) { return n.id === graphState.selectedId; });
    if (hiddenSelected && !isTypeVisible(hiddenSelected.type)) {
      panel.innerHTML = '<h2>Inspector</h2><p class="hint">Selected node is hidden — enable "' +
        esc(TYPE_LABELS[hiddenSelected.type] || hiddenSelected.type) + '" filter.</p>';
      return;
    }
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
    g.addEventListener("click", function(ev) {
      ev.stopPropagation();
      graphState.selectedId = g.getAttribute("data-id");
      if (window.__sigintPayload) mountGraph(window.__sigintPayload);
      bindGraphClicks();
      renderInspector(window.__sigintPayload || {});
    });
    g.addEventListener("dblclick", function(ev) {
      ev.stopPropagation();
      ev.preventDefault();
      focusNode(g.getAttribute("data-id"));
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

function renderStats(payload) {
  const el = document.getElementById("sigint-stats");
  if (!el) return;
  const stats = payload.stats || {};
  el.innerHTML = ["events", "tools", "plans", "external_mcps", "subagents"].map(function(k) {
    if (stats[k] == null) return "";
    return '<span class="sigint-stat">' + esc(k) + ": " + esc(stats[k]) + "</span>";
  }).join("");
}

function ensureShell() {
  if (graphState.shellReady) return;
  const root = document.getElementById("root");
  if (!root) return;
  root.innerHTML =
    '<div class="sigint-stats" id="sigint-stats"></div>' +
    '<div class="sigint-filters" id="sigint-filters"></div>' +
    '<div class="sigint-layout">' +
    '<div class="sigint-graph-wrap" id="sigint-graph"></div>' +
    '<div class="sigint-inspector" id="sigint-inspector"></div></div>' +
    '<div class="sigint-log" id="sigint-log-strip"></div>' +
    '<p class="sigint-legend" id="sigint-legend"></p>';
  graphState.shellReady = true;
}

function renderDashboard(raw) {
  const payload = raw;
  window.__sigintPayload = payload;
  const root = document.getElementById("root");
  const status = document.getElementById("status");
  if (!payload || !payload.nodes) {
    root.innerHTML = "<p class='hint'>No SIGINT map data yet.</p>";
    graphState.shellReady = false;
    graphState.zoomBound = false;
    if (status) status.textContent = "No data";
    return;
  }
  if (status) {
    status.textContent = "Updated " + (payload.generated_at || "") + " · session " + (payload.session_id || "").slice(0, 20);
  }

  ensureShell();
  renderStats(payload);
  renderFilters(payload);

  const legend = payload.legend || {};
  const legendEl = document.getElementById("sigint-legend");
  if (legendEl) {
    legendEl.textContent = (legend.subagent_gap || "") + " " + (legend.external_mcp_edges || "");
  }

  const graphEl = document.getElementById("sigint-graph");
  const firstLoad = !graphState.zoomBound;
  if (graphEl) mountGraph(payload, { autoFit: firstLoad });

  if (!graphState.selectedId && payload.nodes.length) {
    const visible = filterNodes(payload.nodes);
    const session = visible.find(function(n) { return n.type === "session"; });
    graphState.selectedId = session ? session.id : (visible[0] && visible[0].id);
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
