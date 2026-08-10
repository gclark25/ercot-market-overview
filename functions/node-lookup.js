/**
 * Cloudflare Pages Function: GET /node-lookup?node=<settlement_point>
 *
 * Live on-demand DA/RT/DART lookup for any ERCOT settlement point not already
 * baked into the daily static JSON (i.e. not one of the configured hubs or
 * load zones). Called by the Tab 2 search box when a search doesn't match
 * something already in dashboard/data/latest.json.
 *
 * This is a genuinely separate implementation from the Python pipeline, not
 * a port: it runs on Cloudflare's Workers runtime (fetch-based JS) at
 * request time, once per search, rather than once a day in GitHub Actions.
 * The auth flow and report endpoints are the same ones confirmed working in
 * hen-morning-report/hen_morning_report.py (get_token/ercot_get) and this
 * repo's pipeline/ercot_client.py — only the runtime differs.
 *
 * Scope, deliberately kept narrow: single most-recent-available day only
 * (matches what the dashboard already shows for hubs/load zones — see
 * renderEnergySection in app.js), not a full YTD pull. A day of RT (15-min,
 * ~96 rows) or DA (hourly, 24 rows) for one settlement point is small enough
 * that no pagination is needed here, unlike the YTD pipeline pulls.
 *
 * Env vars required (set as Cloudflare Pages project environment variables/
 * secrets in the Cloudflare dashboard — Settings > Environment variables —
 * NOT the GitHub Actions secrets, which are a separate configuration
 * surface and don't carry over here):
 *   ERCOT_API_USERNAME, ERCOT_API_PASSWORD, ERCOT_SUBSCRIPTION_KEY
 *   GITHUB_DISPATCH_TOKEN — optional but recommended: a GitHub token with
 *     permission to trigger repository_dispatch on this repo. When set,
 *     every successful lookup for a node NOT already in the daily pull
 *     fires a "backfill-node" dispatch event (see
 *     .github/workflows/node-backfill.yml), which does a one-time full YTD
 *     pull for that node and commits it to dashboard/data/nodes/<NODE>.json.
 *     From then on, that node behaves like a hub — full window support,
 *     served as a static file, no live ERCOT call needed. Without this var
 *     set, live lookups still work exactly as before; they just never
 *     graduate beyond single-day answers.
 */

const BASE_URL = "https://api.ercot.com/api/public-reports";
const AUTH_URL =
  "https://ercotb2c.b2clogin.com/ercotb2c.onmicrosoft.com/B2C_1_PUBAPI-ROPC-FLOW" +
  "/oauth2/v2.0/token?username={u}&password={p}&grant_type=password" +
  "&scope=openid+fec253ea-0d06-4272-a5e6-b478baeecd70+offline_access" +
  "&client_id=fec253ea-0d06-4272-a5e6-b478baeecd70&response_type=id_token";
const GITHUB_REPO = "gclark25/ercot-market-overview"; // not sensitive, just identifies where to dispatch

const RESULT_CACHE_TTL_SECONDS = 900; // 15 min edge cache per node — repeated searches for
                                       // the same node don't re-hit ERCOT every time.
const TOKEN_CACHE_TTL_SECONDS = 45 * 60; // ERCOT's actual token TTL isn't confirmed anywhere
                                          // in this codebase — 45 min is a conservative guess.
                                          // If lookups start failing with 401s, this is the
                                          // first thing to check/shorten.
const BACKFILL_DEDUPE_TTL_SECONDS = 120; // don't fire a new dispatch for the same node within a
                                          // couple minutes of the last one — just enough to stop a
                                          // literal double-click from spamming two dispatches, without
                                          // blocking a genuine retry after a failed backfill. This
                                          // cache only knows a dispatch was SENT, not whether the
                                          // resulting workflow actually succeeded — confirmed in
                                          // production that a full 1-hour window left someone unable
                                          // to retry a node whose backfill had failed downstream.

export async function onRequestGet(context) {
  const { request, env } = context;
  const url = new URL(request.url);
  const node = (url.searchParams.get("node") || "").trim().toUpperCase();

  if (!node) {
    return jsonResponse({ error: "Missing required 'node' query param" }, 400);
  }
  if (!env.ERCOT_API_USERNAME || !env.ERCOT_API_PASSWORD || !env.ERCOT_SUBSCRIPTION_KEY) {
    // Fail with a clear message rather than a cryptic downstream fetch error —
    // this almost always means the Cloudflare Pages project's environment
    // variables haven't been set yet (see file header).
    return jsonResponse({ error: "Server misconfigured: ERCOT credentials not set on this Cloudflare Pages project." }, 500);
  }

  const cache = caches.default;
  const cacheKey = new Request(`https://internal-cache/node-lookup?node=${encodeURIComponent(node)}`);
  const cached = await cache.match(cacheKey);
  if (cached) return cached;

  let payload;
  try {
    const token = await getErcotToken(env);
    payload = await lookupNode(node, token, env);
  } catch (err) {
    return jsonResponse({ error: err.message || "Lookup failed" }, 502);
  }

  const response = jsonResponse(payload, 200, RESULT_CACHE_TTL_SECONDS);
  await cache.put(cacheKey, response.clone());

  // Fire-and-forget: schedule the backfill trigger to run after the response
  // is already on its way back, so it never adds latency to this search.
  context.waitUntil(triggerNodeBackfill(node, env));

  return response;
}

