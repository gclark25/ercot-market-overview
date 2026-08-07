"""
Bid-close forecast: for each day in the forecast window, find the load/wind/
solar forecast archive posting closest to (but not after) 09:00 CT the day
before — the last forecast run before ERCOT's DA bidding window closes for
that delivery day — and extract that day's hourly values from it.

This is genuinely experimental relative to the rest of the pipeline:

  - The URL patterns (list archive postings by post time, download by docId)
    are confirmed directly from ERCOT's own api-specs GitHub discussions
    (#39, #106) — see ercot_client.py's archive functions.
  - What's NOT confirmed: the exact column headers inside the downloaded
    CSVs. The live JSON endpoints for these same reports use fields like
    DeliveryDate/HourEnding/STWPFSystemWide, and it's a reasonable bet the
    archived CSVs use the same or very similar names — but that's a bet, not
    a confirmed fact, since a CSV export and a JSON API response don't
    always share exact casing/naming even for the same underlying report.

Handled defensively because of that: multiple plausible column name
variants are tried for each field (same pattern as AS_TYPE_MAP elsewhere in
this codebase), and the actual CSV headers get printed to the log on first
use — so if the guess is wrong, the very first real run shows exactly what
to fix instead of requiring more guessing. Every failure (a report with no
matching archive, a CSV that doesn't parse, a day with no matching row) is
caught and skipped individually — never blocks the rest of the build.
"""

import csv as csv_module
import io
import zipfile
from datetime import date, timedelta

from ercot_client import ErcotCredentials, list_archive_documents, download_archive_documents

BID_CLOSE_CUTOFF_HOUR_CT = 9  # 09:00 CT — as specified for this dashboard

LOAD_EMIL = "np3-565-cd"
WIND_EMIL = "np4-732-cd"
SOLAR_EMIL = "np4-745-cd"

# Multiple plausible column-name variants per field, tried in order, since the
# archived CSV's exact headers aren't confirmed (see module docstring).
DATE_FIELD_CANDIDATES = ["DeliveryDate", "deliveryDate", "Delivery Date", "delivery_date"]
LOAD_HOUR_FIELD_CANDIDATES = ["HourEnding", "hourEnding", "Hour Ending", "hour_ending"]
LOAD_VALUE_FIELD_CANDIDATES = ["SystemTotal", "systemTotal", "System Total", "LoadForecast", "MTLF"]
WIND_VALUE_FIELD_CANDIDATES = ["STWPFSystemWide", "STWPF System Wide", "STWPF_SYSTEM_WIDE"]
SOLAR_VALUE_FIELD_CANDIDATES = ["STPPFSystemWide", "STPPF System Wide", "STPPF_SYSTEM_WIDE"]


def _first_present(row: dict, candidates: list[str]):
    for c in candidates:
        if c in row:
            return row[c]
    return None


def _central_time_cutoff(day: date, hour: int) -> str:
    """Archive postDatetime values from ERCOT's examples appear to already be
    in the report's own local (Central) time — treated here as a plain ISO
    string for lexicographic comparison, not converted through a timezone
    library. If bid-close picks look consistently off by several hours once
    this runs against real data, this naive assumption is the first thing to
    revisit."""
    return f"{day.isoformat()}T{hour:02d}:00:00"


def _pick_bid_close_doc(archives: list[dict], cutoff_iso: str) -> dict | None:
    """Latest posting at or before the cutoff — the last run before bid close."""
    candidates = [a for a in archives if a.get("postDatetime", "") <= cutoff_iso]
    if not candidates:
        return None
    return max(candidates, key=lambda a: a["postDatetime"])


def _download_and_parse_csv(emil_id: str, doc_id: int, token: str, creds: ErcotCredentials, label: str) -> list[dict]:
    raw = download_archive_documents(emil_id, [doc_id], token, creds)
    rows: list[dict] = []
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        for name in zf.namelist():
            if not name.lower().endswith(".csv"):
                continue
            with zf.open(name) as f:
                text = io.TextIOWrapper(f, encoding="utf-8-sig")
                reader = csv_module.DictReader(text)
                batch = list(reader)
                if batch and not rows:
                    # Diagnostic: print actual headers once per report type,
                    # so a wrong column-name guess is visible immediately in
                    # the Action log rather than silently producing zero rows.
                    print(f"    [{label}] archive CSV columns: {list(batch[0].keys())}")
                rows.extend(batch)
    return rows


