from datetime import date

from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly.digital_payments import review_store
from cytonn_weekly.report_sections import SECTIONS
from cytonn_weekly.weekly import company_updates, export
from tests.review_helpers import LocalFakeProvider, make_review

SLUGS = [spec.slug for spec in SECTIONS]


def _review(friday):
    return company_updates.build_company_updates_weekly_review("Investment Updates:\n\nRates held.", friday)


def _save(db, slug, period, decision="approved", review=None):
    review = review or _review(date.fromisoformat(period[len("Week ending "):]))
    review.report_type, review.period = "weekly", period
    if decision:
        for item in review.review_items:
            item.resolve("accept")
        review.decide(decision)
    review_store.save_review(review, section=slug, db_path=db)
    return review


def _week(db, friday, skip=(), **by_slug):
    period = f"Week ending {friday}"
    for slug in SLUGS:
        if slug not in skip:
            _save(db, slug, period, review=by_slug.get(slug))
    return period


def test_six_approved_is_listed_and_five_is_not(tmp_path):
    db = tmp_path / "app.db"
    _week(db, "2026-10-02")
    _week(db, "2026-10-09", skip=("focus",))
    weeks = export.approved_weeks(db)["weeks"]
    assert [w["week_ending"] for w in weeks] == ["2026-10-02"]


def test_a_newer_run_in_review_or_rejected_takes_the_week_off_the_list(tmp_path):
    db = tmp_path / "app.db"
    in_review = _week(db, "2026-10-02")
    rejected = _week(db, "2026-10-09")
    _save(db, "equities", in_review, decision=None)          # a newer draft, undecided
    _save(db, "real_estate", rejected, decision="rejected")  # a newer draft, rejected
    assert export.approved_weeks(db) == {"weeks": [], "next_week_ending": None}


def test_the_list_is_newest_first_with_its_fields_and_the_week_after_the_latest(tmp_path):
    db = tmp_path / "app.db"
    _week(db, "2026-10-02")
    _week(db, "2026-10-16")
    _week(db, "2026-10-09")
    out = export.approved_weeks(db)
    assert [w["week_ending"] for w in out["weeks"]] == ["2026-10-16", "2026-10-09", "2026-10-02"]
    assert out["next_week_ending"] == "2026-10-23"
    first = out["weeks"][0]
    assert set(first) == {"period", "week_ending", "approved_at", "is_dev_draft", "can_export", "sections"}
    assert first["period"] == "Week ending 2026-10-16" and first["can_export"] is True and first["is_dev_draft"] is False
    assert [s["slug"] for s in first["sections"]] == SLUGS and all(s["run_id"] for s in first["sections"])
    assert first["approved_at"] == max(review_store.load_review(s["run_id"], db_path=db).decided_at for s in first["sections"])


def test_no_approved_week_leaves_the_default_alone(tmp_path):
    db = tmp_path / "app.db"
    _week(db, "2026-10-02", skip=("company_updates",))
    assert export.approved_weeks(db)["next_week_ending"] is None


def test_a_dev_draft_in_any_section_marks_the_week(tmp_path):
    db = tmp_path / "app.db"
    _week(db, "2026-10-02", digital_payments=make_review(provider=LocalFakeProvider()))
    _week(db, "2026-10-09")
    flags = {w["week_ending"]: w["is_dev_draft"] for w in export.approved_weeks(db)["weeks"]}
    assert flags == {"2026-10-02": True, "2026-10-09": False}


def test_other_report_types_are_never_listed(tmp_path):
    db = tmp_path / "app.db"
    for slug in SLUGS:
        review = _review(date(2026, 10, 2))
        review.report_type, review.period = "quarterly", "Q3'2026"
        for item in review.review_items:
            item.resolve("accept")
        review.decide("approved")
        review_store.save_review(review, section=slug, db_path=db)
    assert export.approved_weeks(db)["weeks"] == []


def test_the_route_returns_the_list_and_the_next_week(tmp_path):
    db = tmp_path / "app.db"
    _week(db, "2026-10-02")
    client = TestClient(create_app(db_path=db, load_dotenv=False))
    body = client.get("/api/previous/weekly").json()
    assert body["next_week_ending"] == "2026-10-09" and [w["period"] for w in body["weeks"]] == ["Week ending 2026-10-02"]
