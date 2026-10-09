"""Report types through the review API: per-type overviews, isolation between reports, and the decision rules.

Weekly drafts run the real section pipelines on fake edges (tests/section_helpers.py),
Markets Review drafts the same (tests/periodic_helpers.py); the database is a temp file.
"""

import pytest
from fastapi.testclient import TestClient

from api.draft_slot import DraftSlot
from api.main import create_app
from cytonn_weekly.digital_payments import review_store, summary
from cytonn_weekly.equities import review_run as eq_run
from cytonn_weekly.equities import weekly as eq_weekly
from cytonn_weekly.periodic import (
    company_updates as p_cu,
    digital_payments as p_dp,
    equities as p_eq,
    fixed_income as p_fi,
    global_markets as p_gm,
    kenya_macro as p_km,
    real_estate as p_re,
    ssa as p_ssa,
)
from cytonn_weekly.real_estate import review_run as re_run
from tests import periodic_helpers as ph
from tests import section_helpers as sh
from tests.review_helpers import make_review

Q3 = {"report_type": "quarterly", "period": "Q3'2026"}


@pytest.fixture
def db(tmp_path):
    return tmp_path / "app.db"


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(eq_weekly, "build_equities_weekly_review", lambda: sh.equities_review())
    monkeypatch.setattr(re_run, "build_real_estate_review", lambda: sh.real_estate_review())
    for module, name, builder in [
        (p_gm, "build_global_markets_review", ph.global_markets_review),
        (p_ssa, "build_ssa_review", ph.ssa_review),
        (p_km, "build_kenya_macro_review", ph.kenya_macro_review),
        (p_fi, "build_fixed_income_review", ph.fixed_income_review),
        (p_eq, "build_equities_review", ph.equities_review),
        (p_re, "build_real_estate_review", ph.real_estate_review),
        (p_dp, "build_digital_payments_review", ph.digital_payments_review),
    ]:
        monkeypatch.setattr(module, name, lambda ctx, _b=builder: _b(ctx))
    return TestClient(create_app(db_path=db, load_dotenv=False))


def overview(client, **params):
    return client.get("/api/sections", params=params)


def approve(client, run_id):
    review = client.post(f"/api/reviews/{run_id}/accept-clean").json()
    for item in review["review_items"]:
        if item["resolution"] is None:
            review = client.patch(f"/api/reviews/{run_id}/items/{item['index']}", json={"resolution": "accept"}).json()
    r = client.post(f"/api/reviews/{run_id}/decide", json={"decision": "approved"})
    assert r.status_code == 200, r.text
    return r.json()

# ---------------------------------------------------------------------------
# The overview per report type
# ---------------------------------------------------------------------------


def test_the_overview_defaults_to_the_weekly_report_as_before(client):
    body = overview(client).json()
    report = body["report"]
    assert {k: report[k] for k in ("type", "title", "period", "kind", "published_as")} == {
        "type": "weekly", "title": "Weekly", "period": "", "kind": None,
        "published_as": "Cytonn Weekly #38.2026 (27 Sept 2026)"}
    assert report["week_ending"] is None and report["suggested_week_ending"]   # no week named; a Friday is suggested
    assert [s["slug"] for s in body["sections"]] == ["company_updates", "fixed_income", "equities", "real_estate",
                                                     "digital_payments", "focus"]
    assert [t["slug"] for t in body["report_types"]] == ["weekly", "quarterly", "half_year", "annual", "companion"]
    assert len(body["companion_kinds"]) == 4
    assert client.get("/api/report-types").json()["report_types"] == body["report_types"]


def test_a_markets_review_overview_needs_a_period_that_fits(client):
    assert "needs a period" in overview(client, report_type="quarterly").json()["detail"]
    assert "half-year" in overview(client, report_type="quarterly", period="Q2'2026").json()["detail"]
    body = overview(client, report_type="quarterly", period="q3 2026").json()
    assert body["report"]["period"] == "Q3'2026"   # normalized by the API, not the screen
    assert [s["slug"] for s in body["sections"]][:3] == ["executive_summary", "company_updates", "global_markets"]
    by = {s["slug"]: s for s in body["sections"]}
    assert by["company_updates"]["needs_text"] and not by["company_updates"]["uses_provider"]
    assert by["executive_summary"]["requires_approved"] and by["fixed_income"]["charts"]
    annual = overview(client, report_type="annual", period="2025").json()
    assert annual["report"]["period"] == "FY'2025" and "digital_payments" not in [s["slug"] for s in annual["sections"]]


def test_a_companion_overview_lists_its_kinds_sections_as_stubs(client, db):
    params = {"report_type": "companion", "period": "#33.2026", "kind": "reits"}
    body = overview(client, **params).json()
    assert body["report"]["period"] == "Weekly #33.2026"
    assert len(body["sections"]) == 4 and not any(s["available"] for s in body["sections"])
    assert "Cytonn's own analysis" in body["sections"][0]["reason"]
    r = client.post("/api/sections/reits.section_1/draft", json=params)
    assert r.status_code == 409 and review_store.load_latest_review("reits.section_1", report_type="companion",
                                                                     db_path=db) is None
    assert overview(client, report_type="companion", period="#33.2026", kind="nope").status_code == 422

# ---------------------------------------------------------------------------
# Isolation: a review for one report or period never collides with another's
# ---------------------------------------------------------------------------


