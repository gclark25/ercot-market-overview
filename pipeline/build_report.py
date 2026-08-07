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
import sys
from pathlib import Path

import yaml

from ercot_client import ErcotCredentials
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

    output: dict = {
        "customer_id": config["customer_id"],
        "display_name": config["display_name"],
    }

    if features.get("net_load_overview"):
        output["net_load"] = get_net_load_series(creds)

    if features.get("hub_dart_table") or features.get("hourly_price_table"):
        hub_prices = get_hub_energy_prices(creds, hubs)
        output["hub_prices"] = hub_prices
        if features.get("hub_dart_table"):
            output["hub_windows"] = {hub: rollup_all_windows(series) for hub, series in hub_prices.items()}

    if features.get("ancillary_services_table"):
        as_prices = get_as_prices(creds)
        output["as_prices"] = as_prices
        output["as_windows"] = {svc: rollup_all_windows(series) for svc, series in as_prices.items()}

    if features.get("ai_narrative"):
        prompt = build_recap_prompt(
            output.get("hub_windows", {}),
            output.get("as_windows", {}),
            output.get("net_load", {}),
        )
        output["ai_recap"] = generate_recap(prompt)

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
