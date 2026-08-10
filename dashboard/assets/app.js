// Renders dashboard/data/latest.json into the 3 tabs. See README for the
// data shapes this expects (they come from pipeline/build_report.py).

let REPORT_DATA = null;
let netLoadChart = null;
let currentWindow = "yesterday";
let currentAsType = null;
const LIVE_NODE_CACHE = {}; // node -> {date: {hour: {...}}}, populated by successful /node-lookup calls
const LIVE_NODE_TB_CACHE = {}; // node -> {tb1, tb2, tb4, hour_count} for "yesterday" only
const BACKFILLED_NODE_CACHE = {}; // node -> {node, last_updated, days, windows}, from dashboard/data/nodes/<NODE>.json

const WINDOW_LABELS = { yesterday: "Yesterday", "3day": "Last 3 Days", mtd: "Month to Date", ytd: "Year to Date" };
const AS_TYPE_ORDER = ["REGUP", "REGDN", "RRS", "NSPIN", "ECRS"];
const AS_TYPE_LABELS = { REGUP: "Reg-Up", REGDN: "Reg-Down", RRS: "RRS", NSPIN: "Non-Spin", ECRS: "ECRS" };
const SAGE_RGB = "124,152,133";
const CLAY_RGB = "181,101,74";

// ── Tab switching ────────────────────────────────────────────────────────────

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
  });
});

// ── Formatting helpers ───────────────────────────────────────────────────────

function fmtMoney(v) {
  return v === null || v === undefined ? "—" : `$${v.toFixed(2)}`;
}

function fmtSignedMoney(v) {
  if (v === null || v === undefined) return "—";
  return v >= 0 ? `+$${v.toFixed(2)}` : `-$${Math.abs(v).toFixed(2)}`;
}

function fmtNum(v, decimals = 2) {
  return v === null || v === undefined ? "—" : v.toFixed(decimals);
}

function dartClass(v) {
  if (v === null || v === undefined) return "null-value";
  return v >= 0 ? "dart-positive" : "dart-negative";
}

function prettifyPoint(key) {
  if (!key) return "";
  if (key === "HB_BUSAVG") return "Bus Average";
  if (key.startsWith("HB_")) return `${titleCase(key.slice(3))} Hub`;
  if (key.startsWith("LZ_")) return `${titleCase(key.slice(3))} Zone`;
  return key;
}

