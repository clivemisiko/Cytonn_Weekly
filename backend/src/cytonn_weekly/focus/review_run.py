"""Runs Focus of the Week up to the coordinator's review.

    coordinator's topic -> draft one researched piece -> check -> review

Deliberately light.  The theme rotates with no fixed structure (#38.2026: SSA
Eurobonds; earlier issues: budget reviews, bank earnings, market outlooks), and
choosing it is an editorial call, so the topic is plain text the coordinator
supplies when starting a draft; nothing here detects or suggests it.  Given the
topic, the piece is drafted exactly like a Digital Payments highlight - searched,
written only from what the search returned, every claim carrying its source -
just longer and single-topic, and checked the same way (each claim's figures
against its cited span).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from cytonn_weekly.common.review import build_review, check_section, narrative_block, numbered
from cytonn_weekly.common.run_events import Observer
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview
from cytonn_weekly.narrative.base import NarrativeBrief, NarrativeProvider
from cytonn_weekly.narrative.drafter import draft_pieces

SECTION = "focus"
TITLE = "Focus of the Week"
WORDS = (400, 700)
# The one topic length limit, counted after whitespace is normalized.  The API (api/main.py)
# refuses a longer topic through clean_topic(), and the web form's MAX_TOPIC
# (frontend/src/components/review/start-screen.tsx) is the same number.
MAX_TOPIC_CHARS = 500


def clean_topic(topic: Optional[str]) -> str:
    """The topic, whitespace-normalized; ValueError if blank or too long."""
    t = " ".join((topic or "").split())
    if not t:
        raise ValueError("a Focus of the Week draft needs a topic")
    if len(t) > MAX_TOPIC_CHARS:
        raise ValueError(f"the topic is {len(t)} characters; keep it under {MAX_TOPIC_CHARS}")
    return t


def brief_for(topic: str) -> NarrativeBrief:
    return NarrativeBrief(
        id="focus", section=TITLE, label=topic,
        focus=(f"recent, sourced data and developments on: {topic}. Material may be published before the report "
               "week if it is the latest available data on the topic; say when each figure dates from"),
        words=WORDS, opener=None, max_searches=8,
    )


def compose(topic: str, draft: dict[str, Any]) -> dict[str, Any]:
    blocks = [narrative_block("focus", p) for p in draft["pieces"]]
    return {
        "section": SECTION, "title": TITLE, "topic": topic, "week_start": draft["week_start"],
        "week_end": draft["week_end"], "blocks": numbered(blocks), "pieces_found": len(draft["pieces"]),
        "pieces_expected": 1, "shortfall": draft["shortfall"], "warnings": list(draft["warnings"]),
    }


def build_focus_review(topic: str, provider: Optional[NarrativeProvider] = None,
                       today: Optional[date] = None, on_event: Optional[Observer] = None) -> CoordinatorReview:
    """Draft and check the Focus piece on ``topic``.

    Raises ValueError for a blank topic and LookupError when the search found
    nothing usable, rather than saving an empty review.  ``on_event``
    (common/run_events.py) is told each step as it happens.
    """
    topic = clean_topic(topic)
    draft = draft_pieces([brief_for(topic)], 1, provider=provider, today=today, on_event=on_event)
    if not draft["pieces"]:
        raise LookupError(f"no sourced material found for the topic {topic!r}; try a more specific topic")
    content = compose(topic, draft)
    return build_review(content, check_section(content, on_event))
