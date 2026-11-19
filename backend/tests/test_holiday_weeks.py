from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly import report_sections
from cytonn_weekly.equities import weekly as eqw
from cytonn_weekly.fixed_income import weekly as fiw
from cytonn_weekly.real_estate import fetcher as reit
from cytonn_weekly.report_types import PeriodError, normalize_period
from cytonn_weekly.weekly import inputs, week as week_module
from cytonn_weekly.weekly.week import NotAFriday, Week
from tests import test_real_estate as re_tests
from tests import test_weekly_equities as eq
from tests import test_weekly_fixed_income as fi
from tests import weekly_helpers as wh
from tests.weekly_helpers import text_pdfs  # noqa: F401 - a fixture

XMAS = Week(date(2026, 12, 25))       # the Friday is Christmas Day
NEW_YEAR = Week(date(2027, 1, 1))     # the Friday is New Year's Day, so the week is as at 2026
NORMAL = Week(date(2026, 10, 9))
CHRISTMAS_NOTE = "Friday 25 Dec 2026 was a market holiday; figures are as at Thursday 24 Dec 2026."
NEW_YEAR_NOTE = "Friday 1 Jan 2027 was a market holiday; figures are as at Thursday 31 Dec 2026."


def iso(days):
    return [d.isoformat() for d in days]


# ---------------------------------------------------------------------------
# The week
# ---------------------------------------------------------------------------

def test_a_normal_week_is_as_at_its_friday_and_has_no_note():
    assert NORMAL.as_at == NORMAL.ending and NORMAL.previous_as_at == NORMAL.previous_friday
    assert iso(NORMAL.trading_days) == ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]
    assert NORMAL.holiday_note is None and NORMAL.report_dates == (NORMAL.ending,) and NORMAL.days_note() == "Monday to Friday"


def test_the_week_of_christmas_is_as_at_thursday_against_the_friday_before():
    assert XMAS.as_at == date(2026, 12, 24) and XMAS.previous_as_at == date(2026, 12, 18)
    assert iso(XMAS.trading_days) == ["2026-12-21", "2026-12-22", "2026-12-23", "2026-12-24"]
    assert XMAS.holiday_note == CHRISTMAS_NOTE
    assert XMAS.report_dates == (date(2026, 12, 25), date(2026, 12, 24))
    assert XMAS.days_note().startswith("4 trading days (Monday, Tuesday, Wednesday, Thursday); the previous week had 5 trading days")


def test_the_week_of_new_year_is_as_at_the_last_day_of_the_old_year_against_the_thursday_before():
    assert NEW_YEAR.as_at == date(2026, 12, 31) and NEW_YEAR.previous_as_at == date(2026, 12, 24)
    assert iso(NEW_YEAR.trading_days) == ["2026-12-28", "2026-12-29", "2026-12-30", "2026-12-31"]
    assert NEW_YEAR.holiday_note == NEW_YEAR_NOTE
    assert NEW_YEAR.days_note() == "4 trading days (Monday, Tuesday, Wednesday, Thursday)"   # both weeks had four


def test_a_holiday_week_is_still_named_by_its_friday_and_a_non_friday_is_still_refused():
    assert normalize_period("weekly", "2026-12-25") == "Week ending 2026-12-25"
    for thursday in ("2026-12-24", "Week ending 2026-12-24"):
        with pytest.raises(PeriodError, match="is a Thursday"):
            normalize_period("weekly", thursday)
    with pytest.raises(NotAFriday):
        Week(date(2026, 12, 24))


def test_an_as_at_date_set_by_hand_replaces_the_last_trading_day():
    week = Week(date(2026, 12, 25), date(2026, 12, 23))
    assert week.as_at == date(2026, 12, 23) and iso(week.trading_days) == ["2026-12-21", "2026-12-22", "2026-12-23"]
    assert week.previous_as_at == date(2026, 12, 18)                      # the week before is never affected
    assert week.holiday_note.startswith("Friday 25 Dec 2026 was a market holiday; figures are as at Wednesday 23 Dec 2026.")
    on_a_normal_week = Week(date(2026, 10, 9), date(2026, 10, 8))
    assert on_a_normal_week.holiday_note == "Figures are as at Thursday 8 Oct 2026, the date set for this week."
    for bad in (date(2026, 12, 28), date(2026, 12, 19), date(2026, 12, 25)):
        with pytest.raises(ValueError):
            Week(date(2026, 12, 25), bad)


