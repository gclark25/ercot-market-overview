"""
Rollup logic for Tab 1's hub performance table and Tab 2's summary stats.

Every rollup window (yesterday / 3-day / MTD / YTD) is computed from the same
hourly series returned by market_data.py — no separate fetch per window.
"""

from datetime import date
from typing import TypedDict


class WindowStats(TypedDict):
    avg_da: float
    avg_rt: float
    dart_spread: float          # avg_rt - avg_da, in $
    dart_spread_pct: float      # dart_spread / avg_da, as a fraction
    rt_volatility: float        # std dev of hourly RT across the window


def rollup_window(hourly_series: dict, window: str, as_of: date | None = None) -> WindowStats:
    """
    hourly_series: { "YYYY-MM-DD": { "DA": [...24...], "RT": [...24...] } }
    window: one of "yesterday", "3day", "mtd", "ytd"

    TODO: implement date-window slicing + avg/spread/volatility calculation.
    Keep this pure (no API calls) so it's easily unit-testable against fixture
    data before wiring it to live pulls.
    """
    raise NotImplementedError


def rollup_all_windows(hourly_series: dict, as_of: date | None = None) -> dict[str, WindowStats]:
    """Convenience wrapper: returns all four windows keyed by window name."""
    return {w: rollup_window(hourly_series, w, as_of) for w in ("yesterday", "3day", "mtd", "ytd")}