export async function triggerNodeBackfill(node, env) {
  if (!env.GITHUB_DISPATCH_TOKEN) return; // feature not configured — silently skip, live lookup still works fine on its own

  const cache = caches.default;
  const dedupeKey = new Request(`https://internal-cache/backfill-dispatch/${encodeURIComponent(node)}`);
  if (await cache.match(dedupeKey)) return; // already triggered recently, don't spam dispatches

  try {
    const res = await fetch(`https://api.github.com/repos/${GITHUB_REPO}/dispatches`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "ercot-market-overview-node-lookup",
      },
      body: JSON.stringify({ event_type: "backfill-node", client_payload: { node } }),
    });
    if (!res.ok) {
      console.error(`Backfill dispatch failed (${res.status}): ${await res.text()}`);
      return; // don't cache a dedupe marker for a failed dispatch — worth retrying on the next search
    }
    await cache.put(dedupeKey, new Response("1", { headers: { "Cache-Control": `public, max-age=${BACKFILL_DEDUPE_TTL_SECONDS}` } }));
  } catch (err) {
    console.error("Failed to trigger node backfill:", err);
  }
}

// ── Auth ──────────────────────────────────────────────────────────────────

async function getErcotToken(env) {
  const cache = caches.default;
  const tokenCacheKey = new Request("https://internal-cache/ercot-token");
  const cachedResp = await cache.match(tokenCacheKey);
  if (cachedResp) {
    const { token } = await cachedResp.json();
    return token;
  }

  const authUrl = AUTH_URL
    .replace("{u}", encodeURIComponent(env.ERCOT_API_USERNAME))
    .replace("{p}", encodeURIComponent(env.ERCOT_API_PASSWORD));

  const res = await fetch(authUrl, {
    method: "POST",
    headers: { "Ocp-Apim-Subscription-Key": env.ERCOT_SUBSCRIPTION_KEY },
  });
  if (!res.ok) throw new Error(`ERCOT auth failed (${res.status})`);
  const body = await res.json();
  const token = body.id_token || body.access_token;
  if (!token) throw new Error("ERCOT auth succeeded but no token in response");

  const tokenResponse = new Response(JSON.stringify({ token }), {
    headers: { "Content-Type": "application/json", "Cache-Control": `public, max-age=${TOKEN_CACHE_TTL_SECONDS}` },
  });
  await cache.put(tokenCacheKey, tokenResponse.clone());
  return token;
}

// ── ERCOT request + row parsing (ported from pipeline/ercot_client.py and
//    pipeline/market_data.py's extract_price_with_interval /
//    extract_da_price_with_hour — same column-position assumptions,
//    translated to JS) ────────────────────────────────────────────────────

async function ercotGetRaw(path, token, env, params) {
  const url = new URL(`${BASE_URL}/${path}`);
  url.searchParams.set("size", "1000");
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);

  const res = await fetch(url.toString(), {
    headers: {
      Authorization: `Bearer ${token}`,
      "Ocp-Apim-Subscription-Key": env.ERCOT_SUBSCRIPTION_KEY,
      Accept: "application/json",
    },
  });
  if (!res.ok) throw new Error(`${path} request failed (${res.status})`);
  const body = await res.json();
  if (Array.isArray(body)) return body;
  if (body.data) return body.data;
  for (const v of Object.values(body)) if (Array.isArray(v)) return v;
  return [];
}

// RT row: [deliveryDate, hour, interval, settlementPoint, type, price, ...]
export function extractRtPrice(row) {
  if (Array.isArray(row) && row.length >= 6) {
    const hour = parseInt(row[1], 10);
    const nums = row.filter((x) => typeof x === "number" && x !== 0);
    const price = nums.length ? nums[nums.length - 1] : null;
    return { hour: Number.isNaN(hour) ? null : hour, price };
  }
  return { hour: null, price: null };
}

// DA row: [deliveryDate, deliveryHour, settlementPoint, price, ...]
export function extractDaPrice(row) {
  if (Array.isArray(row) && row.length >= 4) {
    let hour;
    if (typeof row[1] === "string") hour = parseInt(row[1].split(":")[0], 10);
    else hour = row[1];
    const nums = row.slice(2).filter((x) => typeof x === "number");
    const price = nums.length ? nums[nums.length - 1] : null;
    return { hour: Number.isNaN(hour) ? null : hour, price };
  }
  return { hour: null, price: null };
}

