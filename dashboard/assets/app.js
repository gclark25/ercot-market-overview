// Structural scaffold only — tab switching + wiring to a placeholder data
// shape. Real chart rendering / table population is the frontend build pass.

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
  });
});

async function loadReport() {
  try {
    const res = await fetch("data/latest.json");
    const data = await res.json();
    document.getElementById("product-name").textContent = data.display_name || "ERCOT Market Overview";
    // TODO: populate netLoadChart (Chart.js), hubWindowsTable, hourlyPriceTable,
    // asPriceTable, and aiRecapText from `data` once pipeline/*.py produce it.
  } catch (err) {
    console.error("Failed to load report data:", err);
  }
}

// TODO: wire to functions/node-lookup.js once implemented.
document.getElementById("nodeSearchBtn").addEventListener("click", async () => {
  const node = document.getElementById("nodeSearchInput").value.trim();
  const status = document.getElementById("nodeSearchStatus");
  if (!node) return;
  status.textContent = "Looking up…";
  try {
    const res = await fetch(`/node-lookup?node=${encodeURIComponent(node)}&window=yesterday`);
    if (!res.ok) throw new Error(`Lookup failed (${res.status})`);
    const result = await res.json();
    status.textContent = "";
    console.log("Node lookup result:", result); // TODO: render into hourlyPriceTable
  } catch (err) {
    status.textContent = "Lookup failed — check node name.";
    console.error(err);
  }
});

loadReport();
