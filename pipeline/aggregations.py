"""
Rollup logic for Tab 1's hub performance table and Tab 2's summary stats.

Every rollup window (yesterday / 3-day / MTD / YTD) is computed from the same
hourly series returned by market_data.get_hub_energy_prices() / get_as_prices()
— no separate fetch per window. Each window is broken into three views:
"overall" (every hour), "on_peak", and "off_peak" — see peak_calendar.py for
the on/off-peak rule itself.

This module is pure (no API calls), so it's testable against fixture data
independent of ERCOT access.
"""

import statistics
from datetime import date, timedelta
from typing import TypedDict


class PeakStats(TypedDict):
    avg_da: float | None
    avg_rt: float | None
    dart_spread: float | None       # avg_da - avg_rt, in $ (matches hen-morning-report's DART sign convention)
    dart_spread_pct: float | None   # dart_spread / avg_da, as a fraction — None if avg_da is 0
    rt_volatility: float | None     # population std dev of hourly RT across the window
    hour_count: int


class WindowStats(TypedDict):
    overall: PeakStats
    on_peak: PeakStats
    off_peak: PeakStats


EMPTY_PEAK_STATS: PeakStats = {
    "avg_da": None, "avg_rt": None, "dart_spread": None,
    "dart_spread_pct": None, "rt_volatility": None, "hour_count": 0,
}


def _window_bounds(window: str, as_of: date) -> tuple[date, date]:
    """Returns (start, end) inclusive. Windows run through yesterday — "today"
    is excluded since same-day DA/RT data is incomplete until settlement."""
    yesterday = as_of - timedelta(days=1)
    if window == "yesterday":
        return yesterday, yesterday
    if window == "3day":
        return yesterday - timedelta(days=2), yesterday
    if window == "mtd":
        return yesterday.replace(day=1), yesterday
    if window == "ytd":
        return yesterday.replace(month=1, day=1), yesterday
    raise ValueError(f"Unknown window: {window}")


def _compute_peak_stats(hour_records: list[dict]) -> PeakStats:
    """hour_records: list of {"da": float|None, "rt": float|None} for the hours in scope."""
    da_vals = [r["da"] for r in hour_records if r.get("da") is not None]
    rt_vals = [r["rt"] for r in hour_records if r.get("rt") is not None]

    if not da_vals and not rt_vals:
        return dict(EMPTY_PEAK_STATS, hour_count=0)

    avg_da = round(sum(da_vals) / len(da_vals), 2) if da_vals else None
    avg_rt = round(sum(rt_vals) / len(rt_vals), 2) if rt_vals else None
    dart_spread = round(avg_da - avg_rt, 2) if avg_da is not None and avg_rt is not None else None
    dart_spread_pct = round(dart_spread / avg_da, 4) if dart_spread is not None and avg_da else None
    rt_volatility = round(statistics.pstdev(rt_vals), 2) if len(rt_vals) >= 2 else None

    return {
        "avg_da": avg_da,
        "avg_rt": avg_rt,
        "dart_spread": dart_spread,
        "dart_spread_pct": dart_spread_pct,
        "rt_volatility": rt_volatility,
        "hour_count": len(hour_records),
    }


def rollup_window(hourly_series: dict, window: str, as_of: date | None = None) -> WindowStats:
    """
    hourly_series: { "YYYY-MM-DD": { "HH": {"da": float|None, "rt": float|None,
                                              "dart": float|None, "peak": "on"|"off"} } }
    (this is exactly the per-hub shape returned by market_data.get_hub_energy_prices())
    window: one of "yesterday", "3day", "mtd", "ytd"
    """
    as_of = as_of or date.today()
    start, end = _window_bounds(window, as_of)

    overall_records: list[dict] = []
    on_peak_records: list[dict] = []
    off_peak_records: list[dict] = []

    for day_str, hours in hourly_series.items():
        try:
            d = date.fromisoformat(day_str)
        except ValueError:
            continue
        if not (start <= d <= end):
            continue
        for hour_data in hours.values():
            overall_records.append(hour_data)
            if hour_data.get("peak") == "on":
                on_peak_records.append(hour_data)
            else:
                off_peak_records.append(hour_data)

    return {
        "overall": _compute_peak_stats(overall_records),
        "on_peak": _compute_peak_stats(on_peak_records),
        "off_peak": _compute_peak_stats(off_peak_records),
    }


def rollup_all_windows(hourly_series: dict, as_of: date | None = None) -> dict[str, WindowStats]:
    """Convenience wrapper: returns all four windows keyed by window name."""
    return {w: rollup_window(hourly_series, w, as_of) for w in ("yesterday", "3day", "mtd", "ytd")}
