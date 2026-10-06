"""Tests for cytonn_weekly.digital_payments.review_store, against a real SQLite file.

Every test writes to its own temp database built from the project's actual
cytonn_weekly/schema.sql (via sections.init_db), not a mock.  The reviews come from the real
pipeline code on fake edges (see review_helpers).
"""

import json
import sqlite3
from datetime import date

import pytest
from review_helpers import make_review

from cytonn_weekly.digital_payments import coordinator_review as cr
from cytonn_weekly.digital_payments import review_store as rs


@pytest.fixture
def db(tmp_path):
    return tmp_path / "reviews.db"


def mixed_resolutions(review):
    """Resolve a spread of items: accept, fix_needed with a note, and leave some unresolved."""
    items = review.review_items
    items[0].resolve(cr.ACCEPT)
    items[1].resolve(cr.FIX_NEEDED, "price looks stale; check Yahoo")
    items[2].resolve(cr.ACCEPT, "fine, rounding only")
    # items[3:] stay unresolved
    return review


def accept_everything(review):
    review.accept_all_clean()
    for i in review.review_items:
        if i.resolution is None:
            i.resolve(cr.ACCEPT)
    return review


def rows(db, sql="SELECT * FROM coordinator_reviews ORDER BY run_id"):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def test_schema_has_the_table_columns_and_lookup_index(db):
    rs.save_review(make_review(), db_path=db)
    info = rows(db, "PRAGMA table_info(coordinator_reviews)")
    assert [r["name"] for r in info] == [
        "run_id", "section", "run_date", "created_at", "updated_at",
        "decision", "decided_at", "content_json", "items_json", "report_type", "period",
    ]
    idx = rows(db, "PRAGMA index_list(coordinator_reviews)")
    (lookup,) = [i for i in idx if i["name"] == "idx_coordinator_reviews_lookup"]
    cols = [r["name"] for r in rows(db, "PRAGMA index_info(idx_coordinator_reviews_lookup)")]
    assert cols == ["section", "run_date", "decision"] and lookup["unique"] == 0


def test_schema_rejects_a_bad_decision_and_a_decision_without_a_timestamp(db):
    rs.save_review(make_review(), db_path=db)
    conn = sqlite3.connect(db)
    for bad in ("UPDATE coordinator_reviews SET decision = 'maybe', decided_at = 'x'",
                "UPDATE coordinator_reviews SET decision = 'approved'"):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(bad)
    conn.close()


# ---------------------------------------------------------------------------
# Round trips
# ---------------------------------------------------------------------------

def test_round_trip_with_mixed_resolutions_reloads_identically(db):
    review = mixed_resolutions(make_review(tamper=True))
    run_id = rs.save_review(review, run_date=date(2026, 9, 30), db_path=db)

    loaded = rs.load_review(run_id, db_path=db)

    assert loaded == review  # section, every item (incl. Flag objects, context), decision, run_id
    assert loaded is not review
    assert [i.resolution for i in loaded.review_items[:4]] == [cr.ACCEPT, cr.FIX_NEEDED, cr.ACCEPT, None]
    assert loaded.review_items[1].resolution_note == "price looks stale; check Yahoo"
    flagged = loaded.by_status(cr.FLAGGED)
    assert flagged and all(isinstance(f, cr.Flag) for i in flagged for f in i.detail)
    assert loaded.is_approvable == review.is_approvable is False


def test_round_trip_after_a_decision_keeps_decision_and_timestamp(db):
    review = accept_everything(make_review())
    review.decide("approved")
    assert review.decided_at

    run_id = rs.save_review(review, db_path=db)
    loaded = rs.load_review(run_id, db_path=db)

    assert loaded == review
    assert (loaded.decision, loaded.decided_at) == (cr.APPROVED, review.decided_at)
    assert loaded.is_approvable
    (row,) = rows(db)
    assert (row["decision"], row["decided_at"]) == (cr.APPROVED, review.decided_at)  # indexed column too


def test_rejected_review_round_trips_too(db):
    review = mixed_resolutions(make_review())
    review.decide("rejected")
    loaded = rs.load_review(rs.save_review(review, db_path=db), db_path=db)
    assert loaded == review and loaded.decision == cr.REJECTED


def test_a_reloaded_review_behaves_like_the_original(db):
    run_id = rs.save_review(mixed_resolutions(make_review()), db_path=db)
    loaded = rs.load_review(run_id, db_path=db)
    accept_everything(loaded)
    loaded.review_items[1].resolve(cr.ACCEPT)  # the fix_needed one
    assert loaded.is_approvable
    loaded.decide("approved")


