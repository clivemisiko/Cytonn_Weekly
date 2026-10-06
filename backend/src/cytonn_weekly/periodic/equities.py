"""Equities in the quarterly, half-year and annual Markets Reviews.

Real structure (read 2026-10-05):

* Q3'2026 and H1'2026: Market Performance (the period's and the week's index moves, the
  banking index over the period, the large caps that drove them, turnover and foreign
  flows, and the market P/E and dividend yield charts); Universe of Coverage (table);
  "Kenyan Q3'2026 Equities Outlook" with the "Equities Outlook Summary" table (Cytonn's
  views); "Notable Highlights in Q3'2026".
* FY'2025 adds a long results review: Banking Sector Earnings and Insurance Sector
  Earnings (tables), profit warnings, Listings and Suspensions, Liquidations, Legislation
  and Other Developments, Share Purchase and Consolidation.

Built here: the NSE index table (levels, week and year-to-date moves, from afx.kwayisi.org
through the weekly fetcher's own parser), which carries the week and YTD figures the
review's prose quotes, and the period's highlights drafted with citations.  The period's
own index changes and everything Cytonn's research supplies are stubs.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from cytonn_weekly.common.http import http_get
from cytonn_weekly.common.review import build_review, check_section, narrative_block, table_block, unavailable_block
from cytonn_weekly.common.run_events import Observer, fetch_source, report_blocks
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview
from cytonn_weekly.equities import fetcher, stubs as weekly_stubs
from cytonn_weekly.narrative.base import NarrativeProvider
from cytonn_weekly.periodic.common import PeriodContext, Stub, compose, draft_period, period_brief
from cytonn_weekly.report_types import ANNUAL, HALF_YEAR, QUARTERLY

SECTION = "equities"
TITLE = "Equities"
N_HIGHLIGHTS = 3

CHARTS = {
    QUARTERLY: ("NASI P/E", "NASI Dividend Yield"),
    HALF_YEAR: ("NASI P/E", "NASI Dividend Yield"),
    ANNUAL: ("NASI P/E", "NASI Dividend Yield", "Banking Sector Return on Equity (ROE)",
             "Number of Companies that Issued Profit Warnings", "Total Number of Listed Companies at the NSE"),
}

PERIOD_INDICES_BLOCKED_REASON = (
    "The period's own index changes (e.g. \"During Q3’2026 ... NSE 20, NSE 10, NSE 25, and NASI gaining by 15.0%, "
    "13.5%, 12.4%, and 9.6%\", and the banking index \"to 288.9 from 255.1 recorded the previous quarter\") need "
    "each index's level at the end of the previous period. afx.kwayisi.org shows today's level, the week's and "
    "the year's change only (checked 2026-10-02), and no historical source has been verified."
)
PERIOD_INDICES_UNBLOCK = (
    "A verified source of NSE index history, or the tool recording each index's level at every period end "
    "(a scheduled fetch on the last trading day of each quarter)."
)

OUTLOOK_BLOCKED_REASON = (
    "The Equities Outlook Summary table is Cytonn's own view (positive, neutral or negative) on each market "
    "indicator; the tool never writes an opinion."
)
OUTLOOK_UNBLOCK = "Nothing to unblock: this is the analysts' call, written by them."

RESULTS_REVIEW_BLOCKED_REASON = (
    "The annual results review (Kenyan Listed Banks and Listed Insurance Companies performance tables, profit "
    "warnings, listings and suspensions, banking sector deals) computes Cytonn's own metrics (core EPS growth, "
    "NIM, ROE, ranking inputs) across every listed bank and insurer, from each company's results; it is "
    "Cytonn's research, not one public table."
)
RESULTS_REVIEW_UNBLOCK = "Cytonn's earnings-review sheets for the year, in a fixed format the tool can read."


def fetch_period_index_changes(ctx: PeriodContext) -> Any:
    # TODO: needs index history (PERIOD_INDICES_UNBLOCK).
    raise NotImplementedError(PERIOD_INDICES_BLOCKED_REASON)


def fetch_equities_outlook(ctx: PeriodContext) -> Any:
    # TODO: Cytonn's own view; never drafted by the tool (OUTLOOK_UNBLOCK).
    raise NotImplementedError(OUTLOOK_BLOCKED_REASON)


def fetch_results_review(ctx: PeriodContext) -> Any:
    # TODO: needs Cytonn's earnings-review sheets (RESULTS_REVIEW_UNBLOCK).
    raise NotImplementedError(RESULTS_REVIEW_BLOCKED_REASON)


STUBS = (
    Stub("period_index_changes", "Market Performance: the period's index changes", PERIOD_INDICES_BLOCKED_REASON,
         PERIOD_INDICES_UNBLOCK, fetch_period_index_changes),
    Stub("market_activity", weekly_stubs.MARKET_ACTIVITY_TITLE, weekly_stubs.MARKET_ACTIVITY_REASON,
         weekly_stubs.MARKET_ACTIVITY_UNBLOCK, weekly_stubs.fetch_market_activity),
    Stub("universe_of_coverage", weekly_stubs.UNIVERSE_TITLE, weekly_stubs.UNIVERSE_REASON,
         weekly_stubs.UNIVERSE_UNBLOCK, weekly_stubs.fetch_universe_of_coverage),
    Stub("equities_outlook", "Equities Outlook Summary", OUTLOOK_BLOCKED_REASON, OUTLOOK_UNBLOCK,
         fetch_equities_outlook),
    Stub("results_review", "Banking and insurance earnings, profit warnings, listings and deals",
         RESULTS_REVIEW_BLOCKED_REASON, RESULTS_REVIEW_UNBLOCK, fetch_results_review),
)


def fetch_indices(get: Callable[[str], bytes] = http_get) -> dict[str, Any]:
    """NSE index levels with week and year-to-date changes: the weekly fetcher's parse of afx's NSE page, no share pages."""
    html = get(fetcher.BASE).decode("utf-8", errors="replace")
    return {"as_of": fetcher.parse_as_of(html), "indices": fetcher.parse_indices(html)}


def briefs(ctx: PeriodContext):
    return [
        period_brief(ctx, "corporate", TITLE, "Listed company results and corporate actions",
                     "earnings releases, dividends, profit warnings, rights issues, acquisitions, listings or "
                     "suspensions involving companies listed on the Nairobi Securities Exchange",
                     preferred_domains=("nse.co.ke",)),
        period_brief(ctx, "banking", TITLE, "Listed banks",
                     "developments specific to Kenya's listed banks or the banking sector (capital, Central Bank of "
                     "Kenya regulation, asset quality, major deals)", preferred_domains=("centralbank.go.ke",)),
        period_brief(ctx, "regulation", TITLE, "Capital markets regulation",
                     "policy, rule or market-structure changes by the Capital Markets Authority or the Nairobi "
                     "Securities Exchange", preferred_domains=("cma.or.ke", "nse.co.ke")),
    ]


def build_equities_review(
    ctx: PeriodContext,
    provider: Optional[NarrativeProvider] = None,
    fetch: Callable[[], dict[str, Any]] = fetch_indices,
    on_event: Optional[Observer] = None,
) -> CoordinatorReview:
    """The afx index table, the period's cited highlights, the rest stubs.

    ``on_event`` (common/run_events.py) is told each step as it happens.
    """
    title = "Market Performance: NSE indices (week and year to date)"
    warnings = []
    try:
        market = fetch_source(on_event, fetcher.SOURCE_NAME, fetch)
    except fetcher.SOURCE_DOWN_ERRORS as exc:  # afx down: the table is a missing part, the draft goes on
        table = unavailable_block("indices", title, fetcher.down_reason(exc), fetcher.DOWN_UNBLOCK)
        warnings.append(f"{fetcher.SOURCE_NAME} could not be reached: the index table is not in this draft.")
    else:
        table = table_block("indices", title, fetcher.INDEX_COLUMNS, market["indices"], "index", "name",
                            {"name": fetcher.SOURCE_NAME, "url": fetcher.BASE, "as_of": market.get("as_of")})
        warnings += [w for w in [fetcher.intraday_warning(market.get("as_of"))] if w]
    draft = draft_period(briefs(ctx), N_HIGHLIGHTS, ctx, provider, on_event)
    stubs = {s.id: s.block() for s in STUBS}
    blocks = [stubs["period_index_changes"], table, stubs["market_activity"]]
    if ctx.report_type == ANNUAL:
        blocks.append(stubs["results_review"])
    blocks.append(stubs["universe_of_coverage"])
    if ctx.report_type != ANNUAL:  # FY'2025 closes on the Universe of Coverage, with no outlook table
        blocks.append(stubs["equities_outlook"])
    blocks += [narrative_block(f"highlight_{p['brief_id']}", p) for p in draft["pieces"]]
    content = compose(SECTION, TITLE, ctx, blocks, draft=draft, expected=N_HIGHLIGHTS, warnings=warnings,
                      charts=CHARTS)
    report_blocks(on_event, content)
    return build_review(content, check_section(content, on_event))
