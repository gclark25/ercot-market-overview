#!/usr/bin/env python3
"""
Backfill or incrementally update a single arbitrary ERCOT settlement point's
history, persisted as a git-committed JSON file at dashboard/data/nodes/<NODE>.json.

Two invocation contexts, same script, same idempotent logic:

  1. On-demand backfill (.github/workflows/node-backfill.yml, triggered by a
     repository_dispatch event fired from functions/node-lookup.js the first
     time someone searches a node that isn't a configured hub/load zone) —
     no file exists yet, so this does a full YTD pull.

  2. Daily incremental update (a step in .github/workflows/daily-report.yml
     that loops over every already-tracked node under dashboard/data/nodes/)
     — the file already exists, so this only fetches the day(s) since its
     last_updated date and appends, rather than re-pulling the whole year
     every day the way the hub/load-zone pull still does.

Output shape matches hub_prices/hub_windows in latest.json —
{ "node": ..., "last_updated": ..., "days": {...}, "windows": {...} } — so
the frontend renders a backfilled node with the exact same code path as a hub.

Safety notes:
  - If a node genuinely has no ERCOT data (invalid code, typo), no file is
    written at all — better to leave it untracked (and let a future search
    retry) than silently create an empty "successfully tracked" file that
    then looks like a real, permanently-empty node.
  - If an incremental run finds no new days yet (ERCOT hasn't posted
    yesterday's data at the time this runs), last_updated is NOT advanced —
    it'll retry the same range on the next run rather than silently skipping
    a day forever.
"""

import argparse
import json
import os
from datetime import date, timedelta
from pathlib import Path

import yaml

from ercot_client import ErcotCredentials, get_ercot_token
from market_data import get_hub_energy_prices
from aggregations import rollup_all_windows


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_credentials(config: dict) -> ErcotCredentials:
    secrets = config["secrets"]
    return ErcotCredentials(
        username=os.environ[secrets["ercot_api_user_secret"]],
        password=os.environ[secrets["ercot_api_pass_secret"]],
        subscription_key=os.environ[secrets["ercot_subscription_key_secret"]],
    )


def backfill_or_update(node: str, config: dict, out_dir: Path = Path("dashboard/data/nodes")) -> bool:
    """Returns True if the file was written/updated, False if nothing changed."""
    out_path = out_dir / f"{node}.json"
    out_dir.mkdir(parents=True, exist_ok=True)

    today = date.today()
    yesterday = today - timedelta(days=1)

    existing_days: dict = {}
    existing_windows: dict | None = None
    last_updated: str | None = None
    if out_path.exists():
        existing = json.loads(out_path.read_text())
        existing_days = existing.get("days", {})
        existing_windows = existing.get("windows")
        last_updated = existing.get("last_updated")

        if last_updated == yesterday.isoformat():
            # The underlying data is current — but the aggregation formula
            # itself might have changed since this file was last written
            # (e.g. TB1/TB2/TB4 added after this node was already
            # backfilled). Recomputing is a pure local operation with no
            # ERCOT call, so there's no real cost to always doing it rather
            # than letting an already-tracked node silently go stale on
            # every metric added after the day it was backfilled.
            recomputed = rollup_all_windows(existing_days, today)
            if recomputed == existing_windows:
                print(f"{node}: already up to date through {last_updated} — nothing to do")
                return False
            out_path.write_text(json.dumps({
                "node": node, "last_updated": last_updated,
                "days": existing_days, "windows": recomputed,
            }, indent=2))
            print(f"{node}: data unchanged, but rollups were recomputed (aggregation logic changed since last write) -> {out_path}")
            return True

        start = (date.fromisoformat(last_updated) + timedelta(days=1)).isoformat() if last_updated else today.replace(month=1, day=1).isoformat()
        print(f"{node}: incremental update, {start} -> {yesterday.isoformat()}")
    else:
        start = today.replace(month=1, day=1).isoformat()
        print(f"{node}: full backfill, {start} -> {yesterday.isoformat()}")

    creds = load_credentials(config)
    token = get_ercot_token(creds)

    pulled = get_hub_energy_prices(creds, token, [node], start, yesterday.isoformat())
    new_days = pulled.get(node, {})

    if not new_days:
        if existing_days:
            print(f"{node}: no new days available yet for {start} -> {yesterday.isoformat()} — leaving last_updated as {last_updated}")
        else:
            print(f"{node}: no data found at all — not creating a tracked file (likely an invalid settlement point code)")
        return False

    merged_days = {**existing_days, **new_days}
    windows = rollup_all_windows(merged_days, today)

    out_path.write_text(json.dumps({
        "node": node,
        "last_updated": yesterday.isoformat(),
        "days": merged_days,
        "windows": windows,
    }, indent=2))
    print(f"{node}: wrote {len(merged_days)} total days ({len(new_days)} new) -> {out_path}")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", required=True)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    config = load_config(args.config)
    backfill_or_update(args.node.strip().upper(), config)


if __name__ == "__main__":
    main()
