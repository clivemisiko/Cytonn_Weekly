"""Global Markets Review in the quarterly, half-year and annual Markets Reviews.

Real structure, the same in Q3'2026, H1'2026 and FY'2025 (read 2026-10-05): Global
Economic Growth (the World Bank's Global Economic Prospects against the IMF's World
Economic Outlook), Global Commodities Market Performance (the World Bank commodity price
indices, as a chart), Global Equities Market Performance (as a chart).  There is no table.

All three are drafted with citations, preferring the World Bank and IMF for growth and
commodities.  The charts are listed for the coordinator; the tool does not draw them.
"""

from __future__ import annotations

from typing import Optional

from cytonn_weekly.common.review import build_review, check_section, narrative_block
from cytonn_weekly.common.run_events import Observer, report_blocks
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview
from cytonn_weekly.narrative.base import NarrativeProvider
from cytonn_weekly.periodic.common import PeriodContext, compose, draft_period, period_brief
from cytonn_weekly.report_types import ANNUAL, HALF_YEAR, QUARTERLY

SECTION = "global_markets"
TITLE = "Global Markets Review"

CHARTS = {
    QUARTERLY: ("World Bank Commodity Price Index", "Q3' 2026 Global Equities Markets Performance"),
    HALF_YEAR: ("World Bank Commodity Price Index", "H1'2026 Global Equities Markets Performance"),
    ANNUAL: ("2025 World Bank Commodity Price Index", "Global Equities Market Performance"),
}

STUBS = ()  # nothing in this section lacks a public source


def briefs(ctx: PeriodContext):
    return [
        period_brief(ctx, "growth", TITLE, "Global Economic Growth",
                     "the World Bank's latest Global Economic Prospects projection for global growth (and for advanced "
                     "and emerging market and developing economies) set against the IMF's latest World Economic "
                     "Outlook or its update, with the drivers each names", preferred_domains=("worldbank.org", "imf.org"),
                     words=(150, 300)),
        period_brief(ctx, "commodities", TITLE, "Global Commodities Market Performance",
                     "how the World Bank's commodity price indices (energy, non-energy, agriculture, fertilizers, "
                     "metals and minerals, precious metals) moved over the period, and why",
                     preferred_domains=("worldbank.org",)),
        period_brief(ctx, "equities", TITLE, "Global Equities Market Performance",
                     "how the major global and regional stock market indices performed over the period, and the "
                     "large stocks that drove them"),
    ]


def build_global_markets_review(ctx: PeriodContext, provider: Optional[NarrativeProvider] = None,
                                on_event: Optional[Observer] = None) -> CoordinatorReview:
    """A cited narrative per subsection.  ``on_event`` (common/run_events.py) is told each step as it happens."""
    bs = briefs(ctx)
    draft = draft_period(bs, len(bs), ctx, provider, on_event)
    blocks = [narrative_block(f"subsection_{p['brief_id']}", p) for p in draft["pieces"]]
    content = compose(SECTION, TITLE, ctx, blocks, draft=draft, expected=len(bs), charts=CHARTS)
    report_blocks(on_event, content)
    return build_review(content, check_section(content, on_event))
