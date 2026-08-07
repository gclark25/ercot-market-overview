// Renders dashboard/data/latest.json into the 3 tabs. See README for the
// data shapes this expects (they come from pipeline/build_report.py).

let REPORT_DATA = null;
let netLoadChart = null;
let currentWindow = "yesterday";
let currentAsType = null;

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
  const sign = v >= 0 ? "+" : "";
  return `${sign}$${v.toFixed(2)}`;
}

function fmtNum(v, decimals = 2) {
  return v === null || v === undefined ? "—" : v.toFixed(decimals);
}

function dartClass(v) {
  if (v === null || v === undefined) return "null-value";
  return v >= 0 ? "dart-positive" : "dart-negative";
}

function peakLabel(p) {
  return p === "on" ? "On" : p === "off" ? "Off" : "—";
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
    hour: "numeric", minute: "2-digit", timeZone: "UTC", timeZoneName: "short",
  });
}

function latestDateKey(daysObj) {
  const keys = Object.keys(daysObj || {});
  if (keys.length === 0) return null;
  return keys.sort()[keys.length - 1];
}

// ── Tab 1: Net load chart ───────────────────────────────────────────────────

function buildNetLoadSeries(netLoad) {
  const history = netLoad?.history || {};
  const forecast = netLoad?.forecast || {};
  const points = [];

  for (const day of Object.keys(history).sort()) {
    for (const he of Object.keys(history[day]).sort((a, b) => Number(a) - Number(b))) {
      points.push({ day, he, kind: "history", ...history[day][he] });
    }
  }
  const boundaryIndex = points.length - 1;
  for (const day of Object.keys(forecast).sort()) {
    for (const he of Object.keys(forecast[day]).sort((a, b) => Number(a) - Number(b))) {
      points.push({ day, he, kind: "forecast", ...forecast[day][he] });
    }
  }

  return { points, boundaryIndex };
}

function renderNetLoadChart(netLoad) {
  const canvas = document.getElementById("netLoadChart");
  if (!canvas || typeof Chart === "undefined") return;

  const { points, boundaryIndex } = buildNetLoadSeries(netLoad);
  if (points.length === 0) {
    canvas.parentElement.innerHTML = '<p class="report-date">No net load data available for this report.</p>';
    return;
  }

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
    for (const scope of [s?.on_peak, s?.off_peak]) {
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
      <div>RT Vol.<strong>${fmtNum(o.rt_volatility)}</strong></div>
    </div>
    <div class="hub-card-spread ${dartClass(o.dart_spread)}">${fmtSignedMoney(o.dart_spread)} DART</div>
    <div class="peak-bars">
      ${buildPeakBarRow("On-Peak", stats.on_peak, maxAbsSpread)}
      ${buildPeakBarRow("Off-Peak", stats.off_peak, maxAbsSpread)}
    </div>
  `;
  return card;
}

function buildPeakBarRow(label, scope, maxAbsSpread) {
  const v = scope?.dart_spread;
  const pct = v === null || v === undefined ? 0 : Math.min(100, (Math.abs(v) / maxAbsSpread) * 100);
  const color = v >= 0 ? SAGE_RGB : CLAY_RGB;
  // Bar grows from the center: positive to the right half, negative to the left half.
  const fillStyle = v >= 0
    ? `left:50%; width:${pct / 2}%; background:rgb(${color});`
    : `right:50%; width:${pct / 2}%; background:rgb(${color});`;
  return `
    <div class="peak-bar-row">
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
  return REPORT_DATA?.hub_prices?.[key] || REPORT_DATA?.load_zone_prices?.[key] || null;
}

function renderReferencePoint(key) {
  renderHourlyPriceTable(key);
  renderBasisPanel(key);
}

document.getElementById("hubSelect")?.addEventListener("change", (e) => renderReferencePoint(e.target.value));

// ── Tab 2: Hourly energy price table + heatmap ──────────────────────────────

function renderHourlyPriceTable(key) {
  const tbody = document.querySelector("#hourlyPriceTable tbody");
  const dateLabel = document.getElementById("hourlyPriceDate");
  const heatmap = document.getElementById("hourlyDartHeatmap");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (heatmap) heatmap.innerHTML = "";

  const days = getPointSeries(key);
  const day = latestDateKey(days);
  if (!day) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--text-secondary);padding:16px">No price data for this node.</td></tr>`;
    if (dateLabel) dateLabel.textContent = "";
    return;
  }
  if (dateLabel) dateLabel.textContent = `${prettifyPoint(key)} — most recent available day: ${day}`;

  const hours = days[day];
  const cells = [];
  for (const he of Object.keys(hours).sort((a, b) => Number(a) - Number(b))) {
    const h = hours[he];
    cells.push({ value: h.dart, title: `HE${he}: ${fmtSignedMoney(h.dart)}` });

    const tr = document.createElement("tr");
    tr.className = h.peak === "on" ? "peak-on" : "peak-off";
    tr.innerHTML = `
      <td>HE${he}</td>
      <td>${peakLabel(h.peak)}</td>
      <td>${fmtMoney(h.da)}</td>
      <td>${fmtMoney(h.rt)}</td>
      <td class="${dartClass(h.dart)}">${fmtMoney(h.dart)}</td>
    `;
    tbody.appendChild(tr);
  }
  if (heatmap) renderHeatmapCells(heatmap, cells);
}

