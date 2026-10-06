"""Runs the Equities pipeline up to the coordinator's review.

    fetch market performance -> draft weekly highlights -> compose -> check -> review

Same shape as digital_payments/review_run.py.  The section follows the real
report's order: Market Performance (indices, weekly top gainers and losers, then
the market-activity figures this tool cannot source yet), Universe of Coverage
(a stub: Cytonn's own research), Weekly Highlights.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Optional

from cytonn_weekly.common.review import (
    build_review,
    check_section,
    narrative_block,
    numbered,
    table_block,
    unavailable_block,
)
from cytonn_weekly.common.run_events import Observer, fetch_source, report_blocks, report_failed_rows
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview
from cytonn_weekly.equities import fetcher, stubs
from cytonn_weekly.narrative.base import NarrativeBrief, NarrativeProvider
from cytonn_weekly.narrative.drafter import draft_pieces

SECTION = "equities"
TITLE = "Equities"
N_HIGHLIGHTS = 3

BRIEFS: list[NarrativeBrief] = [
    NarrativeBrief(
        id="earnings", section=TITLE, label="Listed company earnings and dividends",
        focus=("an earnings release, profit warning, dividend declaration or similar financial result announced "
               "by a company listed on the Nairobi Securities Exchange"),
        preferred_domains=("nse.co.ke",),
    ),
    NarrativeBrief(
        id="corporate_actions", section=TITLE, label="Corporate actions and deals",
        focus=("a rights issue, acquisition, merger, listing, delisting, share buyback or strategic transaction "
               "involving a Nairobi Securities Exchange-listed company"),
    ),
    NarrativeBrief(
        id="banking", section=TITLE, label="Listed banks",
        focus=("a development specific to a Kenyan listed bank or the banking sector as a whole (capital, "
               "regulation by the Central Bank of Kenya, asset quality, a major lending or funding deal)"),
        preferred_domains=("centralbank.go.ke",),
    ),
    NarrativeBrief(
        id="market_regulation", section=TITLE, label="Capital markets regulation",
        focus=("a policy, rule or market-structure change announced by the Capital Markets Authority or the "
               "Nairobi Securities Exchange"),
        preferred_domains=("cma.or.ke", "nse.co.ke"),
    ),
]


def _table(block_id: str, title: str, columns, rows, key: str, label: str, as_of: Optional[str]) -> dict[str, Any]:
    return table_block(block_id, title, columns, rows, key, label,
                       {"name": fetcher.SOURCE_NAME, "url": fetcher.BASE, "as_of": as_of})


TABLE_TITLES = (("indices", "Market Performance: NSE indices"), ("gainers", "Weekly top gainers"),
                ("losers", "Weekly top losers"))


def compose(market: Optional[dict[str, Any]], draft: dict[str, Any], down: Optional[str] = None) -> dict[str, Any]:
    """``market`` is None when afx could not be reached; ``down`` is then why (fetcher.down_reason)."""
    titles = dict(TABLE_TITLES)
    warnings = list(draft["warnings"])
    if market is None:
        blocks: list[dict[str, Any]] = [unavailable_block(bid, title, down, fetcher.DOWN_UNBLOCK)
                                        for bid, title in TABLE_TITLES]
        warnings.append(f"{fetcher.SOURCE_NAME} could not be reached: the index, gainers and losers tables are "
                        "not in this draft.")
    else:
        gainers, losers = fetcher.top_movers(market["shares"])
        as_of = market.get("as_of")
        blocks = [
            _table("indices", titles["indices"], fetcher.INDEX_COLUMNS, market["indices"], "index", "name", as_of),
            _table("gainers", titles["gainers"], fetcher.MOVER_COLUMNS, gainers, "ticker", "company", as_of),
            _table("losers", titles["losers"], fetcher.MOVER_COLUMNS, losers, "ticker", "company", as_of),
        ]
        failed = [s["ticker"] for s in market["shares"] if s.get("error")]
        if failed:
            warnings.append(f"{len(failed)} share page(s) failed and are left out of the gainers/losers: {', '.join(failed)}")
        intraday = fetcher.intraday_warning(as_of)
        if intraday:
            warnings.append(intraday)
    blocks += [
        unavailable_block("market_activity", stubs.MARKET_ACTIVITY_TITLE, stubs.MARKET_ACTIVITY_REASON,
                          stubs.MARKET_ACTIVITY_UNBLOCK),
        unavailable_block("universe_of_coverage", stubs.UNIVERSE_TITLE, stubs.UNIVERSE_REASON, stubs.UNIVERSE_UNBLOCK),
    ]
    blocks += [narrative_block(f"highlight_{p['brief_id']}", p) for p in draft["pieces"]]
    return {
        "section": SECTION, "title": TITLE, "week_start": draft["week_start"], "week_end": draft["week_end"],
        "blocks": numbered(blocks), "pieces_found": len(draft["pieces"]), "pieces_expected": N_HIGHLIGHTS,
        "shortfall": draft["shortfall"], "warnings": warnings,
    }


def build_equities_review(
    provider: Optional[NarrativeProvider] = None,
    today: Optional[date] = None,
    fetch_market: Callable[[], dict[str, Any]] = fetcher.fetch_market_performance,
    on_event: Optional[Observer] = None,
) -> CoordinatorReview:
    """Fetch, draft, check; return the review.  Provider errors propagate.

    afx being down (fetcher.SOURCE_DOWN_ERRORS) does not stop the draft: its three tables
    become ``unavailable`` parts and the highlights are still drafted.  Any other fetch
    error propagates.

    ``on_event`` (common/run_events.py) is told each step as it happens.
    """
    market, down = None, None
    try:
        market = fetch_source(on_event, fetcher.SOURCE_NAME, fetch_market)
    except fetcher.SOURCE_DOWN_ERRORS as exc:
        down = fetcher.down_reason(exc)
    else:
        report_failed_rows(on_event, market["shares"], lambda s: f"{fetcher.SOURCE_NAME}: {s['ticker']} share page")
    draft = draft_pieces(BRIEFS, N_HIGHLIGHTS, provider=provider, today=today, on_event=on_event)
    content = compose(market, draft, down)
    report_blocks(on_event, content)
    return build_review(content, check_section(content, on_event))
