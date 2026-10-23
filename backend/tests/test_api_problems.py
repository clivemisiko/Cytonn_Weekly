"""The ``problems`` list an API error can carry (api/problems.py): every failure that stops a whole action, or that
belongs to a part of the screen, answers with its sentence in ``detail`` exactly as before and a well formed
``problems`` list beside it.  Everything else is still ``{"detail": ...}`` alone."""

import ast
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from api.main import create_app
from api.problems import PROBLEMS, TARGETS, ProblemError
from cytonn_weekly.digital_payments import review_store as rs
from cytonn_weekly.equities import weekly as eq_weekly
from cytonn_weekly.weekly import inputs as weekly_inputs
from tests import section_helpers as sh
from tests.review_helpers import make_review

WEEK = "2026-10-02"
MAIN = Path(api_main.__file__)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "app.db"


@pytest.fixture
def client(db):
    return TestClient(create_app(db_path=db, load_dotenv=False, fetch_usd_rates=lambda *a, **k: {}))


def expect(r, status, code, detail_has):
    """The status, the sentence (a part of it, as the older tests assert) and exactly the table's entry for the code."""
    assert r.status_code == status, r.text
    body = r.json()
    assert set(body) == {"detail", "problems"}
    assert detail_has in body["detail"]
    headline, target = PROBLEMS[code]
    assert body["problems"] == [{"code": code, "headline": headline, "target": target}]


# --- the table and the call sites agree ------------------------------------------------------------

def test_every_entry_is_well_formed():
    for code, (headline, target) in PROBLEMS.items():
        assert code == code.lower() and " " not in code
        assert headline and len(headline) <= 60 and "\n" not in headline
        assert target is None or target in TARGETS
    assert len(set(TARGETS)) == len(TARGETS)


