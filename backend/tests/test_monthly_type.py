from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly import db as db_module
from cytonn_weekly import report_sections as rs
from cytonn_weekly import report_types as rt
from cytonn_weekly.digital_payments import review_store
from cytonn_weekly.report_types import (
    MONTHLY,
    PeriodError,
    monthly_week_ending,
    normalize_period,
    period_window,
    prose_label,
    suggested_period,
    year_ago,
)
from tests.review_helpers import make_review

MONTHLY_SLUGS = ["company_updates", "fixed_income", "equities", "real_estate", "digital_payments"]


# -- labels ---------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("typed", ["Oct'2026", "October 2026", "oct 2026", "Oct-2026", "oct/2026", "Oct’2026",
                                   "Oct' 2026", "  OCTOBER 2026  ", "Oct`2026"])
def test_every_accepted_form_is_stored_as_oct_2026(typed):
    assert normalize_period(MONTHLY, typed) == "Oct'2026"


@pytest.mark.parametrize("typed, says", [
    ("Mar'2026", "March 2026 has no Cytonn Monthly: it is covered by the Q1 Markets Review. Choose Quarterly Markets Review."),
    ("June 2026", "June 2026 has no Cytonn Monthly: it is covered by the H1 Markets Review. Choose Half-year Markets Review."),
    ("Sep'2026", "September 2026 has no Cytonn Monthly: it is covered by the Q3 Markets Review. Choose Quarterly Markets Review."),
    ("dec 2025", "December 2025 has no Cytonn Monthly: it is covered by the annual Markets Review. Choose Annual Markets Review."),
])
def test_a_month_a_markets_review_covers_is_refused_naming_the_review(typed, says):
    with pytest.raises(PeriodError) as refused:
        normalize_period(MONTHLY, typed)
    assert str(refused.value) == says


@pytest.mark.parametrize("typed", ["x", "Octember 2026", "Oct'26", "2026 Oct", "Q3'2026", "Oct", "10/2026", "Week ending 2026-10-30"])
def test_what_is_not_a_month_is_refused(typed):
    with pytest.raises(PeriodError, match="is not a month; write it as Oct'2026"):
        normalize_period(MONTHLY, typed)


@pytest.mark.parametrize("typed", [None, "", "   "])
def test_a_monthly_needs_a_period(typed):
    with pytest.raises(PeriodError, match="needs a period"):
        normalize_period(MONTHLY, typed)


def test_the_refusal_table_is_the_one_place_to_relax(monkeypatch):
    monkeypatch.setattr(rt, "MONTHS_COVERED_BY", {m: v for m, v in rt.MONTHS_COVERED_BY.items() if m != 9})
    assert normalize_period(MONTHLY, "Sep'2026") == "Sep'2026"
    assert suggested_period(MONTHLY, date(2026, 10, 15)) == "Sep'2026"
    with pytest.raises(PeriodError, match="Q1 Markets Review"):
        normalize_period(MONTHLY, "Mar'2026")


def test_the_window_comparison_and_prose_label():
    assert period_window(MONTHLY, "Oct'2026") == (date(2026, 10, 1), date(2026, 10, 31))
    assert period_window(MONTHLY, "Feb'2028") == (date(2028, 2, 1), date(2028, 2, 29))
    assert period_window(MONTHLY, "Nov'2026") == (date(2026, 11, 1), date(2026, 11, 30))
    assert year_ago("Oct'2026") == "Oct'2025"
    assert prose_label("Oct'2026") == "Oct’2026"


@pytest.mark.parametrize("today, expected", [
    (date(2026, 11, 3), "Oct'2026"),
    (date(2026, 12, 6), "Nov'2026"),
    (date(2026, 10, 15), ""),          # September has no Monthly
    (date(2027, 1, 4), ""),            # nor December
    (date(2026, 2, 1), "Jan'2026"),
])
def test_the_suggested_period_is_the_latest_ended_month_or_nothing(today, expected):
    assert suggested_period(MONTHLY, today) == expected


@pytest.mark.parametrize("period, friday", [
    ("Oct'2026", date(2026, 10, 30)),   # 31 Oct is a Saturday: Sunday 1 Nov
    ("May'2026", date(2026, 5, 29)),    # 31 May is itself a Sunday
    ("Aug'2026", date(2026, 9, 4)),     # 31 Aug is a Monday: Sunday 6 Sep
    ("Jan'2026", date(2026, 1, 30)),    # 31 Jan is a Saturday
])
def test_the_derived_week_ending_is_the_friday_before_the_monthlys_sunday(period, friday):
    got = monthly_week_ending(period)
    assert got == friday and got.weekday() == 4


# -- registry -------------------------------------------------------------------------------------------------------------

def test_the_monthly_has_five_stub_sections_in_the_issues_order():
    specs = rs.sections_for(MONTHLY)
    assert [s.slug for s in specs] == MONTHLY_SLUGS
    assert rs.spec_for(MONTHLY, "focus") is None and rs.spec_for(MONTHLY, "executive_summary") is None
    for spec in specs:
        assert spec.available is False and spec.build is None
        assert spec.reason and spec.unblock and spec.built_parts and spec.subsections and spec.charts
    assert rs.spec_for(MONTHLY, "fixed_income") is not rs.spec_for("weekly", "fixed_income")
    assert [s.slug for s in rs.sections_for("weekly")] == [s.slug for s in rs.SECTIONS]   # the weekly is untouched


# -- API ------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    return tmp_path / "app.db"


@pytest.fixture
def client(db):
    return TestClient(create_app(db_path=db, load_dotenv=False))