def test_the_list_of_closures_is_a_file_that_can_be_edited(tmp_path, monkeypatch):
    path = tmp_path / "closures.json"
    monkeypatch.setattr(week_module, "CLOSURES_FILE", path)
    path.write_text("{}", encoding="utf-8")
    assert XMAS.as_at == XMAS.ending and XMAS.holiday_note is None          # nothing listed: a normal week
    path.write_text('{"2026-12-25": "Christmas Day", "2026-12-23": "a closure added by hand"}', encoding="utf-8")
    assert XMAS.as_at == date(2026, 12, 24) and iso(XMAS.trading_days) == ["2026-12-21", "2026-12-22", "2026-12-24"]
    assert XMAS.holiday_note == CHRISTMAS_NOTE + " Wednesday 23 Dec 2026 was a market holiday; its data is skipped."
    path.write_text('{"2026-10-09": "a closure added by hand"}', encoding="utf-8")
    assert NORMAL.as_at == date(2026, 10, 8) and NORMAL.previous_as_at == NORMAL.previous_friday
    path.write_text("[not json", encoding="utf-8")
    with pytest.raises(ValueError, match="list of market closures"):
        XMAS.as_at


def test_the_shipped_list_holds_the_two_closures_the_team_named_and_nothing_else():
    assert week_module.closures() == {date(2026, 12, 25): "Christmas Day", date(2027, 1, 1): "New Year's Day"}


# ---------------------------------------------------------------------------
# The inputs
# ---------------------------------------------------------------------------

def test_a_holiday_week_expects_no_daily_report_for_the_closed_friday(tmp_path, text_pdfs):
    status = inputs.status(XMAS, tmp_path)
    daily = next(s for s in status["slots"] if s["slug"] == "kcb_daily")
    assert [d["date"] for d in daily["days"]] == iso(XMAS.trading_days)
    assert status["as_at"] == "2026-12-24" and status["previous_as_at"] == "2026-12-18" and status["holiday_note"] == CHRISTMAS_NOTE
    with pytest.raises(inputs.InputError, match="25 Dec 2026"):
        inputs.store(XMAS, "kcb_daily", wh.fake_pdf(wh.kcb_daily_text(date(2026, 12, 25))), "fri.pdf", tmp_path)
    normal = inputs.status(NORMAL, tmp_path)
    assert normal["as_at"] == "2026-10-09" and normal["holiday_note"] is None


def test_a_report_dated_the_as_at_day_is_this_weeks(tmp_path, text_pdfs):
    saved = inputs.store(XMAS, "kcb_weekly", wh.fake_pdf(wh.kcb_weekly_text(XMAS, flows=flows_for(XMAS))), "weekly.pdf", tmp_path)
    assert saved["read_date"] == "2026-12-24" and saved["matches"] is True
    saved = inputs.store(XMAS, "equities_workbook", wh.equities_workbook_bytes(XMAS), "Eq.xlsx", tmp_path)
    assert saved["read_date"] == "2026-12-24" and saved["matches"] is True


def test_the_as_at_date_is_set_through_the_notes_and_checked(tmp_path):
    assert inputs.write_notes(XMAS, {"as_at": "2026-12-23"}, tmp_path) == {"as_at": "2026-12-23"}
    assert inputs.WeeklyInputs(XMAS, tmp_path).week.as_at == date(2026, 12, 23)
    assert inputs.WeeklyInputs(NEW_YEAR, tmp_path).week.as_at == date(2026, 12, 31)   # another week's notes are its own
    for bad, why in (("2026-12-28", "weekday"), ("2026-12-25", "holiday"), ("tomorrow", "YYYY-MM-DD")):
        with pytest.raises(inputs.InputError, match=why):
            inputs.write_notes(XMAS, {"as_at": bad}, tmp_path)
    assert inputs.write_notes(XMAS, {"as_at": ""}, tmp_path) == {}
    assert inputs.WeeklyInputs(XMAS, tmp_path).week.as_at == date(2026, 12, 24)


