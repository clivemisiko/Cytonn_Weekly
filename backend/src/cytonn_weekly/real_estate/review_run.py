"""Runs the weekly Real Estate pipeline up to the analyst's review.

    confirmed snips -> draft each sector from its own snips -> fetch REIT prices -> compose -> check -> review

The weekly section is written only from the images the analyst uploaded and confirmed (real_estate/snips.py), one
sector at a time; nothing is searched for it.  A sector with no confirmed snip is left out and says so.  The REITs
sector is the Ibuka table, the standing text carried from the newest saved review, and a closing outlook.  ``BRIEFS``
and ``GROUPS`` are the web-search themes the Markets Reviews' Real Estate still uses (periodic/real_estate.py).
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import replace
from datetime import date
from typing import Any, Callable, Optional

from cytonn_weekly.common import sources as source_store
from cytonn_weekly.common.computed import carried_block, show
from cytonn_weekly.common.formatting import PCT, PRICE
from cytonn_weekly.common.review import build_review, check_section, grouped, narrative_block, numbered, table_block, unavailable_block
from cytonn_weekly.common.run_events import Observer, fetch_source, report_blocks
from cytonn_weekly.digital_payments import review_store
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview
from cytonn_weekly.narrative.base import NarrativeBrief, NarrativeProvider
from cytonn_weekly.narrative.drafter import draft_pieces
from cytonn_weekly.narrative.factory import get_narrative_provider
from cytonn_weekly.real_estate import fetcher, snips
from cytonn_weekly.weekly.week import latest_friday

log = logging.getLogger(__name__)
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

# The sources the investments team named on 2026-10-30.
_KNIGHT_FRANK = ("knightfrank.com", "content.knightfrank.com")
_HASS_CONSULT = "hassconsult.co.ke"   # to be confirmed by Clive
_KENYA = "in Kenya, published during the report week"
_BRIEFS: list[NarrativeBrief] = [
    NarrativeBrief(
        id="residential", section=TITLE, label="Residential and mortgage lending",
        focus=f"mortgage lending statistics, mortgage products or residential property market data {_KENYA}",
        preferred_domains=("centralbank.go.ke", "kba.co.ke", "kmrc.co.ke", "knbs.or.ke", *_KNIGHT_FRANK, _HASS_CONSULT),
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
        preferred_domains=_KNIGHT_FRANK,
    ),
    NarrativeBrief(
        id="land", section=TITLE, label="Land",
        focus=f"land prices, land policy or land-registration developments {_KENYA}",
        preferred_domains=(_HASS_CONSULT,),
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
    if block.get("sector") in snips.LABELS:
        return snips.LABELS[block["sector"]]
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
    sectored = any(b.get("sector") for b in blocks)
    return grouped(blocks, group_of, snips.LABELS["reits"] if sectored else REITS_GROUP)


FACTS_ONLY = ("Write only from facts that appear in the supplied sources: a figure, a named proposal or a named event. Every "
              "sentence must rest on one of them and be quoted. Leave out any sentence you cannot support, and make no "
              "general statement, forecast or advice that the sources do not state.")
SNIP_FOCUS = "the figures, named proposals and named events printed in the analyst's snips for this sector"
OUTLOOK_FOCUS = ("what this week's REIT prices and the snips' facts mean for the REITs sector, as the section's closing "
                 "outlook, in one short paragraph")
SECTOR_BRIEFS: list[NarrativeBrief] = [
    NarrativeBrief(id=sid, section=TITLE, label=label, focus=SNIP_FOCUS, opener=None, context=FACTS_ONLY)
    for sid, label in snips.SECTORS if sid != "reits"
] + [NarrativeBrief(id="reits", section=TITLE, label=snips.LABELS["reits"], focus=OUTLOOK_FOCUS, opener=None, words=(60, 120),
                    headed=False, context=FACTS_ONLY)]

NEEDS_BEDROCK = ("The weekly Real Estate section is written from the snips you upload, and reading and drafting them needs "
                 "the production model on Amazon Bedrock (CYTONN_LLM_PROVIDER=bedrock). This server is not using it, so nothing was drafted.")
NO_SNIP = "No snip was uploaded and confirmed for this sector, so it is not included."
UNBLOCK = "Upload a snip for this sector on the start screen, read and confirm it, then draft again."
PLACEHOLDER = "Analyst to add the standing text"


def ibuka_text(reits: dict[str, Any]) -> str:
    """The Ibuka figures as plain sentences, saved as a source so the outlook can quote them like a snip."""
    rows = [r for r in reits["rows"] if r.get("price") is not None]
    return "\n".join([f"NSE Unquoted Securities Platform (Ibuka) weekly summary as at {reits['as_of']}."] + [
        f"{r['name']}: closing unit price Kshs {show(r['price'], PRICE, 1)}; change from the Kshs 20.0 inception price "
        f"{show(r['inception_gain_pct'], PCT, 1)}." for r in rows])


def standing_block(previous: Optional[CoordinatorReview]) -> dict[str, Any]:
    """The REITs standing text (the benefits paragraph and the list of challenges), copied from the newest saved Real Estate
    review, never written by the model; with none saved, a placeholder the analyst fills in by editing the paragraph."""
    old = next((b for b in (previous.section.get("blocks", []) if previous else [])
                if b.get("id") == "standing" and b.get("kind") == "carried" and not b.get("placeholder")), None)
    extra = {"sector": "reits", "role": "standing"}
    if old is None:
        return {**carried_block("standing", "Standing text: the benefits of REITs and their challenges", PLACEHOLDER,
                                {"note": "no earlier Real Estate review holds this text; type it by editing this paragraph"}),
                **extra, "placeholder": True}
    week = previous.section.get("week_end")
    return {**carried_block("standing", old["title"], old["body_md"],
                            {"published": week, "note": f"taken from this tool's saved Real Estate review (run {previous.run_id}, "
                                                        f"week ending {week}); the text does not change from week to week"}), **extra}


def compose(draft: dict[str, Any], reits: dict[str, Any], previous: Optional[CoordinatorReview] = None,
            have: Optional[set[str]] = None) -> dict[str, Any]:
    """Sector by sector in the issue's order: a sector with a drafted piece, else a part saying why it is not included."""
    pieces = {p["brief_id"]: p for p in draft["pieces"]}
    skipped = draft.get("skipped", {})
    blocks: list[dict[str, Any]] = []

    def missing(brief: NarrativeBrief, block_id: str, title: str) -> dict[str, Any]:
        reason = skipped.get(brief.id) or ("The snips gave no claim that held up against their text, so nothing was drafted."
                                           if brief.id in (have or set()) else NO_SNIP)
        return {**unavailable_block(block_id, title, reason, UNBLOCK), "sector": brief.id}

    for b in SECTOR_BRIEFS:
        if b.id == "reits":
            continue
        blocks.append({**narrative_block(f"sector_{b.id}", pieces[b.id]), "sector": b.id} if b.id in pieces
                      else missing(b, f"sector_{b.id}", b.label))
    reit_brief = SECTOR_BRIEFS[-1]
    blocks.append({**table_block("reits", "REITs weekly performance", fetcher.COLUMNS, reits["rows"], "reit", "name",
                                 {"name": fetcher.SOURCE_NAME, "url": reits["source_url"], "as_of": reits["as_of"]}),
                   "sector": "reits"})
    blocks.append(standing_block(previous))
    blocks.append({**narrative_block("outlook_reits", pieces["reits"]), "sector": "reits", "outlook": True} if "reits" in pieces
                  else missing(reit_brief, "outlook_reits", "REITs outlook"))
    return {
        "section": SECTION, "title": TITLE, "week_start": draft["week_start"], "week_end": draft["week_end"],
        "blocks": numbered(blocks), "pieces_found": len(pieces), "pieces_expected": len(SECTOR_BRIEFS),
        "shortfall": len(SECTOR_BRIEFS) - len(pieces), "warnings": list(draft["warnings"]) + list(reits["warnings"]),
    }


