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
from cytonn_weekly.common.computed import PLAIN_PCT, carried_block, computed_block
from cytonn_weekly.common.formatting import PRICE
from cytonn_weekly.review.blocks import (
    build_review,
    check_section,
    grouped,
    narrative_block,
    numbered,
    table_block,
    unavailable_block,
)
from cytonn_weekly.common.run_events import Observer, fetch_source, report_blocks
from cytonn_weekly.review import store as review_store
from cytonn_weekly.review.model import CoordinatorReview
from cytonn_weekly.drafting.base import NarrativeBrief, NarrativeProvider
from cytonn_weekly.drafting.drafter import draft_pieces
from cytonn_weekly.drafting.factory import get_narrative_provider
from cytonn_weekly.real_estate import fetcher, snips
from cytonn_weekly.weekly import previous_issue as issues
from cytonn_weekly.weekly.prose import Figures, published, try_fetch
from cytonn_weekly.weekly.week import latest_friday

log = logging.getLogger(__name__)
SECTION = "real_estate"
TITLE = "Real Estate"
N_SUBSECTIONS = 4

# The team's preferred sites (supplied by the owner, 2026-10-29), searched first by every brief after its own. Nation, Business
# Daily and Bloomberg are never read by the tool (equities/source_policy.json): the analysts send snips of them.
_PREFERRED_SITES_TEXT = """
standardmedia.co.ke
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
# Every snip sector is drafted. The Markets Review link paragraph, the hospitality outlook and the REITs outlook are the
# analyst's own text (analyst_block), and the REITs prices are worked out from the Ibuka rows, so REITs has no snips or brief.
SECTOR_BRIEFS: list[NarrativeBrief] = [
    NarrativeBrief(id=sid, section=TITLE, label=label, focus=SNIP_FOCUS, opener=None, context=FACTS_ONLY,
                   **({"takeouts": True, "words": (110, 420)} if sid == "industry" else {}),
                   **({"words": (120, 320)} if sid == "hospitality" else {}))
    for sid, label in snips.SECTORS
]

NEEDS_BEDROCK = ("The weekly Real Estate section is written from the snips you upload, and reading and drafting them needs "
                 "the production model on Amazon Bedrock (CYTONN_LLM_PROVIDER=bedrock). This server is not using it, so nothing was drafted.")
NO_SNIP = "No snip was uploaded and confirmed for this sector, so it is not included."
UNBLOCK = "Upload a snip for this sector on the start screen, read and confirm it, then draft again."
PLACEHOLDER = "Analyst to add the standing text"
INDUSTRY_CLOSING = "Industry reports: link to the Markets Review"
HOSPITALITY_OUTLOOK = "Hospitality: going forward"
REITS_OUTLOOK = "REITs sector outlook"
BENEFITS_START = "REITs offer various benefits"   # how the standing text opens in the published issues
CHALLENGES_START = "Additional general challenges include"
CHALLENGES_END = "Together,"
OUTLOOK_START = "We expect"
LOWER_ROMAN = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x")


def analyst_block(block_id: str, title: str, sector: str, **extra: Any) -> dict[str, Any]:
    """A part only the analyst can write: a carried block with no text, flagged until they write it by editing the paragraph."""
    return {**carried_block(block_id, title, f"Analyst to write: {title}", {"note": "the tool writes no text here"}),
            "sector": sector, "role": "analyst", "placeholder": True, **extra}


def reits_prices_block(reits: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The REIT prices paragraph, worked out from Ibuka's unrounded prices; the checker works every figure out again."""
    rows = [r for r in reits["rows"] if r.get("price") is not None]
    if not rows:
        return None
    src = f"{fetcher.SOURCE_NAME} as at {reits['as_of']}"
    inception = float(fetcher.INCEPTION_PRICE)
    figs, sentences = Figures(), []
    for r in rows:
        key = r["reit"].lower()
        price = figs.add(f"{key}_price", f"{r['name']} unit price", PRICE, fetcher.PRICE_DECIMALS,
                         {"price": published(r["price"], src)})
        change = figs.add(f"{key}_change", f"{r['name']} change from the inception price", PLAIN_PCT, 1,
                          {"price": published(r["price"], src)}, ["mul", ["div", ["sub", "price", inception], inception], 100])
        word = "gain" if figs.value(f"{key}_change") >= 0 else "loss"
        sentences.append(f"{r['name']} closed at Kshs {price} per unit, representing a {change} {word} from the Kshs "
                         f"{inception:.1f} inception price.")
    return {**computed_block("reits_prices", "REITs weekly performance", " ".join(sentences), figs.items,
                             sources=[{"name": fetcher.SOURCE_NAME, "url": reits["source_url"]}]), "sector": "reits"}