function renderHeatmapCells(container, cells) {
  container.innerHTML = "";
  const maxAbs = Math.max(1, ...cells.map((c) => Math.abs(c.value ?? 0)));
  for (const c of cells) {
    const div = document.createElement("div");
    div.className = "heatmap-cell";
    if (c.value === null || c.value === undefined) {
      div.style.background = "#232323";
    } else {
      const intensity = Math.min(1, Math.abs(c.value) / maxAbs);
      const alpha = 0.15 + intensity * 0.75;
      const color = c.value >= 0 ? SAGE_RGB : CLAY_RGB;
      div.style.background = `rgba(${color},${alpha.toFixed(2)})`;
    }
    div.title = c.title;
    container.appendChild(div);
  }
}

// ── Tab 2: Basis panel (node price - hub price, per hub) ────────────────────

function renderBasisPanel(key) {
  const panel = document.getElementById("basisPanel");
  const dateEl = document.getElementById("basisPanelDate");
  const rowsEl = document.getElementById("basisPanelRows");
  if (!panel || !rowsEl) return;

  const ownDays = getPointSeries(key);
  const day = latestDateKey(ownDays);
  const hubPrices = REPORT_DATA?.hub_prices || {};
  const otherHubs = Object.keys(hubPrices).filter((h) => h !== key);

  if (!day || otherHubs.length === 0) {
    panel.classList.remove("visible");
    return;
  }

  const ownHours = ownDays[day];
  const ownAvgRt = avgField(ownHours, "rt");
  if (ownAvgRt === null) {
    panel.classList.remove("visible");
    return;
  }

  rowsEl.innerHTML = "";
  for (const hub of otherHubs) {
    const hubHours = hubPrices[hub]?.[day];
    const hubAvgRt = avgField(hubHours, "rt");
    const basis = hubAvgRt === null ? null : ownAvgRt - hubAvgRt;
    const row = document.createElement("div");
    row.className = "basis-row";
    row.innerHTML = `<span>vs ${prettifyPoint(hub)}</span><span class="${dartClass(basis)}">${fmtSignedMoney(basis)}</span>`;
    rowsEl.appendChild(row);
  }
  if (dateEl) dateEl.textContent = `(RT, avg for ${day})`;
  panel.classList.add("visible");
}

