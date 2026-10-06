"""Company Updates: Cytonn's own promotional copy, supplied by the coordinator and never drafted.

Real structure, the same in every issue read (the weekly #38.2026 and the Q3'2026, H1'2026
and FY'2025 reviews): "Investment Updates:" (the Cytonn Money Market Fund's weekly rate,
the Wealth Management Training, pension products) and "Hospitality Updates:" (Cysuites
offers).  None of it comes from a public source the tool could check, so the coordinator
pastes the text and it is carried verbatim as one review item.
"""

from __future__ import annotations

from typing import Optional

from cytonn_weekly.common.review import build_review, check_section, supplied_block
from cytonn_weekly.common.run_events import Observer
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview
from cytonn_weekly.periodic.common import PeriodContext, compose

SECTION = "company_updates"
TITLE = "Company Updates"
MAX_TEXT = 10_000
STUBS = ()


def build_company_updates_review(ctx: PeriodContext, on_event: Optional[Observer] = None) -> CoordinatorReview:
    """Raises ValueError (shown to the coordinator) when no text was supplied.

    ``on_event`` is accepted like every builder's and never called: nothing is fetched,
    drafted or checked here, so a run of this section has no step of its own to report.
    """
    text = (ctx.text or "").strip()
    if not text:
        raise ValueError("Company Updates is your own text: paste the Investment Updates and Hospitality Updates to draft it")
    if len(text) > MAX_TEXT:
        raise ValueError(f"Company Updates text is {len(text)} characters; the limit is {MAX_TEXT}")
    content = compose(SECTION, TITLE, ctx, [supplied_block("company_updates", TITLE, text)])
    return build_review(content, check_section(content))
