#!/usr/bin/env python3
"""
Entrypoint: python pipeline/build_report.py --config configs/<name>.yaml

Reads one customer_config.yaml, runs the market data + aggregation + AI
narrative steps according to that config's feature flags, and writes
dashboard/data/latest.json for that deployment.

Also writes CF_PROJECT_NAME to $GITHUB_ENV (when running in Actions) so the
workflow's deploy step knows which Cloudflare Pages project to target without
a second YAML parse in the workflow file itself.
"""

import argparse
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from ercot_client import ErcotCredentials, get_ercot_token
from market_data import get_net_load_series, get_hub_energy_prices, get_as_prices
from aggregations import rollup_all_windows
from ai_narrative import build_recap_prompt, generate_recap
from bid_close_forecast import get_bid_close_forecast
from narrative_highlights import compute_highlights, load_hen_node_windows


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


def build(config: dict) -> dict:
    creds = load_credentials(config)
    features = config["features"]
    hubs = config["data_scope"]["hubs"]

    print("Authenticating with ERCOT...")
    token = get_ercot_token(creds)

    today = date.today()
    ytd_start = today.replace(month=1, day=1).isoformat()
    yesterday = (today - timedelta(days=1)).isoformat()

    output: dict = {
        "customer_id": config["customer_id"],
        "display_name": config["display_name"],
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }

    if features.get("net_load_overview"):
        print("Pulling net load (history + forecast)...")
        output["net_load"] = get_net_load_series(creds, token)

        try:
            print("Pulling bid-close forecast snapshots (experimental)...")
            output["net_load"]["bid_close"] = get_bid_close_forecast(creds, token)
        except Exception as e:
            # Genuinely experimental (see bid_close_forecast.py docstring) —
            # never let this block the rest of the report.
            print(f"  WARN: bid-close forecast failed entirely — {e}")
            output["net_load"]["bid_close"] = {}

    if features.get("hub_dart_table") or features.get("hourly_price_table"):
        print(f"Pulling hub energy DA/RT prices, {ytd_start} -> {yesterday} ({len(hubs)} hubs)...")
        hub_prices = get_hub_energy_prices(creds, token, hubs, ytd_start, yesterday)
        output["hub_prices"] = hub_prices
        if features.get("hub_dart_table"):
            output["hub_windows"] = {hub: rollup_all_windows(series, today) for hub, series in hub_prices.items()}

        load_zones = config["data_scope"].get("load_zones") or []
        if load_zones and features.get("hourly_price_table"):
            print(f"Pulling load zone DA/RT prices, {ytd_start} -> {yesterday} ({len(load_zones)} zones)...")
            load_zone_prices = get_hub_energy_prices(creds, token, load_zones, ytd_start, yesterday)
            output["load_zone_prices"] = load_zone_prices
            output["load_zone_windows"] = {zone: rollup_all_windows(series, today) for zone, series in load_zone_prices.items()}

    if features.get("ancillary_services_table"):
        print(f"Pulling AS DA/RT clearing prices, {ytd_start} -> {yesterday}...")
        as_prices = get_as_prices(creds, token, ytd_start, yesterday)
        output["as_prices"] = as_prices
        output["as_windows"] = {svc: rollup_all_windows(series, today) for svc, series in as_prices.items()}

    if features.get("ai_narrative"):
        try:
            print("Generating AI recap...")
            hen_node_windows = load_hen_node_windows()
            highlights = compute_highlights(
                output.get("hub_windows", {}),
                output.get("as_windows", {}),
                output.get("net_load", {}),
                hen_node_windows,
                today_str=today.isoformat(),
                yesterday_str=yesterday,
            )
            prompt = build_recap_prompt(
                output.get("hub_windows", {}),
                output.get("as_windows", {}),
                output.get("net_load", {}),
                highlights,
                config["display_name"],
                today.isoformat(),
            )
            output["ai_recap"] = generate_recap(prompt)
        except Exception as e:
            # Never let a recap failure (stub, bad key, transient API error,
            # unexpected data shape) block the rest of the report from being
            # written.
            print(f"  WARN: ai_narrative failed ({e}) — skipping recap")
            output["ai_recap"] = None

    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    config = load_config(args.config)
    report = build(config)

    out_path = Path("dashboard/data/latest.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    print(f"Wrote {out_path} for {config['customer_id']}")

    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a") as f:
            f.write(f"CF_PROJECT_NAME={config['deployment']['cloudflare_project_name']}\n")


if __name__ == "__main__":
    main()
