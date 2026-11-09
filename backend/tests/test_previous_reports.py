from datetime import date

from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly.digital_payments import review_store
from cytonn_weekly.report_sections import SECTIONS
from cytonn_weekly.weekly import export
from cytonn_weekly.weekly.week import latest_friday
from tests import section_helpers as sh
from tests.review_helpers import LocalFakeProvider, make_review

SLUGS = [spec.slug for spec in SECTIONS]


def _review():
    return sh.real_estate_review()


def _save(db, slug, period, decision="approved", review=None):
    review = review or _review()
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


def test_five_approved_is_listed_and_four_is_not(tmp_path):
    db = tmp_path / "app.db"
    _week(db, "2026-10-02")
    _week(db, "2026-10-09", skip=("focus",))
    weeks = export.approved_weeks(db)["weeks"]
    assert [w["week_ending"] for w in weeks] == ["2026-10-02"]


def test_an_old_company_updates_run_is_ignored_by_the_count(tmp_path):
    db = tmp_path / "app.db"
    period = _week(db, "2026-10-02")
    _save(db, "company_updates", period, decision="rejected")   # stored by an earlier version, newest run of that slug
    out = export.approved_weeks(db)
    assert [w["week_ending"] for w in out["weeks"]] == ["2026-10-02"] and "company_updates" not in SLUGS
    assert next(c for c in out["choices"] if c["week_ending"] == "2026-10-02")["status"] == "approved"


def test_a_newer_run_in_review_or_rejected_takes_the_week_off_the_list(tmp_path):
    db = tmp_path / "app.db"
    in_review = _week(db, "2026-10-02")
    rejected = _week(db, "2026-10-09")
    _save(db, "equities", in_review, decision=None)          # a newer draft, undecided
    _save(db, "real_estate", rejected, decision="rejected")  # a newer draft, rejected
    out = export.approved_weeks(db)
    assert out["weeks"] == [] and out["next_week_ending"] is None and out["default_week_ending"] is not None


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


def test_no_fully_approved_week_has_no_next_week(tmp_path):
    db = tmp_path / "app.db"
    _week(db, "2026-10-02", skip=("focus",))
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
        review = _review()
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
    friday = latest_friday(date.today())
    assert body["default_week_ending"] == friday.isoformat()   # approvals never move it
    assert len(body["choices"]) == 9 and body["choices"][1]["week_ending"] == friday.isoformat()


def test_no_approved_week_opens_on_the_latest_friday_and_is_never_null(tmp_path):
    db = tmp_path / "app.db"
    out = export.approved_weeks(db, today=date(2026, 10, 14))
    assert out["next_week_ending"] is None and out["default_week_ending"] == "2026-10-09"
    body = TestClient(create_app(db_path=db, load_dotenv=False)).get("/api/previous/weekly").json()
    assert body["next_week_ending"] is None and body["default_week_ending"] == latest_friday(date.today()).isoformat()


def test_a_week_approved_ahead_of_the_calendar_does_not_move_the_default(tmp_path):
    db = tmp_path / "app.db"
    _week(db, "2026-10-16")                                   # approved ahead of the calendar
    out = export.approved_weeks(db, today=date(2026, 10, 12))  # latest Friday 9 Oct
    assert out["next_week_ending"] == "2026-10-23" and out["default_week_ending"] == "2026-10-09"


def test_an_older_approved_week_leaves_the_default_on_the_latest_friday(tmp_path):
    db = tmp_path / "app.db"
    _week(db, "2026-10-02")
    out = export.approved_weeks(db, today=date(2026, 10, 19))  # latest Friday 16 Oct; 9 Oct was skipped
    assert out["next_week_ending"] == "2026-10-09" and out["default_week_ending"] == "2026-10-16"


def test_the_latest_friday_approved_stays_the_default(tmp_path):
    db = tmp_path / "app.db"
    _week(db, "2026-10-09")
    out = export.approved_weeks(db, today=date(2026, 10, 9))   # a Friday: it is its own latest Friday
    assert out["next_week_ending"] == "2026-10-16" and out["default_week_ending"] == "2026-10-09"


def test_the_choices_are_the_coming_friday_and_the_last_eight_with_their_status(tmp_path):
    db = tmp_path / "app.db"
    _week(db, "2026-10-09")                                    # all five approved
    _week(db, "2026-10-02", skip=("focus", "equities"))        # three approved
    out = export.approved_weeks(db, today=date(2026, 10, 14))["choices"]   # latest Friday 9 Oct
    assert [c["week_ending"] for c in out][:3] == ["2026-10-16", "2026-10-09", "2026-10-02"] and len(out) == 9
    assert out[-1]["week_ending"] == "2026-08-21"
    by = {c["week_ending"]: c for c in out}
    assert by["2026-10-16"]["status"] == "not_started" and by["2026-10-16"]["approved"] == 0
    assert by["2026-10-09"]["status"] == "approved" and by["2026-10-09"]["approved"] == by["2026-10-09"]["total"] == 5
    assert by["2026-10-02"]["status"] == "in_progress" and by["2026-10-02"]["approved"] == 3
    assert by["2026-10-02"]["period"] == "Week ending 2026-10-02"