def build_real_estate_review(
    provider: Optional[NarrativeProvider] = None,
    today: Optional[date] = None,
    fetch_reits: Callable[[Optional[date]], dict[str, Any]] = fetcher.fetch_reits,
    on_event: Optional[Observer] = None,
    db_path: Optional[Any] = None,
) -> CoordinatorReview:
    """Read the confirmed snips and the Ibuka summary, draft, check; return the review.  Provider and fetch errors propagate.

    ``on_event`` (common/run_events.py) is told each step as it happens.
    """
    if provider is None and (os.environ.get("CYTONN_LLM_PROVIDER") or "anthropic").strip().lower() != "bedrock":
        raise RuntimeError(NEEDS_BEDROCK)   # the other providers search the web themselves, which this section does not do
    today = today or date.today()
    friday = latest_friday(today)
    reits = fetch_source(on_event, fetcher.SOURCE_NAME, fetch_reits, today)
    if any(r.get("price") is not None for r in reits["rows"]):   # the Ibuka figures, saved so the outlook can quote them
        source_store.from_paste(reits["source_url"], reits["as_of"], ibuka_text(reits), snips.LABELS["reits"], friday,
                                title=fetcher.SOURCE_NAME, origin="fetched")
    have = {b.id for b in SECTOR_BRIEFS
            if any(s.origin == "snip" or b.id == "reits" for s in source_store.list_for(b.label, friday))}
    previous, warnings = None, []
    try:
        previous = review_store.load_latest_review(SECTION, report_type="weekly", db_path=db_path)
    except Exception as exc:  # noqa: BLE001 - a lookup that fails leaves the placeholder, and says so
        log.warning("the saved Real Estate review could not be read for the standing text: %s", type(exc).__name__)
        warnings.append("The earlier Real Estate review could not be read, so the standing text is a placeholder.")
    drafting = [b for b in SECTOR_BRIEFS if b.id in have]
    draft = draft_pieces(drafting, len(drafting), provider=provider or get_narrative_provider(), today=today, on_event=on_event)
    draft["warnings"] = warnings + draft["warnings"]
    content = compose(draft, reits, previous, have)
    report_blocks(on_event, content)
    return build_review(content, check_section(content, on_event))
