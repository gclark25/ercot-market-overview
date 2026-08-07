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

    if features.get("hub_dart_table") or features.get("hourly_price_table"):
        print(f"Pulling hub energy DA/RT prices, {ytd_start} -> {yesterday} ({len(hubs)} hubs)...")
        hub_prices = get_hub_energy_prices(creds, token, hubs, ytd_start, yesterday)
        output["hub_prices"] = hub_prices
        if features.get("hub_dart_table"):
            output["hub_windows"] = {hub: rollup_all_windows(series, today) for hub, series in hub_prices.items()}

        load_zones = config["data_scope"].get("load_zones") or []
        if load_zones and features.get("hourly_price_table"):
            print(f"Pulling load zone DA/RT prices, {ytd_start} -> {yesterday} ({len(load_zones)} zones)...")
            output["load_zone_prices"] = get_hub_energy_prices(creds, token, load_zones, ytd_start, yesterday)

    if features.get("ancillary_services_table"):
        print(f"Pulling AS DA/RT clearing prices, {ytd_start} -> {yesterday}...")
        as_prices = get_as_prices(creds, token, ytd_start, yesterday)
        output["as_prices"] = as_prices
        output["as_windows"] = {svc: rollup_all_windows(series, today) for svc, series in as_prices.items()}

    if features.get("ai_narrative"):
        try:
            print("Generating AI recap...")
            prompt = build_recap_prompt(
                output.get("hub_windows", {}),
                output.get("as_windows", {}),
                output.get("net_load", {}),
            )
            output["ai_recap"] = generate_recap(prompt)
        except (NotImplementedError, RuntimeError) as e:
            # ai_narrative.py is still a stub — don't let that block the rest
            # of the report from being written while it's being filled in.
            print(f"  WARN: ai_narrative not ready yet ({e}) — skipping recap")
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
