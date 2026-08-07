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
│   ├── ercot_client.py        # shared ERCOT API auth + request wrapper
│   ├── market_data.py         # net load (3d history + 5d forecast), hub DA/RT, AS DA/RT pulls
│   ├── aggregations.py        # yesterday / 3-day / MTD / YTD rollups + DART/volatility calcs
│   ├── ai_narrative.py        # Claude API call for the Tab 3 recap
│   └── build_report.py        # entrypoint — reads a config, runs the pipeline, writes output JSON

├── dashboard/
│   ├── index.html             # 3-tab shell (Overview / Prices & AS / Intelligence)
    ├── functions/
│       └── node-lookup.js         # Cloudflare Pages Function — live DA/RT/DART lookup for any node, called by the Tab 2 search box
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

This is scaffolding: directory layout, config schema, and workflow are real and
wired together; the Python pipeline modules and the frontend are stubs with clear
signatures and `TODO`/`PORT FROM` markers, ready to be filled in as separate passes.

## Build order (suggested)

1. ~~Repo scaffolding + config pattern~~ ← this pass
2. Backend pipeline (`pipeline/*.py`) — 3d/5d windows, hub DA/RT/AS aggregations
3. Frontend (`dashboard/`) — real 3-tab design pass
4. `functions/node-lookup.js` — live any-node search
