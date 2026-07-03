"""Self-contained HTML dashboard for plan audit history snapshots."""

from __future__ import annotations

import html
import json
import re
from typing import Any

from braindrain.mcp_apps.html import _BASE_CSS

_AUDIT_HISTORY_CSS = _BASE_CSS + """
.panel { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 12px; margin-bottom: 12px; }
.panel h2 { font-size: 12px; margin: 0 0 8px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); font-weight: 600; }
.kpi { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px; margin-bottom: 12px; }
.kpi .card .delta { font-size: 11px; color: var(--muted); margin-top: 2px; }
.kpi .card .delta.up { color: var(--warn); }
.kpi .card .delta.down { color: var(--good); }
.chart { width: 100%; overflow-x: auto; }
.chart svg { display: block; max-width: 100%; }
.alert { border-left: 3px solid var(--warn); padding: 8px 10px; margin-bottom: 8px; background: color-mix(in srgb, var(--warn) 8%, var(--panel)); border-radius: 6px; font-size: 12px; }
.alert.coverage { border-left-color: var(--accent); background: color-mix(in srgb, var(--accent) 8%, var(--panel)); }
.heatmap { display: flex; flex-wrap: wrap; gap: 3px; }
.heat-cell { width: 12px; height: 12px; border-radius: 2px; background: var(--border); }
.heat-cell.has { background: var(--accent); opacity: 0.35; }
.heat-cell.has[data-trigger="manual"] { background: var(--good); opacity: 0.55; }
.footer { color: var(--muted); font-size: 10px; margin-top: 16px; }
.spark-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px; }
.spark { font-size: 10px; color: var(--muted); }
.spark strong { color: var(--text); display: block; margin-bottom: 4px; font-size: 11px; }
"""

