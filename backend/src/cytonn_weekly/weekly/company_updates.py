"""The weekly report's Company Updates: Cytonn's own copy, pasted by the coordinator and carried verbatim.

#38.2026 opens with "Company updates": "Investment Updates:" (the Cytonn Money Market
Fund's weekly rate, the Wealth Management Training, pension products) and "Hospitality
Updates:" (Cysuites offers).  None of it comes from a source the tool could check, so it is
never drafted: the text is one ``supplied`` block and one review item, never marked
verified.  The Markets Reviews' Company Updates (periodic/company_updates.py) is the same
idea with a period instead of a week.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from cytonn_weekly.common.review import build_review, check_section, numbered, supplied_block
from cytonn_weekly.common.run_events import Observer
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview
from cytonn_weekly.periodic.company_updates import MAX_TEXT
from cytonn_weekly.weekly.week import week_for

SECTION = "company_updates"
TITLE = "Company Updates"


def build_company_updates_weekly_review(text: str, week_ending: Optional[date] = None, today: Optional[date] = None,
                                        on_event: Optional[Observer] = None) -> CoordinatorReview:
    """Raises ValueError (shown to the coordinator) when no text was supplied.

    ``on_event`` is accepted like every builder's and never called: nothing is fetched,
    drafted or checked here.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("Company Updates is your own text: paste the Investment Updates and Hospitality Updates to draft it")
    if len(text) > MAX_TEXT:
        raise ValueError(f"Company Updates text is {len(text)} characters; the limit is {MAX_TEXT}")
    week = week_for(week_ending, today)
    content = {
        "section": SECTION, "title": TITLE, "week_ending": week.ending.isoformat(),
        "week_start": (week.ending - timedelta(days=6)).isoformat(), "week_end": week.ending.isoformat(),
        "blocks": numbered([supplied_block("company_updates", TITLE, text)]), "pieces_found": 0, "pieces_expected": 0,
        "shortfall": 0, "warnings": [],
        # The published issue's Company Updates has no summary of its own (its CMS field is empty).
        "summary": "",
    }
    return build_review(content, check_section(content))
