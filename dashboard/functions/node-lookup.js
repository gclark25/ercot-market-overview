/**
 * Cloudflare Pages Function: GET /node-lookup?node=<settlement_point>&window=<yesterday|3day|mtd>
 *
 * Live on-demand DA/RT/DART lookup for any ERCOT settlement point not already
 * baked into the daily static JSON. Called by the Tab 2 search box.
 *
 * This is a NEW code path, not a port: the existing ERCOT auth/request logic
 * in hen-morning-report is Python (GitHub Actions runtime), and this runs on
 * Cloudflare's Workers runtime (JS/TS only) at request time instead of once a
 * day. Same ERCOT credentials, same report endpoints — different runtime.
 *
 * Env bindings expected (set as Cloudflare Pages project secrets, not in this
 * file): ERCOT_API_USERNAME, ERCOT_API_PASSWORD, ERCOT_SUBSCRIPTION_KEY.
 *
 * Caching: results are cached at the edge for a short TTL so repeated
 * searches for the same node/window within that window don't re-hit the
 * ERCOT API on every keystroke/request.
 */

const CACHE_TTL_SECONDS = 900; // 15 min — adjust once real usage patterns are known

export async function onRequestGet(context) {
  const { request, env } = context;
  const url = new URL(request.url);
  const node = url.searchParams.get("node");
  const window = url.searchParams.get("window") || "yesterday";

  if (!node) {
    return jsonResponse({ error: "Missing required 'node' query param" }, 400);
  }

  const cache = caches.default;
  const cacheKey = new Request(url.toString(), request);
  const cached = await cache.match(cacheKey);
  if (cached) return cached;

  let payload;
  try {
    payload = await lookupNode(node, window, env);
  } catch (err) {
    return jsonResponse({ error: err.message || "Lookup failed" }, 502);
  }

  const response = jsonResponse(payload, 200, CACHE_TTL_SECONDS);
  await cache.put(cacheKey, response.clone());
  return response;
}

/**
 * TODO: implement.
 *   1. Get/refresh an ERCOT bearer token (same auth flow as the Python
 *      pipeline, ported to fetch()-based JS — see ercot_client.py for the
 *      logic to mirror once it's filled in).
 *   2. Pull DA + RT settlement point prices for `node` over `window`.
 *   3. Compute the same DART spread stats as aggregations.py's
 *      rollup_window(), so the response shape matches what the frontend
 *      already expects from the static JSON for hub rows.
 */
async function lookupNode(node, window, env) {
  throw new Error("Not implemented — port ERCOT auth + settlement point price pull to JS");
}

function jsonResponse(body, status = 200, cacheSeconds = 0) {
  const headers = { "Content-Type": "application/json" };
  if (cacheSeconds > 0) headers["Cache-Control"] = `public, max-age=${cacheSeconds}`;
  return new Response(JSON.stringify(body), { status, headers });
}