def _extract_day_from_rows(rows: list[dict], target_date: str, value_field_candidates: list[str], hour_field_candidates: list[str] = LOAD_HOUR_FIELD_CANDIDATES) -> dict[int, float]:
    by_hour: dict[int, float] = {}
    for row in rows:
        d = str(_first_present(row, DATE_FIELD_CANDIDATES) or "")[:10]
        if d != target_date:
            continue
        he_raw = _first_present(row, hour_field_candidates)
        val_raw = _first_present(row, value_field_candidates)
        if he_raw is None or val_raw is None:
            continue
        try:
            he = int(str(he_raw).split(":")[0])
            val = float(val_raw)
        except (ValueError, TypeError):
            continue
        if val and he not in by_hour:  # first-row-per-key, same rule as the live wind/solar pulls
            by_hour[he] = val
    return by_hour


def get_bid_close_forecast(creds: ErcotCredentials, token: str, days_forecast: int = 5) -> dict:
    """
    Returns { "YYYY-MM-DD": { "HH": {"gross_load", "wind", "solar", "net_load"} } }
    for whichever forecast days a matching bid-close posting could be found
    and parsed — missing days are simply absent from the result, not errors.
    """
    today = date.today()

    # One broad archive-list query per report covering the whole window,
    # rather than a separate list call per delivery day.
    earliest_cutoff_day = today - timedelta(days=1)
    latest_cutoff_day = today + timedelta(days=max(days_forecast - 1, 0))
    post_from = f"{earliest_cutoff_day.isoformat()}T00:00:00"
    post_to = f"{latest_cutoff_day.isoformat()}T{BID_CLOSE_CUTOFF_HOUR_CT:02d}:00:00"

    try:
        load_archives = list_archive_documents(LOAD_EMIL, token, creds, post_from, post_to)
        wind_archives = list_archive_documents(WIND_EMIL, token, creds, post_from, post_to)
        solar_archives = list_archive_documents(SOLAR_EMIL, token, creds, post_from, post_to)
    except Exception as e:
        print(f"    WARN: bid-close archive listing failed entirely — {e}")
        return {}

    result: dict[str, dict] = {}
    for offset in range(days_forecast):
        delivery_day = today + timedelta(days=offset)
        cutoff_day = delivery_day - timedelta(days=1)
        cutoff_iso = _central_time_cutoff(cutoff_day, BID_CLOSE_CUTOFF_HOUR_CT)
        target = delivery_day.isoformat()

        try:
            load_doc = _pick_bid_close_doc(load_archives, cutoff_iso)
            wind_doc = _pick_bid_close_doc(wind_archives, cutoff_iso)
            solar_doc = _pick_bid_close_doc(solar_archives, cutoff_iso)
            if not (load_doc and wind_doc and solar_doc):
                print(f"    WARN: bid-close for {target} — missing archive posting for at least one of load/wind/solar before {cutoff_iso}, skipping")
                continue

            load_rows = _download_and_parse_csv(LOAD_EMIL, load_doc["docId"], token, creds, "load")
            wind_rows = _download_and_parse_csv(WIND_EMIL, wind_doc["docId"], token, creds, "wind")
            solar_rows = _download_and_parse_csv(SOLAR_EMIL, solar_doc["docId"], token, creds, "solar")

            load_by_hour = _extract_day_from_rows(load_rows, target, LOAD_VALUE_FIELD_CANDIDATES)
            wind_by_hour = _extract_day_from_rows(wind_rows, target, WIND_VALUE_FIELD_CANDIDATES)
            solar_by_hour = _extract_day_from_rows(solar_rows, target, SOLAR_VALUE_FIELD_CANDIDATES)

            hours = sorted(set(load_by_hour) | set(wind_by_hour) | set(solar_by_hour))
            if not hours:
                print(f"    WARN: bid-close for {target} — archives downloaded but no matching rows parsed (check column names above)")
                continue

            day_data = {}
            for h in hours:
                gl = round(load_by_hour.get(h, 0) / 1000, 2)
                wnd = round(wind_by_hour.get(h, 0) / 1000, 2)
                sol = round(solar_by_hour.get(h, 0) / 1000, 2)
                day_data[str(h)] = {"gross_load": gl, "wind": wnd, "solar": sol, "net_load": round(gl - wnd - sol, 2)}
            result[target] = day_data
            print(f"    bid-close for {target}: {len(hours)} hours (posted {load_doc['postDatetime']} / {wind_doc['postDatetime']} / {solar_doc['postDatetime']})")
        except Exception as e:
            print(f"    WARN: bid-close for {target} failed — {e}")
            continue

    return result
