"""
On-peak / off-peak classification for ERCOT energy hours.

Definition (as specified for this dashboard):
    On-peak  : Monday-Friday, HE 7-22
    Off-peak : HE 23, 24, 1-6 on weekdays, AND all of HE 1-24 on Saturday/Sunday

This does NOT currently account for NERC holidays (some conventions exclude
holidays from on-peak). If that distinction turns out to matter, it's a
one-line change to `is_on_peak` below.

This module is the single source of truth for the rule — market_data.py tags
each hourly record with it when the data is pulled, so aggregations.py and the
frontend both just read a "peak" field rather than each re-deriving the rule.
"""

from datetime import date

ON_PEAK_START_HE = 7
ON_PEAK_END_HE = 22  # inclusive


def is_on_peak(d: date, he: int) -> bool:
    """
    d: the calendar date of the hour (not adjusted for HE 24 = midnight quirks —
       callers should already be passing the correct delivery date for that HE).
    he: hour-ending, 1-24.
    """
    if d.weekday() > 4:  # Saturday=5, Sunday=6
        return False
    return ON_PEAK_START_HE <= he <= ON_PEAK_END_HE


def peak_label(d: date, he: int) -> str:
    """Convenience wrapper returning "on" or "off" instead of a bool —
    matches the string form used in JSON output / WindowStats keys."""
    return "on" if is_on_peak(d, he) else "off"