function avgField(hoursObj, field) {
  if (!hoursObj) return null;
  const vals = Object.values(hoursObj).map((h) => h[field]).filter((v) => v !== null && v !== undefined);
  if (vals.length === 0) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

// ── Tab 2: Node search ───────────────────────────────────────────────────────

document.getElementById("nodeSearchBtn")?.addEventListener("click", async () => {
  const raw = document.getElementById("nodeSearchInput").value.trim();
  const status = document.getElementById("nodeSearchStatus");
  if (!raw) return;

  const knownPoints = [...Object.keys(REPORT_DATA?.hub_prices || {}), ...Object.keys(REPORT_DATA?.load_zone_prices || {})];
  const match = knownPoints.find((h) => {
    const bare = h.replace(/^(HB_|LZ_)/, "").toLowerCase();
    return h.toLowerCase() === raw.toLowerCase() || bare === raw.toLowerCase();
  });
  if (match) {
    document.getElementById("hubSelect").value = match;
    renderReferencePoint(match);
    status.textContent = "";
    return;
  }

  // Not a hub or load zone already in the daily pull — falls back to the
  // live per-node lookup Function, which is still a stub as of this build.
  // Basis-vs-hub for arbitrary searched nodes depends on that Function being
  // real; expect this branch to fail until functions/node-lookup.js is implemented.
  status.textContent = "Looking up…";
  try {
    const res = await fetch(`/node-lookup?node=${encodeURIComponent(raw)}&window=yesterday`);
    if (!res.ok) throw new Error(`Lookup failed (${res.status})`);
    const result = await res.json();
    status.textContent = "";
    console.log("Node lookup result:", result); // TODO: render into hourlyPriceTable + basisPanel once node-lookup.js is real
  } catch (err) {
    status.textContent = "Lookup failed — that node isn't in the daily pull yet. Try a hub or load zone from the dropdown.";
    console.error(err);
  }
});

// ── Tab 2: Ancillary services heatmap strips + table ────────────────────────

function renderAsSection(asPrices) {
  const stripsContainer = document.getElementById("asHeatmapStrips");
  const dateLabel = document.getElementById("asPriceDate");
  if (!stripsContainer) return;
  stripsContainer.innerHTML = "";

  const types = AS_TYPE_ORDER.filter((t) => asPrices?.[t]);
  if (types.length === 0) {
    if (dateLabel) dateLabel.textContent = "";
    document.querySelector("#asPriceTable tbody").innerHTML =
      `<tr><td colspan="5" style="text-align:center;color:var(--text-secondary);padding:16px">No ancillary services data available.</td></tr>`;
    return;
  }

  const day = types.map((t) => latestDateKey(asPrices[t])).filter(Boolean).sort().slice(-1)[0];
  if (dateLabel) dateLabel.textContent = day ? `Most recent available day: ${day} — click a strip to see exact hourly values` : "";

  for (const type of types) {
    const hours = asPrices[type]?.[day] || {};
    const wrap = document.createElement("div");
    wrap.className = "heatmap-strip-wrap";
    wrap.innerHTML = `<div class="heatmap-strip-label"><span>${AS_TYPE_LABELS[type]}</span></div>`;
    const strip = document.createElement("div");
    strip.className = "heatmap-strip";
    strip.dataset.asType = type;
    if (type === currentAsType) strip.classList.add("selected");

    const cells = [];
    for (let he = 1; he <= 24; he++) {
      const h = hours[String(he)];
      cells.push({ value: h?.dart ?? null, title: `HE${he}: ${h ? fmtSignedMoney(h.dart) : "no data"}` });
    }
    renderHeatmapCells(strip, cells);
    strip.addEventListener("click", () => {
      currentAsType = type;
      document.querySelectorAll("#asHeatmapStrips .heatmap-strip").forEach((s) => s.classList.remove("selected"));
      strip.classList.add("selected");
      renderAsPriceTableForType(asPrices, type, day);
    });

    wrap.appendChild(strip);
    stripsContainer.appendChild(wrap);
  }

  currentAsType = currentAsType && types.includes(currentAsType) ? currentAsType : types[0];
  document.querySelector(`#asHeatmapStrips .heatmap-strip[data-as-type="${currentAsType}"]`)?.classList.add("selected");
  renderAsPriceTableForType(asPrices, currentAsType, day);
}

function renderAsPriceTableForType(asPrices, type, day) {
  const tbody = document.querySelector("#asPriceTable tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  const hours = asPrices?.[type]?.[day];
  if (!hours) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--text-secondary);padding:16px">No data for ${AS_TYPE_LABELS[type] || type} on ${day}.</td></tr>`;
    return;
  }
  for (const he of Object.keys(hours).sort((a, b) => Number(a) - Number(b))) {
    const h = hours[he];
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>HE${he}</td>
      <td>${AS_TYPE_LABELS[type] || type}</td>
      <td>${fmtMoney(h.da)}</td>
      <td>${fmtMoney(h.rt)}</td>
      <td class="${dartClass(h.dart)}">${fmtMoney(h.dart)}</td>
    `;
    tbody.appendChild(tr);
  }
}

// ── Tab 3: AI recap ──────────────────────────────────────────────────────────

function renderAiRecap(aiRecap, generatedAt) {
  const dateEl = document.getElementById("aiRecapDate");
  const textEl = document.getElementById("aiRecapText");
  if (!textEl) return;

  if (!aiRecap) {
    if (dateEl) dateEl.textContent = "Recap not yet available";
    textEl.textContent = "AI-generated market recap isn't wired up yet for this deployment. This section will summarize yesterday, the last 3 days, month-to-date, and year-to-date market conditions once pipeline/ai_narrative.py is implemented.";
    return;
  }
  if (dateEl) dateEl.textContent = generatedAt ? `Generated ${formatTimestamp(generatedAt)}` : "";
  textEl.textContent = aiRecap;
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
    renderAsSection(REPORT_DATA.as_prices);
    renderAiRecap(REPORT_DATA.ai_recap, REPORT_DATA.generated_at);
  } catch (err) {
    console.error("Failed to load report data:", err);
    const el = document.getElementById("product-name");
    if (el) el.textContent = "ERCOT Market Overview — data unavailable";
  }
}

loadReport();
