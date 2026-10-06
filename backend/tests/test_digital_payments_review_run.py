"""Tests for review_run (the pipeline wiring) and two CoordinatorReview behaviours the review UI relies on.

These three tests used to live in the Streamlit screen's test file.  They never touched Streamlit, so
they stayed when that screen was retired: the wiring is what the API's Draft endpoint calls, and
accept_all_clean / claim context are what the web screen shows.  No network, no LLM.
"""

from review_helpers import ROWS, TODAY, FakeProvider, make_review

from cytonn_weekly.digital_payments import coordinator_review as cr
from cytonn_weekly.digital_payments import review_run


def idx_of(review, fragment):
    (i,) = [n for n, it in enumerate(review.review_items) if fragment in it.ref]
    return i


def test_build_digital_payments_review_runs_the_pipeline_into_a_review():
    review = review_run.build_digital_payments_review(
        provider=FakeProvider(), today=TODAY, fetch_table=lambda today: ROWS,
    )
    assert isinstance(review, cr.CoordinatorReview)
    kinds = [i.kind for i in review.review_items]
    assert kinds.count(cr.TABLE_ROW) == 3 and kinds.count(cr.HIGHLIGHT_CLAIM) == 4
    # the checker compared formatted rows to the source rows: a faithful draft is all clean
    assert not review.by_status(cr.FLAGGED)
    assert {i.status for i in review.review_items if i.kind != cr.HIGHLIGHT_CLAIM} == {cr.CLEAN}
    assert review.section["week_end"] == TODAY.isoformat()


def test_accept_all_clean_resolves_only_unresolved_clean_items():
    review = make_review(tamper=True)
    mine = review.review_items[idx_of(review, "Visa (V)")]
    mine.resolve(cr.FIX_NEEDED, "I disagree")

    n = review.accept_all_clean()

    clean = review.by_status(cr.CLEAN)
    assert n == len(clean) - 1
    assert all(i.resolution == cr.ACCEPT for i in clean if i is not mine)
    assert mine.resolution == cr.FIX_NEEDED and mine.resolution_note == "I disagree"  # not overwritten
    others = review.by_status(cr.FLAGGED) + review.by_status(cr.NOT_AUTO_VERIFIED)
    assert others and all(i.resolution is None for i in others)
    assert review.accept_all_clean() == 0


def test_claim_items_carry_their_source_for_hand_checking():
    review = make_review()
    claim = next(i for i in review.review_items if i.kind == cr.HIGHLIGHT_CLAIM)
    assert claim.context["url"].startswith("https://") and claim.context["cited_text"]
    assert next(i for i in review.review_items if i.kind == cr.TABLE_ROW).context == {}
