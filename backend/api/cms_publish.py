"""Publishing an approved report to Cytonn's CMS: a stub.  Nothing here publishes anything.

The final report is a PDF that Cytonn's CMS splits into sections (stated by Clive; not yet
confirmed in writing by Cytonn).  Who produces that PDF and what the CMS needs on the way
in are not known, and there is no CMS access, so nothing about the upload is assumed: no
browser automation is imported, there is no network call, and no route, button or script
calls this module.  It exists so the one place publishing will be written is named, with
what blocks it and what would unblock it, and so the rules that must hold before anything
is ever published are already in front of it: a draft from the local model is refused,
and so is a section that is not approved.
"""

from __future__ import annotations

from typing import Any, Iterator, Sequence

from cytonn_weekly.digital_payments.coordinator_review import APPROVED, CoordinatorReview
from cytonn_weekly.report_sections import section_slug

DEV_PREFIX = "local:"

BLOCKED_REASON = (
    "There is no access to Cytonn's CMS and no credentials for it; the input the CMS expects is unconfirmed "
    "(the finished PDF only, or also section text, headings or a manifest it splits the PDF on); and who "
    "produces the PDF is unconfirmed."
)
UNBLOCK = (
    "CMS access and credentials from Cytonn; written confirmation of who produces the PDF; what the CMS needs "
    "on the way in; and whether the upload is done through the admin pages behind SSO. Then implement "
    "publish_report()."
)


class PublishNotAllowed(ValueError):
    """These sections may not be published: none given, a local-model draft among them, or one not approved."""


def local_pieces(content: Any, name: str = "") -> Iterator[tuple[str, str]]:
    """(piece, drafted_by) for every part of a review's content drafted by the local model, whatever its shape.

    It looks at every ``drafted_by`` anywhere in the content, not only the lead piece: Digital
    Payments' highlights and outlook, a block-shaped section's narrative pieces, and the
    Executive Summary's record of local pieces in the sections it was composed from.
    """
    if isinstance(content, dict):
        drafted_by = content.get("drafted_by")
        if drafted_by is not None and str(drafted_by).startswith(DEV_PREFIX):
            label = next((content[k] for k in ("headline", "piece", "topic", "company", "title", "id")
                          if isinstance(content.get(k), str) and content[k]), name or "a piece with no name")
            yield label, str(drafted_by)
        for key, value in content.items():
            yield from local_pieces(value, str(key))
    elif isinstance(content, list):
        for value in content:
            yield from local_pieces(value, name)


def publish_report(report_type: str, period: str, reviews: Sequence[CoordinatorReview]) -> None:
    """Publish the approved sections of one report to the CMS.  Always raises: it cannot be written yet.

    The refusals come first, so they already hold on the day the last line is replaced:
    no sections, a section of another report or period, any piece drafted by the local
    model (named by section and piece), and any section that is not approved.
    """
    reviews = list(reviews or [])
    report = f"{report_type} report ({period or 'no period'})"
    if not reviews:
        raise PublishNotAllowed(f"no sections were given for the {report}; nothing to publish")
    for review in reviews:
        if (review.report_type, review.period) != (report_type, period):
            raise PublishNotAllowed(
                f"the section {section_slug(review)!r} (review run {review.run_id}) belongs to the {review.report_type} "
                f"report ({review.period or 'no period'}), not the {report}"
            )
    dev = [(section_slug(r), piece, drafted_by) for r in reviews for piece, drafted_by in local_pieces(r.section)]
    if dev:
        named = "; ".join(f"section {slug!r}, piece {piece!r} ({drafted_by})" for slug, piece, drafted_by in dev)
        raise PublishNotAllowed(f"a dev-mode draft is never published. Drafted by the local model: {named}")
    for review in reviews:
        if review.decision != APPROVED:
            state = review.decision or "still in progress"
            raise PublishNotAllowed(
                f"the section {section_slug(review)!r} (review run {review.run_id}) is {state}, not approved; "
                "only approved sections are published"
            )
        if not review.is_approvable:  # a decision field alone is not proof; every item must really be accepted
            raise PublishNotAllowed(
                f"the section {section_slug(review)!r} (review run {review.run_id}) is marked approved but not "
                "every item is resolved and accepted"
            )
    # TODO: needs everything in UNBLOCK before any of this can be written without guessing.
    raise NotImplementedError(f"{BLOCKED_REASON} To unblock: {UNBLOCK}")
