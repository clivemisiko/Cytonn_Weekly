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

import re
from dataclasses import replace
from datetime import date
from typing import Any, Callable, Optional

from cytonn_weekly.common.review import build_review, check_section, grouped, narrative_block, numbered, table_block
from cytonn_weekly.common.run_events import Observer, fetch_source, report_blocks
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview
from cytonn_weekly.narrative.base import NarrativeBrief, NarrativeProvider
from cytonn_weekly.narrative.drafter import draft_pieces
from cytonn_weekly.real_estate import fetcher

SECTION = "real_estate"
TITLE = "Real Estate"
N_SUBSECTIONS = 4

# The team's preferred sites (supplied by the owner, 2026-10-29), searched first by every brief after its own.
_PREFERRED_SITES_TEXT = """
nation.africa
businessdailyafrica.com
standardmedia.co.ke
bloomberg.com
"""
_HOST = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)+")
# Social media is never a cited source: left out of the open-web pass.
SOCIAL_DOMAINS = ("x.com", "twitter.com", "facebook.com", "instagram.com", "tiktok.com")


def preferred_sites(text: str) -> tuple[str, ...]:
    """One lowercase hostname a line (no scheme, path or space, at least one dot), duplicates dropped.

    ValueError naming every refused line."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    bad = [line for line in lines if not _HOST.fullmatch(line)]
    if bad:
        raise ValueError("not a lowercase hostname: " + ", ".join(repr(b) for b in bad))
    return tuple(dict.fromkeys(lines))


PREFERRED_SITES = preferred_sites(_PREFERRED_SITES_TEXT)

_KENYA = "in Kenya, published during the report week"
_BRIEFS: list[NarrativeBrief] = [
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
BRIEFS: list[NarrativeBrief] = [
    replace(b, preferred_domains=tuple(dict.fromkeys(b.preferred_domains + PREFERRED_SITES)), blocked_domains=SOCIAL_DOMAINS)
    for b in _BRIEFS
]


# The issue's group headings (issues 891, 893, 894, 895).  "Commercial Sector" has not been seen in an issue yet.
GROUPS = {"residential": "Residential Sector", "affordable_housing": "Residential Sector",
          "hospitality": "Hospitality Sector", "infrastructure": "Infrastructure Sector",
          "land": "Land Sector", "commercial": "Commercial Sector"}
REITS_GROUP = "Real Estate Investment Trusts (REITs)"


def group_of(block: dict[str, Any]) -> Optional[str]:
    if block.get("id") == "reits":
        return REITS_GROUP
    return GROUPS.get(block.get("brief_id")) if block.get("kind") == "narrative" else None


def layout(section: dict[str, Any], report_type: str) -> list[dict[str, Any]]:
    """The section's blocks as the weekly prints them: numbered groups, lettered stories, REITs last.

    Worked out when shown, never stored, so a review saved before groups existed shows them too.  Every
    other section, and the Markets Reviews' Real Estate, get their blocks back unchanged.
    """
    blocks = section.get("blocks", [])
    if report_type != "weekly" or section.get("section") != SECTION:
        return blocks
    return grouped(blocks, group_of, REITS_GROUP)


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
