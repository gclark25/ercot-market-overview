"""
Tab 3 recap: a single Claude API call summarizing yesterday / 3-day / MTD / YTD
market conditions, mirroring the narrative generation already used in
hen-morning-report.

Token discipline carries over directly from that project: this prompt covers
more surface area (multiple hubs x energy x AS x four windows) than HEN's
single-asset narrative, so trimming is more important here, not less.
  - Pass in pre-aggregated WindowStats, never raw hourly series.
  - Cap hub/node lists the same way the HEN prompt caps node lists (names
    only past a certain count, full stats only for the top N).
"""

import os


def build_recap_prompt(hub_windows: dict, as_windows: dict, net_load_summary: dict) -> str:
    """
    Assemble a compact prompt from already-aggregated data (see
    aggregations.py) — do not hand raw hourly series to the model.

    TODO: write the actual prompt template. Structure it the same way as
    the HEN morning narrative prompt: date context up top, then windows
    ordered yesterday -> 3-day -> MTD -> YTD, closing instruction for tone
    and length.
    """
    raise NotImplementedError


def generate_recap(prompt: str) -> str:
    """
    Call the Claude API (model: reuse whatever hen-morning-report currently
    pins) and return the narrative text.

    TODO: port the API call pattern (client init, model string, max_tokens,
    error handling) from the existing pipeline's narrative step.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    raise NotImplementedError