def test_the_start_screen_sets_the_as_at_date_through_the_api(tmp_path):
    client = TestClient(create_app(db_path=tmp_path / "app.db", load_dotenv=False, inputs_root=tmp_path / "weekly"))
    assert client.get("/api/inputs/weekly/2026-12-25").json()["holiday_note"] == CHRISTMAS_NOTE
    status = client.put("/api/inputs/weekly/2026-12-25/notes", json={"as_at": "2026-12-23"}).json()
    assert status["as_at"] == "2026-12-23" and status["notes"] == {"as_at": "2026-12-23"}
    assert [d["date"] for d in next(s for s in status["slots"] if s["slug"] == "kcb_daily")["days"]] == [
        "2026-12-21", "2026-12-22", "2026-12-23"]
    refused = client.put("/api/inputs/weekly/2026-12-25/notes", json={"as_at": "2026-12-28"})
    assert refused.status_code == 422 and "weekday of the week ending 25 Dec 2026" in refused.json()["detail"]
    assert client.get("/api/inputs/weekly/2026-10-09").json()["as_at"] == "2026-10-09"
    assert client.get("/api/inputs/weekly/2026-12-24").status_code == 422     # a Thursday is still not a week


# ---------------------------------------------------------------------------
# Equities, through every reader
# ---------------------------------------------------------------------------

def flows_for(week):
    return {d.strftime("%A"): v for d, v in zip(week.trading_days, (-60_000_000, -6_000_000, 80_000_000, 60_000_000, 40_000_000))}


def rates_for(*weeks):
    out, n = {date(2026, 1, 2): 129.2}, 0
    for day in wh.weekdays(date(2026, 12, 1), date(2027, 1, 8)):
        if day not in (date(2026, 12, 25), date(2027, 1, 1)):
            out[day] = round(129.0 + 0.01 * n, 2)
            n += 1
    return out


def equities_week(week, root):
    inputs.store(week, "equities_workbook", wh.equities_workbook_bytes(week), "Eq.xlsx", root)
    inputs.store(week, "kcb_weekly", wh.fake_pdf(wh.kcb_weekly_text(week, flows=flows_for(week))), "weekly.pdf", root)
    for day in week.trading_days:
        inputs.store(week, "kcb_daily", wh.fake_pdf(wh.kcb_daily_text(day, turnover=500_000_000)), f"{day}.pdf", root)


def equities_review(friday, root):
    week = inputs.WeeklyInputs(Week(friday), root).week
    boxes = {week.as_at: {"nasi": 200.0, "nse_20": 4000.0, "nse_25": 7000.0, "nse_10": 2500.0, "banking": 300.0},
             week.previous_as_at: {"nasi": 202.0, "nse_20": 4040.0, "nse_25": 7070.0, "nse_10": 2525.0, "banking": 303.0},
             date(2026, 1, 2): {"nasi": 160.0, "nse_20": 3200.0, "nse_25": 5600.0, "nse_10": 2000.0, "banking": 200.0}}
    return eqw.build_equities_weekly_review(friday, inputs=inputs.WeeklyInputs(Week(friday), root), draft=wh.no_draft, today=friday,
                                            fetchers=eq.fetchers(boxes, usd_rates=lambda: rates_for()))


@pytest.mark.parametrize("week, note, price_dates, banking, trading", [
    (XMAS, CHRISTMAS_NOTE, ("18/12/2026", "24/12/2026"), ("Thursday", "previous Friday"), "4 trading days (Monday"),
    (NEW_YEAR, NEW_YEAR_NOTE, ("24/12/2026", "31/12/2026"), ("Thursday", "previous Thursday"), "4 trading days (Monday")])
def test_every_equities_reader_uses_the_as_at_day_in_a_holiday_week(tmp_path, text_pdfs, week, note, price_dates, banking, trading):
    equities_week(week, tmp_path)
    review = equities_review(week.ending, tmp_path)
    by = {b["id"]: b for b in review.section["blocks"]}
    assert review.section["week_ending"] == week.ending.isoformat()
    assert review.section["warnings"][0] == note                               # the reviewer note leads the section's warnings
    # prices and w/w: the KCB weekly report and the OCR'd boxes, read for the as-at day and the previous week's
    assert by["indices"]["kind"] == "computed" and {f["key"] for f in by["indices"]["figures"]} >= {"nasi_wow", "nasi_ytd"}
    assert by["banking"]["kind"] == "computed"
    labels = {f["label"] for f in by["banking"]["figures"]}
    assert f"Banking Sector index, {banking[0]}" in labels and f"Banking Sector index, {banking[1]}" in labels
    # the Universe of Coverage reader finds the price columns by exact date
    universe = by["universe_of_coverage"]
    assert [c["label"] for c in universe["columns"][1:3]] == [f"Price as at {price_dates[0]}", f"Price as at {price_dates[1]}"]
    assert universe["columns"][6]["label"] == "Year Open 2026" and len(universe["rows"]) == 5
    # Monday to Friday sums skip the closed day, and the draft says how many days were used
    for block_id in ("turnover", "foreign"):
        assert by[block_id]["kind"] == "computed" and trading in by[block_id]["notes"][0]
    assert len([k for k in by["turnover"]["figures"][0]["inputs"] if k.startswith("kes_")]) == 4
    assert by["valuation"]["kind"] == "computed"                              # the workbook's row for the as-at day
    assert not [b for b in by.values() if b["kind"] == "unavailable" and b["id"] in ("indices", "banking", "turnover", "foreign",
                                                                                      "valuation", "universe_of_coverage")]