def test_every_call_site_names_a_code_in_the_table_and_every_code_is_used():
    used = []
    for node in ast.walk(ast.parse(MAIN.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ProblemError":
            code = node.args[2]
            assert isinstance(code, ast.Constant) and code.value in PROBLEMS, ast.dump(code)
            used.append(code.value)
    assert set(used) == set(PROBLEMS)


def test_an_unknown_code_fails_when_it_is_written():
    with pytest.raises(KeyError):
        ProblemError(409, "x", "not_a_code")


def test_an_error_with_no_problem_is_the_old_body(client):
    r = client.post("/api/sections/nope/draft")
    assert r.status_code == 404 and set(r.json()) == {"detail"}


# --- inputs ----------------------------------------------------------------------------------------

def test_a_week_that_is_not_a_friday_or_not_a_date(client):
    expect(client.get("/api/inputs/weekly/2026-10-01"), 422, "week_not_valid", "is a Thursday")
    expect(client.get("/api/inputs/weekly/soon"), 422, "week_not_valid", "is not a date")


def test_refused_and_oversized_uploads(client):
    expect(client.put(f"/api/inputs/weekly/{WEEK}/kcb_weekly?filename=a.pdf", content=b"PK not a pdf"), 422,
           "upload_refused", "this is not a PDF file")
    big = b"x" * (weekly_inputs.MAX_BYTES + 1)
    expect(client.put(f"/api/inputs/weekly/{WEEK}/cbk_bulletin?filename=a.pdf", content=big), 413, "upload_too_big",
           "over the 30 MB limit")


def test_a_note_the_store_refuses(client, monkeypatch):
    # The request model already caps a note at the store's own limit, so the store's refusal is reached only if it changes.
    def refuse(*args, **kwargs):
        raise weekly_inputs.InputError("Bidding range: too long")

    monkeypatch.setattr(weekly_inputs, "write_notes", refuse)
    expect(client.put(f"/api/inputs/weekly/{WEEK}/notes", json={"bidding_range": "9.5"}), 422, "note_refused", "too long")


def test_the_analyst_form(client):
    url = f"/api/inputs/weekly/{WEEK}/analyst?section=fixed_income"
    expect(client.put(url, json={"fields": {"placements": "0.09"}}), 422, "analyst_refused", "outside the expected range")
    expect(client.post(f"/api/inputs/weekly/{WEEK}/analyst/carry?section=fixed_income"), 409, "analyst_nothing_to_carry",
           "nothing to start from")
    expect(client.post(f"/api/inputs/weekly/{WEEK}/analyst/suggest/turnover_ytd?section=equities"), 409,
           "analyst_suggestion_unavailable", "turnover")


def test_the_cbk_fetch(db):
    def fetcher(result):
        def fetch(day):
            if isinstance(result, Exception):
                raise result
            return result
        return fetch

    def post(result):
        app = create_app(db_path=db, load_dotenv=False, fetch_bulletin=fetcher(result))
        return TestClient(app).post(f"/api/inputs/weekly/{WEEK}/cbk_bulletin/fetch")

    expect(post(LookupError("no issue")), 404, "bulletin_not_published", "no issue.")
    expect(post(RuntimeError("down")), 502, "bulletin_fetch_failed", "could not be fetched")
    expect(post((b"not a pdf", "https://x.example/b.pdf")), 502, "bulletin_fetch_failed",
           "could not be read as the Weekly Bulletin")


# --- starting a draft ------------------------------------------------------------------------------

def test_a_draft_that_cannot_start(client, monkeypatch):
    expect(client.post("/api/runs", json={"section": "focus"}), 422, "draft_topic_missing", "Type a topic")
    expect(client.post("/api/runs", json={"section": "focus", "topic": "x" * 600}), 422, "draft_topic_invalid",
           "the limit is 500")
    expect(client.post("/api/runs", json={"section": "company_updates"}), 422, "draft_text_missing", "Paste the text")
    expect(client.post("/api/sections/reits.section_1/draft",
                       json={"report_type": "companion", "period": "#33.2026", "kind": "reits"}), 409,
           "draft_section_unavailable", "cannot be drafted yet")
    expect(client.post("/api/runs", json={"section": "focus", "topic": "x", "provider": "local"}), 409,
           "draft_mode_changed", "drafting mode changed")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    expect(client.post("/api/runs", json={"section": "focus", "topic": "x"}), 409, "drafting_off", "ANTHROPIC_API_KEY")


def test_a_draft_that_stops_or_is_refused_on_the_section_route(client, monkeypatch):
    def crash():
        raise RuntimeError("afx went away")

    monkeypatch.setattr(eq_weekly, "build_equities_weekly_review", crash)
    expect(client.post("/api/sections/equities/draft"), 502, "draft_failed", "The draft stopped.")

    def bad_input():
        raise ValueError("the input cannot be used")

    monkeypatch.setattr(eq_weekly, "build_equities_weekly_review", bad_input)
    expect(client.post("/api/sections/equities/draft"), 422, "draft_input_invalid", "the input cannot be used")
    expect(client.post("/api/sections/executive_summary/draft", json={"report_type": "quarterly", "period": "Q3'2026"}),
           409, "draft_sections_not_approved", "approved sections only")


def test_a_second_draft_while_one_runs(db, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def stuck(on_event=None):
        entered.set()
        assert release.wait(timeout=10)
        return sh.equities_review()

    monkeypatch.setattr(eq_weekly, "build_equities_weekly_review", stuck)
    client = TestClient(create_app(db_path=db, load_dotenv=False))
    assert client.post("/api/runs", json={"section": "equities"}).status_code == 202
    try:
        assert entered.wait(timeout=10)
        expect(client.post("/api/runs", json={"section": "equities"}), 409, "draft_already_running", "already being drafted")
        expect(client.post("/api/runs", json={"section": "real_estate"}), 409, "draft_busy", "Another draft is running")
    finally:
        release.set()


def test_a_run_the_api_does_not_know(client):
    expect(client.get("/api/runs/nope"), 404, "run_unknown", "no longer known")


# --- the review and the export ---------------------------------------------------------------------

def test_the_review_routes(client, db):
    expect(client.get("/api/reviews/9999"), 404, "review_not_found", "no saved review number 9999")
    run_id = rs.save_review(make_review(), db_path=db)
    expect(client.post(f"/api/reviews/{run_id}/decide", json={"decision": "approved"}), 409, "review_not_decidable",
           "cannot approve")
    assert client.post(f"/api/reviews/{run_id}/decide", json={"decision": "rejected"}).status_code == 200
    expect(client.patch(f"/api/reviews/{run_id}/items/0", json={"resolution": "accept"}), 409, "review_already_decided",
           "already rejected")


def test_the_export_before_every_section_is_approved(client):
    expect(client.post("/api/export/weekly"), 409, "export_not_ready", "cannot be exported yet")
