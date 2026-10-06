"""Sub-Saharan Africa Region Review in the quarterly, half-year and annual Markets Reviews.

Real structure (read 2026-10-05): the region's growth outlook (World Bank); Currency
Performance with the "Select Sub-Saharan Africa Currency Performance vs USD" table
(Currency | Sep-25 | Jan-26 | Sep-26 | Last 12 months | YTD Change (%)); African Eurobonds
(issuance, and a chart of secondary-market yields); Equities Market Performance with the
"Equities Market Performance <period> (Dollarized*)" table; and, in the quarterly and
half-year reviews, "Global Markets and Sub-Saharan Africa Performance Summary and
Outlook" (Cytonn's views).  FY'2025 has the same parts without the summary table.

Drafted with citations: the growth outlook and the period's Eurobond issuance.  Every
table is a stub, each for a reason found in the issue itself (below).
"""

from __future__ import annotations

from typing import Any, Optional

from cytonn_weekly.common.review import build_review, check_section, narrative_block
from cytonn_weekly.common.run_events import Observer, report_blocks
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview
from cytonn_weekly.narrative.base import NarrativeProvider
from cytonn_weekly.periodic.common import PeriodContext, Stub, compose, draft_period, period_brief
from cytonn_weekly.report_types import ANNUAL, HALF_YEAR, QUARTERLY

SECTION = "ssa"
TITLE = "Sub-Saharan Africa Region Review"

CHARTS = {
    QUARTERLY: ("Select Sub-Saharan Africa Currency Performance Q3'2026 YTD Change (%)", "Select SSA Eurobonds",
                "Equities Market Performance YTD Change (Q3'2026)"),
    HALF_YEAR: ("Select Sub-Saharan Africa Currency Performance H1'2026 YTD Change (%)", "Select SSA Eurobonds",
                "Equities Market Performance YTD Change (H1'2026)"),
    ANNUAL: ("Select SSA Eurobonds",),
}

CURRENCY_BLOCKED_REASON = (
    "The table's source line is \"Yahoo Finance, Central Banks\", and Yahoo does not reproduce it: for Q3'2026 "
    "Yahoo's Kenya Shilling closes are 129.0, 128.0 and 128.7 where the issue prints CBK's 129.2, 129.1 and "
    "129.8, and its Ugandan Shilling close for end-September 2026 is 3,806.3 against the printed 3,920.0 "
    "(checked 2026-10-05). Which currency comes from which central bank, at which fixing date, is not stated."
)
CURRENCY_UNBLOCK = (
    "The analysts' per-currency source (central bank or Yahoo) and fixing dates for the ten currencies, then one "
    "fetcher per source, checked against a past issue's table."
)

EUROBOND_YIELDS_BLOCKED_REASON = (
    "The African Eurobonds yields chart is sourced \"Bloomberg, CBK\": secondary-market Eurobond yields for the "
    "other countries are Bloomberg terminal data, which this project has no access to."
)
EUROBOND_YIELDS_UNBLOCK = "A Bloomberg export of the tracked bonds' yields supplied each period, or another licensed source."

SSA_EQUITIES_BLOCKED_REASON = (
    "The dollarized equities table needs eight exchanges' index levels a year ago, at the year start and at the "
    "period end, each divided by that day's USD rate (the issue's footnote: \"index values are dollarized for "
    "ease of comparison\"). afx.kwayisi.org shows "
    "current levels only (checked for the NSE, 2026-10-02) and no historical source has been verified; the "
    "exchange rates have the same per-currency source question as the currency table."
)
SSA_EQUITIES_UNBLOCK = (
    "A verified historical index source for NGX, DSE, RSE, USE, GSE, NSE, LuSE and JSE (or the tool capturing "
    "levels at each period end), plus the currency table's sources."
)

OUTLOOK_BLOCKED_REASON = (
    "The Performance Summary and Outlook table is Cytonn's own view (neutral, positive or negative) on global "
    "and Sub-Saharan markets; the tool never writes an opinion."
)
OUTLOOK_UNBLOCK = "Nothing to unblock: this is the analysts' call, written by them."


def fetch_currency_performance(ctx: PeriodContext) -> Any:
    # TODO: needs each currency's source and fixing date (CURRENCY_UNBLOCK).
    raise NotImplementedError(CURRENCY_BLOCKED_REASON)


def fetch_eurobond_yields(ctx: PeriodContext) -> Any:
    # TODO: Bloomberg data (EUROBOND_YIELDS_UNBLOCK).
    raise NotImplementedError(EUROBOND_YIELDS_BLOCKED_REASON)


def fetch_ssa_equities(ctx: PeriodContext) -> Any:
    # TODO: needs historical index levels for eight exchanges (SSA_EQUITIES_UNBLOCK).
    raise NotImplementedError(SSA_EQUITIES_BLOCKED_REASON)


def fetch_outlook_summary(ctx: PeriodContext) -> Any:
    # TODO: Cytonn's own view; never drafted by the tool (OUTLOOK_UNBLOCK).
    raise NotImplementedError(OUTLOOK_BLOCKED_REASON)


STUBS = (
    Stub("currency_performance", "Select Sub-Saharan Africa Currency Performance vs USD", CURRENCY_BLOCKED_REASON,
         CURRENCY_UNBLOCK, fetch_currency_performance),
    Stub("eurobond_yields", "African Eurobonds: secondary-market yields", EUROBOND_YIELDS_BLOCKED_REASON,
         EUROBOND_YIELDS_UNBLOCK, fetch_eurobond_yields),
    Stub("ssa_equities", "Equities Market Performance (Dollarized)", SSA_EQUITIES_BLOCKED_REASON,
         SSA_EQUITIES_UNBLOCK, fetch_ssa_equities),
    Stub("outlook_summary", "Global Markets and Sub-Saharan Africa Performance Summary and Outlook",
         OUTLOOK_BLOCKED_REASON, OUTLOOK_UNBLOCK, fetch_outlook_summary),
)


def briefs(ctx: PeriodContext):
    return [
        period_brief(ctx, "growth", TITLE, "Sub-Saharan Africa growth outlook",
                     "the World Bank's (or IMF's) latest growth projection for Sub-Saharan Africa, with the risks it "
                     "names (inflation, debt distress, commodity prices)", preferred_domains=("worldbank.org", "imf.org")),
        period_brief(ctx, "eurobonds", TITLE, "African Eurobonds",
                     "Eurobond issues by Sub-Saharan African governments during the period: issuer, amount raised, "
                     "tenor and coupon or yield"),
    ]


def build_ssa_review(ctx: PeriodContext, provider: Optional[NarrativeProvider] = None,
                     on_event: Optional[Observer] = None) -> CoordinatorReview:
    """Two cited narratives, the rest stubs.  ``on_event`` (common/run_events.py) is told each step as it happens."""
    bs = briefs(ctx)
    draft = draft_period(bs, len(bs), ctx, provider, on_event)
    pieces = {p["brief_id"]: narrative_block(f"subsection_{p['brief_id']}", p) for p in draft["pieces"]}
    stubs = {s.id: s.block() for s in STUBS}
    blocks = [b for b in (pieces.get("growth"), stubs["currency_performance"], pieces.get("eurobonds"),
                          stubs["eurobond_yields"], stubs["ssa_equities"]) if b]
    if ctx.report_type != ANNUAL:  # FY'2025 has no summary-and-outlook table here
        blocks.append(stubs["outlook_summary"])
    content = compose(SECTION, TITLE, ctx, blocks, draft=draft, expected=len(bs), charts=CHARTS)
    report_blocks(on_event, content)
    return build_review(content, check_section(content, on_event))