function titleCase(s) {
  return s.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatTimestamp(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleString("en-US", {
    month: "short", day: "numeric", year: "numeric",
    hour: "numeric", minute: "2-digit", timeZone: "America/Chicago", timeZoneName: "short",
  });
}

function latestDateKey(daysObj) {
  const keys = Object.keys(daysObj || {});
  if (keys.length === 0) return null;
  return keys.sort()[keys.length - 1];
}

// ── Tab 1: Net load chart ───────────────────────────────────────────────────

function attachBidClose(point, bidClose, day, he) {
  const bc = bidClose[day]?.[he];
  if (bc) {
    point.bid_close_net_load = bc.net_load;
    point.bid_close_gross_load = bc.gross_load;
    point.bid_close_wind = bc.wind;
    point.bid_close_solar = bc.solar;
  }
  return point;
}

function buildNetLoadSeries(netLoad) {
  const history = netLoad?.history || {};
  const forecast = netLoad?.forecast || {};
  const bidClose = netLoad?.bid_close || {};
  const points = [];

  for (const day of Object.keys(history).sort()) {
    for (const he of Object.keys(history[day]).sort((a, b) => Number(a) - Number(b))) {
      points.push(attachBidClose({ day, he, kind: "history", ...history[day][he] }, bidClose, day, he));
    }
  }
  const boundaryIndex = points.length - 1;
  for (const day of Object.keys(forecast).sort()) {
    for (const he of Object.keys(forecast[day]).sort((a, b) => Number(a) - Number(b))) {
      const point = attachBidClose({ day, he, kind: "forecast", ...forecast[day][he] }, bidClose, day, he);
      points.push(point);
    }
  }

  return { points, boundaryIndex };
}

function setChartVisible(canvas, visible, message) {
  if (!canvas) return;
  canvas.style.display = visible ? "" : "none";
  let msgEl = canvas.parentElement.querySelector(".chart-empty-message");
  if (!visible) {
    if (!msgEl) {
      msgEl = document.createElement("p");
      msgEl.className = "report-date chart-empty-message";
      canvas.parentElement.appendChild(msgEl);
    }
    msgEl.textContent = message;
  } else if (msgEl) {
    msgEl.remove();
  }
}

function renderNetLoadChart(netLoad) {
  const canvas = document.getElementById("netLoadChart");
  if (!canvas) return;
  if (typeof Chart === "undefined") {
    setChartVisible(canvas, false, "Chart library failed to load — check the browser console and the Chart.js <script> tag in index.html.");
    console.error("Chart.js did not load — window.Chart is undefined.");
    return;
  }

  const { points, boundaryIndex } = buildNetLoadSeries(netLoad);
  if (points.length === 0) {
    setChartVisible(canvas, false, "No net load data available for this report.");
    return;
  }
  setChartVisible(canvas, true);

  const labels = points.map((p) => `${p.day.slice(5)} HE${p.he}`);
  const series = (key) => points.map((p) => (p[key] === undefined ? null : p[key]));
  const dashedAfterBoundary = { borderDash: (ctx) => (ctx.p0DataIndex >= boundaryIndex ? [6, 4] : undefined) };

  if (netLoadChart) netLoadChart.destroy();
  netLoadChart = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "Net Load", data: series("net_load"), borderColor: "#c9a24b", borderWidth: 2.5, pointRadius: 0, segment: dashedAfterBoundary },
        { label: "Gross Load", data: series("gross_load"), borderColor: "#9a958a", borderWidth: 1, pointRadius: 0, segment: dashedAfterBoundary },
        { label: "Wind", data: series("wind"), borderColor: "#7c9885", borderWidth: 1, pointRadius: 0, segment: dashedAfterBoundary },
        { label: "Solar", data: series("solar"), borderColor: "#b5654a", borderWidth: 1, pointRadius: 0, segment: dashedAfterBoundary },
        // Bid-close lines deliberately reuse each quantity's own color rather than a
        // separate palette — same color = same physical quantity, line style (dotted
        // here vs. solid/dashed above) = which forecast vintage. Flat dotted throughout
        // (no segment callback) since "bid-close" means the same thing whether it's
        // sitting over a history day or a forecast day.
        { label: "Bid-Close Net Load", data: series("bid_close_net_load"), borderColor: "#c9a24b", borderWidth: 1.5, borderDash: [2, 3], pointRadius: 0, spanGaps: false },
        { label: "Bid-Close Gross Load", data: series("bid_close_gross_load"), borderColor: "#9a958a", borderWidth: 1, borderDash: [2, 3], pointRadius: 0, spanGaps: false },
        { label: "Bid-Close Wind", data: series("bid_close_wind"), borderColor: "#7c9885", borderWidth: 1, borderDash: [2, 3], pointRadius: 0, spanGaps: false },
        { label: "Bid-Close Solar", data: series("bid_close_solar"), borderColor: "#b5654a", borderWidth: 1, borderDash: [2, 3], pointRadius: 0, spanGaps: false },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false, // critical: without this, Chart.js needs the canvas's own
                                  // intrinsic size, which is 0 unless the parent has a fixed
                                  // height (see .chart-container in styles.css) — this was the
                                  // blank-chart bug.
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { ticks: { autoSkip: true, maxTicksLimit: 12, color: "#9a958a" }, grid: { color: "#2a2a2a" } },
        y: { title: { display: true, text: "GW", color: "#9a958a" }, ticks: { color: "#9a958a" }, grid: { color: "#2a2a2a" } },
      },
      plugins: {
        legend: { labels: { color: "#f4f1ea" } },
        tooltip: { callbacks: { title: (items) => labels[items[0].dataIndex] } },
      },
    },
  });
}

