"""
Pre-computes the specific facts the AI narrative should describe, kept
deliberately separate from ai_narrative.py's prompt assembly and API call.
The model is asked to write prose around numbers Python has already gotten
right — never to do the comparisons or arithmetic itself. Same principle
hen-morning-report already leans on, just applied to a wider surface here
(multiple hubs, AS, HEN's own node portfolio, bid-close accuracy).

Every function here degrades gracefully to None on missing/incomplete data
rather than raising — a quiet day, a feature that's off, or an unreadable
node file should never be able to break the recap.
"""

import json
from pathlib import Path


def _safe_get(d, *keys, default=None):
    for k in keys:
        if d is None:
            return default
        d = d.get(k)
    return d if d is not None else default


def load_hen_node_windows(nodes_dir: str = "dashboard/data/nodes") -> dict:
    """Reads every backfilled HEN node file and returns {node: windows} — just
    the precomputed window stats, not the full daily history (no need to load
    megabytes of hourly data just to pick one highlight). A single corrupt or
    unreadable node file is skipped, not fatal to the rest of the recap."""
    result: dict = {}
    p = Path(nodes_dir)
    if not p.is_dir():
        return result
    for f in sorted(p.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            result[data["node"]] = data.get("windows", {})
        except Exception:
            continue
    return result


def find_top_mover_hub(hub_windows: dict) -> dict | None:
    """The hub with the widest |DART spread| yesterday."""
    best = None
    for hub, windows in hub_windows.items():
        spread = _safe_get(windows, "yesterday", "overall", "dart_spread")
        if spread is None:
            continue
        if best is None or abs(spread) > abs(best["dart_spread"]):
            best = {"hub": hub, "dart_spread": spread}
    return best


def find_notable_hen_node(hen_node_windows: dict) -> dict | None:
    """The HEN asset with the highest TB2 yesterday — the widest realized
    2-hour arbitrage spread among HEN's own portfolio that day."""
    best = None
    for node, windows in hen_node_windows.items():
        tb2 = _safe_get(windows, "yesterday", "tb2")
        if tb2 is None:
            continue
        if best is None or tb2 > best["tb2"]:
            dart = _safe_get(windows, "yesterday", "overall", "dart_spread")
            best = {"node": node, "tb2": tb2, "dart_spread": dart}
    return best


def compute_bid_close_accuracy(net_load: dict, day: str) -> dict | None:
    """Actual (history) vs. bid-close forecast for one already-completed day
    — mean error (bias/direction) and mean absolute error (magnitude), net
    load only (the single bottom-line number), plus which component clearly
    dominated the miss if one did."""
    actual_hours = _safe_get(net_load, "history", day, default={})
    bidclose_hours = _safe_get(net_load, "bid_close", day, default={})
    if not actual_hours or not bidclose_hours:
        return None

    diffs, wind_diffs, solar_diffs = [], [], []
    for hour, actual in actual_hours.items():
        bc = bidclose_hours.get(hour)
        if not bc or actual.get("net_load") is None or bc.get("net_load") is None:
            continue
        diffs.append(actual["net_load"] - bc["net_load"])
        if actual.get("wind") is not None and bc.get("wind") is not None:
            wind_diffs.append(actual["wind"] - bc["wind"])
        if actual.get("solar") is not None and bc.get("solar") is not None:
            solar_diffs.append(actual["solar"] - bc["solar"])

    if not diffs:
        return None

    dominant_component = None
    wind_mae = round(sum(abs(d) for d in wind_diffs) / len(wind_diffs), 2) if wind_diffs else None
    solar_mae = round(sum(abs(d) for d in solar_diffs) / len(solar_diffs), 2) if solar_diffs else None
    if wind_mae is not None and solar_mae is not None:
        if wind_mae > solar_mae * 1.5:
            dominant_component = "wind"
        elif solar_mae > wind_mae * 1.5:
            dominant_component = "solar"

    return {
        "day": day,
        # All net_load/wind/solar figures are already in GW throughout this
        # pipeline (bid_close_forecast.py explicitly divides by 1000 from
        # ERCOT's raw MW), matching what the net load chart itself displays
        # — confirmed as a real mislabeling bug in production: this used to
        # be named *_mw, which was wrong by a factor of 1000, not just a
        # cosmetic issue.
        "mean_error_gw": round(sum(diffs) / len(diffs), 2),  # positive = actual came in ABOVE the bid-close forecast
        "mean_abs_error_gw": round(sum(abs(d) for d in diffs) / len(diffs), 2),
        "dominant_component": dominant_component,
        "hours_compared": len(diffs),
    }


def compute_today_forecast_drift(net_load: dict, today: str) -> dict | None:
    """How much today's LATEST forecast has moved from this morning's
    bid-close snapshot, for the same day."""
    forecast_hours = _safe_get(net_load, "forecast", today, default={})
    bidclose_hours = _safe_get(net_load, "bid_close", today, default={})
    if not forecast_hours or not bidclose_hours:
        return None

    diffs = []
    for hour, fc in forecast_hours.items():
        bc = bidclose_hours.get(hour)
        if not bc or fc.get("net_load") is None or bc.get("net_load") is None:
            continue
        diffs.append(fc["net_load"] - bc["net_load"])

    if not diffs:
        return None

    return {
        "day": today,
        # Same GW clarification as compute_bid_close_accuracy above.
        "mean_drift_gw": round(sum(diffs) / len(diffs), 2),  # signed — positive means the current forecast
                                                              # is net HIGHER than this morning's; can mask real
                                                              # movement if the day shifted up in some hours and
                                                              # down in others (confirmed in production: a chart
                                                              # showing a clear midday gap still reported "under
                                                              # 2" here, because it netted out over 24 hours)
        "mean_abs_drift_gw": round(sum(abs(d) for d in diffs) / len(diffs), 2),  # magnitude, hour by hour —
                                                                                  # this is what actually answers
                                                                                  # "how much has today's forecast
                                                                                  # moved," independent of whether
                                                                                  # it netted out over the day
        "max_abs_drift_gw": round(max(abs(d) for d in diffs), 2),  # the single largest hourly swing —
                                                                    # names the actual worst-case shift, not
                                                                    # just an average of it
        "hours_compared": len(diffs),
    }


def find_as_highlight(as_windows: dict) -> dict | None:
    """Flags an AS service only if yesterday's DA average looks like a
    genuine outlier vs. its own YTD average (2x+) — deliberately conservative
    so this doesn't fire on an ordinary day."""
    best = None
    for svc, windows in as_windows.items():
        yesterday_da = _safe_get(windows, "yesterday", "overall", "avg_da")
        ytd_da = _safe_get(windows, "ytd", "overall", "avg_da")
        if yesterday_da is None or not ytd_da:
            continue
        ratio = yesterday_da / ytd_da
        if ratio >= 2.0 and (best is None or ratio > best["ratio"]):
            best = {"service": svc, "yesterday_avg_da": yesterday_da, "ytd_avg_da": ytd_da, "ratio": round(ratio, 2)}
    return best


def compute_highlights(hub_windows: dict, as_windows: dict, net_load: dict, hen_node_windows: dict, today_str: str, yesterday_str: str) -> dict:
    return {
        "top_mover_hub": find_top_mover_hub(hub_windows),
        "notable_hen_node": find_notable_hen_node(hen_node_windows),
        "bid_close_accuracy": compute_bid_close_accuracy(net_load, yesterday_str),
        "today_forecast_drift": compute_today_forecast_drift(net_load, today_str),
        "as_highlight": find_as_highlight(as_windows),
    }