def test_christmas_week_says_the_previous_week_had_five_days(tmp_path, text_pdfs):
    equities_week(XMAS, tmp_path)
    by = {b["id"]: b for b in equities_review(XMAS.ending, tmp_path).section["blocks"]}
    assert "the previous week had 5 trading days" in by["turnover"]["notes"][0]


def test_the_as_at_date_set_on_the_start_screen_moves_every_equities_reader(tmp_path, text_pdfs):
    chosen = Week(date(2026, 12, 25), date(2026, 12, 23))
    inputs.write_notes(XMAS, {"as_at": "2026-12-23"}, tmp_path)
    equities_week(chosen, tmp_path)
    review = equities_review(XMAS.ending, tmp_path)
    by = {b["id"]: b for b in review.section["blocks"]}
    assert review.section["warnings"][0].startswith("Friday 25 Dec 2026 was a market holiday; figures are as at Wednesday 23 Dec 2026.")
    assert [c["label"] for c in by["universe_of_coverage"]["columns"][1:3]] == ["Price as at 18/12/2026", "Price as at 23/12/2026"]
    assert "3 trading days (Monday, Tuesday, Wednesday)" in by["turnover"]["notes"][0]


def test_a_normal_week_prints_what_it_always_did(tmp_path, text_pdfs):
    eq_root = tmp_path
    inputs.store(wh.WEEK, "cbk_bulletin", eq.BULLETIN, "bulletin.pdf", eq_root)
    inputs.store(wh.WEEK, "equities_workbook", wh.equities_workbook_bytes(), "Equities.xlsx", eq_root)
    inputs.store(wh.WEEK, "kcb_weekly", wh.fake_pdf(wh.kcb_weekly_text()), "weekly.pdf", eq_root)
    inputs.store(wh.WEEK, "kcb_daily", wh.fake_pdf(wh.kcb_daily_text(wh.WEEK.ending, turnover=500_000_000)), "fri.pdf", eq_root)
    review = eq.build(eq_root)
    by = {b["id"]: b for b in review.section["blocks"]}
    assert not any("holiday" in w for w in review.section["warnings"])
    assert by["turnover"]["notes"][0] == "Each day's equities turnover in KES is divided by that day's CBK rate; Monday to Friday."
    assert {f["label"] for f in by["banking"]["figures"]} >= {"Banking Sector index, Friday", "Banking Sector index, previous Friday"}
    assert [c["label"] for c in by["universe_of_coverage"]["columns"][1:3]] == ["Price as at 25/09/2026", "Price as at 02/10/2026"]


# ---------------------------------------------------------------------------
# Fixed Income, through every reader
# ---------------------------------------------------------------------------

def fixed_income_review(friday, root):
    return fiw.build_fixed_income_review(friday, inputs=inputs.WeeklyInputs(Week(friday), root), draft=wh.no_draft,
                                         fetchers=fi.fetchers(usd_rates=lambda: rates_for(), tbonds=lambda a, b: {"auctions": []}))


@pytest.mark.parametrize("week, note, last, shilling_note", [
    (XMAS, CHRISTMAS_NOTE, "24-Dec-26", "Friday to Thursday: 2026-12-18 to 2026-12-24."),
    (NEW_YEAR, NEW_YEAR_NOTE, "31-Dec-26", "Thursday to Thursday: 2026-12-24 to 2026-12-31.")])
