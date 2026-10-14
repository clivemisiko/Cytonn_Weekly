"""The notes of a rejected draft, shown on the next draft of the same section, report and period.

The lookup takes only the run just before; the panel is there only when that run was rejected and
holds a fix-needed item or a note; nothing of it reaches the new review's items or its approval.
"""

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly.digital_payments import review_store
from cytonn_weekly.digital_payments.coordinator_review import ACCEPT, FIX_NEEDED, rejected_draft_notes
from tests.review_helpers import make_review

WEEK = "Week ending 2026-10-09"


@pytest.fixture
def db(tmp_path):
    return tmp_path / "notes.db"


@pytest.fixture
def client(db):
    return TestClient(create_app(db_path=db, load_dotenv=False))


def saved(db, *, section="digital_payments", period=WEEK, report_type="weekly", resolve=(), decision=None) -> int:
    """A real Digital Payments review saved under that key; ``resolve`` is [(index, resolution, note)]."""
    review = make_review()
    review.report_type, review.period = report_type, period
    for index, resolution, note in resolve:
        review.review_items[index].resolve(resolution, note)
    if decision == "approved":
        for item in review.review_items:
            if item.resolution is None:
                item.resolve(ACCEPT)
    if decision is not None:
        review.decide(decision)
    return review_store.save_review(review, section=section, db_path=db)


def notes(client, run_id):
    r = client.get(f"/api/reviews/{run_id}/rejected-draft-notes")
    assert r.status_code == 200
    return r.json()


def test_the_run_just_before_is_rejected_its_fix_needed_items_and_notes_are_listed(db, client):
    first = saved(db, resolve=[(0, FIX_NEEDED, "Wrong close for Visa."), (1, ACCEPT, "Checked by hand against Yahoo."),
                               (2, FIX_NEEDED, None)], decision="rejected")
    second = saved(db)
    refs = [i.ref for i in review_store.load_review(first, db_path=db).review_items]
    got = notes(client, second)
    assert got["run_id"] == first and got["decided_at"]
    assert got["entries"] == [
        {"ref": refs[0], "resolution": "fix_needed", "note": "Wrong close for Visa."},
        {"ref": refs[1], "resolution": "accept", "note": "Checked by hand against Yahoo."},   # a note on an Accept item counts
        {"ref": refs[2], "resolution": "fix_needed", "note": None},
    ]
    # nothing was copied onto the new review, and its approval is its own
    new = review_store.load_review(second, db_path=db)
    assert all(i.resolution is None and i.resolution_note is None for i in new.review_items) and not new.is_approvable


def test_none_when_the_run_before_was_approved_or_undecided_or_there_is_none(db, client):
    assert notes(client, saved(db)) is None                                   # a first draft
    assert notes(client, saved(db)) is None                                   # the run before is undecided
    saved(db, resolve=[(0, ACCEPT, "Fine as drafted.")], decision="approved")
    assert notes(client, saved(db)) is None                                   # the run before was approved, note and all


def test_none_when_the_rejected_run_holds_no_fix_needed_item_and_no_note(db, client):
    saved(db, resolve=[(0, ACCEPT, None), (1, ACCEPT, "   ")], decision="rejected")
    assert notes(client, saved(db)) is None


def test_only_the_latest_earlier_run_is_used(db, client):
    saved(db, resolve=[(0, FIX_NEEDED, "From the oldest draft.")], decision="rejected")
    middle = saved(db, resolve=[(1, FIX_NEEDED, "From the middle draft.")], decision="rejected")
    newest = saved(db)
    got = notes(client, newest)
    assert got["run_id"] == middle and [e["note"] for e in got["entries"]] == ["From the middle draft."]
    # and a run whose own predecessor was approved shows nothing, though an older run was rejected
    saved(db, decision="approved")
    assert notes(client, saved(db)) is None


def test_other_sections_weeks_and_reports_are_never_looked_at(db, client):
    rejected = saved(db, resolve=[(0, FIX_NEEDED, "Digital Payments, week of 9 October.")], decision="rejected")
    assert notes(client, saved(db, section="real_estate")) is None                       # another section
    assert notes(client, saved(db, period="Week ending 2026-10-16")) is None             # another week
    assert notes(client, saved(db, report_type="quarterly", period="Q3'2026")) is None   # another report
    assert notes(client, saved(db))["run_id"] == rejected        # the same key still finds it past the others


def test_an_unknown_run_is_a_404_and_the_rule_itself_needs_a_rejected_review():
    client = TestClient(create_app(load_dotenv=False))
    assert client.get("/api/reviews/999/rejected-draft-notes").status_code == 404
    assert rejected_draft_notes(None) is None
    undecided = make_review()
    undecided.review_items[0].resolve(FIX_NEEDED, "a note")
    assert rejected_draft_notes(undecided) is None
