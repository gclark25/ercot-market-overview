// Renders dashboard/data/latest.json into the 3 tabs. See README for the
// data shapes this expects (they come from pipeline/build_report.py).

let REPORT_DATA = null;
let netLoadChart = null;

const WINDOW_ORDER = ["yesterday", "3day", "mtd", "ytd"];
const WINDOW_LABELS = { yesterday: "Yesterday", "3day": "Last 3 Days", mtd: "Month to Date", ytd: "Year to Date" };
const AS_TYPE_ORDER = ["REGUP", "REGDN", "RRS", "NSPIN", "ECRS"];
const AS_TYPE_LABELS = { REGUP: "Reg-Up", REGDN: "Reg-Down", RRS: "RRS", NSPIN: "Non-Spin", ECRS: "ECRS" };

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

function fmtPct(v) {
  return v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`;
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

function prettifyHub(hub) {
  if (hub === "HB_BUSAVG") return "Bus Average";
  return hub.replace(/^HB_/, "").replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
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
    canvas.replaceWith(Object.assign(document.createElement("p"), {
      className: "report-date",
      textContent: "No net load data available for this report.",
      id: "netLoadChart",
    }));
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

// ── Tab 1: Hub DA/RT performance table ──────────────────────────────────────

function renderHubWindowsTable(hubWindows) {
  const tbody = document.querySelector("#hubWindowsTable tbody");
  if (!tbody) return;
  tbody.innerHTML = "";

  const hubs = Object.keys(hubWindows || {});
  if (hubs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-secondary);padding:16px">No hub price data available.</td></tr>`;
    return;
  }

  for (const hub of hubs) {
    for (const window of WINDOW_ORDER) {
      const stats = hubWindows[hub]?.[window];
      if (!stats) continue;
      tbody.appendChild(buildHubRow(hub, window, "Overall", stats.overall, ""));
      tbody.appendChild(buildHubRow(hub, window, "On-Peak", stats.on_peak, "peak-detail-row peak-on"));
      tbody.appendChild(buildHubRow(hub, window, "Off-Peak", stats.off_peak, "peak-detail-row peak-off"));
    }
  }
}

function buildHubRow(hub, window, peakLabelText, stats, extraClass) {
  const tr = document.createElement("tr");
  if (extraClass) tr.className = extraClass;
  const s = stats || {};
  tr.innerHTML = `
    <td>${prettifyHub(hub)}</td>
    <td>${WINDOW_LABELS[window]}</td>
    <td class="peak-cell">${peakLabelText}${s.hour_count ? ` <span class="null-value">(${s.hour_count}h)</span>` : ""}</td>
    <td>${fmtMoney(s.avg_da)}</td>
    <td>${fmtMoney(s.avg_rt)}</td>
    <td class="${dartClass(s.dart_spread)}">${fmtMoney(s.dart_spread)} <span class="null-value">${fmtPct(s.dart_spread_pct)}</span></td>
    <td>${fmtNum(s.rt_volatility)}</td>
  `;
  return tr;
}

document.getElementById("peakBreakdownToggle")?.addEventListener("change", (e) => {
  document.getElementById("hubWindowsTable")?.classList.toggle("show-peak-detail", e.target.checked);
});

// ── Tab 2: Hub selector + hourly energy price table ─────────────────────────

function populateHubSelect(hubPrices) {
  const select = document.getElementById("hubSelect");
  if (!select) return;
  select.innerHTML = "";
  for (const hub of Object.keys(hubPrices || {})) {
    const opt = document.createElement("option");
    opt.value = hub;
    opt.textContent = prettifyHub(hub);
    select.appendChild(opt);
  }
  if (hubPrices?.HB_BUSAVG) select.value = "HB_BUSAVG";
}