def test_every_fixed_income_reader_uses_the_as_at_day_in_a_holiday_week(tmp_path, week, note, last, shilling_note):
    inputs.store(week, "fi_workbook", wh.fi_workbook_bytes(week), "FI.xlsx", tmp_path)
    review = fixed_income_review(week.ending, tmp_path)
    by = {b["id"]: b for b in review.section["blocks"]}
    assert review.section["warnings"][0] == note
    shilling = by["shilling"]
    assert shilling["kind"] == "computed" and shilling["notes"] == [shilling_note]       # the shilling's own days, not the Fridays
    assert {f["key"]: f["inputs"]["friday"]["value"] for f in shilling["figures"] if f["key"] == "rate"}["rate"] == rates_for()[week.as_at]
    assert {f["key"] for f in shilling["figures"]} >= {"week_bps", "ytd_bps"}               # the year is the as-at day's year
    assert by["money_market"]["kind"] == "computed" and by["mmf_table"]["kind"] == "table"   # the fund table is dated the as-at day
    labels = [r["label"] for r in by["eurobonds_table"]["rows"]]
    assert labels[-4] == last and labels[-3:] == ["Weekly Change", "MTD Change", "YTD Change"]
    assert "25-Dec-26" not in labels and "01-Jan-27" not in labels                           # no row for a closed day


def test_a_normal_fixed_income_week_still_says_friday_to_friday(tmp_path):
    inputs.store(wh.WEEK, "fi_workbook", wh.fi_workbook_bytes(), "FI.xlsx", tmp_path)
    by = {b["id"]: b for b in fi.build(tmp_path).section["blocks"]}
    assert by["shilling"]["notes"] == ["Friday to Friday: 2026-09-25 to 2026-10-02."]


def test_the_bulletin_is_asked_for_by_the_friday_then_the_as_at_day():
    asked = []

    def fetch(day):
        asked.append(day)
        if day != date(2026, 12, 24):
            raise LookupError("not listed")
        return b"pdf", "url"

    assert fiw.fetch_week_bulletin(fetch, XMAS) == (b"pdf", "url") and asked == [date(2026, 12, 25), date(2026, 12, 24)]
    asked.clear()
    with pytest.raises(LookupError):
        fiw.fetch_week_bulletin(lambda d: (_ for _ in ()).throw(LookupError("no")), NORMAL)


# ---------------------------------------------------------------------------
# Digital Payments and Real Estate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("friday, as_at", [("2026-12-25", "2026-12-24"), ("2027-01-01", "2026-12-31")])
def test_the_digital_payments_table_is_fetched_as_at_the_last_trading_day(monkeypatch, tmp_path, friday, as_at):
    seen = {}
    from cytonn_weekly.digital_payments import review_run

    monkeypatch.setattr(review_run, "build_digital_payments_review", lambda **kw: seen.update(kw))
    ctx = report_sections.DraftContext(week_ending=date.fromisoformat(friday), inputs_root=tmp_path)
    report_sections.spec_for("weekly", "digital_payments").build(ctx)
    assert seen == {"today": date.fromisoformat(friday), "as_at": date.fromisoformat(as_at)}   # the news window still ends on the Friday


def test_a_normal_week_calls_the_digital_payments_builder_as_before(monkeypatch, tmp_path):
    seen = {}
    from cytonn_weekly.digital_payments import review_run

    monkeypatch.setattr(review_run, "build_digital_payments_review", lambda **kw: seen.update(kw))
    report_sections.spec_for("weekly", "digital_payments").build(report_sections.DraftContext(week_ending=NORMAL.ending, inputs_root=tmp_path))
    assert seen == {"today": NORMAL.ending}


def test_the_digital_payments_table_year_is_the_as_at_days_year():
    from datetime import datetime
    from cytonn_weekly.digital_payments import review_run
    from tests import review_helpers as rh

    asked = []
    review_run.build_digital_payments_review(provider=rh.FakeProvider(), today=date(2027, 1, 1), as_at=date(2026, 12, 31),
                                             fetch_table=lambda day: asked.append(day) or rh.ROWS)
    assert asked == [date(2026, 12, 31)]


def test_real_estate_walks_back_from_a_holiday_friday_to_the_summary_it_was_published_on():
    files = {reit.ibuka_url(date(2026, 12, 24)): re_tests.IBUKA_PDF, reit.ibuka_url(date(2026, 12, 18)): re_tests.IBUKA_PDF,
             reit.ibuka_url(date(2025, 12, 31)): re_tests.IBUKA_PDF}
    out = reit.fetch_reits(date(2026, 12, 25), get=re_tests._getter(files))
    assert out["as_of"] == "2026-09-25" and out["warnings"] == []     # the fixture's own page says 25 Sept; the files found are the 24th and the 18th
    assert out["source_url"].endswith("24-12-2026.pdf") and out["prior_url"].endswith("18-12-2026.pdf")
