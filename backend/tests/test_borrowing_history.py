from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly import db
from cytonn_weekly.fixed_income import net_borrowing as nb
from cytonn_weekly.fixed_income import weekly as fiw
from cytonn_weekly.history import weekly as history_weekly
from cytonn_weekly.weekly import analyst, inputs
from cytonn_weekly.weekly.inputs import InputError
from cytonn_weekly.weekly.week import Week
from tests import weekly_helpers as wh
from tests.test_bond_redemptions import MATURITIES, NEXT, TABLE, WEEK, item, next_releases
from tests.test_net_borrowing import FY, RELEASES
from tests.test_weekly_fixed_income import blocks, fetchers, figures, items

# Every bond, day, amount, source and name below is invented.
BOND, DAY = "TEST1/2026/01", "2026-10-06"
LINE = f"{DAY}  {BOND}  2000.00  Made-up sheet  Tester  2026-10-02"
MATURITY = {"date": "2026-10-13", "bond": "TEST9/2016/10", "face_kes_m": 100.0, "issues": 1}


@pytest.fixture
def root(tmp_path):
    return tmp_path / "data" / "weekly"


def type_on(root, week, text):
    analyst.save_form(week, {"tables": {TABLE: {"text": text}}}, root)


def draft(root, week=NEXT, extra_maturities=(), target=True):
    if target:
        analyst.save_form(week, {"fields": {"borrowing_target": "900"}}, root)

    def releases(start, end, folder):
        return {**next_releases(start, end, folder), "maturities": MATURITIES + list(extra_maturities)}

    return fiw.build_fixed_income_review(week.ending, inputs=inputs.WeeklyInputs(week, root), draft=wh.no_draft,
                                         fetchers=fetchers(releases=releases, tbonds=lambda start, end: {"auctions": []}))


def net(review):
    return Decimal(figures(blocks(review)["borrowing"])["net_borrowing"].replace(",", ""))


def log_row(review, label, day=DAY, bond=BOND):
    ref = f"Net domestic borrowing log: {day} {bond} redemption ({label})"
    return next((i for i in items(review, "Net domestic borrowing log:") if i.ref == ref), None)


def net_item(review):
    return next(i for i in review.review_items if "Net domestic borrowing (Kshs bn)" in i.ref)


def test_a_redemption_typed_once_counts_in_a_later_week_by_exactly_its_amount(root):
    before = net(draft(root))
    type_on(root, WEEK, LINE)                       # typed for the week before; nothing is typed on this week's form
    review = draft(root)
    assert before - net(review) == Decimal("2.0")
    [source_row] = [r for r in blocks(review)["borrowing_log"]["source_rows"] if r["key"] == f"{DAY} {BOND} redemption ({nb.STORED_LABEL})"]
    assert source_row["net_kes_m"] == -2000.0 and source_row["kind"] == nb.STORED_KIND
    row = log_row(review, nb.STORED_LABEL)
    assert row.status == "not_auto_verified"
    assert row.detail.startswith(f"{nb.STORED_LABEL}: Made-up sheet; confirmed by Tester on 2026-10-02")
    assert log_row(review, nb.TYPED_LABEL) is None
    assert net_item(review).status != "clean"           # an analyst input is in it (the fixture's own 12 Oct maturity also flags it)
    assert net_item(review).context["note"].endswith(f"Less 1 bond redemption typed in an earlier week of the fiscal year ({nb.STORED_LABEL}).")


def test_a_redemption_typed_again_this_week_keeps_its_own_label_and_counts_once(root):
    before = net(draft(root))
    type_on(root, WEEK, LINE)
    type_on(root, NEXT, LINE)
    review = draft(root)
    assert before - net(review) == Decimal("2.0")
    row = log_row(review, nb.TYPED_LABEL)
    assert row.status == "not_auto_verified" and row.detail.startswith(f"{nb.TYPED_LABEL}: analyst input typed on the weekly form")
    assert log_row(review, nb.STORED_LABEL) is None


def test_a_retired_redemption_no_longer_counts_and_its_row_is_kept(root):
    before = net(draft(root))
    type_on(root, WEEK, LINE)
    [kept] = item(root)["stored_rows"]
    assert (kept["date"], kept["bond"], kept["kes_m"], kept["confirmed_by"]) == (DAY, BOND, 2000.0, "Tester")
    with pytest.raises(InputError):
        history_weekly.retire_redemption(NEXT, kept["point_id"], "   ", root)
    assert history_weekly.retire_redemption(NEXT, kept["point_id"], "typed in error", root) == {"date": DAY, "bond": BOND}
    review = draft(root)
    assert net(review) == before and log_row(review, nb.STORED_LABEL) is None
    assert item(root)["stored_rows"] is None
    with pytest.raises(InputError):
        history_weekly.retire_redemption(NEXT, kept["point_id"], "again", root)
    conn = db.open_db(None)
    try:
        held = conn.execute("SELECT retired_at, retired_reason FROM series_points WHERE point_id = ?", (kept["point_id"],)).fetchone()
    finally:
        conn.close()
    assert held["retired_at"] and held["retired_reason"] == "typed in error"        # retired, not deleted
    type_on(root, NEXT, LINE)                                                         # typed again: it counts again
    assert [s["bond"] for s in item(root)["stored_rows"]] == [BOND]


