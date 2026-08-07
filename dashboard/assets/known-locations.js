// Curated, hand-verified list of ERCOT hubs and load zones for the Tab 2
// search autocomplete. Deliberately NOT an attempt to cover every ERCOT
// settlement point (there are thousands of resource nodes) — that would
// need pulling ERCOT's full Settlement Points List, which lives on their
// older MIS report portal (a different, unconfirmed access pattern from
// the api.ercot.com/public-reports API this project already uses). This
// list instead covers what a non-expert is actually likely to type: the
// major hubs and all 8 real ERCOT load zones, by common name.
//
// Anything not in this list still works if you know the exact ERCOT
// settlement point code — it just won't show up as you type.

const KNOWN_LOCATIONS = [
  { code: "HB_HOUSTON", name: "Houston Hub", aliases: ["houston", "houston hub", "coast"] },
  { code: "HB_NORTH", name: "North Hub", aliases: ["north", "north hub", "dfw", "dallas", "fort worth"] },
  { code: "HB_SOUTH", name: "South Hub", aliases: ["south", "south hub"] },
  { code: "HB_WEST", name: "West Hub", aliases: ["west", "west hub", "permian", "west texas"] },
  { code: "HB_BUSAVG", name: "Bus Average", aliases: ["bus average", "average", "ercot average"] },
  { code: "LZ_HOUSTON", name: "Houston Load Zone", aliases: ["houston zone", "houston load zone"] },
  { code: "LZ_NORTH", name: "North Load Zone", aliases: ["north zone", "north load zone"] },
  { code: "LZ_SOUTH", name: "South Load Zone", aliases: ["south zone", "south load zone"] },
  { code: "LZ_WEST", name: "West Load Zone", aliases: ["west zone", "west load zone"] },
  // These 4 are NOT in the daily pull (see configs/_template.yaml) — selecting
  // one of these always goes through the live node-lookup Function.
  { code: "LZ_AEN", name: "Austin Energy Zone", aliases: ["austin", "austin energy", "aen"] },
  { code: "LZ_CPS", name: "CPS Energy Zone (San Antonio)", aliases: ["san antonio", "cps", "cps energy"] },
  { code: "LZ_LCRA", name: "LCRA Zone", aliases: ["lcra", "lower colorado river authority"] },
  { code: "LZ_RAYBN", name: "Rayburn Zone", aliases: ["rayburn", "raybn", "rayburn country"] },
];

function locationMatchScore(query, entry) {
  const q = query.toLowerCase();
  const candidates = [entry.code, entry.name, ...entry.aliases].map((s) => s.toLowerCase());
  let best = 0;
  for (const c of candidates) {
    if (c === q) best = Math.max(best, 100);
    else if (c.startsWith(q)) best = Math.max(best, 80);
    else if (c.includes(q)) best = Math.max(best, 50);
  }
  return best;
}

function getLocationSuggestions(query, limit = 6) {
  if (!query || query.trim().length < 2) return [];
  return KNOWN_LOCATIONS
    .map((entry) => ({ entry, score: locationMatchScore(query.trim(), entry) }))
    .filter((r) => r.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map((r) => r.entry);
}