// ── Tab 1: Hub summary cards ─────────────────────────────────────────────────

document.querySelectorAll("#windowSelector button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#windowSelector button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentWindow = btn.dataset.window;
    renderHubCards(REPORT_DATA?.hub_windows);
  });
});

function renderHubCards(hubWindows) {
  const grid = document.getElementById("hubCardGrid");
  if (!grid) return;
  grid.innerHTML = "";

  const hubs = Object.keys(hubWindows || {});
  if (hubs.length === 0) {
    grid.innerHTML = '<p class="report-date">No hub price data available.</p>';
    return;
  }

  // Scale for the peak bars: use the largest |dart_spread| seen across every
  // hub for the currently selected window, so bars are comparable to each
  // other and not dominated by a single outlier from a different window.
  let maxAbsSpread = 1;
  for (const hub of hubs) {
    const s = hubWindows[hub]?.[currentWindow];
    for (const scope of [s?.overall, s?.on_peak, s?.off_peak]) {
      if (scope?.dart_spread !== null && scope?.dart_spread !== undefined) {
        maxAbsSpread = Math.max(maxAbsSpread, Math.abs(scope.dart_spread));
      }
    }
  }

  for (const hub of hubs) {
    const stats = hubWindows[hub]?.[currentWindow];
    if (!stats) continue;
    grid.appendChild(buildHubCard(hub, stats, maxAbsSpread));
  }
}

function buildHubCard(hub, stats, maxAbsSpread) {
  const card = document.createElement("div");
  card.className = "hub-card";
  const o = stats.overall || {};

  card.innerHTML = `
    <div class="hub-card-name">${prettifyPoint(hub)}</div>
    <div class="hub-card-metrics">
      <div>Avg DA<strong>${fmtMoney(o.avg_da)}</strong></div>
      <div>Avg RT<strong>${fmtMoney(o.avg_rt)}</strong></div>
      <div>On-Peak RT<strong>${fmtMoney(stats.on_peak?.avg_rt)}</strong></div>
    </div>
    <div class="hub-card-spread ${dartClass(o.dart_spread)}">${fmtSignedMoney(o.dart_spread)} DART</div>
    <div class="peak-bars">
      ${buildPeakBarRow("24Hr Avg", stats.overall, maxAbsSpread, "peak-bar-row--total")}
      ${buildPeakBarRow("On-Peak", stats.on_peak, maxAbsSpread)}
      ${buildPeakBarRow("Off-Peak", stats.off_peak, maxAbsSpread)}
    </div>
    <div class="hub-card-metrics hub-card-tb">
      <div>TB1<strong>${fmtMoney(stats.tb1)}</strong></div>
      <div>TB2<strong>${fmtMoney(stats.tb2)}</strong></div>
      <div>TB4<strong>${fmtMoney(stats.tb4)}</strong></div>
    </div>
  `;
  return card;
}

function buildPeakBarRow(label, scope, maxAbsSpread, extraClass = "") {
  const v = scope?.dart_spread;
  const pct = v === null || v === undefined ? 0 : Math.min(100, (Math.abs(v) / maxAbsSpread) * 100);
  const color = v >= 0 ? SAGE_RGB : CLAY_RGB;
  // Bar grows from the center: positive to the right half, negative to the left half.
  const fillStyle = v >= 0
    ? `left:50%; width:${pct / 2}%; background:rgb(${color});`
    : `right:50%; width:${pct / 2}%; background:rgb(${color});`;
  return `
    <div class="peak-bar-row ${extraClass}">
      <span class="peak-bar-label">${label}</span>
      <div class="peak-bar-track"><div class="peak-bar-fill" style="${fillStyle}"></div></div>
      <span class="peak-bar-value ${dartClass(v)}">${fmtSignedMoney(v)}</span>
    </div>
  `;
}

// ── Tab 2: Reference point selector ─────────────────────────────────────────