def test_quarterly_and_weekly_reviews_of_the_same_section_coexist(client, db):
    weekly = client.post("/api/sections/equities/draft").json()
    q3 = client.post("/api/sections/equities/draft", json=Q3).json()
    q1 = client.post("/api/sections/equities/draft", json={"report_type": "quarterly", "period": "Q1'2026"}).json()
    assert len({weekly["run_id"], q3["run_id"], q1["run_id"]}) == 3
    assert (weekly["report_type"], weekly["period"]) == ("weekly", "")
    assert (q3["report_type"], q3["period"], q3["report_title"]) == ("quarterly", "Q3'2026", "Quarterly Markets Review")

    def latest(**params):
        return next(s for s in overview(client, **params).json()["sections"] if s["slug"] == "equities")["latest"]

    assert latest()["run_id"] == weekly["run_id"]                                   # the weekly overview
    assert latest(**Q3)["run_id"] == q3["run_id"] and latest(**Q3)["current"] is True
    assert latest(report_type="quarterly", period="Q1'2026")["run_id"] == q1["run_id"]
    assert latest(report_type="half_year", period="H1'2026") is None
    # A run-id lookup that names no report type is the weekly one, always.
    assert review_store.load_latest_review("equities", db_path=db).run_id == weekly["run_id"]
    # Deciding the quarterly review leaves the weekly one open, and the reverse.
    approve(client, q3["run_id"])
    assert client.get(f"/api/reviews/{weekly['run_id']}").json()["decision"] is None
    assert latest()["decision"] is None and latest(**Q3)["decision"] == "approved"


def test_the_quarterly_fixed_income_is_its_own_section(client):
    r = client.post("/api/sections/fixed_income/draft", json=Q3)
    assert r.status_code == 200
    sec = r.json()["section"]
    assert sec["chart_notes"][0] == "91-Day T-Bill Yield Growth (bps)"
    assert sec["chart_reference"] == "Cytonn Q3' 2026 Markets Review (4 Oct 2026)"
    table = next(b for b in sec["blocks"] if b["kind"] == "table")
    assert table["title"] == "Bond Issuances in Q3’2026"


def test_a_section_outside_the_report_type_is_not_found(client):
    assert client.post("/api/sections/focus/draft", json={**Q3, "topic": "x"}).status_code == 404
    assert client.post("/api/sections/digital_payments/draft",
                       json={"report_type": "annual", "period": "FY'2025"}).status_code == 404
    assert client.post("/api/sections/fixed_income/draft",
                       json={"report_type": "quarterly", "period": "Q4'2026"}).status_code == 422


def test_a_decision_is_still_once_per_section_and_irreversible(client):
    run = client.post("/api/sections/global_markets/draft", json=Q3).json()["run_id"]
    approve(client, run)
    again = client.post(f"/api/reviews/{run}/decide", json={"decision": "rejected"})
    assert again.status_code == 409
    assert client.patch(f"/api/reviews/{run}/items/0", json={"resolution": "fix_needed"}).status_code == 409


def test_a_newer_quarterly_digital_payments_review_never_reaches_the_weekly_summary(client, db, tmp_path):
    weekly = make_review()
    for item in weekly.review_items:
        item.resolve("accept")
    weekly.decide("approved")
    review_store.save_review(weekly, db_path=db)
    q3 = client.post("/api/sections/digital_payments/draft", json=Q3).json()
    assert q3["run_id"] > weekly.run_id and q3["report_type"] == "quarterly"
    assert review_store.load_latest_review(db_path=db).run_id == weekly.run_id
    path = summary.write_latest_summary(tmp_path / "s.docx", db_path=db)  # the weekly, approved review
    assert path.exists()

# ---------------------------------------------------------------------------
# Sections that call no provider: Company Updates and the Executive Summary
# ---------------------------------------------------------------------------


def test_company_updates_needs_text_but_no_api_key(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert client.post("/api/sections/global_markets/draft", json=Q3).status_code == 409  # needs the provider
    assert client.post("/api/sections/company_updates/draft", json=Q3).status_code == 422
    r = client.post("/api/sections/company_updates/draft", json={**Q3, "text": "Investment Updates: demo."})
    assert r.status_code == 200
    review = r.json()
    assert review["review_items"][0]["kind"] == "supplied_text" and review["section"]["blocks"][0]["kind"] == "supplied"
    assert overview(client, **Q3).json()["drafting"] is None


def test_the_executive_summary_waits_for_approvals_then_composes(client):
    r = client.post("/api/sections/executive_summary/draft", json=Q3)
    assert r.status_code == 409 and "Still to approve" in r.json()["detail"] and "Fixed Income (not drafted)" in r.json()["detail"]
    for slug in ["global_markets", "ssa", "kenya_macro", "fixed_income", "equities", "real_estate", "digital_payments"]:
        approve(client, client.post(f"/api/sections/{slug}/draft", json=Q3).json()["run_id"])
    r = client.post("/api/sections/executive_summary/draft", json=Q3)
    assert r.status_code == 200
    blocks = r.json()["section"]["blocks"]
    assert [b["source_section"] for b in blocks] == ["global_markets", "ssa", "kenya_macro", "fixed_income", "equities",
                                                     "real_estate", "digital_payments"]
    # The weekly report has no Executive Summary section at all.
    assert client.post("/api/sections/executive_summary/draft").status_code == 404


def test_the_draft_slot_names_its_report():
    slot = DraftSlot()
    slot.claim("fixed_income", "Fixed Income (Q3'2026)", "quarterly", "Q3'2026")
    status = slot.status()
    assert (status["slug"], status["report_type"], status["period"]) == ("fixed_income", "quarterly", "Q3'2026")
