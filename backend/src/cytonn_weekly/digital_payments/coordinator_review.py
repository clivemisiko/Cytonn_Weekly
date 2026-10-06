"""Coordinator review model for the Digital Payments section (backlog task 8).

Turns compose_section()'s output plus the checking layer's CheckReport into one
flat list of ReviewItems, one per checkable unit (a table row, an outlook stat,
or a highlight claim), so the coordinator's single accuracy pass has something
concrete to resolve.  The tool never approves anything: the only thing this
module computes is whether the coordinator's own resolutions allow an approval
decision, and ``decide()`` records the coordinator's call.

Statuses
--------
* ``flagged``           -- the checker raised a mismatch / missing / unsourced /
                           sources_disagree flag for it.
* ``clean``             -- checked with no flag.  Still listed, so the
                           coordinator sees full coverage and not just problems.
* ``not_auto_verified`` -- every highlight claim, until task 6b exists.  This is
                           deliberately not a flag: nothing was found wrong, the
                           tool just has not checked it.

This module only consumes existing outputs; it changes nothing in
compose_section(), checkers/digital_payments.py or any provider.

Typical usage
-------------
    review = build_coordinator_review(compose_section(draft, table, outlook), report)
    review.items[0].resolve("accept")
    ...
    if review.is_approvable:
        review.decide("approved")
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Union

from cytonn_weekly.checkers.digital_payments import NOT_IMPLEMENTED, CheckReport, Flag

# ReviewItem.kind
TABLE_ROW = "table_row"
OUTLOOK_STAT = "outlook_stat"
HIGHLIGHT_CLAIM = "highlight_claim"

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

NOT_AUTO_VERIFIED_NOTE = (
    "Not yet automatically checked: citation verification (task 6b) is not built. "
    "This is not a flag and nothing was found wrong; the tool has simply not verified "
    "this claim, so check it against its cited source by hand."
)

_REF_CLAIM_CHARS = 80


@dataclass
class ReviewItem:
    """One checkable unit awaiting the coordinator's resolution."""

    kind: str                       # TABLE_ROW | OUTLOOK_STAT | HIGHLIGHT_CLAIM
    ref: str                        # human-readable label
    status: str                     # FLAGGED | CLEAN | NOT_AUTO_VERIFIED
    # FLAGGED: the checker's Flag objects for this unit (a table row can carry
    # several, one per figure).  NOT_AUTO_VERIFIED: the fixed note.  CLEAN: None.
    detail: Union[list[Flag], str, None] = None
    resolution: Optional[str] = None  # None | ACCEPT | FIX_NEEDED
    resolution_note: Optional[str] = None
    # HIGHLIGHT_CLAIM only: the claim as drafted ({text, url, title, cited_text}), so the
    # coordinator can open the source and check it by hand.  Empty for other kinds.
    context: dict[str, Any] = field(default_factory=dict)

    def resolve(self, resolution: Optional[str], note: Optional[str] = None) -> None:
        """Record the coordinator's call (``None`` clears it)."""
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
        """True only when every item is resolved and none needs a fix.

        An empty review is never approvable: nothing was reviewed.
        """
        return bool(self.review_items) and all(
            i.resolution is not None and i.resolution != FIX_NEEDED for i in self.review_items
        )

    def by_status(self, status: str) -> list[ReviewItem]:
        return [i for i in self.review_items if i.status == status]

    def accept_all_clean(self) -> int:
        """Accept every CLEAN item the coordinator has not resolved yet; return how many.

        Touches nothing else: flagged and not_auto_verified items always need an
        individual call, and a clean item the coordinator already resolved (say, as
        fix_needed because they spotted something the checker could not) is left alone.
        """
        n = 0
        for i in self.review_items:
            if i.status == CLEAN and i.resolution is None:
                i.resolve(ACCEPT)
                n += 1
        return n

    def decide(self, decision: str) -> None:
        """Record the coordinator's final call, once.

        "approved" requires ``is_approvable``.  "rejected" is always allowed:
        ``fix_needed`` makes the review unapprovable, and sending it back is
        exactly what a coordinator does then, so gating rejection on
        approvability would make it impossible when it is needed most.
        """
        if decision not in (APPROVED, REJECTED):
            raise ValueError(f"decision must be {APPROVED!r} or {REJECTED!r}, got {decision!r}")
        if self.decision is not None:
            raise ValueError(f"review already decided ({self.decision!r}); build a new review")
        if decision == APPROVED and not self.is_approvable:
            unresolved = sum(1 for i in self.review_items if i.resolution is None)
            fixes = sum(1 for i in self.review_items if i.resolution == FIX_NEEDED)
            raise ValueError(
                f"cannot approve: {unresolved} item(s) unresolved, {fixes} marked fix_needed"
                if self.review_items else "cannot approve: the review has no items"
            )
        self.decision = decision
        self.decided_at = datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

