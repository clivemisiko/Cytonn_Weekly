"""Drafts a section's narrative pieces from an ordered list of briefs.

The same orchestration as Digital Payments' draft_highlights(), with briefs in
place of companies: briefs are tried in priority order until ``target`` pieces
are drafted, a brief with no qualifying material that week is skipped (and
said so), and a shortfall is reported rather than backfilled.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from typing import Any, Optional, Sequence

from cytonn_weekly.common.run_events import PART_SKIPPED, PIECE_FINISHED, PIECE_STARTED, Observer, emit
from cytonn_weekly.drafting.base import NarrativeBrief, NarrativeProvider
from cytonn_weekly.drafting.factory import get_narrative_provider
from cytonn_weekly.weekly.previous_issue import norm_url


def week_window(today: date) -> tuple[date, date]:
    return today - timedelta(days=6), today


def piece_dict(res, brief: NarrativeBrief) -> dict[str, Any]:
    return {
        "brief_id": brief.id,
        "topic": brief.label,
        "headline": res.headline,
        "body": res.paragraph,
        "body_md": res.paragraph_md,
        "links": res.links,
        "claims": res.claims,
        "warnings": res.warnings,
        "search_scope": res.search_scope,
        "preferred_domains": list(brief.preferred_domains),
        "drafted_by": res.drafted_by,
    }


REPEAT = "already reported in the previous issue"


def repeated_url(claims: Sequence[dict[str, Any]], urls: set[str]) -> Optional[str]:
    """The first address a claim cites that the previous issue's section already linked (same page, compared by norm_url)."""
    return next((c["url"] for c in claims if c.get("url") and norm_url(c["url"]) in urls), None)


def piece_urls(piece: dict[str, Any]) -> set[str]:
    return {u for u in (str(c.get("url") or "").split("#")[0].rstrip("/").lower() for c in piece.get("claims", [])) if u}


def held_by(piece: dict[str, Any], existing: Sequence[dict[str, Any]]) -> Optional[str]:
    """The topic of an already drafted piece whose claims cite every page this piece cites, so the event is shown once.
    ponytail: same page address, not same event; a closer match needs the sentences compared."""
    mine = piece_urls(piece)
    return next((e["topic"] for e in existing if mine and mine <= piece_urls(e)), None)


def draft_pieces(
    briefs: Sequence[NarrativeBrief],
    target: int,
    provider: Optional[NarrativeProvider] = None,
    today: Optional[date] = None,
    window: Optional[tuple[date, date]] = None,
    on_event: Optional[Observer] = None,
    earlier: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Returns {"week_start", "week_end", "pieces", "shortfall", "warnings"}.  Provider errors propagate.

    ``window`` replaces the report week (the seven days ending ``today``) with an explicit
    first and last day, e.g. a quarter for the quarterly review; the keys keep their names.

    ``on_event`` (common/run_events.py) is told as each brief's search and draft starts and
    ends, labelled with the brief's own label; it changes nothing about the result.

    ``earlier`` is ``previous_issue.digest`` of the same section of the previous issue.  Its headings go into each
    brief's context as already reported; and, in code, a piece whose claims cite an address that section already
    linked is left out (said in the warnings and the run), and the next brief is tried in its place.  So is a piece whose
    claims cite only pages an earlier piece of this run already cites (``held_by``).
    """
    provider = provider or get_narrative_provider()
    today = today or date.today()
    start, end = window or week_window(today)
    pieces: list[dict[str, Any]] = []
    warnings: list[str] = []
    skipped: dict[str, str] = {}   # brief id -> the provider's own reason, only where it gave one
    for brief in briefs:
        if len(pieces) == target:
            warnings.append(f"{brief.label}: not searched ({target} higher-priority pieces already drafted)")
            continue
        emit(on_event, PIECE_STARTED, brief.label)
        if earlier and earlier["headings"]:
            seen = "Already reported in the previous issue, do not repeat: " + "; ".join(earlier["headings"][:12]) + "."
            brief = replace(brief, context=f"{brief.context}\n\n{seen}".strip())
        res = provider.draft_piece(brief, start=start, end=end, today=today)
        warnings.extend(res.draft_warnings)
        if res.no_story and res.reason:   # the provider already put its sentence in draft_warnings
            skipped[brief.id] = res.reason
            emit(on_event, PART_SKIPPED, brief.label, detail=res.reason)
        elif res.no_story:
            warnings.append(f"{brief.label}: nothing qualifying found for the {brief.window.split()[-1]}")
            emit(on_event, PART_SKIPPED, brief.label,
                 detail=f"Nothing qualifying found for the {brief.window.split()[-1]}.")
        elif earlier and (url := repeated_url(res.claims, earlier["urls"])):
            skipped[brief.id] = REPEAT
            warnings.append(f"{brief.label}: left out, {REPEAT} (it cites {url}, which that section already linked)")
            emit(on_event, PART_SKIPPED, brief.label, detail=f"Left out: {REPEAT} (it cites {url}).")
        elif not brief.findings and (holder := held_by(piece_dict(res, brief), pieces)):   # Focus notes share one topic's pages
            skipped[brief.id] = f"already drafted in this run under {holder}"
            warnings.append(f"{brief.label}: left out, it cites the same page(s) as the piece already drafted under {holder}")
            emit(on_event, PART_SKIPPED, brief.label, detail=f"Left out: the same story as {holder}.")
        else:
            pieces.append(piece_dict(res, brief))
            emit(on_event, PIECE_FINISHED, brief.label, detail=res.headline)
    shortfall = target - len(pieces)
    if shortfall:
        warnings.append(f"only {len(pieces)} of {target} pieces drafted for {start.isoformat()} to {end.isoformat()}")
    out = {"week_start": start.isoformat(), "week_end": end.isoformat(), "pieces": pieces,
           "shortfall": shortfall, "warnings": warnings}
    if skipped:
        out["skipped"] = skipped
    return out