def test_the_overview_lists_the_monthlys_five_sections_each_with_its_reason(client):
    body = client.get("/api/sections", params={"report_type": "monthly", "period": "October 2026"}).json()
    assert body["report"]["period"] == "Oct'2026" and body["report"]["type"] == "monthly"
    assert [s["slug"] for s in body["sections"]] == MONTHLY_SLUGS
    for section, spec in zip(body["sections"], rs.sections_for(MONTHLY)):
        assert section["available"] is False and section["reason"] == spec.reason and section["unblock"] == spec.unblock
    monthly = next(t for t in body["report_types"] if t["slug"] == "monthly")
    assert monthly["period_required"] is True and monthly["suggested_period"] == suggested_period(MONTHLY, date.today())


def test_the_overview_refuses_a_month_a_review_covers_and_what_is_not_a_month(client):
    sep = client.get("/api/sections", params={"report_type": "monthly", "period": "Sep'2026"})
    assert sep.status_code == 422 and "covered by the Q3 Markets Review" in sep.json()["detail"]
    assert client.get("/api/sections", params={"report_type": "monthly", "period": "x"}).status_code == 422
    assert client.get("/api/sections", params={"report_type": "monthly"}).status_code == 422


def test_the_weekly_overview_is_unchanged(client):
    body = client.get("/api/sections").json()
    assert body["report"]["type"] == "weekly" and [s["slug"] for s in body["sections"]] == [s.slug for s in rs.SECTIONS]


def test_a_monthly_section_cannot_be_drafted_or_exported(client):
    for slug in MONTHLY_SLUGS:
        r = client.post(f"/api/sections/{slug}/draft", json={"report_type": "monthly", "period": "Oct'2026", "text": "x"})
        assert r.status_code == 409, slug
        run = client.post("/api/runs", json={"section": slug, "report_type": "monthly", "period": "Oct'2026", "text": "x"})
        assert run.status_code == 409, slug
    assert client.get("/api/export/weekly", params={"period": "Oct'2026"}).status_code == 422
    assert client.post("/api/export/weekly", params={"period": "Oct'2026"}).status_code == 422


def test_an_approved_monthly_review_is_not_a_previous_weekly_report(client, db):
    review = make_review()
    review.report_type, review.period = "monthly", "Oct'2026"
    for item in review.review_items:
        item.resolve("accept")
    review.decide("approved")
    review_store.save_review(review, db_path=db)
    body = client.get("/api/previous/weekly").json()
    assert body["weeks"] == [] and "Oct'2026" not in str(body)


# -- PostgreSQL: the SQL the migration sends (the live run is in test_postgres_smoke.py) ------------------------------------

def test_the_postgres_check_is_found_by_catalog_and_widened_in_one_statement():
    assert db_module.REPORT_TYPES_SQL == "('weekly', 'monthly', 'quarterly', 'half_year', 'annual', 'companion')"
    assert db_module.PG_FIND_REPORT_TYPE_CHECK == (
        "SELECT c.conname, pg_get_constraintdef(c.oid) AS definition FROM pg_constraint c "
        "JOIN pg_class t ON t.oid = c.conrelid JOIN pg_namespace n ON n.oid = t.relnamespace "
        "WHERE n.nspname = ? AND t.relname = 'coordinator_reviews' AND c.contype = 'c' "
        "AND pg_get_constraintdef(c.oid) LIKE '%report_type%'")
    assert db_module.pg_widen_report_type_check("coordinator_reviews_report_type_check") == (
        'ALTER TABLE coordinator_reviews DROP CONSTRAINT IF EXISTS "coordinator_reviews_report_type_check", '
        "ADD CONSTRAINT coordinator_reviews_report_type_check CHECK (report_type IN "
        "('weekly', 'monthly', 'quarterly', 'half_year', 'annual', 'companion'))")
    assert 'DROP CONSTRAINT IF EXISTS "odd""name"' in db_module.pg_widen_report_type_check('odd"name')


class FakePg:
    schema = "public"

    def __init__(self, found):
        self.found, self.sent = found, []

    def execute(self, sql, params=()):
        self.sent.append((sql, params))
        rows = self.found if sql == db_module.PG_FIND_REPORT_TYPE_CHECK else []
        return type("Cursor", (), {"fetchall": lambda _self: rows})()


FIVE = "CHECK ((report_type = ANY (ARRAY['weekly'::text, 'quarterly'::text, 'half_year'::text, 'annual'::text, 'companion'::text])))"
SIX = FIVE.replace("'weekly'::text, ", "'weekly'::text, 'monthly'::text, ")


def test_postgres_is_widened_once_and_left_alone_after():
    old = FakePg([{"conname": "coordinator_reviews_report_type_check", "definition": FIVE}])
    db_module._allow_monthly_postgres(old)
    assert old.sent == [(db_module.PG_FIND_REPORT_TYPE_CHECK, ("public",)),
                        (db_module.pg_widen_report_type_check("coordinator_reviews_report_type_check"), ())]
    done = FakePg([{"conname": "coordinator_reviews_report_type_check", "definition": SIX}])
    db_module._allow_monthly_postgres(done)
    assert done.sent == [(db_module.PG_FIND_REPORT_TYPE_CHECK, ("public",))]


@pytest.mark.parametrize("found", [[], [{"conname": "a", "definition": FIVE}, {"conname": "b", "definition": FIVE}]])
def test_postgres_stops_rather_than_guess_when_the_check_is_not_one(found):
    with pytest.raises(RuntimeError):
        db_module._allow_monthly_postgres(FakePg(found))
