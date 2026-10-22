"""The chart files and their route: written once per run, served only while their SHA-256 matches the review's.

The Equities builder is replaced by one that returns a review with the two invented charts, so the
draft and run routes go through the real save path and write the real files.
"""

import time

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly.charts import store
from cytonn_weekly.charts.block import TEAM_CHART_NOTE, chart_blocks
from cytonn_weekly.common.review import build_review, check_section
from cytonn_weekly.equities import weekly as eq_weekly
from tests.chart_helpers import FRIDAY, book, day
from tests.test_charts_block import MISSING_BOOK, QUOTED, STATED


def chart_review(workbook=True, **kw):
    kw.setdefault("stated", STATED)
    blocks, files = chart_blocks(book(**kw) if workbook else None, "Equities workbook", FRIDAY, QUOTED, MISSING_BOOK)
    content = {"section": "equities", "title": "Equities", "week_ending": FRIDAY.isoformat(), "week_start": None,
               "week_end": None, "blocks": blocks, "chart_notes": [b["caption"] for b in blocks]}
    review = build_review(content, check_section(content))
    store.attach(review, files)
    return review


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(eq_weekly, "build_equities_weekly_review", lambda **kw: chart_review())
    return TestClient(create_app(db_path=tmp_path / "app.db", load_dotenv=False))


def draft(client) -> dict:
    r = client.post("/api/sections/equities/draft")
    assert r.status_code == 200, r.text
    return r.json()


def png_path(run_id: int, chart_id: str = "nasi_pe"):
    return store.root_dir() / str(run_id) / f"{chart_id}.png"


def test_a_draft_writes_each_drawn_charts_files_under_its_run_id_and_the_route_serves_them(client):
    review = draft(client)
    run_id = review["run_id"]
    blocks = {b["id"]: b for b in review["section"]["blocks"]}
    for chart_id in ("nasi_pe", "nasi_yield"):
        assert png_path(run_id, chart_id).is_file() and png_path(run_id, chart_id).with_suffix(".json").is_file()
        r = client.get(f"/api/reviews/{run_id}/charts/{chart_id}.png")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        assert store.sha256(r.content) == blocks[f"chart_{chart_id}"]["png_sha256"] == store.sha256(png_path(run_id, chart_id).read_bytes())
    assert "checks" not in blocks["chart_nasi_pe"]           # the screen gets metadata; the flags arrive as review items


def test_the_hash_is_checked_on_every_read_and_a_changed_file_is_409(client):
    run_id = draft(client)["run_id"]
    url = f"/api/reviews/{run_id}/charts/nasi_pe.png"
    assert client.get(url).status_code == 200
    png_path(run_id).write_bytes(png_path(run_id).read_bytes() + b"\0")
    r = client.get(url)
    assert r.status_code == 409 and "SHA-256" in r.json()["detail"]


def test_a_missing_file_is_a_clear_404(client):
    run_id = draft(client)["run_id"]
    png_path(run_id).unlink()
    r = client.get(f"/api/reviews/{run_id}/charts/nasi_pe.png")
    assert r.status_code == 404 and "missing" in r.json()["detail"]


@pytest.mark.parametrize("chart_id", ["nope", "NASI_PE", "..%2F..%2Fapp.db", "..%5C..%5Capp", "nasi_pe%00", "%2E%2E", "nasi_pe.png%2F.."])
def test_an_unknown_chart_id_or_a_path_is_refused_and_nothing_outside_the_folder_is_read(client, tmp_path, chart_id):
    run_id = draft(client)["run_id"]
    r = client.get(f"/api/reviews/{run_id}/charts/{chart_id}.png")
    assert r.status_code == 404
    assert r.headers.get("content-type", "").startswith("application/json")