_AUDIT_HISTORY_JS = r"""
function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

function lastPoint(series) {
  return series && series.length ? series[series.length - 1] : null;
}

function lineChart(svg, series, keys, colors, w, h, pad) {
  pad = pad || 28;
  if (!series.length) return;
  const xs = series.map((_, i) => i);
  const maxY = Math.max(1, ...series.flatMap(p => keys.map(k => (p.counts && p.counts[k]) || (p.scores && p.scores[k]) || 0)));
  const xScale = i => pad + (i / Math.max(1, series.length - 1)) * (w - pad * 2);
  const yScale = v => h - pad - (v / maxY) * (h - pad * 2);
  keys.forEach((key, ki) => {
    const pts = series.map((p, i) => {
      const v = (p.counts && p.counts[key]) != null ? p.counts[key] : (p.scores && p.scores[key]) || 0;
      return xScale(i) + "," + yScale(v);
    }).join(" ");
    const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    line.setAttribute("fill", "none");
    line.setAttribute("stroke", colors[ki % colors.length]);
    line.setAttribute("stroke-width", "2");
    line.setAttribute("points", pts);
    svg.appendChild(line);
  });
  const axis = document.createElementNS("http://www.w3.org/2000/svg", "line");
  axis.setAttribute("x1", pad); axis.setAttribute("x2", w - pad);
  axis.setAttribute("y1", h - pad); axis.setAttribute("y2", h - pad);
  axis.setAttribute("stroke", "var(--border)");
  svg.appendChild(axis);
}

function renderDashboard(data) {
  const root = document.getElementById("root");
  if (!root || !data) return;
  const series = data.series || [];
  const summary = data.summary || {};
  const latest = lastPoint(series) || {};
  const counts = latest.counts || {};
  const deltas = summary.deltas || {};
  let html = "";

  html += '<div class="kpi">';
  ["blocked", "implemented", "in_progress", "outstanding"].forEach(k => {
    const label = k.replace(/_/g, " ");
    const val = counts[k] || 0;
    const d = deltas[k] || 0;
    const cls = d > 0 && k === "blocked" ? "up" : d < 0 && k === "blocked" ? "down" : "";
  html += '<div class="card"><div class="label">' + esc(label) + '</div><div class="value">' + val +
    '</div><div class="delta ' + cls + '">' + (d > 0 ? "+" : "") + d + ' vs start</div></div>';
  });
  html += '</div>';

  if (((data.alerts && data.alerts.regressions) || []).length) {
    html += '<div class="panel"><h2>Regression flags</h2>';
    data.alerts.regressions.forEach(a => {
      html += '<div class="alert">' + esc(a.date) + ': ' + esc(a.message) + '</div>';
    });
    html += '</div>';
  }
  if (((data.alerts && data.alerts.coverage) || []).length) {
    html += '<div class="panel"><h2>Coverage alerts</h2>';
    data.alerts.coverage.forEach(a => {
      html += '<div class="alert coverage">' + esc(a.message) + '</div>';
    });
    html += '</div>';
  }
  if (((data.alerts && data.alerts.stalled_plans) || []).length) {
    html += '<div class="panel"><h2>Stalled plans</h2>';
    data.alerts.stalled_plans.slice(0, 8).forEach(p => {
      html += '<div class="alert">' + esc(p.slug) + ' — active since ' + esc(p.first_seen) + '</div>';
    });
    html += '</div>';
  }

  html += '<div class="panel"><h2>Status over time</h2><div class="chart"><svg id="status-chart" width="900" height="220"></svg></div></div>';
  html += '<div class="panel"><h2>Health scores</h2><div class="chart"><svg id="score-chart" width="900" height="180"></svg></div></div>';
  html += '<div class="panel"><h2>Plan inventory</h2><div class="chart"><svg id="plan-chart" width="900" height="160"></svg></div></div>';

  html += '<div class="panel"><h2>Audit cadence</h2><div class="heatmap" id="heatmap"></div></div>';

  html += '<div class="panel"><h2>Recurring risks</h2><table><thead><tr><th>Risk</th><th>Runs</th><th>First</th><th>Last</th></tr></thead><tbody>';
  (summary.recurring_risks || []).slice(0, 12).forEach(r => {
    html += '<tr><td>' + esc(r.text) + '</td><td>' + r.occurrences + '</td><td>' + esc(r.first_seen) +
      '</td><td>' + esc(r.last_seen) + '</td></tr>';
  });
  html += '</tbody></table></div>';

  html += '<div class="panel"><h2>Top active plans (latest)</h2><div class="spark-grid">';
  (latest.plans || []).slice(0, 12).forEach(p => {
    const items = p.items || {};
    html += '<div class="spark"><strong>' + esc(p.slug) + '</strong> ' + esc(p.disposition) +
      ' — impl ' + (items.implemented || 0) + ', blocked ' + (items.blocked || 0) + '</div>';
  });
  html += '</div></div>';

  html += '<div class="footer">Reports: ' + (summary.report_count || 0) + ' · Range: ' +
    esc((summary.date_range || []).join(" → ")) + ' · Peak blocked: ' +
    ((summary.peak_blocked && summary.peak_blocked.value) || 0) + ' on ' +
    esc((summary.peak_blocked && summary.peak_blocked.date) || "") +
    (summary.pre_card_era_end ? ' · Per-plan cards from ' + esc(summary.pre_card_era_end) + ' onward' : '') +
    '</div>';

  if ((data.skipped || []).length) {
    html += '<div class="footer">Skipped: ' + data.skipped.map(s => esc(s.file) + " (" + esc(s.reason) + ")").join("; ") + '</div>';
  }

  root.innerHTML = html;

  lineChart(document.getElementById("status-chart"), series,
    ["implemented", "in_progress", "blocked", "outstanding", "unknown"],
    ["var(--good)", "var(--accent)", "var(--warn)", "var(--muted)", "var(--border)"], 900, 220);
  lineChart(document.getElementById("score-chart"), series,
    ["coverage_score", "overlap_score", "gap_score"],
    ["var(--warn)", "var(--accent)", "var(--good)"], 900, 180);
  const planSeries = series.map(p => ({ counts: { plan_count: p.plan_count || 0 } }));
  lineChart(document.getElementById("plan-chart"), planSeries, ["plan_count"], ["var(--accent)"], 900, 160);

  const hm = document.getElementById("heatmap");
  if (hm) {
    series.forEach(p => {
      const c = document.createElement("div");
      c.className = "heat-cell has";
      c.title = (p.date || "") + " · " + (p.trigger || "");
      c.setAttribute("data-trigger", (p.trigger || "").indexOf("manual") >= 0 ? "manual" : "auto");
      hm.appendChild(c);
    });
  }
}

(function bootstrap() {
  const el = document.getElementById("snapshot-data");
  if (!el) return;
  try {
    const data = JSON.parse(el.textContent || "{}");
    renderDashboard(data);
    const st = document.getElementById("status");
    if (st) st.textContent = "Generated " + (data.generated_at || "");
  } catch (e) {
    const st = document.getElementById("status");
    if (st) st.textContent = "Failed to parse snapshot: " + e;
  }
})();
"""


def _safe_json_embed(snapshot: dict[str, Any]) -> str:
    raw = json.dumps(snapshot, ensure_ascii=False)
    return re.sub(r"</(script)", r"<\\/\\1", raw, flags=re.IGNORECASE)


def render_history_html(snapshot: dict[str, Any], *, title: str = "Plan Audit History") -> str:
    """Build self-contained HTML with embedded snapshot JSON."""
    payload = _safe_json_embed(snapshot)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)}</title>
  <style>{_AUDIT_HISTORY_CSS}</style>
</head>
<body>
  <div class="wrap">
    <h1>{html.escape(title)}</h1>
    <div id="status">Loading…</div>
    <div id="root"></div>
  </div>
  <script type="application/json" id="snapshot-data">{payload}</script>
  <script>{_AUDIT_HISTORY_JS}</script>
</body>
</html>
"""