def _item(kind: str, ref: str, flags: list[Flag]) -> ReviewItem:
    if flags:
        return ReviewItem(kind=kind, ref=ref, status=FLAGGED, detail=flags)
    return ReviewItem(kind=kind, ref=ref, status=CLEAN)


def _claim_ref(numeral: str, h: dict[str, Any], text: str) -> str:
    text = " ".join(text.split())
    if len(text) > _REF_CLAIM_CHARS:
        text = text[: _REF_CLAIM_CHARS - 1].rstrip() + "…"
    who = h.get("company") or h.get("headline", "")
    return f"Highlight {numeral} ({who}): {text}" if text else f"Highlight {numeral} ({who})"


def _claim_context(claim: dict[str, Any]) -> dict[str, Any]:
    return {k: claim.get(k, "") for k in ("text", "url", "title", "cited_text")}


def _unverified(ref: str, claim: dict[str, Any]) -> ReviewItem:
    return ReviewItem(
        kind=HIGHLIGHT_CLAIM, ref=ref, status=NOT_AUTO_VERIFIED,
        detail=NOT_AUTO_VERIFIED_NOTE, context=_claim_context(claim),
    )


def build_coordinator_review(compose_result: dict[str, Any], check_report: CheckReport) -> CoordinatorReview:
    """Build the coordinator's review items from compose_section() and its CheckReport.

    CheckReport holds only flags and a count of figures compared; it records
    nothing about what passed.  "Clean" is therefore derived: every unit that
    compose_section() contains and that no flag points at.  Every flag the
    checker raised (other than the NOT_IMPLEMENTED placeholder, which the
    ``not_auto_verified`` highlight items stand in for) ends up on some item,
    even if it points at something compose_section() does not contain, so none
    can go missing.

    Raises ValueError if the report compared nothing at all while the section
    has things to check, since every item would then read "clean" without
    anything having been checked.
    """
    flags = [f for f in check_report.flags if f.kind != NOT_IMPLEMENTED]
    table_flags: dict[str, list[Flag]] = {}
    outlook_flags: dict[str, list[Flag]] = {}
    highlight_flags: dict[str, list[Flag]] = {}
    for f in flags:
        if f.scope == "table":
            table_flags.setdefault(f.subject, []).append(f)
        elif f.scope == "outlook":
            outlook_flags.setdefault(f.field or "outlook", []).append(f)
        elif f.scope == "highlight":
            highlight_flags.setdefault(f.subject, []).append(f)
        else:
            raise ValueError(f"flag with unrecognised scope {f.scope!r}: {f.message}")

    items: list[dict[str, Any]] = compose_result.get("items", [])
    outlook = compose_result.get("outlook") or {}
    stats: dict[str, Any] = outlook.get("stats") or {}
    table_rows = [r for it in items if it.get("kind") == "stock_table" for r in it.get("rows", [])]

    if check_report.checked == 0 and not flags and (table_rows or stats):
        raise ValueError(
            "check_report compared no figures, so nothing would be checked; "
            "run check_digital_payments() with the drafted table rows and outlook stats first"
        )

    review: list[ReviewItem] = []

    # Table rows: one per source row, then any flagged ticker compose does not contain.
    seen: set[str] = set()
    for r in table_rows:
        ticker = r["ticker"]
        seen.add(ticker)
        review.append(_item(TABLE_ROW, f"{r.get('company', ticker)} ({ticker})", table_flags.get(ticker, [])))
    for ticker, fl in table_flags.items():
        if ticker not in seen:
            review.append(_item(TABLE_ROW, ticker, fl))

    # Outlook stats: one per drafted stat, then any flagged stat that was not drafted (e.g. missing).
    stat_keys = list(stats) + [k for k in outlook_flags if k not in stats]
    for key in stat_keys:
        review.append(_item(OUTLOOK_STAT, f"Outlook: {key}", outlook_flags.get(key, [])))

    # Highlight claims: always not_auto_verified until 6b; a highlight flag (6b's, once it
    # exists) marks every claim of that highlight as flagged rather than being dropped.
    matched: set[str] = set()
    for it in items:
        if it.get("kind") != "highlight":
            continue
        numeral = it.get("numeral", "")
        headline = it.get("headline", "")
        own = highlight_flags.get(headline, [])
        if own:
            matched.add(headline)
        claims = it.get("claims") or [{"text": ""}]  # no claims: still list the highlight itself
        for c in claims:
            ref = _claim_ref(numeral, it, c.get("text", ""))
            if own:
                review.append(ReviewItem(
                    kind=HIGHLIGHT_CLAIM, ref=ref, status=FLAGGED, detail=list(own),
                    context=_claim_context(c),
                ))
            else:
                review.append(_unverified(ref, c))
    for headline, fl in highlight_flags.items():
        if headline not in matched:
            review.append(ReviewItem(kind=HIGHLIGHT_CLAIM, ref=headline, status=FLAGGED, detail=fl))

    return CoordinatorReview(section=compose_result, review_items=review)
