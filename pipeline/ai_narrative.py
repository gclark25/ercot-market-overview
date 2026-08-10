"""
Tab 3 recap: a single Claude API call summarizing yesterday's market, how
well it was forecast, and what's ahead — written for someone who doesn't
look at ERCOT data every day and wants the "so what," not a data dump.

The model is only ever asked to narrate facts pipeline/narrative_highlights.py
has already computed and verified — never to do comparisons or arithmetic
itself. Same discipline hen-morning-report already applies to raw hourly
series: pass in pre-aggregated stats, cap what gets full detail (5 hubs and
a handful of AS types get their full window stats; HEN's ~30-node portfolio
only ever contributes the one pre-picked highlight, never the full list).
"""

import json
import os

import anthropic

MODEL = "claude-sonnet-5"  # reasonable default for a short, tone-sensitive summarization
                           # task — swap this if hen-morning-report pins something specific
MAX_TOKENS = 1024  # generous margin: Sonnet 5's tokenizer produces ~30% more tokens for the
                   # same text than earlier models, and 150-250 words of final output still
                   # needs real headroom now that thinking is explicitly disabled below


def build_recap_prompt(hub_windows: dict, as_windows: dict, net_load: dict, highlights: dict, display_name: str, report_date: str) -> str:
    """
    Assembles the recap prompt from already-aggregated window stats (see
    aggregations.py) and pre-computed highlights (see narrative_highlights.py).
    """
    sections = [f"""You are writing a short daily market recap for {display_name}'s ERCOT dashboard, dated {report_date}.

AUDIENCE: people who do NOT look at ERCOT market data every day. They want the "so what," not a wall of numbers. If you use a term like "DART" or "on-peak," give a short plain-English gloss the first time you use it. Never give trading advice or tell anyone what to do — describe and explain what happened and what's expected, nothing more.

LENGTH: 200-300 words total. Plain prose in short paragraphs, separated by a blank line between paragraphs — no bullet lists, no markdown headers, nothing a reader can't skim in under a minute or two.

Cover, in this order, skipping any part with nothing genuinely notable to say:
1. One-sentence headline: the single most notable thing in today's data.
2. Yesterday's hub recap — which hub(s) moved most, on-peak vs off-peak only if it's a real story. If there's a notable HEN asset below, name it as HEN's own standout for the day.
3. Battery arbitrage value — TB1/TB2/TB4 are the price spread a 1/2/4-hour battery could theoretically have captured that day. Say plainly whether it's currently running above or below its normal year-to-date level, both for the hubs broadly and — this is the important part — for HEN's own assets specifically, using the figures below. This is a genuine, recurring part of the recap, not an occasional aside: it's what actually feeds hedging decisions, so give it a real sentence or two even on an unremarkable day, not just a passing mention.
4. How yesterday's forecast held up against what actually happened, using the bid-close accuracy figures below.
5. Outlook for today and tomorrow — net load shape, and whether today's forecast has already shifted meaningfully from this morning's snapshot.
6. Only if something below is a genuine outlier: one line flagging it. Omit this section entirely on an ordinary day — most days should NOT have this section."""]

    sections.append("Hub performance — DA/RT/DART/volatility, on-peak vs off-peak, and TB1/TB2/TB4, across Yesterday/3-Day/MTD/YTD:\n" + json.dumps(hub_windows, separators=(",", ":")))

    if as_windows:
        sections.append("Ancillary services performance — same structure, per service:\n" + json.dumps(as_windows, separators=(",", ":")))

    if highlights.get("top_mover_hub"):
        sections.append("Pre-computed: yesterday's biggest DART mover among the hubs:\n" + json.dumps(highlights["top_mover_hub"]))

    if highlights.get("notable_hen_node"):
        sections.append("Pre-computed: HEN's own standout asset yesterday, by realized 2-hour arbitrage spread (TB2):\n" + json.dumps(highlights["notable_hen_node"]))

    if highlights.get("tb_trend_hub"):
        sections.append("Pre-computed: the hub + battery duration (TB1/TB2/TB4) whose yesterday reading diverged most from its own YTD baseline — pct_change is signed, positive means yesterday ran above the normal YTD level for that duration:\n" + json.dumps(highlights["tb_trend_hub"]))

    if highlights.get("tb_trend_hen_node"):
        sections.append("Pre-computed: same check, but over HEN's own asset portfolio specifically — this is the one that actually matters for HEN's own hedging decisions, since it's HEN's own assets whose forward value is being reassessed:\n" + json.dumps(highlights["tb_trend_hen_node"]))

    if highlights.get("bid_close_accuracy"):
        sections.append("Pre-computed: yesterday's actual net load vs. the forecast as of bid-close (09:00 CT the day before) — all figures are in GW (matching the net load chart's own units). mean_error_gw is signed, positive means actual came in above the bid-close forecast:\n" + json.dumps(highlights["bid_close_accuracy"]))

    if highlights.get("today_forecast_drift"):
        sections.append("Pre-computed: how much today's current forecast has moved from this morning's bid-close snapshot — all figures are in GW (matching the net load chart's own units). mean_drift_gw is signed and net over the day (can look small even if the forecast genuinely shifted, if it moved up in some hours and down in others) — mean_abs_drift_gw and max_abs_drift_gw show the real hour-by-hour magnitude and describe how much it actually moved, which is usually the more accurate story to tell:\n" + json.dumps(highlights["today_forecast_drift"]))

    if highlights.get("as_highlight"):
        sections.append("Pre-computed: an ancillary service price that looks like a genuine outlier vs. its own YTD average:\n" + json.dumps(highlights["as_highlight"]))

    sections.append("Write the recap now — plain text only, no headers, no bullets.")

    return "\n\n".join(sections)


def generate_recap(prompt: str) -> str:
    """Calls the Claude API and returns the narrative text. Any failure
    (missing key, network error, empty response) raises RuntimeError, which
    build_report.py already catches so a recap failure never blocks the rest
    of the report."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            # This is a simple narration task over facts narrative_highlights.py
            # already computed — no multi-step reasoning needed. Confirmed in
            # production that leaving Sonnet 5's default adaptive thinking on
            # let the model spend its entire max_tokens budget "thinking"
            # before ever emitting response text, since thinking tokens draw
            # from the same budget by default on this model.
            thinking={"type": "disabled"},
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        raise RuntimeError(f"Anthropic API call failed: {e}")

    text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text").strip()
    if not text:
        block_types = [getattr(b, "type", "?") for b in response.content]
        raise RuntimeError(f"Anthropic API returned no text content (stop_reason={getattr(response, 'stop_reason', '?')!r}, block_types={block_types})")
    return text
