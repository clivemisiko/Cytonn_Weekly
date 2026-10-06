"""Tests for the FastAPI layer over the coordinator review (api/main.py, api/serialize.py).

Driven with FastAPI's TestClient against a real SQLite file (each test gets its own, built
from the project's cytonn_weekly/schema.sql).  Reviews come from the real draft/compose/check code
on fake edges (review_helpers), and the "Draft" endpoint's pipeline is wrapped the same
way, so there is no network and no LLM anywhere.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from review_helpers import ROWS, TODAY, FakeProvider, LocalFakeProvider, make_review

from api.main import CORS_ENV_VAR, create_app
from cytonn_weekly import env as env_module
from cytonn_weekly.digital_payments import coordinator_review as cr
from cytonn_weekly.digital_payments import review_run
from cytonn_weekly.digital_payments import review_store as rs
from cytonn_weekly.digital_payments.providers.base import OutlookResult


@pytest.fixture
def db(tmp_path):
    return tmp_path / "api.db"


@pytest.fixture
def client(db):
    return TestClient(create_app(db_path=db, load_dotenv=False))


def seed(db, review=None, **kw):
    """Save a review straight through the store (as an earlier session would have) and return its run_id."""
    return rs.save_review(review or make_review(), db_path=db, **kw)


def idx_of(review, fragment):
    (i,) = [n for n, it in enumerate(review.review_items) if fragment in it.ref]
    return i


def resolve(client, run_id, index, resolution, **extra):
    return client.patch(f"/api/reviews/{run_id}/items/{index}", json={"resolution": resolution, **extra})


def accept_everything(client, run_id):
    body = client.post(f"/api/reviews/{run_id}/accept-clean").json()
    for item in body["review_items"]:
        if item["resolution"] is None:
            body = resolve(client, run_id, item["index"], "accept").json()
    return body


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_latest_is_404_json_when_nothing_is_saved(client):
    r = client.get("/api/reviews/latest")
    assert r.status_code == 404 and "no saved review" in r.json()["detail"]


def test_latest_returns_the_newest_review_and_by_id_matches(client, db):
    seed(db)
    newest = seed(db, make_review(tamper=True))
    body = client.get("/api/reviews/latest").json()
    assert body["run_id"] == newest
    assert client.get(f"/api/reviews/{newest}").json() == body


def test_latest_for_today_ignores_yesterdays_review(client, db):
    seed(db, run_date=date.today() - timedelta(days=1))
    assert client.get("/api/reviews/latest", params={"run_date": "today"}).status_code == 404
    assert client.get("/api/reviews/latest", params={"run_date": (date.today() - timedelta(days=1)).isoformat()}).status_code == 200
    today = seed(db)
    assert client.get("/api/reviews/latest", params={"run_date": "today"}).json()["run_id"] == today


def test_latest_rejects_a_malformed_run_date(client):
    assert client.get("/api/reviews/latest", params={"run_date": "last tuesday"}).status_code == 422


def test_unknown_run_id_is_404(client):
    assert client.get("/api/reviews/999").status_code == 404


def test_review_json_shape_for_a_tampered_review(client, db):
    review = make_review(tamper=True)
    run_id = seed(db, review)
    body = client.get(f"/api/reviews/{run_id}").json()

    assert body["run_id"] == run_id and body["decision"] is None and body["locked"] is False
    assert body["is_approvable"] is False and body["is_dev_draft"] is False and body["dev_mode_label"] is None
    n = len(review.review_items)
    assert body["progress"] == {"total": n, "resolved": 0, "unresolved": n, "fix_needed": 0}
    assert {s: body["counts"][s]["total"] for s in body["counts"]} == {"flagged": 2, "not_auto_verified": 4, "clean": n - 6}
    # items carry their position, which is how the write endpoints address them
    assert [i["index"] for i in body["review_items"]] == list(range(n))
    ma = body["review_items"][idx_of(review, "Mastercard (MA)")]
    assert ma["status"] == "flagged" and ma["resolution"] is None
    (flag,) = ma["detail"]
    assert (flag["kind"], flag["field"], flag["drafted"], flag["expected"], flag["source_value"]) == (
        "mismatch", "current_price", "101.0", "100.0", 100.0)
    claim = next(i for i in body["review_items"] if i["kind"] == "highlight_claim")
    assert claim["context"]["url"].startswith("https://") and claim["context"]["cited_text"]


def test_table_is_display_formatted_and_flagged_rows_are_marked(client, db):
    run_id = seed(db, make_review(tamper=True))
    section = client.get(f"/api/reviews/{run_id}").json()["section"]
    table = next(i for i in section["items"] if i["kind"] == "stock_table")
    rows = {r["ticker"]: r for r in table["rows"]}
    # the stored section holds raw fetcher rows; the API serves the report's own string format
    assert (rows["MA"]["current_price"], rows["MA"]["wow_pct"], rows["MA"]["forward_pe"]) == ("100.0", "(1.5%)", "20.0x")
    assert rows["MA"]["flagged"] and rows["AXP"]["flagged"] and not rows["V"]["flagged"]
    assert table["title"] == "Digital Payments NYSE and LSE Stock Performance"
    assert section["week_end"] == TODAY.isoformat()
    assert [i["numeral"] for i in section["items"]] == ["I", "II", "III", "IV", "V"]
    assert any(s["key"] == "avg_wow_pct" for s in section["outlook"]["stats"])
    assert all(isinstance(s["value"], str) for s in section["outlook"]["stats"])


def test_highlight_shortfall_is_reported(client, db):
    review = make_review()
    review.section["shortfall"] = 1
    review.section["items"] = [i for i in review.section["items"] if i.get("numeral") != "IV"]
    section = client.get(f"/api/reviews/{seed(db, review)}").json()["section"]
    assert (section["highlights_found"], section["highlights_expected"], section["shortfall"]) == (3, 4, 1)


class OutlookOnlyLocal(FakeProvider):
    """Highlights from a production-style provider, the outlook from the local one."""

    def draft_outlook(self, table_stats, highlights):
        return OutlookResult(text="Outlook.", stats=table_stats, drafted_by="local:phi4-mini")


@pytest.mark.parametrize("provider, dev", [
    (FakeProvider(), False), (LocalFakeProvider(), True), (OutlookOnlyLocal(), True),
])
def test_is_dev_draft_follows_the_local_drafted_by_prefix(client, db, provider, dev):
    body = client.get(f"/api/reviews/{seed(db, make_review(provider=provider))}").json()
    assert body["is_dev_draft"] is dev
    assert (body["dev_mode_label"] is not None) is dev
    if dev:
        assert "NOT FOR PUBLICATION" in body["dev_mode_label"]


def test_non_finite_source_values_do_not_break_the_response(client, db):
    review = make_review(tamper=True)
    review.review_items[idx_of(review, "Mastercard (MA)")].detail[0].source_value = float("nan")
    body = client.get(f"/api/reviews/{seed(db, review)}")
    assert body.status_code == 200
    ma = body.json()["review_items"][idx_of(review, "Mastercard (MA)")]
    assert ma["detail"][0]["source_value"] == "nan"


@pytest.mark.parametrize("provider, spends, dev", [("", True, False), ("anthropic", True, False), ("local", False, True)])
def test_config_reports_the_provider_and_what_a_draft_costs(client, monkeypatch, provider, spends, dev):
    if provider:
        monkeypatch.setenv("CYTONN_LLM_PROVIDER", provider)
    else:
        monkeypatch.delenv("CYTONN_LLM_PROVIDER", raising=False)
    cfg = client.get("/api/config").json()
    assert (cfg["provider"], cfg["provider_valid"]) == (provider or "anthropic", True)
    assert (cfg["spends_api_budget"], cfg["dev_mode"]) == (spends, dev)


def test_config_flags_an_unknown_provider(client, monkeypatch):
    monkeypatch.setenv("CYTONN_LLM_PROVIDER", "gpt")
    cfg = client.get("/api/config").json()
    assert cfg["provider_valid"] is False and not cfg["spends_api_budget"] and not cfg["dev_mode"]


def test_cors_allows_the_web_app_origin_only(db, monkeypatch):
    monkeypatch.setenv(CORS_ENV_VAR, "http://localhost:3000")
    c = TestClient(create_app(db_path=db, load_dotenv=False))
    ask = {"Access-Control-Request-Method": "PATCH", "Access-Control-Request-Headers": "content-type"}
    ok = c.options("/api/reviews/1/items/0", headers={"Origin": "http://localhost:3000", **ask})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"
    other = c.options("/api/reviews/1/items/0", headers={"Origin": "http://evil.example", **ask})
    assert "access-control-allow-origin" not in other.headers


CORS_ASK = {"Access-Control-Request-Method": "PATCH", "Access-Control-Request-Headers": "content-type"}


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    """A .env-format file standing in for the repo-root .env; CYTONN_WEB_ORIGINS is absent from the shell.

    setenv-then-delenv makes monkeypatch restore the variable's absence afterwards, since load_env writes to
    os.environ directly.
    """
    path = tmp_path / ".env"
    monkeypatch.setattr(env_module, "ENV_FILE", path)
    monkeypatch.setenv(CORS_ENV_VAR, "placeholder")
    monkeypatch.delenv(CORS_ENV_VAR)
    return path


def test_cors_origins_set_only_in_dotenv_take_effect(db, env_file):
    """Regression: CYTONN_WEB_ORIGINS used to be read when the app was built, before .env was loaded (in the startup
    hook), so an origin set only in .env was silently ignored and the defaults applied."""
    env_file.write_text(f"{CORS_ENV_VAR}=http://review.example:4000\n", encoding="utf-8")
    c = TestClient(create_app(db_path=db))
    ok = c.options("/api/reviews/1/items/0", headers={"Origin": "http://review.example:4000", **CORS_ASK})
    assert ok.headers.get("access-control-allow-origin") == "http://review.example:4000"
    default = c.options("/api/reviews/1/items/0", headers={"Origin": "http://localhost:3000", **CORS_ASK})
    assert "access-control-allow-origin" not in default.headers  # .env replaced the defaults


def test_cors_origins_from_the_shell_still_win_over_dotenv(db, env_file, monkeypatch):
    env_file.write_text(f"{CORS_ENV_VAR}=http://review.example:4000\n", encoding="utf-8")
    monkeypatch.setenv(CORS_ENV_VAR, "http://shell.example:5000")
    c = TestClient(create_app(db_path=db))
    assert c.options("/api/reviews/1/items/0", headers={"Origin": "http://shell.example:5000", **CORS_ASK}
                     ).headers.get("access-control-allow-origin") == "http://shell.example:5000"
    assert "access-control-allow-origin" not in c.options(
        "/api/reviews/1/items/0", headers={"Origin": "http://review.example:4000", **CORS_ASK}).headers


def test_importing_the_api_does_not_load_the_real_dotenv():
    """The served app is built on first access (uvicorn's getattr), so importing create_app, as every test does,
    never loads a developer's real .env into the test process."""
    import api.main as main_module
    assert "app" not in vars(main_module)


# ---------------------------------------------------------------------------
# Resolving items
# ---------------------------------------------------------------------------

def test_resolving_an_item_updates_it_saves_it_and_returns_the_review(client, db):
    review = make_review(tamper=True)
    run_id = seed(db, review)
    i = idx_of(review, "Mastercard (MA)")

    r = resolve(client, run_id, i, "fix_needed", note="price is off")
    assert r.status_code == 200
    body = r.json()
    assert (body["review_items"][i]["resolution"], body["review_items"][i]["resolution_note"]) == ("fix_needed", "price is off")
    assert body["progress"]["resolved"] == 1 and body["progress"]["fix_needed"] == 1
    assert body["counts"]["flagged"]["fix_needed"] == 1 and body["counts"]["flagged"]["unresolved"] == 1

    saved = rs.load_review(run_id, db_path=db).review_items[i]
    assert (saved.resolution, saved.resolution_note) == (cr.FIX_NEEDED, "price is off")

    cleared = resolve(client, run_id, i, None).json()  # null clears the resolution
    assert cleared["review_items"][i]["resolution"] is None
    assert rs.load_review(run_id, db_path=db).review_items[i].resolution is None


def test_an_omitted_note_is_kept_and_a_present_one_replaces_it(client, db):
    review = make_review()
    run_id, i = seed(db, review), idx_of(review, "Visa (V)")
    resolve(client, run_id, i, "accept", note="checked on Yahoo")

    kept = resolve(client, run_id, i, "fix_needed").json()["review_items"][i]
    assert (kept["resolution"], kept["resolution_note"]) == ("fix_needed", "checked on Yahoo")

    replaced = resolve(client, run_id, i, "fix_needed", note="  stale quote  ").json()["review_items"][i]
    assert replaced["resolution_note"] == "stale quote"  # trimmed

    for blank in ("", "   ", None):
        resolve(client, run_id, i, "fix_needed", note="x")
        assert resolve(client, run_id, i, "fix_needed", note=blank).json()["review_items"][i]["resolution_note"] is None


def test_a_note_can_be_saved_while_the_item_is_unresolved(client, db):
    review = make_review()
    run_id, i = seed(db, review), idx_of(review, "Visa (V)")
    item = resolve(client, run_id, i, None, note="look at this later").json()["review_items"][i]
    assert (item["resolution"], item["resolution_note"]) == (None, "look at this later")


@pytest.mark.parametrize("payload", [
    {"resolution": "approved"}, {"resolution": "ACCEPT"}, {}, {"note": "no resolution given"},
])
def test_invalid_resolution_bodies_are_422_and_change_nothing(client, db, payload):
    review = make_review()
    run_id = seed(db, review)
    assert client.patch(f"/api/reviews/{run_id}/items/0", json=payload).status_code == 422
    assert all(i.resolution is None for i in rs.load_review(run_id, db_path=db).review_items)


def test_overlong_notes_are_rejected(client, db):
    run_id = seed(db)
    assert resolve(client, run_id, 0, "accept", note="x" * 2001).status_code == 422


@pytest.mark.parametrize("index", [-1, 14, 999])
def test_an_index_outside_the_items_is_404(client, db, index):
    review = make_review()
    assert len(review.review_items) == 14
    run_id = seed(db, review)
    assert resolve(client, run_id, index, "accept").status_code == 404
    assert all(i.resolution is None for i in rs.load_review(run_id, db_path=db).review_items)


def test_resolving_on_an_unknown_run_is_404(client):
    assert resolve(client, 999, 0, "accept").status_code == 404


def test_concurrent_resolutions_on_different_items_are_all_kept(client, db):
    review = make_review()
    run_id = seed(db, review)
    n = len(review.review_items)

    def one(i):
        return resolve(client, run_id, i, "accept").status_code

    with ThreadPoolExecutor(max_workers=n) as pool:
        codes = list(pool.map(one, range(n)))

    assert codes == [200] * n
    assert all(i.resolution == cr.ACCEPT for i in rs.load_review(run_id, db_path=db).review_items)  # none overwritten


# ---------------------------------------------------------------------------
# Accept all clean
# ---------------------------------------------------------------------------

def test_accept_clean_resolves_only_unresolved_clean_items(client, db):
    review = make_review(tamper=True)
    run_id = seed(db, review)
    mine = idx_of(review, "Visa (V)")
    resolve(client, run_id, mine, "fix_needed", note="I disagree")

    body = client.post(f"/api/reviews/{run_id}/accept-clean").json()

    items = body["review_items"]
    clean = [i for i in items if i["status"] == "clean"]
    assert clean and all(i["resolution"] == "accept" for i in clean if i["index"] != mine)
    assert (items[mine]["resolution"], items[mine]["resolution_note"]) == ("fix_needed", "I disagree")  # not overwritten
    others = [i for i in items if i["status"] != "clean"]
    assert others and all(i["resolution"] is None for i in others)
    assert body["counts"]["clean"]["unresolved"] == 0
    saved = rs.load_review(run_id, db_path=db)  # and it was saved
    assert all(i.resolution == cr.ACCEPT for n, i in enumerate(saved.review_items) if i.status == cr.CLEAN and n != mine)
    assert saved.review_items[mine].resolution == cr.FIX_NEEDED
    assert client.post(f"/api/reviews/{run_id}/accept-clean").status_code == 200  # nothing left to do is not an error


def test_accept_clean_on_an_unknown_run_is_404(client):
    assert client.post("/api/reviews/999/accept-clean").status_code == 404


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

def test_approve_is_blocked_while_items_are_unresolved(client, db):
    run_id = seed(db)
    r = client.post(f"/api/reviews/{run_id}/decide", json={"decision": "approved"})
    assert r.status_code == 409 and "cannot approve" in r.json()["detail"]
    assert rs.load_review(run_id, db_path=db).decision is None


def test_approve_is_blocked_while_an_item_needs_a_fix(client, db):
    review = make_review()
    run_id = seed(db, review)
    accept_everything(client, run_id)
    body = resolve(client, run_id, idx_of(review, "Visa (V)"), "fix_needed").json()
    assert body["is_approvable"] is False

    r = client.post(f"/api/reviews/{run_id}/decide", json={"decision": "approved"})
    assert r.status_code == 409 and "fix_needed" in r.json()["detail"]
    assert rs.load_review(run_id, db_path=db).decision is None


def test_approve_records_the_decision_once_everything_is_resolved(client, db):
    run_id = seed(db)
    body = accept_everything(client, run_id)
    assert body["is_approvable"] is True and body["locked"] is False

    r = client.post(f"/api/reviews/{run_id}/decide", json={"decision": "approved"})
    assert r.status_code == 200
    done = r.json()
    assert (done["decision"], done["locked"]) == ("approved", True) and done["decided_at"]
    saved = rs.load_review(run_id, db_path=db)
    assert (saved.decision, saved.decided_at) == (cr.APPROVED, done["decided_at"])


def test_reject_works_with_items_unresolved_or_fix_needed(client, db):
    review = make_review(tamper=True)
    run_id = seed(db, review)
    resolve(client, run_id, idx_of(review, "Mastercard (MA)"), "fix_needed")

    r = client.post(f"/api/reviews/{run_id}/decide", json={"decision": "rejected"})
    assert r.status_code == 200 and r.json()["decision"] == "rejected"
    assert rs.load_review(run_id, db_path=db).decision == cr.REJECTED


@pytest.mark.parametrize("decision", ["maybe", "approve", "", None])
def test_an_invalid_decision_is_422(client, db, decision):
    run_id = seed(db)
    assert client.post(f"/api/reviews/{run_id}/decide", json={"decision": decision}).status_code == 422
    assert client.post(f"/api/reviews/{run_id}/decide", json={}).status_code == 422


def test_a_decision_can_only_be_made_once(client, db):
    run_id = seed(db)
    client.post(f"/api/reviews/{run_id}/decide", json={"decision": "rejected"})
    for decision in ("rejected", "approved"):
        r = client.post(f"/api/reviews/{run_id}/decide", json={"decision": decision})
        assert r.status_code == 409 and "already decided" in r.json()["detail"]
    assert rs.load_review(run_id, db_path=db).decision == cr.REJECTED


def test_deciding_an_unknown_run_is_404(client):
    assert client.post("/api/reviews/999/decide", json={"decision": "rejected"}).status_code == 404


@pytest.mark.parametrize("decision", ["approved", "rejected"])
def test_a_decided_reviews_items_can_no_longer_be_mutated(client, db, decision):
    review = make_review()
    run_id = seed(db, review)
    accept_everything(client, run_id)
    assert client.post(f"/api/reviews/{run_id}/decide", json={"decision": decision}).status_code == 200
    frozen = rs.load_review(run_id, db_path=db)
    visa = idx_of(review, "Visa (V)")

    r = resolve(client, run_id, visa, "fix_needed", note="changed my mind")
    assert r.status_code == 409 and f"already {decision}" in r.json()["detail"]
    assert resolve(client, run_id, visa, None).status_code == 409
    assert client.post(f"/api/reviews/{run_id}/accept-clean").status_code == 409

    after = rs.load_review(run_id, db_path=db)
    assert after == frozen  # items, decision and timestamp all untouched


def test_a_stale_copy_saving_over_a_decision_made_elsewhere_is_409(client, db, monkeypatch):
    review = make_review()
    run_id = seed(db, review)
    stale = rs.load_review(run_id, db_path=db)  # what a slow request would be holding

    twin = rs.load_review(run_id, db_path=db)
    twin.decide("rejected")
    rs.save_review(twin, db_path=db)

    with monkeypatch.context() as m:
        m.setattr(rs, "load_review", lambda *a, **k: stale)  # the race: this request loaded before the decision
        r = resolve(client, run_id, idx_of(review, "Visa (V)"), "accept")
    assert r.status_code == 409 and "already rejected" in r.json()["detail"]
    assert rs.load_review(run_id, db_path=db).decision == cr.REJECTED
    assert rs.load_review(run_id, db_path=db).review_items[idx_of(review, "Visa (V)")].resolution is None


# ---------------------------------------------------------------------------
# Drafting
# ---------------------------------------------------------------------------

REAL_BUILD = review_run.build_digital_payments_review  # captured before any test patches it


def fake_pipeline(monkeypatch, provider=None):
    """Make the Draft endpoint run the real pipeline with a fake provider and fixed price rows."""
    calls = []

    def build():
        calls.append(1)
        return REAL_BUILD(provider=provider or FakeProvider(), today=TODAY, fetch_table=lambda today: ROWS)

    monkeypatch.setattr(review_run, "build_digital_payments_review", build)
    return calls


def test_draft_runs_the_pipeline_saves_it_and_returns_it(client, db, monkeypatch):
    calls = fake_pipeline(monkeypatch)
    assert rs.load_latest_review(db_path=db) is None

    r = client.post("/api/reviews/draft")

    assert r.status_code == 200 and len(calls) == 1
    body = r.json()
    assert body["run_id"] is not None and body["decision"] is None
    assert body["progress"]["total"] == 14 and body["progress"]["resolved"] == 0
    assert body["section"]["week_end"] == TODAY.isoformat()
    assert body["counts"]["flagged"]["total"] == 0  # a faithful draft on fixed prices checks clean
    # saved at once: a closed tab does not lose the (paid) run
    assert rs.load_latest_review(run_date=date.today(), db_path=db).run_id == body["run_id"]


def test_a_new_draft_leaves_the_earlier_review_in_the_database(client, db, monkeypatch):
    first = seed(db)
    fake_pipeline(monkeypatch)
    second = client.post("/api/reviews/draft").json()["run_id"]
    assert second != first
    assert rs.load_review(first, db_path=db).decision is None
    assert client.get("/api/reviews/latest").json()["run_id"] == second


def test_a_local_provider_draft_is_marked_dev_mode(client, monkeypatch):
    fake_pipeline(monkeypatch, provider=LocalFakeProvider())
    body = client.post("/api/reviews/draft").json()
    assert body["is_dev_draft"] is True and "NOT FOR PUBLICATION" in body["dev_mode_label"]


def test_draft_failure_is_shown_not_swallowed_and_saves_nothing(client, db, monkeypatch):
    def boom():
        raise RuntimeError("no API key")

    monkeypatch.setattr(review_run, "build_digital_payments_review", boom)
    r = client.post("/api/reviews/draft")
    assert r.status_code == 502 and "RuntimeError: no API key" in r.json()["detail"]
    assert rs.load_latest_review(db_path=db) is None
    # and the failure does not wedge the next attempt
    fake_pipeline(monkeypatch)
    assert client.post("/api/reviews/draft").status_code == 200


def test_a_second_draft_while_one_is_running_is_409_and_spends_nothing(db, monkeypatch):
    app = create_app(db_path=db, load_dotenv=False)
    entered, release = threading.Event(), threading.Event()
    calls = []

    def slow_build():
        calls.append(1)
        entered.set()
        assert release.wait(timeout=10)
        return REAL_BUILD(provider=FakeProvider(), today=TODAY, fetch_table=lambda today: ROWS)

    monkeypatch.setattr(review_run, "build_digital_payments_review", slow_build)
    first = {}
    t = threading.Thread(target=lambda: first.update(r=TestClient(app).post("/api/reviews/draft")))
    t.start()
    try:
        assert entered.wait(timeout=10)
        second = TestClient(app).post("/api/reviews/draft")
        assert second.status_code == 409 and "already running" in second.json()["detail"]
        assert len(calls) == 1  # the pipeline, and so the API spend, was not started again
    finally:
        release.set()
        t.join(timeout=10)
    assert first["r"].status_code == 200
    assert len(rs.load_latest_review(db_path=db).review_items) == 14  # exactly one draft was saved


def test_the_draft_lock_is_released_after_a_run(client, monkeypatch):
    fake_pipeline(monkeypatch)
    assert client.post("/api/reviews/draft").status_code == 200
    assert client.post("/api/reviews/draft").status_code == 200
