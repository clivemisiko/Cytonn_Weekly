"""Stage P2 smoke test: the PostgreSQL path against a real server.  Four checks, and only these.

Skipped unless CYTONN_TEST_DATABASE_URL is set, in the environment or in the repo-root .env (the environment wins, as
everywhere).  Everything runs in a throwaway schema with a random name (cw_smoke_<hex>), created by the first use and
dropped when the module ends, whether or not a check failed.  The app's own schema (cytonn) is never touched.  The URL
is never a test argument or a local, so a failure's output cannot show it.
"""

import json
import os
import secrets
from urllib.parse import urlsplit

import pytest
from dotenv import dotenv_values

from cytonn_weekly import db as database
from cytonn_weekly.digital_payments import coordinator_review as cr
from cytonn_weekly.digital_payments import review_store as rs
from cytonn_weekly.notable import store as notable_store
from cytonn_weekly.paths import REPO_ROOT
from tests.review_helpers import make_review

TEST_URL_ENV = "CYTONN_TEST_DATABASE_URL"
SCHEMA = f"cw_smoke_{secrets.token_hex(4)}"
WEEK, SECTION = "2026-10-02", "equities"


def configured_url() -> str:
    """The environment's value when the variable is there at all (even empty, which skips the test), else .env's."""
    value = os.environ[TEST_URL_ENV] if TEST_URL_ENV in os.environ else dotenv_values(REPO_ROOT / ".env").get(TEST_URL_ENV)
    return (value or "").strip()


pytestmark = pytest.mark.skipif(not configured_url(), reason=f"{TEST_URL_ENV} is not set")


@pytest.fixture(scope="module", autouse=True)
def the_throwaway_schema(network_allowlist):
    """Lets the session's network guard resolve the test database's host, and only that host, while this module runs;
    drops the throwaway schema at the end, whether or not a check failed."""
    host = urlsplit(configured_url()).hostname
    network_allowlist.add(host)
    try:
        yield
        assert SCHEMA.startswith("cw_smoke_")                      # the one thing this may drop
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv(database.DATABASE_URL_ENV, configured_url())
            mp.setenv(database.DATABASE_SCHEMA_ENV, SCHEMA)
            conn = database.connect()
            try:
                conn.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
            finally:
                conn.close()
    finally:
        network_allowlist.discard(host)


@pytest.fixture
def pg(no_ambient_settings, monkeypatch):
    """The test URL and the throwaway schema, for every database call that passes no path.  (It asks for
    no_ambient_settings itself so that the conftest's clean-up runs first and cannot remove what this sets.)"""
    monkeypatch.setenv(database.DATABASE_URL_ENV, configured_url())
    monkeypatch.setenv(database.DATABASE_SCHEMA_ENV, SCHEMA)


def stored(run_id):
    conn = database.connect()
    try:
        return dict(conn.execute("SELECT * FROM coordinator_reviews WHERE run_id = ?", (run_id,)).fetchone())
    finally:
        conn.close()


def decided(review, how=cr.APPROVED):
    review.accept_all_clean()
    for i in review.review_items:
        if i.resolution is None:
            i.resolve(cr.ACCEPT)
    review.decide(how)
    return review


# (i) the schema creates, and its table and column names are schema.sql's ---------------------------------------------------

def test_the_schema_creates_and_its_tables_and_columns_have_the_names_schema_sql_gives(pg, tmp_path):
    database.init_db()                                              # no path and a URL: PostgreSQL
    conn = database.connect()
    try:
        in_postgres = {(r["table_name"], r["column_name"]) for r in conn.execute(
            "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = ?", (SCHEMA,))}
    finally:
        conn.close()
    lite = database.open_db(tmp_path / "names.db")                  # an explicit path: SQLite, the reference
    try:
        tables = [r["name"] for r in lite.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        in_sqlite = {(t, c["name"]) for t in tables for c in lite.execute(f"PRAGMA table_info({t})")}
    finally:
        lite.close()
    assert {t for t, _ in in_sqlite} == {"sections", "coordinator_reviews", "suggestion_decisions"}
    assert in_postgres == in_sqlite


# (ii) a review is saved and read back with the same id and content ---------------------------------------------------------

def test_a_review_is_saved_and_read_back_with_the_same_id_and_content(pg):
    review = make_review()
    run_id = rs.save_review(review)
    assert isinstance(run_id, int) and review.run_id == run_id
    loaded = rs.load_review(run_id)
    assert loaded.run_id == run_id
    assert loaded.section == json.loads(json.dumps(review.section))
    assert [i.to_dict() for i in loaded.review_items] == [i.to_dict() for i in review.review_items]
    assert (loaded.report_type, loaded.period, loaded.decision, loaded.decided_at) == (review.report_type, review.period, None, None)


# (iii) a decided review cannot be changed to a different decision; an identical retry is accepted; NULL compares correctly -----

@pytest.mark.parametrize("change", ["other decision", "other time"])
def test_a_decided_review_refuses_a_different_decision_and_stays_as_it_was(pg, change):
    run_id = rs.save_review(decided(make_review()))
    before = stored(run_id)
    other = rs.load_review(run_id)
    if change == "other decision":
        other.decision = cr.REJECTED
    else:
        other.decided_at = "2099-01-01T00:00:00+00:00"
    with pytest.raises(rs.ReviewAlreadyDecided):
        rs.save_review(other)
    assert stored(run_id) == before


def test_an_identical_retry_of_a_decision_is_accepted(pg):
    review = decided(make_review(), cr.REJECTED)
    run_id = rs.save_review(review)
    before = stored(run_id)
    assert rs.save_review(review) == run_id
    after = stored(run_id)
    assert (after["decision"], after["decided_at"]) == (before["decision"], before["decided_at"]) == (cr.REJECTED, review.decided_at)
    assert after["content_json"] == before["content_json"]


def test_a_null_decided_at_compares_without_a_cast(pg):
    review = make_review()
    run_id = rs.save_review(review)                                 # decision and decided_at are both NULL
    review.review_items[0].resolve(cr.ACCEPT, "first")
    rs.save_review(review)                                          # NULL bound for both: the server must infer their type
    stale = rs.load_review(run_id)                                  # still undecided, so NULL and NULL
    rs.save_review(decided(review))
    stale.review_items[0].resolve(cr.FIX_NEEDED, "late edit")
    with pytest.raises(rs.ReviewAlreadyDecided, match="already approved"):
        rs.save_review(stale)                                       # NULL is not distinct from NULL, but 'approved' is not NULL
    assert stored(run_id)["decision"] == cr.APPROVED


# (iv) a Notable decision is saved with the upsert and read back ------------------------------------------------------------

def test_a_notable_decision_is_saved_with_the_upsert_and_read_back(pg):
    notable_store.save(None, WEEK, SECTION, "abc123", "selected", "An edited headline", None)
    first = notable_store.load(None, WEEK, SECTION)["abc123"]
    assert (first["decision"], first["edited_headline"], first["dismiss_reason"]) == ("selected", "An edited headline", None)
    assert first["decided_at"]
    notable_store.save(None, WEEK, SECTION, "abc123", "dismissed", None, "not_relevant")      # the same key: replaced, not added
    again = notable_store.load(None, WEEK, SECTION)
    assert list(again) == ["abc123"]
    assert (again["abc123"]["decision"], again["abc123"]["edited_headline"], again["abc123"]["dismiss_reason"]) == (
        "dismissed", None, "not_relevant")