// ── Peak calendar (ported from pipeline/peak_calendar.py — same rule:
//    Mon-Fri HE 7-22 = on-peak, everything else = off-peak) ────────────────

export function isOnPeak(dateUtc, he) {
  const weekday = dateUtc.getUTCDay(); // 0=Sun ... 6=Sat (JS convention, differs from
                                        // Python's Mon=0 — logic below is adjusted accordingly)
  if (weekday === 0 || weekday === 6) return false;
  return he >= 7 && he <= 22;
}

// ── Central-Time "yesterday" (search can happen at any time of day, unlike
//    the pipeline's fixed 07:15 CT run, so this needs to be timezone-aware
//    rather than a naive UTC date subtraction) ──────────────────────────────

export function centralTimeYesterday(now = new Date()) {
  const ctDateStr = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Chicago", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(now); // "MM/DD/YYYY"
  const [month, day, year] = ctDateStr.split("/").map(Number);
  const ctToday = new Date(Date.UTC(year, month - 1, day));
  ctToday.setUTCDate(ctToday.getUTCDate() - 1);
  return ctToday.toISOString().slice(0, 10);
}

function round2(n) {
  return Math.round(n * 100) / 100;
}

// ── Main lookup ──────────────────────────────────────────────────────────

export async function lookupNode(node, token, env) {
  const day = centralTimeYesterday();

  const [rtRows, daRows] = await Promise.all([
    ercotGetRaw("np6-905-cd/spp_node_zone_hub", token, env, { settlementPoint: node, deliveryDateFrom: day, deliveryDateTo: day }),
    ercotGetRaw("np4-190-cd/dam_stlmnt_pnt_prices", token, env, { settlementPoint: node, deliveryDateFrom: day, deliveryDateTo: day }),
  ]);

  const rtBuckets = {};
  for (const row of rtRows) {
    const { hour, price } = extractRtPrice(row);
    if (hour !== null && price !== null) (rtBuckets[hour] ||= []).push(price);
  }
  const rtByHour = {};
  for (const [hour, prices] of Object.entries(rtBuckets)) {
    rtByHour[hour] = prices.reduce((a, b) => a + b, 0) / prices.length;
  }

  const daByHour = {};
  for (const row of daRows) {
    const { hour, price } = extractDaPrice(row);
    if (hour !== null && price !== null) daByHour[hour] = price;
  }

  const hours = new Set([...Object.keys(rtByHour), ...Object.keys(daByHour)].map(Number));
  if (hours.size === 0) {
    throw new Error(`No price data found for "${node}" on ${day} — check that this is a valid ERCOT settlement point name.`);
  }

  const dateUtc = new Date(`${day}T00:00:00Z`);
  const hourData = {};
  for (const hr of [...hours].sort((a, b) => a - b)) {
    const da = daByHour[hr] ?? null;
    const rt = rtByHour[hr] ?? null;
    hourData[String(hr)] = {
      da,
      rt,
      dart: da !== null && rt !== null ? round2(da - rt) : null,
      peak: isOnPeak(dateUtc, hr) ? "on" : "off",
    };
  }

  // Shape matches hub_prices/load_zone_prices in latest.json — { date: { hour: {...} } } —
  // so the frontend can reuse the exact same rendering code path (getPointSeries, etc.)
  // rather than needing special-case handling for live-searched nodes.
  //
  // tb is deliberately single-day only (this Function never fetches more than
  // one day) — same per-metric hour thresholds as aggregations.py's
  // _daily_tb_values, so a live node's "yesterday" TB1/TB2/TB4 means exactly
  // the same thing as a hub/load-zone's "yesterday" TB1/TB2/TB4. There's no
  // 3-day/MTD/YTD equivalent for live-searched nodes without extending this
  // Function to pull (and paginate) a much wider date range — not done here.
  return { node, days: { [day]: hourData }, tb: computeDailyTb(hourData) };
}

export function computeDailyTb(hourData) {
  const rtVals = Object.values(hourData).map((h) => h.rt).filter((v) => v !== null && v !== undefined).sort((a, b) => a - b);
  const n = rtVals.length;
  const sum = (arr) => arr.reduce((a, b) => a + b, 0);
  return {
    tb1: n >= 2 ? round2((rtVals[n - 1] - rtVals[0]) / 24) : null,
    tb2: n >= 4 ? round2((sum(rtVals.slice(-2)) - sum(rtVals.slice(0, 2))) / 24) : null,
    tb4: n >= 8 ? round2((sum(rtVals.slice(-4)) - sum(rtVals.slice(0, 4))) / 24) : null,
    hour_count: n,
  };
}

function jsonResponse(body, status = 200, cacheSeconds = 0) {
  const headers = { "Content-Type": "application/json" };
  if (cacheSeconds > 0) headers["Cache-Control"] = `public, max-age=${cacheSeconds}`;
  return new Response(JSON.stringify(body), { status, headers });
}