def standing_text(paragraphs: list[str]) -> Optional[str]:
    """The REITs benefits paragraph and the challenges list from a published issue's Real Estate section, the list numbered
    i., ii., iii. as the issue prints it; None when the section does not hold the benefits paragraph."""
    start = next((i for i, p in enumerate(paragraphs) if p.startswith(BENEFITS_START)), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(paragraphs)) if paragraphs[i].startswith(OUTLOOK_START)), len(paragraphs))
    lines, n = [], None
    for p in paragraphs[start:end]:
        if n is not None and p.startswith(CHALLENGES_END):
            n = None
        if n is not None and n < len(LOWER_ROMAN):
            lines.append(f"{LOWER_ROMAN[n]}. {p}")
            n += 1
        else:
            lines.append(p)
        if p.startswith(CHALLENGES_START):
            n = 0
    return "\n".join(lines)


def standing_block(approved: Optional[CoordinatorReview], issue: Optional[Any] = None) -> dict[str, Any]:
    """The REITs standing text, never written by the model. In order: the newest APPROVED Real Estate review's copy, else the
    previous published issue's text (cytonnreport.com), else a placeholder the analyst fills in by editing the paragraph."""
    from cytonn_weekly.fixed_income.weekly import _carried

    old = next((b for b in (approved.section.get("blocks", []) if approved else [])
                if b.get("id") == "standing" and b.get("kind") == "carried" and not b.get("placeholder")), None)
    extra = {"sector": "reits", "role": "standing"}
    title = "Standing text: the benefits of REITs and their challenges"
    if old is not None:
        week = approved.section.get("week_end")
        return {**carried_block("standing", old["title"], old["body_md"],
                                {"published": week, "note": f"taken from this tool's approved Real Estate review (run {approved.run_id}, "
                                                            f"week ending {week}); the text does not change from week to week"}), **extra}
    if issue is not None:
        found = _carried(issue, "standing", title, standing_text, slugs=("real-estate",))
        if found["kind"] == "carried":
            return {**found, **extra}
    return {**carried_block("standing", title, PLACEHOLDER,
                            {"note": "no approved Real Estate review and no previous issue holds this text; type it by editing this paragraph"}),
            **extra, "placeholder": True}


def industry_briefs(friday: date) -> list[NarrativeBrief]:
    """One brief for each report the analyst confirmed: a PDF's pages are one report, every image its own."""
    base = next(b for b in SECTOR_BRIEFS if b.id == "industry")
    reports: dict[str, list[str]] = {}
    for s in source_store.list_for(base.label, friday):
        if s.origin == "snip":
            reports.setdefault(s.url.split("#")[0], []).append(s.id)
    return [replace(base, id=base.id if n == 0 else f"{base.id}_{n + 1}", source_ids=tuple(ids))
            for n, ids in enumerate(reports.values())]