function populateHubSelect() {
  const select = document.getElementById("hubSelect");
  if (!select) return;
  select.innerHTML = "";

  const hubs = Object.keys(REPORT_DATA?.hub_prices || {});
  const zones = Object.keys(REPORT_DATA?.load_zone_prices || {});

  if (hubs.length) {
    const grp = document.createElement("optgroup");
    grp.label = "Hubs";
    for (const h of hubs) grp.appendChild(new Option(prettifyPoint(h), h));
    select.appendChild(grp);
  }
  if (zones.length) {
    const grp = document.createElement("optgroup");
    grp.label = "Load Zones";
    for (const z of zones) grp.appendChild(new Option(prettifyPoint(z), z));
    select.appendChild(grp);
  }
  if (hubs.includes("HB_BUSAVG")) select.value = "HB_BUSAVG";
}

function getPointSeries(key) {
  return REPORT_DATA?.hub_prices?.[key] || REPORT_DATA?.load_zone_prices?.[key] || BACKFILLED_NODE_CACHE[key]?.days || LIVE_NODE_CACHE[key] || null;
}

function getTbStats(key) {
  // Hub, load zone, or a fully-backfilled node: full window rollups already computed.
  const windowStats = REPORT_DATA?.hub_windows?.[key] || REPORT_DATA?.load_zone_windows?.[key] || BACKFILLED_NODE_CACHE[key]?.windows;
  if (windowStats) {
    return { yesterday: windowStats.yesterday, "3day": windowStats["3day"], mtd: windowStats.mtd, ytd: windowStats.ytd, liveOnly: false };
  }
  // Live-searched node not yet backfilled: this Function only ever fetches
  // one day, so only "yesterday" is available — 3-Day/MTD/YTD would need it
  // to pull (and paginate) a much wider date range, which isn't built. Once
  // this node is backfilled (see resolveAndRenderLocation), it'll show up
  // via the windowStats branch above instead on the next search.
  const liveTb = LIVE_NODE_TB_CACHE[key];
  if (liveTb) {
    return { yesterday: liveTb, "3day": null, mtd: null, ytd: null, liveOnly: true };
  }
  return null;
}

function renderTbPanel(key) {
  const panel = document.getElementById("tbPanel");
  const grid = document.getElementById("tbPanelGrid");
  const note = document.getElementById("tbPanelNote");
  if (!panel || !grid) return;

  const stats = getTbStats(key);
  if (!stats) {
    panel.classList.remove("visible");
    return;
  }

  const windows = [["yesterday", "Yesterday"], ["3day", "3-Day"], ["mtd", "MTD"], ["ytd", "YTD"]];
  let html = "<div></div>" + windows.map(([, label]) => `<div class="tb-header">${label}</div>`).join("");
  for (const metric of ["tb1", "tb2", "tb4"]) {
    html += `<div class="tb-label">${metric.toUpperCase()}</div>`;
    for (const [w] of windows) {
      const val = stats[w] ? stats[w][metric] : null;
      html += `<div class="tb-value">${fmtMoney(val)}</div>`;
    }
  }
  grid.innerHTML = html;
  if (note) note.textContent = stats.liveOnly ? "(live-searched node — Yesterday only)" : "";
  panel.classList.add("visible");
}

function renderReferencePoint(key) {
  renderEnergySection(key);
  renderBasisPanel(key);
  renderTbPanel(key);
}

document.getElementById("hubSelect")?.addEventListener("change", (e) => renderReferencePoint(e.target.value));

// ── Shared: hourly time-series chart (DA/RT lines + DART bars) ──────────────

