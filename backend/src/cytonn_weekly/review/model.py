"""Analyst review model, shared by every report section (backlog task 8).

Turns compose_section()'s output plus the checking layer's CheckReport into one
flat list of ReviewItems, one per checkable unit (a table row, an outlook stat,
or a highlight claim), so the analyst's single accuracy pass has something
concrete to resolve.  The tool never approves anything: the only thing this
module computes is whether there is a draft to decide on, and ``decide()``
records the analyst's call.

Statuses
--------
* ``flagged``           -- the checker raised a mismatch / missing / unsourced /
                           sources_disagree flag for it.
* ``clean``             -- checked with no flag.  Still listed, so the
                           analyst sees full coverage and not just problems.
* ``not_auto_verified`` -- every highlight claim, until task 6b exists.  This is
                           deliberately not a flag: nothing was found wrong, the
                           tool just has not checked it.

This module only consumes existing outputs; it changes nothing in
compose_section(), digital_payments/checks.py or any provider.

Typical usage
-------------
    review = build_coordinator_review(compose_section(draft, table, outlook), report)   # digital_payments/review_run.py
    review.items[0].resolve("accept")
    ...
    if review.is_approvable:
        review.decide("approved")
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Union

from cytonn_weekly.review.figures import Flag

# ReviewItem.kind
TABLE_ROW = "table_row"
OUTLOOK_STAT = "outlook_stat"
HIGHLIGHT_CLAIM = "highlight_claim"
WORKBOOK_QUARTER = "workbook_quarter"

# ReviewItem.status
FLAGGED = "flagged"
CLEAN = "clean"
NOT_AUTO_VERIFIED = "not_auto_verified"

# ReviewItem.resolution
ACCEPT = "accept"
FIX_NEEDED = "fix_needed"
RESOLUTIONS = (ACCEPT, FIX_NEEDED)

# CoordinatorReview.decision
APPROVED = "approved"
REJECTED = "rejected"

ACCEPTED_ON_APPROVAL = "Accepted as part of approving the section, at (UTC)"


class FlaggedNotAcknowledged(ValueError):
    """Approval was asked for without the right count of flagged items."""

    def __init__(self, flagged: int, acknowledged: Optional[int]):
        what = f"{flagged} flagged item" + ("" if flagged == 1 else "s")
        seen = ("no count of flagged items was sent" if acknowledged is None
                else f"the count sent was {acknowledged}")
        super().__init__(f"cannot approve: this section has {what} and {seen}. Reload the review, read the flagged "
                         "items, then approve again.")
        self.flagged, self.acknowledged = flagged, acknowledged


NOT_AUTO_VERIFIED_NOTE = (
    "Not yet automatically checked: citation verification (task 6b) is not built. "
    "This is not a flag and nothing was found wrong; the tool has simply not verified "
    "this claim, so check it against its cited source by hand."
)


@dataclass
class ReviewItem:
    """One checkable unit awaiting the analyst's resolution."""

    kind: str                       # TABLE_ROW | OUTLOOK_STAT | HIGHLIGHT_CLAIM | WORKBOOK_QUARTER
    ref: str                        # human-readable label
    status: str                     # FLAGGED | CLEAN | NOT_AUTO_VERIFIED
    # FLAGGED: the checker's Flag objects for this unit (a table row can carry
    # several, one per figure).  NOT_AUTO_VERIFIED: the fixed note.  CLEAN: None.
    detail: Union[list[Flag], str, None] = None
    resolution: Optional[str] = None  # None | ACCEPT | FIX_NEEDED
    resolution_note: Optional[str] = None
    # HIGHLIGHT_CLAIM only: the claim as drafted ({text, url, title, cited_text}), so the
    # analyst can open the source and check it by hand.  Empty for other kinds.
    context: dict[str, Any] = field(default_factory=dict)

    def resolve(self, resolution: Optional[str], note: Optional[str] = None) -> None:
        """Record the analyst's call (``None`` clears it)."""
        if resolution is not None and resolution not in RESOLUTIONS:
            raise ValueError(f"resolution must be one of {RESOLUTIONS} or None, got {resolution!r}")
        self.resolution = resolution
        self.resolution_note = note

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form; ``detail`` is a list of flag dicts, the fixed note, or None."""
        return asdict(self)  # deep-converts the Flag dataclasses inside ``detail``

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ReviewItem":
        detail = d.get("detail")
        if isinstance(detail, list):
            detail = [Flag(**f) for f in detail]
        return cls(**{**d, "detail": detail})


@dataclass
class CoordinatorReview:
    """compose_section()'s output, unchanged, plus the items to resolve."""

    section: dict[str, Any]
    review_items: list[ReviewItem] = field(default_factory=list)
    decision: Optional[str] = None  # None until decide() is called
    decided_at: Optional[str] = None  # ISO-8601 UTC, set by decide()
    run_id: Optional[int] = None  # set by review_store when the review is saved
    # Which report and period this review belongs to (report_types.py).  With the section
    # slug they are the review's key, fixed at its first save; the API sets them before then.
    report_type: str = "weekly"
    period: str = ""

    @property
    def is_approvable(self) -> bool:
        """True when the review holds a draft (any item).  Resolutions no longer gate approval: a section is approved or
        rejected as a whole.  They are still stored, so older reviews load and show them."""
        return bool(self.review_items)

    def by_status(self, status: str) -> list[ReviewItem]:
        return [i for i in self.review_items if i.status == status]

    def accept_all_clean(self) -> int:
        """Accept every CLEAN item the analyst has not resolved yet; return how many.

        Touches nothing else: flagged and not_auto_verified items always need an
        individual call, and a clean item the analyst already resolved (say, as
        fix_needed because they spotted something the checker could not) is left alone.
        """
        n = 0
        for i in self.review_items:
            if i.status == CLEAN and i.resolution is None:
                i.resolve(ACCEPT)
                n += 1
        return n

    @property
    def flagged_count(self) -> int:
        return len(self.by_status(FLAGGED))

    def decide(self, decision: str, acknowledged_flagged: Optional[int] = None) -> None:
        """Record the analyst's final call, once.

        "approved" needs a draft (``is_approvable``).  With flagged items it also needs
        ``acknowledged_flagged`` to equal their count, so the caller must have been shown exactly
        what is flagged now (a stale screen or a guess is refused).  Each flagged item with no
        resolution is then accepted, with a note saying it was accepted as part of approving the
        section; one the analyst already resolved is left alone.
        "rejected" is always allowed.
        """
        if decision not in (APPROVED, REJECTED):
            raise ValueError(f"decision must be {APPROVED!r} or {REJECTED!r}, got {decision!r}")
        if self.decision is not None:
            raise ValueError(f"review already decided ({self.decision!r}); build a new review")
        if decision == APPROVED and not self.is_approvable:
            raise ValueError("cannot approve: the review has no items")
        if decision == APPROVED and self.flagged_count and acknowledged_flagged != self.flagged_count:
            raise FlaggedNotAcknowledged(self.flagged_count, acknowledged_flagged)
        decided_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if decision == APPROVED:
            for item in self.by_status(FLAGGED):
                if item.resolution is None:
                    item.resolve(ACCEPT, f"{ACCEPTED_ON_APPROVAL} {decided_at}.")
        self.decision = decision
        self.decided_at = decided_at

    def accepted_on_approval(self) -> int:
        """How many flagged items were accepted by approving the section (not one by one)."""
        return sum(1 for i in self.by_status(FLAGGED)
                   if i.resolution == ACCEPT and (i.resolution_note or "").startswith(ACCEPTED_ON_APPROVAL))


def rejected_draft_notes(previous: Optional[CoordinatorReview]) -> Optional[dict[str, Any]]:
    """What the analyst said about a rejected draft, for the next draft of the same section.

    Only when ``previous`` (the run just before) was rejected, and only its items marked fix_needed
    or carrying a note (a note on an accepted item is kept too).  None otherwise.  Read-only: it is
    shown beside the new review and never copied onto its items or counted in its approval.
    """
    if previous is None or previous.decision != REJECTED:
        return None
    entries = [{"ref": i.ref, "resolution": i.resolution, "note": i.resolution_note}
               for i in previous.review_items if i.resolution == FIX_NEEDED or (i.resolution_note or "").strip()]
    if not entries:
        return None
    return {"run_id": previous.run_id, "decided_at": previous.decided_at, "entries": entries}


# What a claim quoted from a supplied source adds (drafting/bedrock.py): the quote, which source it is and when
# it was saved. Only a claim that has them carries them, so every other claim's context is as it always was.
SOURCE_KEYS = ("source_id", "sha256", "fetched_at", "host", "published_date", "origin", "source_flags")
