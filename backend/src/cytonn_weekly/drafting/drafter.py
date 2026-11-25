"""Drafts a section's narrative pieces from an ordered list of briefs.

The same orchestration as Digital Payments' draft_highlights(), with briefs in
place of companies: briefs are tried in priority order until ``target`` pieces
are drafted, a brief with no qualifying material that week is skipped (and
said so), and a shortfall is reported rather than backfilled.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date, timedelta
from typing import Any, Optional, Sequence
from urllib.parse import urlsplit

from cytonn_weekly.common.run_events import PART_SKIPPED, PIECE_FINISHED, PIECE_STARTED, Observer, emit
from cytonn_weekly.common.sources import NEWS_SITE
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


SAME_HEADLINE = 0.75   # share of headline words two pieces must have in common to be one event
_STOP = frozenset("a an and as at be by for from has have in is it its of on or the to was were with".split())
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _headline_words(piece: dict[str, Any]) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", str(piece.get("headline") or "").lower()) if w not in _STOP}


def _figures(piece: dict[str, Any]) -> set[str]:
    return {n.replace(",", "") for c in piece.get("claims", []) for n in _NUMBER.findall(str(c.get("text") or ""))}


def same_event(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Whether two drafted pieces report one event, so it is shown once. Either every page one cites is cited by the other,
    or, from different pages, their headlines share at least SAME_HEADLINE of their words and their claims do not give
    different figures (when both give figures, at least one is common). Conservative: two stories about one company
    ("KCB Q3 profit rises 24%", "KCB signs Afreximbank deal") share too few headline words, and two results stories with
    similar headlines ("Equity Group Q3 2026 profit rises", "KCB Group Q3 2026 profit rises") differ in name and figures.
    ponytail: word overlap, not meaning; two differently worded headlines of one event both survive."""
    ua, ub = piece_urls(a), piece_urls(b)
    if (ua and ua <= ub) or (ub and ub <= ua):
        return True
    wa, wb = _headline_words(a), _headline_words(b)
    if not wa or not wb or len(wa & wb) / len(wa | wb) < SAME_HEADLINE:
        return False
    fa, fb = _figures(a), _figures(b)
    return not (fa and fb) or bool(fa & fb)


def _sourcing(piece: dict[str, Any]) -> tuple[bool, int]:
    """How well a piece is sourced, for keeping the better of two on one event: a primary source (a claim not from a news
    site) first, then the more specific page (the deepest address it cites; a home or listing page is shallow)."""
    claims = piece.get("claims", [])
    primary = any(NEWS_SITE not in (c.get("source_flags") or []) for c in claims)
    depth = max((len([p for p in urlsplit(str(c.get("url") or "")).path.split("/") if p]) for c in claims), default=0)
    return primary, depth


def held_by(piece: dict[str, Any], existing: Sequence[dict[str, Any]]) -> Optional[str]:
    """The topic of an already drafted piece that reports the same event (``same_event``), so the event is shown once."""
    return next((e["topic"] for e in existing if same_event(piece, e)), None)


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
        elif not brief.findings and (j := next((i for i, p in enumerate(pieces) if same_event(piece_dict(res, brief), p)), None)) is not None:
            # Focus notes share one topic's pages. One event, one item: the better-sourced version stays, in the earlier place.
            new, old = piece_dict(res, brief), pieces[j]
            keep, drop = (new, old) if _sourcing(new) > _sourcing(old) else (old, new)
            pieces[j] = keep
            skipped[drop["brief_id"]] = f"already drafted in this run under {keep['topic']}"
            warnings.append(f"{drop['topic']}: left out, it reports the same event as the piece drafted under {keep['topic']}"
                            + (", which is better sourced" if keep is new else ""))
            emit(on_event, PART_SKIPPED, drop["topic"], detail=f"Left out: the same story as {keep['topic']}.")
            if keep is new:
                emit(on_event, PIECE_FINISHED, brief.label, detail=res.headline)
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
