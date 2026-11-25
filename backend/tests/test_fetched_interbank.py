import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly.agent import readiness
from cytonn_weekly.history import store
from cytonn_weekly.weekly import analyst, cbk_kesonia, fetched_items
from cytonn_weekly.weekly.week import Week

FIXTURE = Path(__file__).parent / "fixtures" / "sources" / "cbk_kesonia_captured_2026-11-18.json"
BODY = FIXTURE.read_bytes()
FRIDAY = "2026-10-02"
TODAY = date(2026, 11, 18)


def post(url, form):
    return BODY


def fake(key, week):
    return fetched_items.interbank(week, TODAY, post=post)


@pytest.fixture
def client(tmp_path):
    root, db = tmp_path / "weekly", tmp_path / "app.db"
    return TestClient(create_app(db_path=db, load_dotenv=False, inputs_root=root, fetch_items=fake)), root, db


def item(response, key="interbank"):
    return next(i for g in response.json()["groups"] for i in g["items"] if i["key"] == key)


def test_the_table_is_read_as_cbk_prints_it():
    rates, sha = cbk_kesonia.fetch_rates(post)
    assert len(rates) == 14 and rates[date(2026, 10, 1)] == str(json.loads(BODY)["data"][1][1]) and len(sha) == 64


@pytest.mark.parametrize("payload", [b"<html>", b"{}", b'{"data": []}', b'{"data": [["2026-10-01", "9.1"]]}', b'{"data": [["01/10/2026", "n/a"]]}'])
def test_a_page_not_in_the_expected_shape_is_refused_whole(payload):
    with pytest.raises(ValueError, match="KESONIA"):
        cbk_kesonia.parse_rates(payload)


def test_two_weeks_of_weekdays_are_fetched_with_the_source_in_the_note():
    rows, note = fetched_items.interbank(Week(date(2026, 10, 2)), TODAY, post=post)
    assert [r["date"] for r in rows][:2] == ["2026-09-18", "2026-09-21"] and rows[-1]["date"] == "2026-10-01" and len(rows) == 10
    assert note.startswith("Central Bank of Kenya, KESONIA, https://www.centralbank.go.ke/kesonia/, fetched 2026-11-18, sha256 ")


def test_a_day_the_table_does_not_have_yet_is_not_filled_in():
    with pytest.raises(LookupError, match="no rate yet for 2026-10-05, 2026-10-06, 2026-10-07, 2026-10-08"):
        fetched_items.interbank(Week(date(2026, 10, 9)), TODAY, post=post)


def test_the_route_keeps_the_rows_as_fetched_and_writes_each_point_once_with_its_source(client):
    c, root, db = client
    r = c.post(f"/api/inputs/weekly/{FRIDAY}/analyst/fetch/interbank?section=fixed_income")
    assert r.status_code == 200
    got = item(r)
    assert len(got["rows"]) == 10 and got["carried"]["from"] == "fetched" and got["carried"]["whole"] and not got["needs_confirmation"]
    assert got["source"] == "Central Bank of Kenya, KESONIA"
    points = store.current(db, "fi.interbank.rate")
    assert len(points) == 10
    assert {p["origin"] for p in points} == {"fetched"} and {p["source_kind"] for p in points} == {"source"}
    assert all("sha256 " in p["source_ref"] and p["confirmed_by"] == store.FETCHED for p in points)
    assert next(p for p in points if p["as_of"] == "2026-09-18")["week_ending"] == "2026-09-18"
    # a second fetch changes no point
    assert c.post(f"/api/inputs/weekly/{FRIDAY}/analyst/fetch/interbank").status_code == 200
    assert len(store.current(db, "fi.interbank.rate")) == 10


def test_the_chat_groups_a_fetched_table_as_fetched_until_someone_edits_it(client):
    c, root, db = client
    status = c.post(f"/api/inputs/weekly/{FRIDAY}/analyst/fetch/interbank").json()
    out = readiness.classify("fixed_income", {"slots": [], "week_ending": FRIDAY}, status)
    assert {"kind": "table", "key": "interbank", "label": "Daily interbank rates", "why": "fetched by the tool", "other_week": False} in out["groups"]["fetched"]
    rows = item(c.get(f"/api/inputs/weekly/{FRIDAY}/analyst")) ["rows"]
    rows[0] = {**rows[0], "rate": "9.9999"}
    assert c.put(f"/api/inputs/weekly/{FRIDAY}/analyst", json={"tables": {"interbank": {"rows": rows}}}).status_code == 200
    edited = item(c.get(f"/api/inputs/weekly/{FRIDAY}/analyst"))
    assert not (edited["carried"] or {}).get("whole")
    first = next(p for p in store.current(db, "fi.interbank.rate") if p["as_of"] == "2026-09-18")
    assert first["origin"] == "typed" and first["value"] == "9.9999"


def test_rows_someone_typed_are_never_replaced(client):
    c, root, db = client
    typed = [{"date": "2026-10-01", "rate": "9.1"}]
    assert c.put(f"/api/inputs/weekly/{FRIDAY}/analyst", json={"tables": {"interbank": {"rows": typed}}}).status_code == 200
    r = c.post(f"/api/inputs/weekly/{FRIDAY}/analyst/fetch/interbank")
    assert r.status_code == 409 and "already typed" in r.json()["detail"]
    assert analyst.read_form(Week(date(2026, 10, 2)), root)["tables"]["interbank"] == typed


def test_a_fetch_that_fails_says_to_type_it_and_keeps_nothing(tmp_path):
    cases = [(LookupError("KESONIA has no rate yet"), 404, "not available yet"), (ValueError("CBK's KESONIA table returned no rows"), 502, "could not be fetched"),
             (OSError("down"), 502, "could not be fetched")]
    for exc, status, words in cases:
        def broken(key, week, exc=exc):
            raise exc
        root, db = tmp_path / f"w{status}{type(exc).__name__}", tmp_path / f"{type(exc).__name__}.db"
        c = TestClient(create_app(db_path=db, load_dotenv=False, inputs_root=root, fetch_items=broken))
        r = c.post(f"/api/inputs/weekly/{FRIDAY}/analyst/fetch/interbank")
        assert r.status_code == status and words in r.json()["detail"] and "type" in r.json()["detail"].lower()
        assert r.json()["problems"][0]["code"] == "item_fetch_failed"
        assert analyst.read_form(Week(date(2026, 10, 2)), root)["tables"] == {} and store.current(db, "fi.interbank.rate") == []


def test_a_key_that_is_not_fetched_is_a_404(client):
    assert client[0].post(f"/api/inputs/weekly/{FRIDAY}/analyst/fetch/mmf").status_code == 404