function renderHourlyTimeSeriesChart(canvas, existingChart, hoursObj) {
  if (existingChart) existingChart.destroy();
  if (!canvas || typeof Chart === "undefined" || !hoursObj) return null;

  const heList = Object.keys(hoursObj).sort((a, b) => Number(a) - Number(b));
  const labels = heList.map((he) => `HE${he}`);
  const da = heList.map((he) => (hoursObj[he].da ?? null));
  const rt = heList.map((he) => (hoursObj[he].rt ?? null));
  const dart = heList.map((he) => (hoursObj[he].dart ?? null));
  const dartColors = dart.map((v) => (v === null ? "#333" : v >= 0 ? `rgba(${SAGE_RGB},0.55)` : `rgba(${CLAY_RGB},0.55)`));

  return new Chart(canvas, {
    data: {
      labels,
      datasets: [
        { type: "bar", label: "DART", data: dart, backgroundColor: dartColors, order: 2 },
        { type: "line", label: "DA", data: da, borderColor: "#c9a24b", borderWidth: 2, pointRadius: 0, order: 1 },
        { type: "line", label: "RT", data: rt, borderColor: "#f4f1ea", borderWidth: 1.5, pointRadius: 0, order: 1 },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { ticks: { color: "#9a958a" }, grid: { color: "#2a2a2a" } },
        y: { title: { display: true, text: "$/MWh", color: "#9a958a" }, ticks: { color: "#9a958a" }, grid: { color: "#2a2a2a" } },
      },
      plugins: { legend: { labels: { color: "#f4f1ea" } } },
    },
  });
}

