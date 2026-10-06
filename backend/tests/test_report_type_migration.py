"""The coordinator_reviews migration that added report_type and period (sections._migrate).

A database from before report types has neither column; every review in it must stay
readable, unchanged, as a weekly review with no period label.
"""

import hashlib
import json
import shutil
import sqlite3

import pytest

from cytonn_weekly import paths, sections
from cytonn_weekly.digital_payments import review_store as rs
from cytonn_weekly.report_sections import latest_runs
from tests.review_helpers import make_review

# coordinator_reviews exactly as schema.sql created it before report types (and its index).
OLD_SCHEMA = """
CREATE TABLE coordinator_reviews (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    section       TEXT    NOT NULL,
    run_date      TEXT    NOT NULL,
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL,
    decision      TEXT    CHECK (decision IN ('approved', 'rejected') OR decision IS NULL),
    decided_at    TEXT,
    content_json  TEXT    NOT NULL,
    items_json    TEXT    NOT NULL,
    CHECK ((decision IS NULL) = (decided_at IS NULL))
);
CREATE INDEX idx_coordinator_reviews_lookup ON coordinator_reviews (section, run_date, decision);
"""


def columns(db):
    conn = sqlite3.connect(db)
    try:
        return [r[1] for r in conn.execute("PRAGMA table_info(coordinator_reviews)")]
    finally:
        conn.close()


def rows(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM coordinator_reviews ORDER BY run_id")]
    finally:
        conn.close()


@pytest.fixture
def old_db(tmp_path):
    """A pre-report-types database holding a decided Digital Payments review and an open Real Estate one."""
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    review = make_review()
    items = json.dumps([i.to_dict() for i in review.review_items])
    conn.executescript(OLD_SCHEMA)
    conn.execute("INSERT INTO coordinator_reviews (section, run_date, created_at, updated_at, decision, decided_at, "
                 "content_json, items_json) VALUES ('digital_payments', '2026-10-02', 't', 't', 'approved', 'd', ?, ?)",
                 (json.dumps(review.section), items))
    conn.execute("INSERT INTO coordinator_reviews (section, run_date, created_at, updated_at, decision, decided_at, "
                 "content_json, items_json) VALUES ('real_estate', '2026-10-02', 't', 't', NULL, NULL, ?, ?)",
                 (json.dumps({"section": "real_estate", "blocks": []}), "[]"))
    conn.commit()
    conn.close()
    return db


def test_migration_adds_the_columns_and_keeps_every_row(old_db):
    before = rows(old_db)
    sections.init_db(old_db)
    after = rows(old_db)
    assert columns(old_db)[-2:] == ["report_type", "period"]
    assert len(after) == len(before)
    for b, a in zip(before, after):
        assert {k: a[k] for k in b} == b                       # nothing that was there changed
        assert (a["report_type"], a["period"]) == ("weekly", "")


def test_migrated_reviews_read_back_as_weekly_and_stay_frozen(old_db):
    sections.init_db(old_db)
    dp = rs.load_review(1, db_path=old_db)
    assert (dp.report_type, dp.period, dp.decision) == ("weekly", "", "approved")
    assert rs.load_latest_review("digital_payments", db_path=old_db).run_id == 1
    assert set(latest_runs(old_db)) == {"digital_payments", "real_estate"}
    dp.decision = "rejected"
    with pytest.raises(rs.ReviewAlreadyDecided):
        rs.save_review(dp, db_path=old_db)


def test_migration_is_idempotent_and_matches_a_fresh_database(old_db, tmp_path):
    sections.init_db(old_db)
    sections.init_db(old_db)
    fresh = tmp_path / "fresh.db"
    sections.init_db(fresh)
    assert columns(old_db) == columns(fresh)
    conn = sqlite3.connect(old_db)
    try:
        idx = [r[1] for r in conn.execute("PRAGMA index_list(coordinator_reviews)")]
        cols = [r[2] for r in conn.execute("PRAGMA index_info(idx_coordinator_reviews_report)")]
        with pytest.raises(sqlite3.IntegrityError):  # the CHECK came along with the column
            conn.execute("UPDATE coordinator_reviews SET report_type = 'monthly'")
    finally:
        conn.close()
    assert "idx_coordinator_reviews_lookup" in idx and cols == ["report_type", "period", "section", "run_id"]


def test_new_reviews_after_migration_are_keyed_by_type_and_period(old_db):
    sections.init_db(old_db)
    review = make_review()
    review.report_type, review.period = "quarterly", "Q3'2026"
    rs.save_review(review, db_path=old_db)
    assert rs.load_latest_review("digital_payments", db_path=old_db).run_id == 1  # the weekly one, still
    q3 = rs.load_latest_review("digital_payments", report_type="quarterly", period="Q3'2026", db_path=old_db)
    assert (q3.run_id, q3.report_type, q3.period) == (review.run_id, "quarterly", "Q3'2026")


def test_migration_on_a_copy_of_the_real_database(tmp_path):
    """Migrates a copy of data/app.db when one exists; the original is only read, and its bytes must not change."""
    real = paths.DATA_DIR / "app.db"
    if not real.exists():
        pytest.skip("no data/app.db on this machine")
    digest = hashlib.sha256(real.read_bytes()).hexdigest()
    copy = tmp_path / "copy.db"
    shutil.copyfile(real, copy)
    before = rows(copy) if "section" in columns(copy) else []
    sections.init_db(copy)
    after = rows(copy)
    assert len(after) == len(before)
    for b, a in zip(before, after):
        assert {k: a[k] for k in b} == b
    for r in after:
        review = rs.load_review(r["run_id"], db_path=copy)
        assert len(review.review_items) == len(json.loads(r["items_json"]))
    assert hashlib.sha256(real.read_bytes()).hexdigest() == digest
