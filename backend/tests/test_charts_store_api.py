"""The chart files and their route: written once per run, served only while their SHA-256 matches the review's.

The Equities builder is replaced by one that returns a review with the two invented charts, so the
draft and run routes go through the real save path and write the real files.
"""

import time

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly.charts import store
from cytonn_weekly.charts.block import chart_blocks
from cytonn_weekly.common.review import build_review, check_section
from cytonn_weekly.equities import weekly as eq_weekly
from tests.chart_helpers import FRIDAY, book, day
from tests.test_charts_block import MISSING_BOOK, QUOTED, STATED


def chart_review(**kw):
    kw.setdefault("stated", STATED)
    blocks, files = chart_blocks(book(**kw), "Equities workbook", FRIDAY, QUOTED, MISSING_BOOK)
    content = {"section": "equities", "title": "Equities", "week_ending": FRIDAY.isoformat(), "week_start": None,
               "week_end": None, "blocks": blocks}
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
