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
PAGE_PACING_SECONDS = 2  # delay between successive pages during pagination — ERCOT's
                          # rate limit tripped (429) when pages fired back-to-back with
                          # no delay at all; the original single-day pulls never hit this
                          # because they never paginated.
DEFAULT_429_BACKOFF_SECONDS = 20
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


def _get_json_with_retry(path: str, headers: dict, params: dict, max_attempts: int = 3) -> dict:
    """
    Single-page GET with retry logic that treats 429 (rate limited) differently
    from other transient errors: honors the Retry-After header when present,
    and falls back to a longer fixed backoff than the generic retry uses,
    since a 10s wait was not enough to clear ERCOT's rate limit in practice.
    """
    last_exc = None
    for attempt in range(max_attempts):
        try:
            r = requests.get(f"{BASE_URL}/{path}", headers=headers, params=params, timeout=45)
            if r.status_code == 429:
                retry_after = r.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else DEFAULT_429_BACKOFF_SECONDS
                if attempt < max_attempts - 1:
                    print(f"    WARN: {path} rate limited (429) — waiting {wait:.0f}s before retry...")
                    time.sleep(wait)
                    continue
                r.raise_for_status()  # final attempt: raise the 429 as an error
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_exc = e
            if attempt < max_attempts - 1:
                print(f"    WARN: {path} attempt {attempt + 1} failed ({e}) — retrying in 10s...")
                time.sleep(10)
    raise last_exc


def ercot_get_raw(
    path: str,
    token: str,
    creds: ErcotCredentials,
    params: dict[str, Any] | None = None,
    paginate: bool = False,
) -> list:
    """Positional-access style — mirrors hen_morning_report.ercot_get(), with
    pagination (and pacing between pages) added on top. The original
    single-day pulls never needed pagination (a day of RT data is well under
    one page); YTD-range pulls used elsewhere in this codebase do, so set
    paginate=True for those or rows past the first page/`size` will silently
    go missing — no error, just quietly wrong (too-short) history."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Ocp-Apim-Subscription-Key": creds.subscription_key,
        "Accept": "application/json",
    }
    base_params = {"size": 1000}
    if params:
        base_params.update(params)
    page_size = base_params.get("size", 1000)

    all_rows: list = []
    page = 1
    while True:
        p = dict(base_params)
        if paginate:
            p["page"] = page
            if page > 1:
                time.sleep(PAGE_PACING_SECONDS)

        try:
            body = _get_json_with_retry(path, headers, p)
        except Exception as e:
            print(f"    WARN: {path} page {page} — giving up after retries ({e})")
            break

        if isinstance(body, list):
            page_rows = body
        elif "data" in body:
            page_rows = body["data"]
        else:
            page_rows = next((v for v in body.values() if isinstance(v, list)), [])

        all_rows.extend(page_rows)

        if not paginate or len(page_rows) < page_size:
            break
        page += 1

    return all_rows


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
            if page > 1:
                time.sleep(PAGE_PACING_SECONDS)

        try:
            body = _get_json_with_retry(path, headers, p)
        except Exception as e:
            print(f"    WARN [{path}] page {page} — giving up after retries ({e})")
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


# ── Archive access (for bid-close forecast snapshots) ───────────────────────
#
# Confirmed via ERCOT's own api-specs GitHub discussions (#39, #106) — a
# genuinely different access pattern from everything above: instead of "give
# me the current data," this lets you list and download specific historical
# postings of a report by their post time, which is what "the forecast as of
# 09:00 CT yesterday" requires. Same auth (Bearer token + subscription key)
# as everywhere else in this file.
#
# UNVERIFIED: the archive returns actual CSV files inside a ZIP, not the nice
# pre-parsed JSON the rest of this pipeline uses. The exact column headers
# inside those CSVs haven't been confirmed against a real download — see
# pipeline/bid_close_forecast.py for how this is handled defensively.

def _post_bytes_with_retry(path: str, headers: dict, json_body: dict, max_attempts: int = 3) -> bytes:
    """POST counterpart to _get_json_with_retry — same 429/Retry-After handling,
    just returning raw bytes instead of parsed JSON (the archive download
    endpoint returns a ZIP, not JSON)."""
    last_exc = None
    for attempt in range(max_attempts):
        try:
            r = requests.post(f"{BASE_URL}/{path}", headers=headers, json=json_body, timeout=60)
            if r.status_code == 429:
                retry_after = r.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else DEFAULT_429_BACKOFF_SECONDS
                if attempt < max_attempts - 1:
                    print(f"    WARN: {path} rate limited (429) — waiting {wait:.0f}s before retry...")
                    time.sleep(wait)
                    continue
                r.raise_for_status()
            r.raise_for_status()
            return r.content
        except Exception as e:
            last_exc = e
            if attempt < max_attempts - 1:
                print(f"    WARN: {path} attempt {attempt + 1} failed ({e}) — retrying in 10s...")
                time.sleep(10)
    raise last_exc


def list_archive_documents(emil_id: str, token: str, creds: ErcotCredentials, post_datetime_from: str, post_datetime_to: str) -> list[dict]:
    """GET /archive/{emil_id}?postDatetimeFrom=...&postDatetimeTo=...
    Returns [{"docId": ..., "friendlyName": ..., "postDatetime": ...}, ...]."""
    headers = {"Authorization": f"Bearer {token}", "Ocp-Apim-Subscription-Key": creds.subscription_key}
    params = {"postDatetimeFrom": post_datetime_from, "postDatetimeTo": post_datetime_to, "size": 1000}
    body = _get_json_with_retry(f"archive/{emil_id}", headers, params)
    return body.get("archives", [])


def download_archive_documents(emil_id: str, doc_ids: list[int], token: str, creds: ErcotCredentials) -> bytes:
    """POST /archive/{emil_id}/download {"docIds": [...]} -> raw ZIP bytes."""
    headers = {"Authorization": f"Bearer {token}", "Ocp-Apim-Subscription-Key": creds.subscription_key}
    return _post_bytes_with_retry(f"archive/{emil_id}/download", headers, {"docIds": doc_ids})