def compose(draft: dict[str, Any], reits: dict[str, Any], standing: dict[str, Any], have: Optional[set[str]] = None) -> dict[str, Any]:
    """Sector by sector in the issue's order: a sector with a drafted piece, else a part saying why it is not included."""
    pieces = {p["brief_id"]: p for p in draft["pieces"]}
    skipped = draft.get("skipped", {})
    blocks: list[dict[str, Any]] = []

    def missing(brief: NarrativeBrief, block_id: str, title: str) -> dict[str, Any]:
        reason = skipped.get(brief.id) or ("The snips gave no claim that held up against their text, so nothing was drafted."
                                           if brief.id in (have or set()) else NO_SNIP)
        return {**unavailable_block(block_id, title, reason, UNBLOCK), "sector": brief.id}

    closing = {"industry": analyst_block("industry_closing", INDUSTRY_CLOSING, "industry"),
               "hospitality": analyst_block("hospitality_going_forward", HOSPITALITY_OUTLOOK, "hospitality")}
    for b in SECTOR_BRIEFS:
        found = [p for pid, p in pieces.items() if pid == b.id or (b.id == "industry" and pid.startswith("industry_"))]
        for p in found:
            blocks.append({**narrative_block(f"sector_{p['brief_id']}", p), "sector": b.id})
        if not found:
            blocks.append(missing(b, f"sector_{b.id}", b.label))
        elif b.id in closing:
            blocks.append(closing[b.id])
    if (prices := reits_prices_block(reits)) is not None:
        blocks.append(prices)
    blocks.append({**table_block("reits", "REITs weekly performance", fetcher.COLUMNS, reits["rows"], "reit", "name",
                                 {"name": fetcher.SOURCE_NAME, "url": reits["source_url"], "as_of": reits["as_of"]}),
                   "sector": "reits", "export": False})   # the review screen's table; the Word file prints the paragraph
    blocks.append(standing)
    blocks.append(analyst_block("outlook_reits", REITS_OUTLOOK, "reits", outlook=True))
    sectors = {b["sector"] for b in blocks if b["kind"] == "narrative"}
    return {
        "section": SECTION, "title": TITLE, "week_start": draft["week_start"], "week_end": draft["week_end"],
        "blocks": numbered(blocks), "pieces_found": len(sectors), "pieces_expected": len(SECTOR_BRIEFS),
        "shortfall": len(SECTOR_BRIEFS) - len(sectors), "warnings": list(draft["warnings"]) + list(reits["warnings"]),
    }


def build_real_estate_review(
    provider: Optional[NarrativeProvider] = None,
    today: Optional[date] = None,
    fetch_reits: Callable[[Optional[date]], dict[str, Any]] = fetcher.fetch_reits,
    on_event: Optional[Observer] = None,
    db_path: Optional[Any] = None,
    fetch_previous_issue: Callable[[date], Any] = lambda day: issues.find_previous_issue(day),
) -> CoordinatorReview:
    """Read the confirmed snips and the Ibuka summary, draft, check; return the review.  Provider and fetch errors propagate.

    ``on_event`` (common/run_events.py) is told each step as it happens.
    """
    if provider is None and (os.environ.get("CYTONN_LLM_PROVIDER") or "").strip().lower() != "bedrock":
        raise RuntimeError(NEEDS_BEDROCK)   # the other providers search the web themselves, which this section does not do
    today = today or date.today()
    friday = latest_friday(today)
    reits = fetch_source(on_event, fetcher.SOURCE_NAME, fetch_reits, today)
    have = {b.id for b in SECTOR_BRIEFS if any(s.origin == "snip" for s in source_store.list_for(b.label, friday))}
    approved, issue, warnings = None, None, []
    try:
        approved = review_store.load_latest_review(SECTION, report_type="weekly", db_path=db_path, approved_only=True)
    except Exception as exc:  # noqa: BLE001 - a lookup that fails goes on to the previous issue, and says so
        log.warning("the approved Real Estate review could not be read for the standing text: %s", type(exc).__name__)
        warnings.append("The approved Real Estate review could not be read, so the standing text is looked for in the previous issue.")
    if approved is None:   # only then is the published issue read
        issue = try_fetch(on_event, "Previous issue on cytonnreport.com", fetch_previous_issue, friday, problems=warnings)
    try:   # an uploaded snip the draft will not read is said before the draft starts; drafting goes ahead either way
        warnings += snips.problems(friday)
    except snips.SnipError as exc:
        warnings.append(str(exc))
    drafting = [r for b in SECTOR_BRIEFS if b.id in have for r in (industry_briefs(friday) if b.id == "industry" else [b])]
    draft = draft_pieces(drafting, len(drafting), provider=provider or get_narrative_provider(), today=today, on_event=on_event)
    draft["warnings"] = warnings + draft["warnings"]
    content = compose(draft, reits, standing_block(approved, issue), have)
    report_blocks(on_event, content)
    return build_review(content, check_section(content, on_event))