def test_the_form_retires_a_stored_redemption_through_the_api(root):
    type_on(root, WEEK, LINE)
    [kept] = item(root)["stored_rows"]
    client = TestClient(create_app(load_dotenv=False, inputs_root=root))
    url, section = "/api/inputs/weekly/2026-10-09/analyst", {"section": "fixed_income"}
    bad = client.put(url, params=section, json={"retire": [{"point_id": kept["point_id"], "reason": ""}]})
    assert bad.status_code == 422
    ok = client.put(url, params=section, json={"retire": [{"point_id": kept["point_id"], "reason": "typed in error"}]})
    assert ok.status_code == 200
    assert next(i for g in ok.json()["groups"] for i in g["items"] if i["key"] == TABLE)["stored_rows"] is None


def test_a_row_taken_off_or_re_dated_on_its_own_weeks_form_stops_counting_at_the_old_date(root):
    type_on(root, WEEK, LINE)
    type_on(root, WEEK, LINE.replace(DAY, "2026-10-07"))
    assert [s["date"] for s in item(root)["stored_rows"]] == ["2026-10-07"]
    type_on(root, WEEK, "")
    assert item(root)["stored_rows"] is None


def test_a_stored_redemption_answers_the_maturity_question_and_none_leaves_it_asked(root):
    ref = f"Net domestic borrowing log: {MATURITY['date']} {MATURITY['bond']} maturity"
    asked = [i for i in items(draft(root, extra_maturities=[MATURITY]), "Net domestic borrowing log:") if i.ref == ref]
    assert [i.status for i in asked] == ["flagged"]
    type_on(root, WEEK, f"{MATURITY['date']}  {MATURITY['bond']}  100.00  Made-up sheet  Tester  2026-10-02")
    review = draft(root, extra_maturities=[MATURITY])
    assert not any(i.ref == ref for i in items(review, "Net domestic borrowing log:"))
    assert log_row(review, nb.STORED_LABEL, MATURITY["date"], MATURITY["bond"]) is not None


def test_with_the_constant_off_a_workbook_log_is_never_set_beside_cbks(monkeypatch):
    class Cell:
        def __init__(self, number):
            self.number, self.source, self.ref = number, "a made-up workbook log", "ref"

    theirs = [{"date": date(2026, 7, 6), "accepted": Cell(1.0), "redemptions": Cell(-1.0)}]
    limit = WEEK.value_date_window[1]
    assert nb.WORKBOOK_BORROWING is False
    off, plain = nb.build_log(RELEASES, FY, limit, workbook_log=theirs), nb.build_log(RELEASES, FY, limit)
    assert off.workbook_net_kes_m is None and off.workbook_difference() is None
    assert (off.rows, off.second_sources, off.warnings, off.flags) == (plain.rows, plain.second_sources, plain.warnings, plain.flags)
    monkeypatch.setattr(nb, "WORKBOOK_BORROWING", True)                                 # the switch is what turns it on
    assert nb.build_log(RELEASES, FY, limit, workbook_log=theirs).workbook_net_kes_m is not None


def test_with_the_constant_off_an_uploaded_workbook_changes_nothing_in_the_borrowing_item(root):
    without = draft(root, WEEK)
    inputs.store(WEEK, "fi_workbook", wh.fi_workbook_bytes(), "FI.xlsx", root)
    with_book = draft(root, WEEK)
    for key in ("borrowing", "borrowing_log"):
        assert blocks(with_book)[key] == blocks(without)[key]
    assert [(i.ref, i.status, i.detail) for i in items(with_book, "Net domestic borrowing")] == \
        [(i.ref, i.status, i.detail) for i in items(without, "Net domestic borrowing")]
    assert not any(w.startswith("Net domestic borrowing") and "workbook" in w for w in with_book.section["warnings"])


def test_a_missing_target_points_at_the_form_not_at_a_workbook(root):
    inputs.store(WEEK, "fi_workbook", wh.fi_workbook_bytes(), "FI.xlsx", root)
    b = blocks(draft(root, WEEK, target=False))["borrowing"]
    assert b["kind"] == "unavailable" and "workbook" not in b["reason"] and f'"{analyst.FORM}"' in b["reason"]
    assert b["unblock"] == f'Type it under "{analyst.FORM}" on the start screen and draft again.'


def test_last_fiscal_years_redemptions_do_not_apply_after_1_july(root):
    june, july = Week(date(2027, 6, 25)), Week(date(2027, 7, 2))
    type_on(root, june, "2027-06-28  TEST2/2027/02  750.00  Made-up sheet  Tester  2027-06-25")
    june_start = analyst.Analyst(inputs.WeeklyInputs(june, root)).borrowing()["fy_start"].day
    july_start = analyst.Analyst(inputs.WeeklyInputs(july, root)).borrowing()["fy_start"].day
    assert (june_start, july_start) == (date(2026, 7, 1), date(2027, 7, 1))
    assert [s["bond"] for s in history_weekly.stored_redemptions(june_start, june.value_date_window[1])[0]] == ["TEST2/2027/02"]
    assert history_weekly.stored_redemptions(july_start, july.value_date_window[1]) == ([], None)
    assert item(root, july)["stored_rows"] is None
