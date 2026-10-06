"""Executive Summary of a Markets Review, composed only from that review's approved sections.

Real structure: the website builds an issue's "Executive Summary" from each section's
summary paragraph, in report order (Global Markets Review, Sub-Saharan Africa, Kenya
Macro, Fixed Income, Equities, Real Estate, Digital Payments), and the PDFs print it first
("Executive Summary:").  Those paragraphs are the sections' own lead paragraphs, so
nothing new is written for it.

So this section drafts nothing and searches nothing.  It can only be built once every
other drafted section of the same report and period has been approved (Company Updates
is not summarised and not required); it then carries each approved section's lead
narrative piece verbatim, with that piece's claims and ``drafted_by`` (a dev-mode piece
keeps its ``local:`` mark), and the claims are checked again exactly as they were.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from cytonn_weekly.common.review import build_review, check_section, narrative_block, unavailable_block
from cytonn_weekly.common.run_events import Observer
from cytonn_weekly.digital_payments import review_store
from cytonn_weekly.digital_payments.coordinator_review import APPROVED, CoordinatorReview
from cytonn_weekly.periodic.common import PeriodContext, compose

SECTION = "executive_summary"
TITLE = "Executive Summary"
NOT_SUMMARISED = (SECTION, "company_updates")
STUBS = ()

SUMMARY_NOTE = ("Composed from the lead piece of each section. It does not summarize tables, parts not yet drafted, "
                "or Cytonn's own outlook.")

NO_LEAD_REASON = "The approved section has no drafted narrative piece to lead its summary with (only tables or stubs)."
NO_LEAD_UNBLOCK = "Nothing to unblock: write this section's summary line yourself, or accept the summary without it."


class SectionsNotApproved(ValueError):
    """The summary was asked for before every section it summarises was approved."""

    def __init__(self, waiting: list[str]):
        self.waiting = waiting
        super().__init__("The Executive Summary is composed from approved sections only. Still to approve: "
                         + "; ".join(waiting) + ".")


def summarised_sections(report_type: str):
    from cytonn_weekly.report_sections import sections_for  # the registry imports this module lazily

    return [s for s in sections_for(report_type) if s.slug not in NOT_SUMMARISED]


def left_out(spec: Any, review: CoordinatorReview) -> dict[str, Any]:
    """What an approved section holds that its line in the summary does not carry.

    The summary carries the section's first narrative piece only, so everything else is listed by
    name (and any local-model piece, carried or not, is recorded as ``dev_pieces``): each table (by title), each part not yet drafted (by name), and each further narrative
    piece (by headline).  Nothing here is summarised or checked; it only says what is absent.
    """
    blocks = review.section.get("blocks", [])
    lead = next((b for b in blocks if b["kind"] == "narrative"), None)
    return {
        "section": spec.slug, "title": spec.title, "run_id": review.run_id,
        # Provenance, not carried text: every piece of the approved section drafted by the local model,
        # lead or not.  It is what marks the summary as a dev draft (api/serialize.is_dev_draft,
        # delivery.is_dev_mode_review, the send script's scan of every ``drafted_by``).
        "dev_pieces": [{"piece": b.get("headline") or b.get("topic") or b["id"], "drafted_by": b["drafted_by"]}
                       for b in blocks if b["kind"] == "narrative" and str(b.get("drafted_by")).startswith("local:")],
        "tables": [b["title"] for b in blocks if b["kind"] == "table"],
        "unavailable": [b["title"] for b in blocks if b["kind"] == "unavailable"],
        "further_pieces": [b.get("headline") or b.get("topic") or b["id"] for b in blocks
                           if b["kind"] == "narrative" and b is not lead],
    }


def build_executive_summary_review(
    ctx: PeriodContext,
    load_latest: Callable[..., Optional[CoordinatorReview]] = review_store.load_latest_review,
    on_event: Optional[Observer] = None,
) -> CoordinatorReview:
    """Raises SectionsNotApproved (naming each section and its state) unless all are approved.

    ``on_event`` is accepted like every builder's and never called: the summary fetches and
    drafts nothing, it is composed in one step, so a run of it is only its start and its end.
    """
    approved: list[tuple[Any, CoordinatorReview]] = []
    waiting: list[str] = []
    for spec in summarised_sections(ctx.report_type):
        review = load_latest(spec.slug, report_type=ctx.report_type, period=ctx.period, db_path=ctx.db_path)
        if review is None:
            waiting.append(f"{spec.title} (not drafted)")
        elif review.decision != APPROVED:
            waiting.append(f"{spec.title} ({review.decision or 'in review'}, run {review.run_id})")
        else:
            approved.append((spec, review))
    if waiting:
        raise SectionsNotApproved(waiting)
    blocks: list[dict[str, Any]] = []
    not_covered: list[dict[str, Any]] = []
    for spec, review in approved:
        not_covered.append(left_out(spec, review))
        lead = next((b for b in review.section.get("blocks", []) if b["kind"] == "narrative"), None)
        if lead is None:
            blocks.append(unavailable_block(f"summary_{spec.slug}", spec.title, NO_LEAD_REASON, NO_LEAD_UNBLOCK))
            continue
        piece = {k: v for k, v in lead.items() if k not in ("kind", "id", "numeral")}
        # The real summary heads each paragraph with the section's name ("Fixed Income:").
        blocks.append(narrative_block(f"summary_{spec.slug}", {
            **piece, "headline": spec.title, "source_headline": piece.get("headline"), "topic": spec.title,
            "source_section": spec.slug, "source_run_id": review.run_id}))
    content = compose(SECTION, TITLE, ctx, blocks)
    content["composed_from"] = [{"section": s.slug, "run_id": r.run_id} for s, r in approved]
    content["summary_note"] = SUMMARY_NOTE
    content["not_covered"] = not_covered
    return build_review(content, check_section(content))
