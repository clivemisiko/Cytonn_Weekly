"""Drafts a section's narrative pieces from an ordered list of briefs.

The same orchestration as Digital Payments' draft_highlights(), with briefs in
place of companies: briefs are tried in priority order until ``target`` pieces
are drafted, a brief with no qualifying material that week is skipped (and
said so), and a shortfall is reported rather than backfilled.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional, Sequence

from cytonn_weekly.common.run_events import PART_SKIPPED, PIECE_FINISHED, PIECE_STARTED, Observer, emit
from cytonn_weekly.narrative.base import NarrativeBrief, NarrativeProvider
from cytonn_weekly.narrative.factory import get_narrative_provider


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


def draft_pieces(
    briefs: Sequence[NarrativeBrief],
    target: int,
    provider: Optional[NarrativeProvider] = None,
    today: Optional[date] = None,
    window: Optional[tuple[date, date]] = None,
    on_event: Optional[Observer] = None,
) -> dict[str, Any]:
    """Returns {"week_start", "week_end", "pieces", "shortfall", "warnings"}.  Provider errors propagate.

    ``window`` replaces the report week (the seven days ending ``today``) with an explicit
    first and last day, e.g. a quarter for the quarterly review; the keys keep their names.

    ``on_event`` (common/run_events.py) is told as each brief's search and draft starts and
    ends, labelled with the brief's own label; it changes nothing about the result.
    """
    provider = provider or get_narrative_provider()
    today = today or date.today()
    start, end = window or week_window(today)
    pieces: list[dict[str, Any]] = []
    warnings: list[str] = []
    for brief in briefs:
        if len(pieces) == target:
            warnings.append(f"{brief.label}: not searched ({target} higher-priority pieces already drafted)")
            continue
        emit(on_event, PIECE_STARTED, brief.label)
        res = provider.draft_piece(brief, start=start, end=end, today=today)
        warnings.extend(res.draft_warnings)
        if res.no_story:
            warnings.append(f"{brief.label}: nothing qualifying found for the {brief.window.split()[-1]}")
            emit(on_event, PART_SKIPPED, brief.label,
                 detail=f"Nothing qualifying found for the {brief.window.split()[-1]}.")
        else:
            pieces.append(piece_dict(res, brief))
            emit(on_event, PIECE_FINISHED, brief.label, detail=res.headline)
    shortfall = target - len(pieces)
    if shortfall:
        warnings.append(f"only {len(pieces)} of {target} pieces drafted for {start.isoformat()} to {end.isoformat()}")
    return {"week_start": start.isoformat(), "week_end": end.isoformat(), "pieces": pieces,
            "shortfall": shortfall, "warnings": warnings}
