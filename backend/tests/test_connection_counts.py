"""How many database connections each screen's calls open, on SQLite, with no network.

Every store call opens its own connection (``db.connect``); on PostgreSQL each costs about 1.5 s, so this count is the cost
of a screen.  The numbers are pinned: a change in them is a change in what a screen costs, and should be deliberate.
Run with ``-s`` to see the table.
"""

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly import db as database
from cytonn_weekly.digital_payments import review_run, review_store
from tests.review_helpers import ROWS, TODAY, FakeProvider, make_review
from tests.test_runs_api import WEEKLY_DP, finished, start

WEEK = "2026-10-02"
SECTIONS = ("digital_payments", "fixed_income", "equities")  # three sections with a saved run
TABLE: list[tuple[str, int]] = []


@pytest.fixture
def counted(tmp_path, monkeypatch):
    """A client over a temp database with three saved weekly reviews, and a function that counts connects around a block."""
    path = tmp_path / "app.db"
    ids = {}
    for slug in SECTIONS:
        review = make_review()
        review.period = ""
        ids[slug] = review_store.save_review(review, section=slug, db_path=path)
    client = TestClient(create_app(db_path=path, load_dotenv=False))
    real, opened = database.connect, []
    monkeypatch.setattr(database, "connect", lambda p=None: (opened.append(1), real(p))[1])

    def count(label, call):
        opened.clear()
        response = call(client)
        assert response.status_code < 400, (label, response.status_code, response.text)
        TABLE.append((label, len(opened)))
        return len(opened)

    return client, ids, count


def test_connections_per_call(counted):
    client, ids, count = counted
    run_id = ids["digital_payments"]
    assert count("overview, 3 sections with a run", lambda c: c.get("/api/sections")) == 4          # 1 latest_runs + 1 per run
    assert count("review load", lambda c: c.get(f"/api/reviews/{run_id}")) == 1
    assert count("rejected-draft notes", lambda c: c.get(f"/api/reviews/{run_id}/rejected-draft-notes")) == 1
    assert count("notable panel", lambda c: c.get("/api/notable/digital_payments", params={"week_ending": WEEK})) == 1
    assert count("resolve one item", lambda c: c.patch(f"/api/reviews/{run_id}/items/0", json={"resolution": "accept"})) == 2
    assert count("accept clean", lambda c: c.post(f"/api/reviews/{run_id}/accept-clean")) == 2
    assert count("export status, 3 sections with a run", lambda c: c.get("/api/export/weekly")) == 4   # 1 latest_runs + 1 per run


def test_a_finished_draft_costs_one_connection_to_save_and_the_run_view_none(counted, monkeypatch):
    client, ids, count = counted
    real = review_run.build_digital_payments_review
    monkeypatch.setattr(review_run, "build_digital_payments_review", lambda on_event=None: real(
        provider=FakeProvider(), today=TODAY, fetch_table=lambda today: ROWS, on_event=on_event))
    opened = []
    real_connect = database.connect
    monkeypatch.setattr(database, "connect", lambda p=None: (opened.append(1), real_connect(p))[1])
    run_id = start(client, **WEEKLY_DP)
    run = finished(client, run_id)
    assert run["status"] == "finished"
    TABLE.append(("a finished draft (its save)", len(opened)))
    assert len(opened) == 1
    assert count("run view (one poll)", lambda c: c.get(f"/api/runs/{run_id}")) == 0


def test_zz_print_the_table(capsys):
    with capsys.disabled():
        print("\n  connections opened per call (SQLite, per-call connect)")
        for label, n in TABLE:
            print(f"  {n:>3}  {label}")