function avgOf(arr, field) {
  const vals = arr.map((h) => h[field]).filter((v) => v !== null && v !== undefined);
  if (vals.length === 0) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

function renderPeakSummary(containerId, hoursObj) {
  const el = document.getElementById(containerId);
  if (!el) return;
  if (!hoursObj) { el.innerHTML = ""; return; }

  const all = Object.values(hoursObj);
  const on = all.filter((h) => h.peak === "on");
  const off = all.filter((h) => h.peak === "off");
  const summarize = (arr) => ({ da: avgOf(arr, "da"), rt: avgOf(arr, "rt"), dart: avgOf(arr, "dart"), count: arr.length });
  const allS = summarize(all);
  const onS = summarize(on);
  const offS = summarize(off);

  el.innerHTML = `
    <div class="peak-summary-card total">
      <div class="peak-summary-title">24Hr Avg (${allS.count}h)</div>
      <div class="peak-summary-metrics">
        <div>DA<strong>${fmtMoney(allS.da)}</strong></div>
        <div>RT<strong>${fmtMoney(allS.rt)}</strong></div>
        <div>DART<strong class="${dartClass(allS.dart)}">${fmtSignedMoney(allS.dart)}</strong></div>
      </div>
    </div>
    <div class="peak-summary-card on">
      <div class="peak-summary-title">On-Peak (${onS.count}h)</div>
      <div class="peak-summary-metrics">
        <div>DA<strong>${fmtMoney(onS.da)}</strong></div>
        <div>RT<strong>${fmtMoney(onS.rt)}</strong></div>
        <div>DART<strong class="${dartClass(onS.dart)}">${fmtSignedMoney(onS.dart)}</strong></div>
      </div>
    </div>
    <div class="peak-summary-card off">
      <div class="peak-summary-title">Off-Peak (${offS.count}h)</div>
      <div class="peak-summary-metrics">
        <div>DA<strong>${fmtMoney(offS.da)}</strong></div>
        <div>RT<strong>${fmtMoney(offS.rt)}</strong></div>
        <div>DART<strong class="${dartClass(offS.dart)}">${fmtSignedMoney(offS.dart)}</strong></div>
      </div>
    </div>
  `;
}

// ── Tab 2: Energy section (reference point's most recent day) ───────────────

let energyChart = null;

function renderEnergySection(key) {
  const dateLabel = document.getElementById("hourlyPriceDate");
  const canvas = document.getElementById("energyHourlyChart");
  const days = getPointSeries(key);
  const day = latestDateKey(days);

  if (!day) {
    if (dateLabel) dateLabel.textContent = "";
    setChartVisible(canvas, false, "No price data for this node.");
    renderPeakSummary("energyPeakSummary", null);
    return;
  }
  if (dateLabel) dateLabel.textContent = `${prettifyPoint(key)} — most recent available day: ${day}`;
  setChartVisible(canvas, true);
  energyChart = renderHourlyTimeSeriesChart(canvas, energyChart, days[day]);
  renderPeakSummary("energyPeakSummary", days[day]);
}

// ── Tab 2: Basis panel (node price - hub price, per hub) ────────────────────

function getWindowAvgRt(key, window) {
  // Hub, load zone, or fully-backfilled node: reuse the already-computed
  // window rollup rather than re-deriving an average from raw hourly data.
  const windowStats = REPORT_DATA?.hub_windows?.[key] || REPORT_DATA?.load_zone_windows?.[key] || BACKFILLED_NODE_CACHE[key]?.windows;
  if (windowStats) {
    return windowStats[window]?.overall?.avg_rt ?? null;
  }
  // Live-only node: no precomputed windows exist at all, only whatever the
  // Function returned for its single fetched day — so only "yesterday" has
  // any value; 3-Day/MTD/YTD are genuinely unavailable, not just uncomputed.
  if (window !== "yesterday") return null;
  const days = getPointSeries(key);
  const day = latestDateKey(days);
  if (!day) return null;
  return avgField(days[day], "rt");
}

function renderBasisPanel(key) {
  const panel = document.getElementById("basisPanel");
  const dateEl = document.getElementById("basisPanelDate");
  const gridEl = document.getElementById("basisPanelRows");
  if (!panel || !gridEl) return;

  const hubPrices = REPORT_DATA?.hub_prices || {};
  const otherHubs = Object.keys(hubPrices).filter((h) => h !== key);
  if (otherHubs.length === 0) {
    panel.classList.remove("visible");
    return;
  }

  const windowStatsForKey = REPORT_DATA?.hub_windows?.[key] || REPORT_DATA?.load_zone_windows?.[key] || BACKFILLED_NODE_CACHE[key]?.windows;
  const isLiveOnly = !windowStatsForKey;

  const windows = [["yesterday", "Yesterday"], ["3day", "3-Day"], ["mtd", "MTD"], ["ytd", "YTD"]];
  const ownAvgRtByWindow = {};
  for (const [w] of windows) ownAvgRtByWindow[w] = getWindowAvgRt(key, w);

  if (ownAvgRtByWindow.yesterday === null) {
    panel.classList.remove("visible");
    return;
  }

  let html = "<div></div>" + windows.map(([, label]) => `<div class="tb-header">${label}</div>`).join("");
  for (const hub of otherHubs) {
    html += `<div class="tb-label">${prettifyPoint(hub)}</div>`;
    for (const [w] of windows) {
      const hubAvgRt = getWindowAvgRt(hub, w);
      const ownAvgRt = ownAvgRtByWindow[w];
      const basis = ownAvgRt === null || hubAvgRt === null ? null : ownAvgRt - hubAvgRt;
      html += `<div class="tb-value ${dartClass(basis)}">${fmtSignedMoney(basis)}</div>`;
    }
  }
  gridEl.innerHTML = html;
  if (dateEl) dateEl.textContent = isLiveOnly ? "(RT average — live-searched node, Yesterday only)" : "(RT average per window)";
  panel.classList.add("visible");
}

function avgField(hoursObj, field) {
  if (!hoursObj) return null;
  const vals = Object.values(hoursObj).map((h) => h[field]).filter((v) => v !== null && v !== undefined);
  if (vals.length === 0) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

// ── Tab 2: Node search + autocomplete ────────────────────────────────────────

async function resolveAndRenderLocation(query) {
  const status = document.getElementById("nodeSearchStatus");
  if (!query) return;

  const knownPoints = [...Object.keys(REPORT_DATA?.hub_prices || {}), ...Object.keys(REPORT_DATA?.load_zone_prices || {})];
  const bareMatch = knownPoints.find((h) => {
    const bare = h.replace(/^(HB_|LZ_)/, "").toLowerCase();
    return h.toLowerCase() === query.toLowerCase() || bare === query.toLowerCase();
  });
  const exactCode = query.toUpperCase();
  const match = bareMatch || (getPointSeries(exactCode) ? exactCode : null);

  if (match) {
    document.getElementById("hubSelect").value = match;
    renderReferencePoint(match);
    if (status) status.textContent = "";
    return;
  }

  if (status) status.textContent = "Looking up…";

  // Already backfilled from a previous search (by anyone, any session)?
  // Check the static file before ever calling the live Function — this is
  // just a normal cached static-asset fetch, no Function invocation, no
  // ERCOT call, and it has full multi-window history once it exists.
  try {
    const res = await fetch(`data/nodes/${encodeURIComponent(exactCode)}.json`);
    if (res.ok) {
      const nodeData = await res.json();
      BACKFILLED_NODE_CACHE[nodeData.node] = nodeData;
      if (status) status.textContent = `${nodeData.node} — full history available (updated through ${nodeData.last_updated})`;
      renderReferencePoint(nodeData.node);
      return;
    }
  } catch (err) {
    // fall through to the live lookup below
  }

  // Not a hub or load zone already in the daily pull, and not yet backfilled
  // — go to the live per-node Function for an immediate single-day answer.
  // That Function also triggers a one-time backfill in the background, so a
  // repeat search for this same node later on will hit the branch above
  // instead and get full history.
  try {
    const res = await fetch(`/node-lookup?node=${encodeURIComponent(query)}`);
    const result = await res.json();
    if (!res.ok) throw new Error(result.error || `Lookup failed (${res.status})`);

    LIVE_NODE_CACHE[result.node] = result.days;
    if (result.tb) LIVE_NODE_TB_CACHE[result.node] = result.tb;
    if (status) status.textContent = `Showing live lookup for ${result.node} (not in the daily pull yet — full history will be available on a future visit)`;
    renderReferencePoint(result.node);
  } catch (err) {
    if (status) status.textContent = err.message || "Lookup failed.";
    console.error(err);
  }
}

document.getElementById("nodeSearchBtn")?.addEventListener("click", () => {
  const raw = document.getElementById("nodeSearchInput").value.trim();
  hideLocationSuggestions();
  if (raw) resolveAndRenderLocation(raw);
});

const nodeSearchInput = document.getElementById("nodeSearchInput");
const nodeSearchSuggestions = document.getElementById("nodeSearchSuggestions");

nodeSearchInput?.addEventListener("input", () => {
  const suggestions = typeof getLocationSuggestions === "function" ? getLocationSuggestions(nodeSearchInput.value) : [];
  renderLocationSuggestions(suggestions);
});

nodeSearchInput?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    document.getElementById("nodeSearchBtn").click();
  } else if (e.key === "Escape") {
    hideLocationSuggestions();
  }
});

