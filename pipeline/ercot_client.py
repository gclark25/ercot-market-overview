"""
Shared ERCOT Public API client.

Ported from hen-morning-report (hen_morning_report.py's get_token/ercot_get,
and the local _ercot_get closures used inside collect_ercot_forecasts /
collect_as_prices in hen_integrations.py). Two request styles exist there for
a reason, so both are kept here rather than collapsed into one:

  - ercot_get_raw(): returns rows as ERCOT sends them (list-of-lists, or
    whatever body["data"] is), no field-name remapping. Used where the
    existing code accesses columns positionally (row[0], row[1], ...) — e.g.
    system load, wind/solar actuals, hub RT/DA prices. Positional access only
    works because the existing pipeline already reverse-engineered these
    column orders in production; don't "improve" this by remapping fields
    without re-verifying the report's actual column layout.

  - ercot_get_records(): zips list-of-lists rows against the report's "fields"
    metadata to return one dict per row, so callers can do row.get("deliveryDate")
    etc. Used where the existing code needs named-field access (forecast pulls
    with inUseFlag / STWPFSystemWide / STPPFSystemWide, and AS clearing prices
    with ancillaryType/MCPC).
"""

import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests

BASE_URL = "https://api.ercot.com/api/public-reports"
AUTH_URL = (
    "https://ercotb2c.b2clogin.com"
    "/ercotb2c.onmicrosoft.com"
    "/B2C_1_PUBAPI-ROPC-FLOW"
    "/oauth2/v2.0/token"
    "?username={u}&password={p}"
    "&grant_type=password"
    "&scope=openid+fec253ea-0d06-4272-a5e6-b478baeecd70+offline_access"
    "&client_id=fec253ea-0d06-4272-a5e6-b478baeecd70"
    "&response_type=id_token"
)


@dataclass
class ErcotCredentials:
    username: str
    password: str
    subscription_key: str


def get_ercot_token(creds: ErcotCredentials) -> str:
    """Password-grant token from ERCOT's B2C login. Ported as-is from
    hen_morning_report.get_token() — do not change the URL params/scope,
    they're specific to ERCOT's public API app registration."""
    r = requests.post(
        AUTH_URL.format(
            u=quote(creds.username, safe=""),
            p=quote(creds.password, safe=""),
        ),
        headers={"Ocp-Apim-Subscription-Key": creds.subscription_key},
        timeout=15,
    )
    r.raise_for_status()
    d = r.json()
    token = d.get("id_token") or d.get("access_token")
    if not token:
        raise RuntimeError(f"ERCOT auth succeeded but no token in response: {list(d.keys())}")
    return token


def ercot_get_raw(path: str, token: str, creds: ErcotCredentials, params: dict[str, Any] | None = None) -> list:
    """Positional-access style — mirrors hen_morning_report.ercot_get().
    One retry on transient failures (timeout / 5xx)."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Ocp-Apim-Subscription-Key": creds.subscription_key,
        "Accept": "application/json",
    }
    p = {"size": 1000}
    if params:
        p.update(params)
    for attempt in range(2):
        try:
            r = requests.get(f"{BASE_URL}/{path}", headers=headers, params=p, timeout=45)
            r.raise_for_status()
            body = r.json()
            if isinstance(body, list):
                return body
            if "data" in body:
                return body["data"]
            for v in body.values():
                if isinstance(v, list):
                    return v
            return []
        except Exception as e:
            if attempt == 0:
                print(f"    WARN: {path} attempt 1 failed ({e}) — retrying in 10s...")
                time.sleep(10)
            else:
                raise
    return []


def _normalize_field_name(f: Any) -> str:
    if isinstance(f, dict):
        return str(f.get("name") or f.get("label") or f.get("column") or "")
    return str(f).strip()


def ercot_get_records(
    path: str,
    token: str,
    creds: ErcotCredentials,
    params: dict[str, Any] | None = None,
    paginate: bool = False,
    page_size: int = 5000,
) -> list[dict]:
    """
    Named-field-access style — mirrors the local _ercot_get closures in
    collect_ercot_forecasts / collect_as_prices. Returns one dict per row,
    keyed by the report's field names.

    Set paginate=True for pulls that can exceed one page (e.g. a full year of
    RT 15-min AS clearing prices) — mirrors the page-looping pattern already
    used for AS RT collection. Stops once a page returns fewer than
    `page_size` rows.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Ocp-Apim-Subscription-Key": creds.subscription_key,
    }
    base_params = {"size": page_size}
    if params:
        base_params.update(params)

    all_rows: list[dict] = []
    page = 1
    while True:
        p = dict(base_params)
        if paginate:
            p["page"] = page
        try:
            r = requests.get(f"{BASE_URL}/{path}", headers=headers, params=p, timeout=45)
            r.raise_for_status()
            body = r.json()
        except Exception as e:
            print(f"    WARN [{path}] page {page} — {e}")
            break

        fields_raw = body.get("fields") or []
        raw = body.get("data") or []
        if isinstance(raw, dict):
            fields_raw = raw.get("fields") or fields_raw
            raw = raw.get("rows") or raw.get("data") or []
        if not raw:
            break

        fields = [_normalize_field_name(f) for f in fields_raw]
        if raw and isinstance(raw[0], list):
            if not fields:
                print(f"    WARN [{path}] list-of-lists but no fields metadata — skipping page")
                break
            raw = [dict(zip(fields, row)) for row in raw]

        all_rows.extend(raw)

        if not paginate or len(raw) < page_size:
            break
        page += 1

    return all_rows
