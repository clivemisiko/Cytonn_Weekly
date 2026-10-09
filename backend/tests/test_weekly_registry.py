"""The weekly report as a whole: its sections in the real order, each with a summary, drafted for one week.

The order and the summaries are read from Cytonn Weekly #38.2026 (cytonnreport.com issue
891): Company updates, Fixed Income, Equities, Real Estate, Digital Payments Weekly
Highlights, Focus of the Week; each CMS section carries a ``summary`` of its own lead
paragraphs, except Company updates, whose summary is empty.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.serialize import serialize_review
from cytonn_weekly import report_sections as rs
from cytonn_weekly.equities import weekly as eq_weekly
from cytonn_weekly.fixed_income import weekly as fi_weekly
from cytonn_weekly.weekly import company_updates, inputs
from cytonn_weekly.weekly.summaries import LIMIT, section_summary
from tests import section_helpers as sh
from tests import weekly_helpers as wh
from tests.review_helpers import make_review
from tests.test_weekly_fixed_income import BULLETIN, fetchers

WEEK = wh.WEEK
UPDATES = "Investment Updates:\n\nWeekly Rates: the fund closed the week at 11.0% p.a.\n\nHospitality Updates:\n\nStaycation offers."


def test_the_weekly_sections_are_in_issue_38s_order():
    assert [(s.slug, s.title) for s in rs.SECTIONS] == [
        ("company_updates", "Company Updates"), ("fixed_income", "Fixed Income"), ("equities", "Equities"),
        ("real_estate", "Real Estate"), ("digital_payments", "Digital Payments"), ("focus", "Focus of the Week")]
    assert all(s.available and s.build is not None for s in rs.SECTIONS)
    by = rs.BY_SLUG
    assert by["company_updates"].needs_text and by["focus"].needs_topic and not by["fixed_income"].needs_text
    assert by["fixed_income"].subsections == fi_weekly.SUBSECTIONS and by["fixed_income"].charts == fi_weekly.CHARTS
    assert by["equities"].subsections == eq_weekly.SUBSECTIONS and by["equities"].charts == eq_weekly.CHARTS
    assert [t for t, _ in by["fixed_income"].steps][:1] == ["This week's inputs"] and by["fixed_income"].steps[-1][0] == "Your review"
    assert "afx" not in " ".join(body for _, body in by["equities"].steps)   # the weekly prints no afx tables any more


def test_company_updates_is_the_coordinators_text_carried_verbatim():
    review = company_updates.build_company_updates_weekly_review(UPDATES, WEEK.ending)
    assert review.section["section"] == "company_updates" and review.section["week_ending"] == "2026-10-02"
    block = review.section["blocks"][0]
    assert (block["kind"], block["body_md"], block["supplied_by"]) == ("supplied", UPDATES, "coordinator")
    assert [(i.kind, i.status) for i in review.review_items] == [("supplied_text", "not_auto_verified")]
    assert review.section["summary"] == ""   # the published Company updates has no summary
    with pytest.raises(ValueError, match="paste the Investment Updates and Hospitality Updates"):
        company_updates.build_company_updates_weekly_review("   ")
    with pytest.raises(ValueError, match="the limit is 10000"):
        company_updates.build_company_updates_weekly_review("x" * 10_001)


def test_every_weekly_section_has_a_summary_composed_from_its_own_text():
    equities = sh.equities_review().section          # block-shaped, with drafted pieces
    summary = section_summary(equities)
    first = next(b for b in equities["blocks"] if b["kind"] == "narrative")
    assert summary.startswith(" ".join(first["body_md"].split("\n\n")[0].split())) and len(summary) <= LIMIT
    dp = make_review().section                       # the weekly Digital Payments shape: highlights as items
    highlights = [i for i in dp["items"] if i["kind"] == "highlight"]
    assert section_summary(dp).split("\n\n")[0] == " ".join(highlights[0]["body_md"].split("\n\n")[0].split())
    assert section_summary(sh.focus_review(topic="SSA Eurobonds").section)
    assert section_summary({"blocks": [], "summary": "Already composed."}) == "Already composed."
    assert section_summary({"blocks": [{"kind": "unavailable", "id": "x", "title": "X", "reason": "r", "unblock": "u"}]}) == ""
    # never cut inside a paragraph: a paragraph that does not fit is left out whole
    long = {"blocks": [{"kind": "narrative", "body_md": "a" * 2000}, {"kind": "narrative", "body_md": "b" * 2000},
                       {"kind": "narrative", "body_md": "c" * 900}]}
    assert section_summary(long) == "a" * 2000 + "\n\n" + "c" * 900


def test_computed_and_carried_blocks_reach_the_screen_with_their_figures_and_the_summary(tmp_path):
    inputs.store(WEEK, "cbk_bulletin", BULLETIN, "bulletin.pdf", tmp_path)
    inputs.store(WEEK, "fi_workbook", wh.fi_workbook_bytes(), "FI.xlsx", tmp_path)
    review = fi_weekly.build_fixed_income_review(WEEK.ending, inputs=inputs.WeeklyInputs(WEEK, tmp_path), fetchers=fetchers(),
                                                 draft=wh.no_draft)
    body = serialize_review(review)
    by = {b["id"]: b for b in body["section"]["blocks"]}
    tbills = by["tbills"]
    assert tbills["kind"] == "computed" and tbills["numeral"] == "I" and tbills["figures"][0]["display"] == "170.4%"
    assert tbills["figures"][0]["inputs"]["bids_91"]["source"] == "CBK Weekly Bulletin, Table 4"
    assert by["outlook"]["kind"] == "carried" and by["outlook"]["carried_from"]["issue_id"] == 891
    assert all(r["typed"] for r in by["mmf_table"]["rows"]) and "source_rows" not in by["mmf_table"]
    assert by["eurobonds_table"]["notes"] == ["Changes are in percentage points."]
    assert body["summary"].startswith("This week, T-bills were oversubscribed") and body["section"]["week_ending"] == "2026-10-02"
    kinds = {i["kind"] for i in body["review_items"]}
    assert {"computed_figure", "carried_text", "table_row", "unavailable_part"} <= kinds
    figure = next(i for i in body["review_items"] if i["kind"] == "computed_figure")
    assert figure["context"]["inputs"] and figure["context"]["text"] == tbills["body_md"]


# ---------------------------------------------------------------------------
# The API: one report week
# ---------------------------------------------------------------------------

@pytest.fixture
def api(tmp_path, monkeypatch):
    """A client whose Fixed Income and Equities builders record how they were called and return a small real review."""
    calls = []

    def fake(name):
        def builder(**kwargs):
            calls.append((name, kwargs))
            review = company_updates.build_company_updates_weekly_review(f"{name} stand-in", kwargs.get("week_ending"))
            review.section["section"] = name   # saved under the section it stands in for
            return review
        return builder

    monkeypatch.setattr(fi_weekly, "build_fixed_income_review", fake("fixed_income"))
    monkeypatch.setattr(eq_weekly, "build_equities_weekly_review", fake("equities"))
    client = TestClient(create_app(db_path=tmp_path / "app.db", load_dotenv=False, inputs_root=tmp_path / "weekly"))
    return client, calls, tmp_path


def test_a_weekly_section_is_drafted_for_the_week_its_period_names(api):
    client, calls, tmp_path = api
    r = client.post("/api/sections/fixed_income/draft", json={"period": "2026-10-02"})
    assert r.status_code == 200 and r.json()["period"] == "Week ending 2026-10-02"
    name, kwargs = calls[-1]
    assert name == "fixed_income" and kwargs["week_ending"] == date(2026, 10, 2) and kwargs["inputs_root"] == tmp_path / "weekly"
    # with no period, the builder is left to take the latest week that has ended
    assert client.post("/api/sections/equities/draft").status_code == 200
    assert "week_ending" not in calls[-1][1]
    refused = client.post("/api/sections/fixed_income/draft", json={"period": "2026-10-01"})
    assert refused.status_code == 422 and "week ends on a Friday" in refused.json()["detail"]


def test_each_week_has_its_own_reviews(api):
    client, _, _ = api
    this = client.post("/api/sections/fixed_income/draft", json={"period": "2026-10-02"}).json()
    last = client.post("/api/sections/fixed_income/draft", json={"period": "2026-09-25"}).json()
    assert this["run_id"] != last["run_id"]
    overview = client.get("/api/sections", params={"period": "Week ending 2026-10-02"}).json()
    fi = next(s for s in overview["sections"] if s["slug"] == "fixed_income")
    assert fi["latest"]["run_id"] == this["run_id"] and fi["latest"]["current"] is True
    assert overview["report"]["week_ending"] == "2026-10-02"
    assert all(s["latest"] is None for s in overview["sections"] if s["slug"] != "fixed_income")
    assert all(s["latest"] is None for s in client.get("/api/sections").json()["sections"])   # the unlabelled weekly is separate


def test_company_updates_needs_no_provider_and_no_key(api, monkeypatch):
    client, _, _ = api
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert client.post("/api/sections/company_updates/draft").status_code == 422   # no text
    r = client.post("/api/sections/company_updates/draft", json={"text": UPDATES, "period": "2026-10-02"})
    assert r.status_code == 200
    body = r.json()
    assert body["section"]["blocks"][0]["body_md"] == UPDATES and body["summary"] == "" and body["is_dev_draft"] is False
    updates = client.get("/api/sections").json()["sections"][0]
    assert (updates["slug"], updates["uses_provider"], updates["needs_text"]) == ("company_updates", False, True)


def test_a_run_of_a_weekly_section_carries_the_week_too(api):
    client, calls, _ = api
    started = client.post("/api/runs", json={"section": "equities", "period": "2026-10-02"})
    assert started.status_code == 202
    run_id = started.json()["run_id"]
    for _ in range(200):
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] != "running":
            break
    assert run["status"] == "finished" and calls[-1][1]["week_ending"] == date(2026, 10, 2)
    assert callable(calls[-1][1]["on_event"])
