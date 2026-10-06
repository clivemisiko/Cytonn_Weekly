"""The multi-section review API: the overview, per-section drafts, and the shared review endpoints.

Drafts run the real section pipelines on fake providers and fixed source data
(tests/section_helpers.py); the database is a temp file.
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly.digital_payments import review_store
from cytonn_weekly.equities import review_run as eq_run
from cytonn_weekly.focus import review_run as focus_run
from cytonn_weekly.real_estate import review_run as re_run
from tests import section_helpers as sh
from tests.review_helpers import make_review


@pytest.fixture
def db(tmp_path):
    return tmp_path / "app.db"


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(eq_run, "build_equities_review", lambda: sh.equities_review())
    monkeypatch.setattr(re_run, "build_real_estate_review", lambda: sh.real_estate_review())
    monkeypatch.setattr(focus_run, "build_focus_review", lambda topic: sh.focus_review(topic=topic))
    return TestClient(create_app(db_path=db, load_dotenv=False))


def test_overview_lists_five_sections_in_report_order(client):
    body = client.get("/api/sections").json()
    assert [s["slug"] for s in body["sections"]] == ["fixed_income", "equities", "digital_payments", "real_estate", "focus"]
    fi = body["sections"][0]
    assert fi["available"] is False and "KCB" in fi["reason"] and fi["unblock"] and len(fi["built_parts"]) == 3
    assert all(s["latest"] is None for s in body["sections"])
    focus = body["sections"][-1]
    assert focus["needs_topic"] is True and focus["steps"][0]["title"] == "Your topic"


def test_draft_saves_under_the_section_slug_and_shows_in_the_overview(client, db):
    r = client.post("/api/sections/equities/draft")
    assert r.status_code == 200
    review = r.json()
    assert (review["section_slug"], review["section_title"]) == ("equities", "Equities")
    assert review_store.load_latest_review("equities", db_path=db).run_id == review["run_id"]
    eq = next(s for s in client.get("/api/sections").json()["sections"] if s["slug"] == "equities")
    assert eq["latest"]["run_id"] == review["run_id"] and eq["latest"]["this_week"] is True
    assert eq["latest"]["progress"]["total"] == review["progress"]["total"] and eq["latest"]["decision"] is None


def test_generic_section_serialization(client):
    sec = client.post("/api/sections/equities/draft").json()["section"]
    kinds = [b["kind"] for b in sec["blocks"]]
    assert kinds[:5] == ["table", "table", "table", "unavailable", "unavailable"] and set(kinds[5:]) == {"narrative"}
    indices = sec["blocks"][0]
    assert indices["columns"][1] == {"key": "close", "label": "Close", "numeric": True}
    assert indices["rows"][0]["close"] == "246.8" and indices["rows"][0]["flagged"] is False
    assert "source_rows" not in indices  # the screen gets display strings only
    uoc = sec["blocks"][4]
    assert uoc["title"] == "Universe of Coverage" and "proprietary" in uoc["reason"]
    assert (sec["pieces_found"], sec["pieces_expected"]) == (3, 3)


def test_unavailable_section_cannot_be_drafted(client):
    r = client.post("/api/sections/fixed_income/draft")
    assert r.status_code == 409 and "KCB" in r.json()["detail"]
    assert client.post("/api/sections/nope/draft").status_code == 404


def test_focus_needs_a_topic_and_carries_it(client):
    assert client.post("/api/sections/focus/draft").status_code == 422
    assert client.post("/api/sections/focus/draft", json={"topic": "   "}).status_code == 422
    r = client.post("/api/sections/focus/draft", json={"topic": "SSA Eurobonds"})
    assert r.status_code == 200 and r.json()["section"]["topic"] == "SSA Eurobonds"


def test_resolve_and_approve_a_generic_review(client):
    review = client.post("/api/sections/real_estate/draft").json()
    run = review["run_id"]
    for item in review["review_items"]:
        if item["status"] != "clean":
            review = client.patch(f"/api/reviews/{run}/items/{item['index']}", json={"resolution": "accept"}).json()
    review = client.post(f"/api/reviews/{run}/accept-clean").json()
    assert review["is_approvable"] is True
    done = client.post(f"/api/reviews/{run}/decide", json={"decision": "approved"}).json()
    assert done["decision"] == "approved" and done["section_slug"] == "real_estate"
    assert client.patch(f"/api/reviews/{run}/items/0", json={"resolution": None}).status_code == 409
    re_row = next(s for s in client.get("/api/sections").json()["sections"] if s["slug"] == "real_estate")
    assert re_row["latest"]["decision"] == "approved"


def test_sections_are_independent(client, db):
    eq = client.post("/api/sections/equities/draft").json()
    focus = client.post("/api/sections/focus/draft", json={"topic": "Budget review"}).json()
    client.post(f"/api/reviews/{eq['run_id']}/decide", json={"decision": "rejected"})
    rows = {s["slug"]: s["latest"] for s in client.get("/api/sections").json()["sections"]}
    assert rows["equities"]["decision"] == "rejected" and rows["focus"]["decision"] is None
    assert rows["focus"]["topic"] == "Budget review"


def test_digital_payments_appears_in_the_overview_with_its_own_shape(client, db):
    review = make_review()
    review_store.save_review(review, db_path=db)
    row = next(s for s in client.get("/api/sections").json()["sections"] if s["slug"] == "digital_payments")
    assert row["latest"]["run_id"] == review.run_id
    body = client.get(f"/api/reviews/{review.run_id}").json()
    assert body["section_slug"] == "digital_payments" and "items" in body["section"]


def test_old_review_is_not_this_week(client, db):
    review = sh.focus_review()
    review_store.save_review(review, run_date=date.today() - timedelta(days=9), section="focus", db_path=db)
    row = next(s for s in client.get("/api/sections").json()["sections"] if s["slug"] == "focus")
    assert row["latest"]["this_week"] is False


def test_dev_mode_draft_is_marked(client, monkeypatch):
    monkeypatch.setattr(eq_run, "build_equities_review",
                        lambda: sh.equities_review(sh.LocalFakeNarrativeProvider()))
    body = client.post("/api/sections/equities/draft").json()
    assert body["is_dev_draft"] is True and body["dev_mode_label"]


def test_failed_draft_is_reported_not_saved(client, db, monkeypatch):
    def boom():
        raise RuntimeError("afx down")

    monkeypatch.setattr(eq_run, "build_equities_review", boom)
    r = client.post("/api/sections/equities/draft")
    assert r.status_code == 502 and "afx down" in r.json()["detail"]
    assert review_store.load_latest_review("equities", db_path=db) is None


def test_flagged_table_row_is_marked_in_the_serialized_table(client, db):
    from cytonn_weekly.common.review import build_review, check_section

    review = sh.real_estate_review()
    content = review.section
    content["blocks"][-1]["rows"][0]["price"] = "29.6"  # source 29.65 shows as "29.7"
    tampered = build_review(content, check_section(content))
    review_store.save_review(tampered, section="real_estate", db_path=db)
    body = client.get(f"/api/reviews/{tampered.run_id}").json()
    rows = body["section"]["blocks"][-1]["rows"]
    assert [r["flagged"] for r in rows] == [True, False, False]


def test_conftest_guard_covers_new_sections(monkeypatch):
    """An app built with no db_path falls back to sections._DEFAULT_DB, which conftest points at a temp file."""
    from pathlib import Path

    from cytonn_weekly import sections

    monkeypatch.setattr(eq_run, "build_equities_review", lambda: sh.equities_review())
    real_db = Path(__file__).parents[1] / "data" / "app.db"
    assert Path(sections._DEFAULT_DB) != real_db
    run_id = TestClient(create_app(load_dotenv=False)).post("/api/sections/equities/draft").json()["run_id"]
    assert review_store.load_review(run_id, db_path=sections._DEFAULT_DB).section["section"] == "equities"
