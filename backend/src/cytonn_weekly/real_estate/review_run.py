"""Runs the Real Estate pipeline up to the coordinator's review.

    draft rotating subsections -> fetch REIT prices -> compose -> check -> review

Which subsections lead varies week to week (Cytonn Weekly #38.2026 ran
residential/mortgage lending, an affordable-housing funding gap, hospitality,
infrastructure, then REITs), so they are drafted like Digital Payments'
highlights but from themed briefs instead of a company list: each theme is
searched broadly for the week, a theme with nothing that week is skipped, and
the section always closes with the REITs table.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Optional

from cytonn_weekly.common.review import build_review, check_section, narrative_block, numbered, table_block
from cytonn_weekly.common.run_events import Observer, fetch_source, report_blocks
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview
from cytonn_weekly.narrative.base import NarrativeBrief, NarrativeProvider
from cytonn_weekly.narrative.drafter import draft_pieces
from cytonn_weekly.real_estate import fetcher

SECTION = "real_estate"
TITLE = "Real Estate"
N_SUBSECTIONS = 4

_KENYA = "in Kenya, published during the report week"
BRIEFS: list[NarrativeBrief] = [
    NarrativeBrief(
        id="residential", section=TITLE, label="Residential and mortgage lending",
        focus=f"mortgage lending statistics, mortgage products or residential property market data {_KENYA}",
        preferred_domains=("centralbank.go.ke", "kba.co.ke", "kmrc.co.ke"),
    ),
    NarrativeBrief(
        id="affordable_housing", section=TITLE, label="Affordable housing",
        focus=f"affordable housing programme funding, delivery, policy or levy developments {_KENYA}",
        preferred_domains=("housing.go.ke", "bomayangu.go.ke"),
    ),
    NarrativeBrief(
        id="hospitality", section=TITLE, label="Hospitality and tourism",
        focus=f"hotel, tourism arrivals, tourism earnings or hospitality investment developments {_KENYA}",
        preferred_domains=("tourism.go.ke", "ktb.go.ke"),
    ),
    NarrativeBrief(
        id="infrastructure", section=TITLE, label="Infrastructure",
        focus=f"road, rail, port, energy or urban infrastructure project financing or delivery {_KENYA}",
    ),
    NarrativeBrief(
        id="commercial", section=TITLE, label="Commercial office, retail and industrial",
        focus=f"office, retail mall, warehouse or industrial property market data or major transactions {_KENYA}",
    ),
    NarrativeBrief(
        id="land", section=TITLE, label="Land",
        focus=f"land prices, land policy or land-registration developments {_KENYA}",
    ),
]


def compose(draft: dict[str, Any], reits: dict[str, Any]) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = [narrative_block(f"subsection_{p['brief_id']}", p) for p in draft["pieces"]]
    blocks.append(table_block("reits", "REITs weekly performance", fetcher.COLUMNS, reits["rows"], "reit", "name",
                              {"name": fetcher.SOURCE_NAME, "url": reits["source_url"], "as_of": reits["as_of"]}))
    return {
        "section": SECTION, "title": TITLE, "week_start": draft["week_start"], "week_end": draft["week_end"],
        "blocks": numbered(blocks), "pieces_found": len(draft["pieces"]), "pieces_expected": N_SUBSECTIONS,
        "shortfall": draft["shortfall"], "warnings": list(draft["warnings"]) + list(reits["warnings"]),
    }


def build_real_estate_review(
    provider: Optional[NarrativeProvider] = None,
    today: Optional[date] = None,
    fetch_reits: Callable[[Optional[date]], dict[str, Any]] = fetcher.fetch_reits,
    on_event: Optional[Observer] = None,
) -> CoordinatorReview:
    """Fetch, draft, check; return the review.  Provider and fetch errors propagate.

    ``on_event`` (common/run_events.py) is told each step as it happens.
    """
    draft = draft_pieces(BRIEFS, N_SUBSECTIONS, provider=provider, today=today, on_event=on_event)
    content = compose(draft, fetch_source(on_event, fetcher.SOURCE_NAME, fetch_reits, today))
    report_blocks(on_event, content)
    return build_review(content, check_section(content, on_event))