def test_a_chart_that_is_not_drawn_and_an_unknown_run_have_no_image(client, monkeypatch):
    monkeypatch.setattr(eq_weekly, "build_equities_weekly_review", lambda **kw: chart_review(newest=day(1)))
    review = draft(client)
    run_id = review["run_id"]
    assert not (store.root_dir() / str(run_id)).exists()
    assert client.get(f"/api/reviews/{run_id}/charts/nasi_pe.png").status_code == 404
    assert client.get("/api/reviews/999999/charts/nasi_pe.png").status_code == 404


def test_drafting_again_makes_a_new_folder_and_leaves_the_old_one_untouched(client):
    first = draft(client)["run_id"]
    before = png_path(first).read_bytes()
    second = draft(client)["run_id"]
    assert second != first and png_path(second).is_file() and png_path(first).read_bytes() == before


def test_files_are_written_once_and_never_replaced(tmp_path):
    review = chart_review()
    review.run_id = 7
    files = dict(getattr(review, store._FILES))
    store.persist(review, tmp_path)
    store.attach(review, files)
    with pytest.raises(FileExistsError):
        store.persist(review, tmp_path)


def test_a_run_started_in_the_background_writes_its_files_too(client):
    started = client.post("/api/runs", json={"section": "equities"})
    assert started.status_code == 202, started.text
    run = started.json()["run_id"]
    for _ in range(200):
        state = client.get(f"/api/runs/{run}").json()
        if state["status"] != "running":
            break
        time.sleep(0.05)
    assert state["status"] == "finished", state
    assert png_path(state["review_id"]).is_file()
    assert client.get(f"/api/reviews/{state['review_id']}/charts/nasi_yield.png").status_code == 200


def test_read_png_refuses_a_chart_id_that_is_a_path_even_when_the_hash_would_match(tmp_path):
    planted = b"not a chart"
    (tmp_path / "x.png").write_bytes(planted)
    (tmp_path / "1").mkdir()
    for bad in ("../x", r"..\x", "x"):
        with pytest.raises(store.UnknownChart):
            store.read_png(1, bad, store.sha256(planted), tmp_path)


# ---------------------------------------------------------------------------
# The stored series, behind its own hash
# ---------------------------------------------------------------------------

def series_path(run_id: int, chart_id: str = "nasi_pe"):
    return png_path(run_id, chart_id).with_suffix(".json")


def test_the_series_route_serves_the_stored_series_while_its_hash_matches(client):
    review = draft(client)
    run_id = review["run_id"]
    blocks = {b["chart_id"]: b for b in review["section"]["blocks"]}
    for chart_id in ("nasi_pe", "nasi_yield"):
        r = client.get(f"/api/reviews/{run_id}/charts/{chart_id}/series")
        assert r.status_code == 200 and r.headers["content-type"] == "application/json"
        assert store.sha256(r.content) == store.sha256(series_path(run_id, chart_id).read_bytes())
        body = r.json()
        assert body["chart_id"] == chart_id and len(body["points"]) == 60 and body["points"][-1][3] in ("10.0x", "5.0%")
    assert "series_sha256" not in blocks["nasi_pe"]           # the screen is told where to read it, not given the hash


def test_a_tampered_series_is_409_and_a_missing_one_404(client):
    run_id = draft(client)["run_id"]
    url = f"/api/reviews/{run_id}/charts/nasi_pe/series"
    series_path(run_id).write_bytes(series_path(run_id).read_bytes().replace(b"B8", b"B9", 1))
    r = client.get(url)
    assert r.status_code == 409 and "SHA-256" in r.json()["detail"] and "series" in r.json()["detail"]
    assert client.get(f"/api/reviews/{run_id}/charts/nasi_yield/series").status_code == 200       # the other chart is untouched
    series_path(run_id).unlink()
    r = client.get(url)
    assert r.status_code == 404 and "missing" in r.json()["detail"]


