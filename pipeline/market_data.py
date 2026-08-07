"""
Market-wide ERCOT data pulls for Tabs 1 and 2.

Every function here is ported from confirmed-working logic in hen-morning-report,
generalized from HEN's single-day/single-node use case to this dashboard's
multi-day-window/multi-hub use case. Column layouts and field-name quirks are
copied exactly from the source rather than re-derived — see ercot_client.py's
docstring for why two request styles exist.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
import time
from typing import Any

from ercot_client import ErcotCredentials, ercot_get_raw, ercot_get_records
from peak_calendar import peak_label


def safe_float(val: Any) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


# ── Net load (Tab 1: 2-day history + 5-day forecast) ────────────────────────

def get_net_load_series(creds: ErcotCredentials, token: str, days_history: int = 2, days_forecast: int = 5) -> dict:
    """
    Returns:
        {
          "history":  { "YYYY-MM-DD": { "HH": {"gross_load": mw, "wind": mw, "solar": mw, "net_load": mw} } },
          "forecast": { same shape, for the forecast window },
        }
    MW values are in GW (divided by 1000) to match the existing dashboard convention.

    History uses ACTUAL generation (positional access, same report + column
    positions as collect_data() in hen_morning_report.py). Forecast uses the
    STWPF/STPPF forecast fields (named access, same as collect_ercot_forecasts()
    in hen_integrations.py) — these are deliberately different pulls because a
    forecast value for an already-elapsed hour is not the same as what actually
    happened.

    days_history defaults to 2, not 3: np4-732-cd/np4-737-cd (wind/solar actuals)
    only retain a rolling 48-hour historical window per ERCOT's own data product
    docs — requesting further back than that returns real gross_load (a separate
    report with its own retention) alongside zeroed-out wind/solar for the
    portion of the oldest day outside that window, which reads as a data error
    rather than the source limitation it actually is. Don't raise this above 2
    without confirming ERCOT has changed that retention.
    """
    today = date.today()
    hist_start = (today - timedelta(days=days_history)).isoformat()
    hist_end = (today - timedelta(days=1)).isoformat()
    fcst_start = today.isoformat()
    fcst_end = (today + timedelta(days=days_forecast)).isoformat()

    history = _get_net_load_actuals(creds, token, hist_start, hist_end)
    forecast = _get_net_load_forecast(creds, token, fcst_start, fcst_end)

    return {"history": history, "forecast": forecast}


def _get_net_load_actuals(creds: ErcotCredentials, token: str, start: str, end: str) -> dict:
    load_by_day_hour: dict[str, dict[int, float]] = defaultdict(dict)
    wind_by_day_hour: dict[str, dict[int, float]] = defaultdict(dict)
    solar_by_day_hour: dict[str, dict[int, float]] = defaultdict(dict)

    # Gross load — np6-345-cd/act_sys_load_by_wzn
    # Row layout: [date, hourEnding, ...zone values..., systemTotal] — take the
    # last numeric value in row[1:] as systemTotal (matches collect_data()).
    try:
        rows = ercot_get_raw("np6-345-cd/act_sys_load_by_wzn", token, creds,
                              {"operatingDayFrom": start, "operatingDayTo": end})
        for row in rows:
            if not isinstance(row, list) or len(row) < 3:
                continue
            d = str(row[0])[:10]
            try:
                hr = int(str(row[1]).split(":")[0])
            except (ValueError, AttributeError):
                continue
            nums = [x for x in row[1:] if isinstance(x, (int, float)) and not isinstance(x, bool)]
            val = nums[-1] if nums else 0
            if start <= d <= end and val:
                load_by_day_hour[d][hr] = round(float(val) / 1000, 2)
    except Exception as e:
        print(f"    WARN: net load actual gross load failed — {e}")

    # Wind actual — np4-732-cd/wpp_hrly_avrg_actl_fcast, row[1]=date, row[2]=hour, row[3]=value
    try:
        rows = ercot_get_raw("np4-732-cd/wpp_hrly_avrg_actl_fcast", token, creds,
                              {"deliveryDateFrom": start, "deliveryDateTo": end})
        for row in rows:
            if not isinstance(row, list) or len(row) < 4:
                continue
            d = str(row[1])[:10]
            hr = int(row[2]) if isinstance(row[2], (int, float)) else 0
            val = safe_float(row[3])
            if start <= d <= end and val:
                wind_by_day_hour[d][hr] = round(val / 1000, 2)
    except Exception as e:
        print(f"    WARN: net load actual wind failed — {e}")

    # Solar actual — np4-737-cd/spp_hrly_avrg_actl_fcast, same layout as wind
    try:
        rows = ercot_get_raw("np4-737-cd/spp_hrly_avrg_actl_fcast", token, creds,
                              {"deliveryDateFrom": start, "deliveryDateTo": end})
        for row in rows:
            if not isinstance(row, list) or len(row) < 4:
                continue
            d = str(row[1])[:10]
            hr = int(row[2]) if isinstance(row[2], (int, float)) else 0
            val = safe_float(row[3])
            if start <= d <= end and val:
                solar_by_day_hour[d][hr] = round(val / 1000, 2)
    except Exception as e:
        print(f"    WARN: net load actual solar failed — {e}")

    return _combine_net_load(load_by_day_hour, wind_by_day_hour, solar_by_day_hour)


def _get_net_load_forecast(creds: ErcotCredentials, token: str, start: str, end: str) -> dict:
    load_by_day_hour: dict[str, dict[int, float]] = defaultdict(dict)
    wind_by_day_hour: dict[str, dict[int, float]] = defaultdict(dict)
    solar_by_day_hour: dict[str, dict[int, float]] = defaultdict(dict)

    # Load forecast — np3-565-cd/lf_by_model_weather_zone, filter inUseFlag == True only
    try:
        rows = ercot_get_records("np3-565-cd/lf_by_model_weather_zone", token, creds,
                                  {"deliveryDateFrom": start, "deliveryDateTo": end, "size": 5000})
        for row in rows:
            in_use = row.get("inUseFlag") if row.get("inUseFlag") is not None else row.get("InUseFlag")
            if in_use is False:
                continue
            d = str(row.get("deliveryDate") or row.get("DeliveryDate") or "")[:10]
            he_raw = str(row.get("hourEnding") or row.get("HourEnding") or "0")
            try:
                he = int(he_raw.split(":")[0])
            except ValueError:
                continue
            mw = safe_float(row.get("systemTotal") or row.get("SystemTotal") or
                             row.get("loadForecast") or row.get("mtlf") or row.get("total") or 0)
            if start <= d <= end and mw > 0:
                load_by_day_hour[d][he] = round(mw / 1000, 2)
    except Exception as e:
        print(f"    WARN: net load forecast load failed — {e}")

    # Wind forecast — np4-732-cd/wpp_hrly_avrg_actl_fcast, STWPFSystemWide.
    # This is a system-wide total repeated across zone rows — take the FIRST
    # occurrence per (date, hour) key, never sum across rows.
    try:
        rows = ercot_get_records("np4-732-cd/wpp_hrly_avrg_actl_fcast", token, creds,
                                  {"deliveryDateFrom": start, "deliveryDateTo": end, "size": 5000})
        for row in rows:
            d = str(row.get("deliveryDate") or row.get("DeliveryDate") or "")[:10]
            he_raw = str(row.get("hourEnding") or row.get("HourEnding") or "0")
            try:
                he = int(he_raw.split(":")[0])
            except ValueError:
                continue
            mw = safe_float(row.get("STWPFSystemWide"))
            if start <= d <= end and mw > 0 and he not in wind_by_day_hour[d]:
                wind_by_day_hour[d][he] = round(mw / 1000, 2)
    except Exception as e:
        print(f"    WARN: net load forecast wind failed — {e}")

    # Solar forecast — np4-745-cd/spp_hrly_actual_fcast_geo, STPPFSystemWide, same first-row-per-key rule
    try:
        rows = ercot_get_records("np4-745-cd/spp_hrly_actual_fcast_geo", token, creds,
                                  {"deliveryDateFrom": start, "deliveryDateTo": end, "size": 5000})
        for row in rows:
            d = str(row.get("deliveryDate") or row.get("DeliveryDate") or "")[:10]
            he_raw = str(row.get("hourEnding") or row.get("HourEnding") or "0")
            try:
                he = int(he_raw.split(":")[0])
            except ValueError:
                continue
            mw = safe_float(row.get("STPPFSystemWide"))
            if start <= d <= end and mw > 0 and he not in solar_by_day_hour[d]:
                solar_by_day_hour[d][he] = round(mw / 1000, 2)
    except Exception as e:
        print(f"    WARN: net load forecast solar failed — {e}")

    return _combine_net_load(load_by_day_hour, wind_by_day_hour, solar_by_day_hour)


def _combine_net_load(load_by_day_hour, wind_by_day_hour, solar_by_day_hour) -> dict:
    all_days = sorted(set(load_by_day_hour) | set(wind_by_day_hour) | set(solar_by_day_hour))
    out: dict[str, dict] = {}
    for d in all_days:
        hours = sorted(set(load_by_day_hour.get(d, {})) | set(wind_by_day_hour.get(d, {})) | set(solar_by_day_hour.get(d, {})))
        out[d] = {}
        for h in hours:
            gl = load_by_day_hour.get(d, {}).get(h, 0.0)
            wnd = wind_by_day_hour.get(d, {}).get(h, 0.0)
            sol = solar_by_day_hour.get(d, {}).get(h, 0.0)
            out[d][str(h)] = {
                "gross_load": gl,
                "wind": wnd,
                "solar": sol,
                "net_load": round(gl - wnd - sol, 2),
            }
    return out


# ── Hub energy prices (Tab 1 hub table, Tab 2 hourly price table) ───────────

def extract_price_with_interval(row) -> tuple[int | None, float | None]:
    """RT row: [deliveryDate, hour, interval, settlementPoint, type, price, ...]"""
    if isinstance(row, list) and len(row) >= 6:
        try:
            hour = int(row[1])
            nums = [x for x in row if isinstance(x, (int, float)) and not isinstance(x, bool) and x != 0]
            price = nums[-1] if nums else None
            return hour, price
        except (ValueError, TypeError):
            return None, None
    elif isinstance(row, dict):
        hour = int(row.get("deliveryHour", 0))
        price = safe_float(row.get("settlementPointPrice") or row.get("spp") or row.get("price") or 0)
        return hour, (price if price != 0 else None)
    return None, None


def extract_da_price_with_hour(row) -> tuple[int | None, float | None]:
    """DA row: [deliveryDate, deliveryHour, settlementPoint, price, ...]"""
    if isinstance(row, list) and len(row) >= 4:
        try:
            hour = int(row[1]) if not isinstance(row[1], str) else int(row[1].split(":")[0])
            nums = [x for x in row[2:] if isinstance(x, (int, float)) and not isinstance(x, bool)]
            price = nums[-1] if nums else None
            return hour, price
        except (ValueError, TypeError):
            return None, None
    elif isinstance(row, dict):
        hour = int(row.get("deliveryHour", 0))
        price = safe_float(row.get("settlementPointPrice") or row.get("spp") or row.get("price") or 0)
        return hour, (price if price != 0 else None)
    return None, None


def get_hub_energy_prices(creds: ErcotCredentials, token: str, hubs: list[str], start: str, end: str) -> dict:
    """
    Works for load zones too, not just hubs — "hubs" and "load zones" are both
    just settlement points as far as np6-905-cd/np4-190-cd are concerned, so
    this same function pulls either; build_report.py calls it twice with two
    different lists rather than needing a separate load-zone-specific pull.

    Returns: { hub: { "YYYY-MM-DD": { "HH": {"da": p, "rt": p, "dart": p, "peak": "on"|"off"} } } }

    dart = da - rt (matches hen-morning-report's sign convention: positive
    means DA cleared above RT). Kept consistent so a value read here means the
    same thing it does in hen-morning-report's existing DART tables.

    start/end should span far enough back to cover the YTD rollup window
    (i.e. Jan 1 of the current year through yesterday) — this pulls one
    request per hub per price type, not per day, so the date range itself
    doesn't add extra calls; it does increase row volume, which is why RT
    (15-min intervals) needs a larger `size` than DA (hourly).
    """
    out: dict[str, dict] = {}
    for i, hub in enumerate(hubs):
        if i > 0:
            time.sleep(3)  # pacing between hubs, matching the original per-node loop

        rt_hourly: dict[str, dict[int, float]] = defaultdict(dict)
        da_hourly: dict[str, dict[int, float]] = defaultdict(dict)

        try:
            rows = ercot_get_raw("np6-905-cd/spp_node_zone_hub", token, creds, {
                "settlementPoint": hub, "deliveryDateFrom": start, "deliveryDateTo": end, "size": 5000,
            }, paginate=True)
            day_hour_prices: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
            for row in rows:
                d = str(row[0])[:10] if isinstance(row, list) and row else None
                hr, price = extract_price_with_interval(row)
                if d and hr is not None and price is not None:
                    day_hour_prices[d][hr].append(price)
            for d, hours in day_hour_prices.items():
                for hr, prices in hours.items():
                    rt_hourly[d][hr] = round(sum(prices) / len(prices), 2)
        except Exception as e:
            print(f"    WARN: RT prices for {hub} — {e}")

        time.sleep(3)  # pacing between the RT and DA pulls for the same hub

        try:
            rows = ercot_get_raw("np4-190-cd/dam_stlmnt_pnt_prices", token, creds, {
                "settlementPoint": hub, "deliveryDateFrom": start, "deliveryDateTo": end, "size": 5000,
            }, paginate=True)
            for row in rows:
                d = str(row[0])[:10] if isinstance(row, list) and row else None
                hr, price = extract_da_price_with_hour(row)
                if d and hr is not None and price is not None:
                    da_hourly[d][hr] = round(price, 2)
        except Exception as e:
            print(f"    WARN: DA prices for {hub} — {e}")

        all_days = sorted(set(rt_hourly) | set(da_hourly))
        hub_out: dict[str, dict] = {}
        for d in all_days:
            d_date = datetime.strptime(d, "%Y-%m-%d").date()
            hours = sorted(set(rt_hourly.get(d, {})) | set(da_hourly.get(d, {})))
            hub_out[d] = {}
            for hr in hours:
                rt = rt_hourly.get(d, {}).get(hr)
                da = da_hourly.get(d, {}).get(hr)
                hub_out[d][str(hr)] = {
                    "da": da,
                    "rt": rt,
                    "dart": round(da - rt, 2) if da is not None and rt is not None else None,
                    "peak": peak_label(d_date, hr),
                }
        out[hub] = hub_out

    return out


# ── Ancillary service prices (Tab 2 AS table) ────────────────────────────────

AS_TYPES = ["REGUP", "REGDN", "RRS", "NSPIN", "ECRS"]

AS_TYPE_MAP = {
    "REGUP": "REGUP", "REG-UP": "REGUP", "REGULATION_UP": "REGUP",
    "REGDN": "REGDN", "REG-DN": "REGDN", "REG-DOWN": "REGDN", "REGULATION_DOWN": "REGDN",
    "RRS": "RRS", "RESPONSIVE_RESERVE": "RRS",
    "NSPIN": "NSPIN", "NON-SPIN": "NSPIN", "NONSPIN": "NSPIN", "NON_SPIN": "NSPIN",
    "ECRS": "ECRS", "ERCRS": "ECRS",
}


def _parse_as_date_he(row: dict) -> tuple[str, int]:
    dt = str(row.get("deliveryDate") or row.get("DeliveryDate") or
              row.get("delivery_date") or row.get("date") or "")[:10]
    he_raw = (row.get("hourEnding") or row.get("HourEnding") or
              row.get("hour_ending") or row.get("Hour") or row.get("hour") or
              row.get("settlementInterval") or "")

    if not dt or not he_raw:
        ts = str(row.get("SCEDTimestamp") or row.get("sced_timestamp") or
                  row.get("timestamp") or row.get("Timestamp") or "")
        if "T" in ts:
            dt = ts[:10]
            ts_hour = int(ts[11:13])
            he_raw = str(ts_hour + 1)

    try:
        he = int(str(he_raw).split(":")[0])
    except (ValueError, TypeError):
        he = 0
    return dt, max(1, min(24, he))


def get_as_prices(creds: ErcotCredentials, token: str, start: str, end: str) -> dict:
    """
    Returns: { as_type: { "YYYY-MM-DD": { "HH": {"da": p, "rt": p, "dart": p} } } }
    dart = da - rt, same sign convention as energy DART.

    DA source: np4-188-cd/dam_clear_price_for_cap (long format, confirmed working)
    RT source: np6-332-cd/rt_clear_price_cap_sced (SCED 5-min, paginated — confirmed
    working; earlier candidate endpoints in hen-morning-report's history all 404'd,
    this is the one that actually returns data)
    """
    da_rows = ercot_get_records("np4-188-cd/dam_clear_price_for_cap", token, creds,
                                 {"deliveryDateFrom": start, "deliveryDateTo": end}, paginate=True)
    da = _bucket_as_rows(da_rows, start, end)

    time.sleep(3)  # pacing between the two big paginated pulls, not just within each one

    rt_rows = ercot_get_records("np6-332-cd/rt_clear_price_cap_sced", token, creds, {
        "SCEDTimestampFrom": start + "T00:00:00", "SCEDTimestampTo": end + "T23:59:59",
    }, paginate=True)
    rt = _bucket_as_rows(rt_rows, start, end)

    all_days = sorted(set(da) | set(rt))
    out: dict[str, dict] = {at: {} for at in AS_TYPES}
    for d in all_days:
        d_date = datetime.strptime(d, "%Y-%m-%d").date()
        hours = sorted(set(da.get(d, {})) | set(rt.get(d, {})))
        for hr in hours:
            da_prices = da.get(d, {}).get(hr, {})
            rt_prices = rt.get(d, {}).get(hr, {})
            for at in AS_TYPES:
                dv = da_prices.get(at)
                rv = rt_prices.get(at)
                if dv is None and rv is None:
                    continue
                out[at].setdefault(d, {})[str(hr)] = {
                    "da": dv,
                    "rt": rv,
                    "dart": round(dv - rv, 2) if dv is not None and rv is not None else None,
                    "peak": peak_label(d_date, hr),
                }
    return out


def _bucket_as_rows(rows: list[dict], start: str, end: str) -> dict[str, dict[int, dict[str, float]]]:
    buckets: dict[str, dict[int, dict[str, list[float]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for row in rows:
        dt, he = _parse_as_date_he(row)
        if not dt or not (start <= dt <= end):
            continue
        raw_type = str(row.get("ancillaryType") or row.get("AncillaryType") or
                        row.get("ASType") or row.get("asType") or row.get("type") or "").strip().upper()
        canonical = AS_TYPE_MAP.get(raw_type)
        if not canonical:
            continue
        price = row.get("MCPC") or row.get("mcpc") or row.get("price") or row.get("Price")
        if price is None:
            continue
        try:
            buckets[dt][he][canonical].append(round(float(price), 2))
        except (TypeError, ValueError):
            continue
    return {
        dt: {he: {at: round(sum(vals) / len(vals), 2) for at, vals in types.items()} for he, types in hours.items()}
        for dt, hours in buckets.items()
    }
