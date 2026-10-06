"""Real Estate in the quarterly, half-year and annual Markets Reviews.

Real structure (read 2026-10-05), the same full sectoral review in Q3'2026, H1'2026 and
FY'2025: the sector's contribution to GDP (KNBS) and the period's initiatives;
construction financing; Sectoral Market Performance: Industry Report (table, Q3/H1),
Leading Economic Indicators (cement consumption, Q3), Residential (Detached Units and
Apartments performance tables), Commercial Office, Retail, Hospitality, Land (tables),
Infrastructure, Real Estate Investment Trusts, then "Real Estate Performance Summary and
Outlook" (table).  FY'2025 adds Mixed-Use Developments and the Industrial Sector, and an
annual rental yields summary table.

Built here: the REITs table (the weekly Ibuka fetcher; Q3'2026 itself quotes the 25
September summary), the sector overview and each sector's period developments, drafted
with citations.  The NMA market tables are Cytonn's own market research and are one stub.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any, Callable, Optional

from cytonn_weekly.common.review import build_review, check_section, narrative_block, table_block
from cytonn_weekly.common.run_events import Observer, fetch_source, report_blocks
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview
from cytonn_weekly.narrative.base import NarrativeProvider
from cytonn_weekly.periodic.common import PeriodContext, Stub, compose, draft_period, period_brief
from cytonn_weekly.real_estate import fetcher
from cytonn_weekly.real_estate.review_run import BRIEFS as WEEKLY_BRIEFS
from cytonn_weekly.report_types import ANNUAL, HALF_YEAR, QUARTERLY

SECTION = "real_estate"
TITLE = "Real Estate"
N_PIECES = 5

CHARTS = {
    QUARTERLY: ("Real Estate and Construction sector contribution to GDP (2021-Q1’2026)",
                "Construction Financing in Kenya vs Developed Economies", "Cement Consumption in Metric Tonnes"),
    HALF_YEAR: ("Real Estate and Construction sector contribution to GDP (2020-2025)",
                "Construction Financing in Kenya vs Developed Economies"),
    ANNUAL: ("Real Estate and Construction Sector contribution to GDP (2020-Q2'2025)",
             "Number of Visitor Arrivals via JKIA and MIA"),
}

RESEARCH_TABLES_BLOCKED_REASON = (
    "The Nairobi Metropolitan Area market tables (Residential Sector Summary, Detached Units and Apartments "
    "summaries, Commercial Office returns and submarket performance, Retail summary and submarkets, Land "
    "performance by submarket; in FY'2025 also Mixed-Use Developments and the annual rental yields summary) and "
    "the Thematic Performance and Outlook table are Cytonn Research's own surveys and views, with no public source."
)
RESEARCH_TABLES_UNBLOCK = "Cytonn's Real Estate research team sharing the period's survey tables in a fixed, readable format."

LEI_BLOCKED_REASON = (
    "Q3'2026's Leading Economic Indicators part (cement consumption, from KNBS's monthly LEI release) needs a "
    "parser for that PDF, whose layout has not been inspected."
)
LEI_UNBLOCK = "One real KNBS Leading Economic Indicators PDF as the reference sample, then a parser for its cement table."


def fetch_research_tables(ctx: PeriodContext) -> Any:
    # TODO: Cytonn Research's own surveys (RESEARCH_TABLES_UNBLOCK).
    raise NotImplementedError(RESEARCH_TABLES_BLOCKED_REASON)


def fetch_leading_indicators(ctx: PeriodContext) -> Any:
    # TODO: needs a real LEI PDF sample (LEI_UNBLOCK).
    raise NotImplementedError(LEI_BLOCKED_REASON)


STUBS = (
    Stub("research_tables", "Sectoral market performance tables and outlook (Cytonn Research)",
         RESEARCH_TABLES_BLOCKED_REASON, RESEARCH_TABLES_UNBLOCK, fetch_research_tables),
    Stub("leading_indicators", "Leading Economic Indicators: cement consumption", LEI_BLOCKED_REASON, LEI_UNBLOCK,
         fetch_leading_indicators),
)

_WEEKLY_PHRASE = "in Kenya, published during the report week"


def briefs(ctx: PeriodContext):
    overview = period_brief(ctx, "overview", TITLE, "Sector overview",
                            "the Real Estate and Construction sectors' contribution to Kenya's GDP as published by "
                            "KNBS, and government initiatives that shaped the sector",
                            preferred_domains=("knbs.or.ke",))
    themes = [
        replace(b, focus=b.focus.replace(_WEEKLY_PHRASE, "in Kenya"), opener=None, words=(120, 260),
                report=ctx.report_name, window="report period")
        for b in WEEKLY_BRIEFS
    ]
    # The weekly briefs' own wording names the week; restate the period the same way period_brief does.
    themes = [replace(b, focus=f"{b.focus}, during {ctx.prose}") for b in themes]
    return [overview] + themes


def build_real_estate_review(
    ctx: PeriodContext,
    provider: Optional[NarrativeProvider] = None,
    fetch_reits: Callable[[Optional[date]], dict[str, Any]] = fetcher.fetch_reits,
    on_event: Optional[Observer] = None,
) -> CoordinatorReview:
    """The cited overview and themes over the period, the Ibuka REITs table, the rest stubs.

    ``on_event`` (common/run_events.py) is told each step as it happens.
    """
    draft = draft_period(briefs(ctx), N_PIECES, ctx, provider, on_event)
    reits = fetch_source(on_event, fetcher.SOURCE_NAME, fetch_reits, ctx.today)
    pieces = [narrative_block(f"subsection_{p['brief_id']}", p) for p in draft["pieces"]]
    stubs = {s.id: s.block() for s in STUBS}
    blocks = pieces[:1] + [stubs["research_tables"]]
    if ctx.report_type == QUARTERLY:
        blocks.append(stubs["leading_indicators"])
    blocks += pieces[1:]
    blocks.append(table_block("reits", "Real Estate Investments Trusts (REITs)", fetcher.COLUMNS, reits["rows"],
                              "reit", "name", {"name": fetcher.SOURCE_NAME, "url": reits["source_url"],
                                               "as_of": reits["as_of"]}))
    content = compose(SECTION, TITLE, ctx, blocks, draft=draft, expected=N_PIECES,
                      warnings=list(reits["warnings"]), charts=CHARTS)
    report_blocks(on_event, content)
    return build_review(content, check_section(content, on_event))