nodeSearchSuggestions?.addEventListener("click", (e) => {
  const item = e.target.closest(".suggestion-item");
  if (!item) return;
  const code = item.dataset.code;
  nodeSearchInput.value = "";
  hideLocationSuggestions();
  resolveAndRenderLocation(code);
});

document.addEventListener("click", (e) => {
  if (!e.target.closest(".search-input-wrap")) hideLocationSuggestions();
});

function renderLocationSuggestions(list) {
  if (!nodeSearchSuggestions) return;
  if (!list || list.length === 0) {
    hideLocationSuggestions();
    return;
  }
  nodeSearchSuggestions.innerHTML = list
    .map((entry) => `<div class="suggestion-item" data-code="${entry.code}"><span>${entry.name}</span><span class="null-value">${entry.code}</span></div>`)
    .join("");
  nodeSearchSuggestions.classList.add("visible");
}

function hideLocationSuggestions() {
  if (!nodeSearchSuggestions) return;
  nodeSearchSuggestions.innerHTML = "";
  nodeSearchSuggestions.classList.remove("visible");
}

// ── Tab 2: Ancillary services section (segmented service selector + chart) ──

let asChart = null;

function populateAsTypeSelector(asPrices) {
  const selector = document.getElementById("asTypeSelector");
  if (!selector) return;
  selector.innerHTML = "";

  const types = AS_TYPE_ORDER.filter((t) => asPrices?.[t]);
  currentAsType = currentAsType && types.includes(currentAsType) ? currentAsType : (types[0] || null);

  for (const type of types) {
    const btn = document.createElement("button");
    btn.textContent = AS_TYPE_LABELS[type] || type;
    btn.dataset.asType = type;
    if (type === currentAsType) btn.classList.add("active");
    btn.addEventListener("click", () => {
      currentAsType = type;
      selector.querySelectorAll("button").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      renderAsSection(asPrices);
    });
    selector.appendChild(btn);
  }
}

