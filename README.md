# ERCOT Market Overview

A market-wide ERCOT daily report — net load, hub DA/RT/AS pricing, and an AI recap —
built to serve both internal use and white-labeled third-party BESS customers from
the same codebase.

This is a sibling project to `hen-morning-report`, not a fork of it. That repo covers
HEN's 32 asset-specific nodes; this one covers ERCOT market-wide data (hubs, load
zones, system fundamentals, AS clearing prices) that doesn't depend on any one
customer's asset list. Where logic already exists and works in
`hen_integrations.py` (ERCOT auth/token handling, AS DA/RT pulls, load/wind/solar
collectors), this repo ports it rather than re-deriving it — those spots are marked
`# PORT FROM hen-morning-report` in the stub files.

## Structure

```
ercot-market-overview/
├── .github/workflows/
│   └── daily-report.yml       # matrix build: one job per config in configs/, deploys to that config's Cloudflare Pages project
├── configs/
│   ├── _template.yaml         # schema + comments — copy this to onboard a new customer/tenant
│   └── internal.yaml          # HEN internal deployment (default branding, all features on)
├── pipeline/
│   ├── ercot_client.py        # shared ERCOT API auth + request wrapper (real, ported from hen-morning-report)
│   ├── peak_calendar.py       # on-peak/off-peak rule: Mon-Fri HE 7-22 = on-peak, everything else = off-peak
│   ├── market_data.py         # net load (3d history + 5d forecast), hub DA/RT, AS DA/RT pulls (real, ported)
│   ├── aggregations.py        # yesterday / 3-day / MTD / YTD rollups, each split into overall/on-peak/off-peak (real)
│   ├── ai_narrative.py        # Claude API call for the Tab 3 recap (still a stub)
│   └── build_report.py        # entrypoint — reads a config, runs the pipeline, writes output JSON
├── functions/
│   └── node-lookup.js         # Cloudflare Pages Function — live DA/RT/DART lookup for any node, called by the Tab 2 search box
├── dashboard/
│   ├── index.html             # 3-tab shell (Overview / Prices & AS / Intelligence)
│   ├── assets/
│   │   ├── styles.css
│   │   └── app.js
│   └── data/
│       └── latest.json        # placeholder — real file is written daily by build_report.py per deployment
├── requirements.txt
└── .gitignore
```

## Multi-tenant model

One config file per deployment target in `configs/`. The GitHub Actions workflow
matrix-builds every config found there (except `_template.yaml`) and deploys each
to its own Cloudflare Pages project. Adding a new customer means adding one YAML
file — no code changes, unless they need a feature the pipeline doesn't have yet.

## Status

- `ercot_client.py`, `peak_calendar.py`, `market_data.py`, `aggregations.py` —
  real, working implementations, ported from hen-morning-report's confirmed
  endpoints/parsing logic and unit-tested against fixture data (peak
  boundaries + a hand-verified DART rollup).
- `ai_narrative.py` — still a stub. `build_report.py` catches its
  `NotImplementedError`/`RuntimeError` so the rest of the report still writes
  successfully in the meantime.
- `dashboard/` frontend — real rendering: net load chart, hub cards, time-series
  charts with on/off-peak summaries for energy and AS, basis panel, and search
  autocomplete for known hubs/load zones (see `dashboard/assets/known-locations.js`).
- `functions/node-lookup.js` — real implementation: live ERCOT auth + single-day
  DA/RT/DART lookup for any settlement point, with token + result caching.
  **Must stay at the repo root** (sibling to `dashboard/`), not nested inside it —
  Cloudflare Pages looks for `functions/` relative to where the deploy command
  runs, independent of which directory's static assets get uploaded. This bit
  us once already; don't move it.

## On-peak / off-peak

On-peak = Monday-Friday, HE 7-22. Off-peak = everything else. Defined once in
`pipeline/peak_calendar.py`; `market_data.get_hub_energy_prices()` tags every
hourly record with it at pull time, and `aggregations.rollup_window()` returns
`overall` / `on_peak` / `off_peak` stats for every window. The frontend reads
the tag rather than re-deriving the rule.

## Node search: backfill-once, append-daily

Hubs and load zones get full YTD history via the daily pipeline. An
arbitrary searched node starts with just a live single-day answer (fast,
via `functions/node-lookup.js`), but graduates to full history automatically:

1. First search for a new node → live Function answers immediately with
   "Yesterday" only, and fires a `repository_dispatch` event in the
   background (needs `GITHUB_DISPATCH_TOKEN` set as a Cloudflare Pages env
   var — see the Function's file header).
2. `.github/workflows/node-backfill.yml` catches that event, runs
   `pipeline/backfill_node.py` for just that one node (a full YTD pull,
   reusing the same paginated `get_hub_energy_prices` hubs already use), and
   commits the result to `dashboard/data/nodes/<NODE>.json`.
3. From then on, `daily-report.yml` tops that file up incrementally —
   fetching only the new day since `last_updated`, not re-pulling the whole
   year every time (an efficiency the hub/load-zone pull still doesn't have).
4. The frontend tries `data/nodes/<NODE>.json` as a plain static file before
   ever calling the live Function — once backfilled, a node is exactly as
   fast as a hub, with full on/off-peak, basis, and TB1/TB2/TB4 support.

This is currently a shared, not per-tenant, resource — fine at today's
single-config scale; worth revisiting before a second customer onboards
(see the comment in `daily-report.yml`'s node-update step).

## Build order (suggested)

1. ~~Repo scaffolding + config pattern~~ ← done
2. ~~Backend pipeline core~~ ← done (`ai_narrative.py` pending)
3. ~~Frontend real rendering pass~~ ← done
4. ~~`functions/node-lookup.js` — live any-node search~~ ← done
5. `pipeline/ai_narrative.py` — the Tab 3 AI recap, still a stub
