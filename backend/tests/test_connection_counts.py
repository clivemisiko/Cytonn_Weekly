"""How many database connections each screen's calls open, on SQLite, with no network.

Every store call opens its own connection (``db.connect``); on PostgreSQL each costs about 1.5 s, so this count is the cost
of a screen.  The numbers are pinned: a change in them is a change in what a screen costs, and should be deliberate.
Run with ``-s`` to see the table.
"""

import threading

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly import db as database
from cytonn_weekly import jobs
from cytonn_weekly.run_store import RunStore
from cytonn_weekly.digital_payments import review_run
from cytonn_weekly.review import store as review_store
from tests.agent_helpers import agent_for, say
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
    for write in ("put_run", "put_event", "put_usage"):   # a run is also written through to its own tables, one connection a write (test_run_store.py)
        monkeypatch.setattr(RunStore, write, lambda *a, **k: None)
    opened = []
    real_connect = database.connect
    monkeypatch.setattr(database, "connect", lambda p=None: (opened.append(1), real_connect(p))[1])
    run_id = start(client, **WEEKLY_DP)
    run = finished(client, run_id)
    assert run["status"] == "finished"
    TABLE.append(("a finished draft (its save)", len(opened)))
    assert len(opened) == 1
    assert count("run view (one poll)", lambda c: c.get(f"/api/runs/{run_id}")) == 0


def test_the_chat_routes_cost(counted, tmp_path, monkeypatch):
    client, _, count = counted
    week = {"section": "equities", "period": "Week ending 2026-10-02"}
    assert count("chat: open a conversation (and its readiness card)", lambda c: c.post("/api/jobs", json=week)) == 2
    assert count("chat: open it again", lambda c: c.post("/api/jobs", json=week)) == 1
    assert count("chat: the job", lambda c: c.get("/api/jobs/1")) == 1
    assert count("chat: one poll for messages", lambda c: c.get("/api/jobs/1/messages", params={"after": 0})) == 2
    assert count("chat: the readiness check, run again", lambda c: c.get("/api/jobs/1/readiness")) == 1
    jobs.finish(tmp_path / "app.db", 1, jobs.CALL_BUDGET)
    assert count("chat: raise the budget", lambda c: c.post("/api/jobs/1/raise-budget")) == 4
    # a message: the worker is held at the model factory, so only the request's own connections are counted
    gate = threading.Event()
    agent, _ = agent_for(say("Hi."))
    app = create_app(db_path=tmp_path / "app.db", load_dotenv=False, chat_agent=lambda: (gate.wait(10), agent)[1])
    with TestClient(app) as chat:
        opened = []
        real_connect = database.connect
        monkeypatch.setattr(database, "connect", lambda p=None: (opened.append(1), real_connect(p))[1])
        assert chat.post("/api/jobs/1/messages", json={"content": "hello"}).status_code == 202
        TABLE.append(("chat: send a message (202)", len(opened)))
        assert len(opened) == 4
        gate.set()


def test_zz_print_the_table(capsys):
    with capsys.disabled():
        print("\n  connections opened per call (SQLite, per-call connect)")
        for label, n in TABLE:
            print(f"  {n:>3}  {label}")