def test_content_is_stored_as_json_and_survives_float_and_none_values(db):
    review = make_review()
    run_id = rs.save_review(review, db_path=db)
    (row,) = rows(db)
    assert json.loads(row["content_json"]) == review.section
    assert len(json.loads(row["items_json"])) == len(review.review_items)
    rows_in = next(i["rows"] for i in rs.load_review(run_id, db_path=db).section["items"] if i["kind"] == "stock_table")
    assert rows_in[0]["current_price"] == 100.0 and rows_in[0]["error"] is None


# ---------------------------------------------------------------------------
# Insert vs update
# ---------------------------------------------------------------------------

def test_first_save_inserts_and_sets_run_id_later_saves_update_the_same_row(db):
    review = make_review()
    assert review.run_id is None
    run_id = rs.save_review(review, run_date="2026-09-30", db_path=db)
    assert review.run_id == run_id
    (before,) = rows(db)
    assert (before["section"], before["run_date"], before["decision"]) == ("digital_payments", "2026-09-30", None)

    review.review_items[0].resolve(cr.ACCEPT, "ok")
    assert rs.save_review(review, db_path=db) == run_id

    (after,) = rows(db)  # still exactly one row
    assert after["run_id"] == run_id and after["created_at"] == before["created_at"]
    assert after["content_json"] == before["content_json"]  # draft content is never rewritten
    assert rs.load_review(run_id, db_path=db).review_items[0].resolution_note == "ok"


def test_each_review_gets_its_own_run_id(db):
    a, b = make_review(), make_review()
    assert rs.save_review(a, db_path=db) != rs.save_review(b, db_path=db)
    assert len(rows(db)) == 2


def test_run_date_defaults_to_today_and_rejects_garbage(db):
    rs.save_review(make_review(), db_path=db)
    assert rows(db)[0]["run_date"] == date.today().isoformat()
    with pytest.raises(ValueError):
        rs.save_review(make_review(), run_date="not-a-date", db_path=db)


def test_updating_an_unknown_run_id_raises(db):
    review = make_review()
    review.run_id = 999
    with pytest.raises(LookupError):
        rs.save_review(review, db_path=db)


# ---------------------------------------------------------------------------
# Frozen once decided
# ---------------------------------------------------------------------------

def test_a_stale_copy_cannot_reopen_a_decided_review(db):
    review = make_review()
    run_id = rs.save_review(review, db_path=db)
    stale = rs.load_review(run_id, db_path=db)  # e.g. a second browser tab

    accept_everything(review)
    review.decide("approved")
    rs.save_review(review, db_path=db)

    stale.review_items[0].resolve(cr.FIX_NEEDED, "late edit")
    with pytest.raises(rs.ReviewAlreadyDecided, match="already approved"):
        rs.save_review(stale, db_path=db)

    reloaded = rs.load_review(run_id, db_path=db)
    assert reloaded.decision == cr.APPROVED and reloaded == review


def test_saving_the_same_decided_review_again_is_a_no_op(db):
    review = make_review()
    review.decide("rejected")
    rs.save_review(review, db_path=db)
    rs.save_review(review, db_path=db)  # same decision and timestamp: allowed
    assert rs.load_review(review.run_id, db_path=db) == review


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def test_load_review_of_unknown_id_raises_keyerror(db):
    with pytest.raises(KeyError):
        rs.load_review(1, db_path=db)


def test_load_latest_is_none_on_an_empty_database(db):
    assert rs.load_latest_review(db_path=db) is None


def test_load_latest_returns_the_newest_review_for_the_section(db):
    first, second = make_review(), make_review()
    rs.save_review(first, run_date="2026-09-29", db_path=db)
    rs.save_review(second, run_date="2026-09-30", db_path=db)
    other = make_review()
    rs.save_review(other, section="equities", db_path=db)

    assert rs.load_latest_review(db_path=db).run_id == second.run_id
    assert rs.load_latest_review("equities", db_path=db).run_id == other.run_id
    assert rs.load_latest_review("focus", db_path=db) is None


def test_load_latest_can_be_limited_to_a_run_date(db):
    old, today = make_review(), make_review()
    rs.save_review(old, run_date="2026-09-29", db_path=db)
    assert rs.load_latest_review(run_date=date(2026, 9, 30), db_path=db) is None
    rs.save_review(today, run_date=date(2026, 9, 30), db_path=db)
    assert rs.load_latest_review(run_date="2026-09-30", db_path=db).run_id == today.run_id
    assert rs.load_latest_review(run_date="2026-09-29", db_path=db).run_id == old.run_id


def test_decided_reviews_are_returned_too_so_later_tasks_can_find_them(db):
    review = accept_everything(make_review())
    review.decide("approved")
    rs.save_review(review, db_path=db)
    assert rs.load_latest_review(db_path=db).decision == cr.APPROVED


def test_the_review_table_lives_alongside_the_sections_table(db):
    from cytonn_weekly import sections

    rs.save_review(make_review(), db_path=db)
    assert sections.get_section_config("Digital Payments", db_path=db)["in_active_build"]  # seed intact