@pytest.mark.parametrize("chart_id", ["nope", "NASI_PE", "..%2F..%2Fapp.db", "..%5C..%5Capp", "nasi_pe%00", "%2E%2E", "nasi_pe.json"])
def test_the_series_route_refuses_an_unknown_chart_id_or_a_path(client, chart_id):
    run_id = draft(client)["run_id"]
    r = client.get(f"/api/reviews/{run_id}/charts/{chart_id}/series")
    assert r.status_code == 404 and r.headers.get("content-type", "").startswith("application/json")


def test_a_chart_that_is_not_drawn_or_has_no_workbook_has_no_series(client, monkeypatch):
    for kw in ({"newest": day(1)}, {"workbook": False}):
        monkeypatch.setattr(eq_weekly, "build_equities_weekly_review", lambda _kw=kw, **_: chart_review(**_kw))
        run_id = draft(client)["run_id"]
        assert client.get(f"/api/reviews/{run_id}/charts/nasi_pe/series").status_code == 404
        assert client.get(f"/api/reviews/{run_id}/charts/nasi_pe.png").status_code == 404


# ---------------------------------------------------------------------------
# The team's own chart, saved with the review
# ---------------------------------------------------------------------------

def put_team(client, run_id, chart_id="nasi_pe", use=True):
    return client.put(f"/api/reviews/{run_id}/charts/{chart_id}/team-chart", json={"use": use})


def chart_items(review, title="NASI P/E chart"):
    return [i for i in review["review_items"] if i["ref"].startswith(title)]


def test_using_the_team_chart_is_saved_with_the_review_and_lists_the_chart_to_add_by_hand(client):
    review = draft(client)
    run_id = review["run_id"]
    caption = next(b["caption"] for b in review["section"]["blocks"] if b["chart_id"] == "nasi_pe")
    assert review["section"]["chart_notes"] == []                         # both charts were drawn: none left to add by hand
    r = put_team(client, run_id)
    assert r.status_code == 200
    saved = client.get(f"/api/reviews/{run_id}").json()                   # read back from the database, not the response
    assert [b["use_team_chart"] for b in saved["section"]["blocks"]] == [True, False]
    assert saved["section"]["chart_notes"] == [caption]
    assert {(i["resolution"], i["resolution_note"]) for i in chart_items(saved)} == {("accept", TEAM_CHART_NOTE)}
    assert {i["resolution"] for i in chart_items(saved, "NASI dividend yield chart")} == {None}
    assert put_team(client, run_id, use=False).json()["section"]["chart_notes"] == []
    assert {i["resolution"] for i in chart_items(client.get(f"/api/reviews/{run_id}").json())} == {None}


def test_the_team_chart_choice_is_refused_once_decided_for_an_unknown_chart_and_for_no_workbook(client, monkeypatch):
    run_id = draft(client)["run_id"]
    assert put_team(client, run_id, "nope").status_code == 404
    assert client.put(f"/api/reviews/{run_id}/charts/nasi_pe/team-chart", json={}).status_code == 422
    for i in client.get(f"/api/reviews/{run_id}").json()["review_items"]:
        client.patch(f"/api/reviews/{run_id}/items/{i['index']}", json={"resolution": "accept"})
    assert client.post(f"/api/reviews/{run_id}/decide", json={"decision": "approved"}).status_code == 200
    r = put_team(client, run_id)
    assert r.status_code == 409 and "approved" in r.json()["detail"]      # a decided review is frozen
    monkeypatch.setattr(eq_weekly, "build_equities_weekly_review", lambda **_: chart_review(workbook=False))
    none = draft(client)
    assert [b["status"] for b in none["section"]["blocks"]] == ["no_workbook", "no_workbook"]
    assert [b["use_team_chart"] for b in none["section"]["blocks"]] == [False, False]
    assert none["review_items"] == [] and len(none["section"]["chart_notes"]) == 2     # nothing to resolve; both listed to add by hand
    r = put_team(client, none["run_id"])
    assert r.status_code == 409 and "nothing to set aside" in r.json()["detail"]
