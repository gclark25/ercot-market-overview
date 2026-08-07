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
    tb1: float | None       # avg daily (max hourly RT - min hourly RT) / 24, across the window
    tb1_days: int           # how many days contributed a value (needs >=2 valid RT hours/day)
    tb2: float | None       # avg daily (sum top-2 RT - sum bottom-2 RT) / 24
    tb2_days: int           # needs >=4 valid RT hours/day
    tb4: float | None       # avg daily (sum top-4 RT - sum bottom-4 RT) / 24
    tb4_days: int           # needs >=8 valid RT hours/day


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


def _daily_tb_values(hours: dict) -> tuple[float | None, float | None, float | None]:
    """
    hours: {"HH": {"rt": float|None, ...}} for a single day.

    Each metric needs enough distinct valid (non-null) hourly RT values to
    fill its top-N and bottom-N without overlap — TB1 needs 2, TB2 needs 4,
    TB4 needs 8. A metric is independently None for a day that falls short,
    rather than dropping the whole day from all three just because TB4 (the
    strictest) can't be computed.
    """
    rt_vals = sorted(h["rt"] for h in hours.values() if h.get("rt") is not None)
    n = len(rt_vals)
    tb1 = round((rt_vals[-1] - rt_vals[0]) / 24, 3) if n >= 2 else None
    tb2 = round((sum(rt_vals[-2:]) - sum(rt_vals[:2])) / 24, 3) if n >= 4 else None
    tb4 = round((sum(rt_vals[-4:]) - sum(rt_vals[:4])) / 24, 3) if n >= 8 else None
    return tb1, tb2, tb4


def _compute_tb_stats(hourly_series: dict, start: date, end: date) -> dict:
    tb1_vals: list[float] = []
    tb2_vals: list[float] = []
    tb4_vals: list[float] = []

    for day_str, hours in hourly_series.items():
        try:
            d = date.fromisoformat(day_str)
        except ValueError:
            continue
        if not (start <= d <= end):
            continue
        tb1, tb2, tb4 = _daily_tb_values(hours)
        if tb1 is not None:
            tb1_vals.append(tb1)
        if tb2 is not None:
            tb2_vals.append(tb2)
        if tb4 is not None:
            tb4_vals.append(tb4)

    def _avg(vals: list[float]) -> float | None:
        return round(sum(vals) / len(vals), 3) if vals else None

    return {
        "tb1": _avg(tb1_vals), "tb1_days": len(tb1_vals),
        "tb2": _avg(tb2_vals), "tb2_days": len(tb2_vals),
        "tb4": _avg(tb4_vals), "tb4_days": len(tb4_vals),
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

    tb_stats = _compute_tb_stats(hourly_series, start, end)

    return {
        "overall": _compute_peak_stats(overall_records),
        "on_peak": _compute_peak_stats(on_peak_records),
        "off_peak": _compute_peak_stats(off_peak_records),
        **tb_stats,
    }


def rollup_all_windows(hourly_series: dict, as_of: date | None = None) -> dict[str, WindowStats]:
    """Convenience wrapper: returns all four windows keyed by window name."""
    return {w: rollup_window(hourly_series, w, as_of) for w in ("yesterday", "3day", "mtd", "ytd")}