function renderAsSection(asPrices) {
  const dateLabel = document.getElementById("asPriceDate");
  const canvas = document.getElementById("asHourlyChart");

  const types = AS_TYPE_ORDER.filter((t) => asPrices?.[t]);
  if (types.length === 0 || !currentAsType) {
    if (dateLabel) dateLabel.textContent = "";
    setChartVisible(canvas, false, "No ancillary services data available.");
    renderPeakSummary("asPeakSummary", null);
    return;
  }

  const day = latestDateKey(asPrices[currentAsType]);
  if (!day) {
    setChartVisible(canvas, false, `No data for ${AS_TYPE_LABELS[currentAsType] || currentAsType}.`);
    renderPeakSummary("asPeakSummary", null);
    return;
  }
  if (dateLabel) dateLabel.textContent = `Most recent available day: ${day}`;
  setChartVisible(canvas, true);
  const hours = asPrices[currentAsType][day];
  asChart = renderHourlyTimeSeriesChart(canvas, asChart, hours);
  renderPeakSummary("asPeakSummary", hours);
}

// ── Tab 3: AI recap ──────────────────────────────────────────────────────────

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function renderAiRecap(aiRecap, generatedAt) {
  const dateEl = document.getElementById("aiRecapDate");
  const textEl = document.getElementById("aiRecapText");
  if (!textEl) return;

  if (!aiRecap) {
    if (dateEl) dateEl.textContent = "Recap not yet available";
    textEl.innerHTML = "<p>AI-generated market recap isn't wired up yet for this deployment. This section will summarize yesterday's market, how well it was forecast, and what's ahead once pipeline/ai_narrative.py is generating recaps for this deployment.</p>";
    return;
  }
  if (dateEl) dateEl.textContent = generatedAt ? `Generated ${formatTimestamp(generatedAt)}` : "";

  // Split on blank lines so multi-paragraph recaps actually render as
  // separate paragraphs — plain .textContent collapses "\n\n" to nothing
  // visually. Falls back to one paragraph if the model didn't include any
  // blank lines at all. Escaped since this is free-form model-authored text,
  // not our own computed values like everywhere else in this file.
  const paragraphs = aiRecap.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);
  textEl.innerHTML = paragraphs.map((p) => `<p>${escapeHtml(p)}</p>`).join("");
}

// ── Load + render everything ────────────────────────────────────────────────

async function loadReport() {
  try {
    const res = await fetch("data/latest.json");
    REPORT_DATA = await res.json();

    document.getElementById("product-name").textContent = REPORT_DATA.display_name || "ERCOT Market Overview";
    const reportDateEl = document.getElementById("report-date");
    if (reportDateEl) reportDateEl.textContent = REPORT_DATA.generated_at ? `Generated ${formatTimestamp(REPORT_DATA.generated_at)}` : "";

    renderNetLoadChart(REPORT_DATA.net_load);
    renderHubCards(REPORT_DATA.hub_windows);
    populateHubSelect();
    renderReferencePoint(document.getElementById("hubSelect")?.value);
    populateAsTypeSelector(REPORT_DATA.as_prices);
    renderAsSection(REPORT_DATA.as_prices);
    renderAiRecap(REPORT_DATA.ai_recap, REPORT_DATA.generated_at);
  } catch (err) {
    console.error("Failed to load report data:", err);
    const el = document.getElementById("product-name");
    if (el) el.textContent = "ERCOT Market Overview — data unavailable";
  }
}

loadReport();