function renderHourlyPriceTable(hubKey) {
  const tbody = document.querySelector("#hourlyPriceTable tbody");
  const dateLabel = document.getElementById("hourlyPriceDate");
  if (!tbody) return;
  tbody.innerHTML = "";

  const hubDays = REPORT_DATA?.hub_prices?.[hubKey];
  const day = latestDateKey(hubDays);
  if (!day) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--text-secondary);padding:16px">No price data for this node.</td></tr>`;
    if (dateLabel) dateLabel.textContent = "";
    return;
  }
  if (dateLabel) dateLabel.textContent = `${prettifyHub(hubKey)} — most recent available day: ${day}`;

  const hours = hubDays[day];
  for (const he of Object.keys(hours).sort((a, b) => Number(a) - Number(b))) {
    const h = hours[he];
    const tr = document.createElement("tr");
    tr.className = h.peak === "on" ? "peak-on" : "peak-off";
    tr.innerHTML = `
      <td>HE${he}</td>
      <td class="peak-cell">${peakLabel(h.peak)}</td>
      <td>${fmtMoney(h.da)}</td>
      <td>${fmtMoney(h.rt)}</td>
      <td class="${dartClass(h.dart)}">${fmtMoney(h.dart)}</td>
    `;
    tbody.appendChild(tr);
  }
}

document.getElementById("hubSelect")?.addEventListener("change", (e) => renderHourlyPriceTable(e.target.value));

document.getElementById("nodeSearchBtn")?.addEventListener("click", async () => {
  const raw = document.getElementById("nodeSearchInput").value.trim();
  const status = document.getElementById("nodeSearchStatus");
  if (!raw) return;

  const knownHubs = Object.keys(REPORT_DATA?.hub_prices || {});
  const match = knownHubs.find((h) => h.toLowerCase() === raw.toLowerCase() || h.toLowerCase() === `hb_${raw.toLowerCase()}`);
  if (match) {
    document.getElementById("hubSelect").value = match;
    renderHourlyPriceTable(match);
    status.textContent = "";
    return;
  }

  // Not one of the hubs already in the daily pull — fall back to the live
  // per-node lookup Function (still a stub as of this build; expect this
  // branch to fail until functions/node-lookup.js is implemented).
  status.textContent = "Looking up…";
  try {
    const res = await fetch(`/node-lookup?node=${encodeURIComponent(raw)}&window=yesterday`);
    if (!res.ok) throw new Error(`Lookup failed (${res.status})`);
    const result = await res.json();
    status.textContent = "";
    console.log("Node lookup result:", result); // TODO: render into hourlyPriceTable once node-lookup.js is real
  } catch (err) {
    status.textContent = "Lookup failed — check the node name, or pick a hub from the dropdown.";
    console.error(err);
  }
});

// ── Tab 2: Ancillary services table ─────────────────────────────────────────

function renderAsPriceTable(asPrices) {
  const tbody = document.querySelector("#asPriceTable tbody");
  const dateLabel = document.getElementById("asPriceDate");
  if (!tbody) return;
  tbody.innerHTML = "";

  const types = Object.keys(asPrices || {});
  if (types.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--text-secondary);padding:16px">No ancillary services data available.</td></tr>`;
    if (dateLabel) dateLabel.textContent = "";
    return;
  }

  // All AS types are pulled over the same date range, but find the latest
  // day per type defensively rather than assuming they're all identical.
  const latestPerType = {};
  for (const t of types) latestPerType[t] = latestDateKey(asPrices[t]);
  const day = Object.values(latestPerType).filter(Boolean).sort().slice(-1)[0];
  if (!day) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--text-secondary);padding:16px">No ancillary services data available.</td></tr>`;
    return;
  }
  if (dateLabel) dateLabel.textContent = `Most recent available day: ${day}`;

  for (let he = 1; he <= 24; he++) {
    for (const type of AS_TYPE_ORDER) {
      const h = asPrices[type]?.[day]?.[String(he)];
      if (!h) continue;
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
    renderHubWindowsTable(REPORT_DATA.hub_windows);
    populateHubSelect(REPORT_DATA.hub_prices);
    renderHourlyPriceTable(document.getElementById("hubSelect")?.value);
    renderAsPriceTable(REPORT_DATA.as_prices);
    renderAiRecap(REPORT_DATA.ai_recap, REPORT_DATA.generated_at);
  } catch (err) {
    console.error("Failed to load report data:", err);
    const el = document.getElementById("product-name");
    if (el) el.textContent = "ERCOT Market Overview — data unavailable";
  }
}

loadReport();
