"""The net borrowing part of the weekly analyst inputs form: the fiscal year's start and the switch auctions.

CBK's results are the captured value file of test_net_borrowing.py (public figures); what is
typed is synthetic, except the two amounts of the 26 August 2026 switch, which are the
published difference the form exists to settle (CBK printed 21,816.46; the 594.8 the Q3'2026
review printed needs 22,510.90).
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly.checkers.digital_payments import SOURCES_DISAGREE
from cytonn_weekly.fixed_income import net_borrowing as nb
from cytonn_weekly.weekly import analyst, inputs
from cytonn_weekly.weekly.inputs import InputError
from cytonn_weekly.weekly.week import Week
from tests import weekly_helpers as wh
from tests.test_net_borrowing import RELEASES, captured_releases
from tests.test_weekly_fixed_income import blocks, build, fetchers, figures

WEEK = wh.WEEK
NEXT = Week(date(2026, 10, 9))
SWITCHES = "borrowing_switches"
FOUND = [{"date": "2026-07-15", "amount": "7954.71"}, {"date": "2026-08-26", "amount": "21816.46"},
         {"date": "2026-09-09", "amount": "11020.44"}, {"date": "2026-10-07", "amount": "8963.83"}]


@pytest.fixture
def root(tmp_path):
    """A weekly inputs folder of its own, so the CBK results kept beside it are this test's alone."""
    return tmp_path / "data" / "weekly"


def read_cbk(root, week=WEEK):
    fetched = captured_releases(date(2026, 7, 1), week.value_date_window[1], None)
    nb.write_snapshot(analyst.results_dir(root), fetched)


def save(root, fields=None, tables=None, week=WEEK):
    return analyst.save_form(week, {"fields": fields or {}, "tables": tables or {}}, root)


def refused(root, fields=None, tables=None, week=WEEK) -> str:
    with pytest.raises(InputError) as exc:
        save(root, fields, tables, week)
    return str(exc.value)


def item(key, root, week=WEEK):
    return next(i for g in analyst.status(week, root, "fixed_income")["groups"] for i in g["items"] if i["key"] == key)


def cbk_build(root, week=WEEK):
    return build(root, fetchers=fetchers(releases=captured_releases)) if week == WEEK else None


def target(root, week=WEEK):
    save(root, {"borrowing_target": "919.36"}, week=week)


# ---------------------------------------------------------------------------
# What the form holds
# ---------------------------------------------------------------------------

def test_the_borrowing_group_asks_for_the_target_the_start_and_the_switches(root):
    group = next(g for g in analyst.status(WEEK, root, "fixed_income")["groups"] if g["key"] == "borrowing")
    assert [i["key"] for i in group["items"]] == ["borrowing_target", "fiscal_year_start", SWITCHES, "borrowing_log"]
    start = item("fiscal_year_start", root)
    assert (start["kind"], start["value"], start["default"]) == ("date", None, "2026-07-01") and "1 July is used" in start["help"]
    assert item("borrowing_target", root)["default"] is None
    switches = item(SWITCHES, root)
    assert switches["mode"] == "switches" and [c["key"] for c in switches["columns"]] == ["date", "count", "amount"]
    assert switches["found"] is None and "have not been read on this machine yet" in switches["found_note"]
    log = item("borrowing_log", root)
    assert log["help"].startswith("Optional. Leave this empty") and "the log is built from CBK's auction results" in log["help"]


def test_the_switch_auctions_listed_are_the_ones_cbks_results_hold(root):
    read_cbk(root)
    switches = item(SWITCHES, root)
    assert [{k: s[k] for k in ("date", "amount")} for s in switches["found"]] == FOUND
    assert switches["found"][1]["file"].endswith("DATED 26-08-2026 Final.pdf") and switches["rows"] is None
    assert switches["found_note"] == ("CBK's results as last read, up to 2026-10-09. 4 switch auctions since the fiscal year began.")
    # a later week than the results cover: said, and only what is known is listed
    later = item(SWITCHES, root, NEXT)
    assert len(later["found"]) == 4 and "which does not cover this week: read them again" in later["found_note"]
    # an earlier week lists only the switches settled by then
    assert [s["date"] for s in item(SWITCHES, root, Week(date(2026, 9, 4)))["found"]] == ["2026-07-15", "2026-08-26", "2026-09-09"]


def test_a_switch_is_chosen_by_ticking_it_and_an_amount_needs_the_tick(root):
    read_cbk(root)
    save(root, tables={SWITCHES: {"rows": [{"date": "2026-08-26", "count": "yes", "amount": "22,510.90"},
                                           {"date": "2026-07-15", "count": "no"}, {"date": "2026-09-09"}]}})
    assert analyst.read_form(WEEK, root)["tables"][SWITCHES] == [{"date": "2026-08-26", "count": "yes", "amount": "22510.90"}]
    shown = item(SWITCHES, root)
    assert shown["rows"] == [{"date": "2026-08-26", "count": "yes", "amount": "22510.90"}]
    assert shown["warnings"] == ["The switch auction of 2026-08-26 counts at the typed 22510.90 instead of CBK's printed amount; "
                                 "the reviewer is shown both."]
    assert "an amount is typed for the switch auction of 2026-07-15 but it is not ticked" in refused(
        root, tables={SWITCHES: {"rows": [{"date": "2026-07-15", "amount": "8000"}]}})
    assert "CBK's results list no switch auction with value date 2026-08-27 (they list 2026-07-15, 2026-08-26" in refused(
        root, tables={SWITCHES: {"rows": [{"date": "2026-08-27", "count": "yes"}]}})
    assert "is outside the expected range, 0.01 to 2000000 Kshs mn" in refused(
        root, tables={SWITCHES: {"rows": [{"date": "2026-08-26", "count": "yes", "amount": "0"}]}})
    assert "2026-08-26 appears twice" in refused(
        root, tables={SWITCHES: {"rows": [{"date": "2026-08-26", "count": "yes"}, {"date": "2026-08-26", "count": "yes"}]}})
    assert "'maybe' is not yes or no" in refused(root, tables={SWITCHES: {"rows": [{"date": "2026-08-26", "count": "maybe"}]}})
    assert "this table is typed cell by cell" in refused(root, tables={SWITCHES: {"text": "2026-08-26 yes"}})
    assert analyst.read_form(WEEK, root)["tables"][SWITCHES][0]["amount"] == "22510.90"      # a refusal stores nothing
    save(root, tables={SWITCHES: None})
    assert SWITCHES not in analyst.read_form(WEEK, root)["tables"]


def test_the_fiscal_years_start_is_a_date_in_the_year_before_the_week(root):
    assert analyst.Analyst(inputs.WeeklyInputs(WEEK, root)).borrowing()["fy_start"].day == date(2026, 7, 1)     # the default
    save(root, {"fiscal_year_start": "6 July 2026"})
    data = analyst.Analyst(inputs.WeeklyInputs(WEEK, root)).borrowing()
    assert data["fy_start"].day == date(2026, 7, 6) and data["fy_start_typed"] is True
    assert "2026-10-04 is not within the year before 2026-10-03" in refused(root, {"fiscal_year_start": "2026-10-04"})
    assert "2025-07-01 is not within the year before 2026-10-03" in refused(root, {"fiscal_year_start": "2025-07-01"})
    save(root, {"fiscal_year_start": ""})
    data = analyst.Analyst(inputs.WeeklyInputs(WEEK, root)).borrowing()
    assert data["fy_start"].day == date(2026, 7, 1) and data["fy_start_typed"] is False


def test_an_uploaded_workbooks_start_is_shown_and_a_typed_one_that_differs_is_said(root):
    inputs.store(WEEK, "fi_workbook", wh.fi_workbook_bytes(), "FI.xlsx", root)
    start = item("fiscal_year_start", root)
    assert start["workbook"]["value"] == "2026-07-01" and start["workbook"]["ref"].startswith("'Government Borrowing'!")
    save(root, {"fiscal_year_start": "2026-07-02"})
    assert item("fiscal_year_start", root)["differences"] == [
        "Fiscal year starts on: typed as 2026-07-02, but the uploaded fixed income workbook has 2026-07-01 "
        f"({start['workbook']['ref']}). The typed value is used."]


# ---------------------------------------------------------------------------
# What a draft makes of it
# ---------------------------------------------------------------------------

def test_a_ticked_switch_counts_at_cbks_amount_and_is_no_longer_listed_as_not_counted(root):
    target(root)
    read_cbk(root)
    save(root, tables={SWITCHES: {"rows": [{"date": "2026-08-26", "count": "yes"}]}})
    review = cbk_build(root)
    b = blocks(review)["borrowing"]
    assert b["body_md"] == ("The government is at 245.0% of its pro-rated net domestic borrowing target of Kshs 242.5 bn, with a "
                            "net borrowing position of Kshs 594.1 bn (inclusive of T-bills).")
    net = next(i for i in review.review_items if "Net domestic borrowing (Kshs bn)" in i.ref)
    assert net.status == "clean" and "and the switch of 26-08-2026 (Kshs 21,816.46 mn) chosen by the analysts" in net.context["note"]
    left = next(i for i in review.review_items if "Switch auctions found, not counted" in i.ref)
    assert "26-08-2026" not in left.ref and "15-07-2026 (Kshs 7,954.71 mn), 09-09-2026" in left.ref
    row = next(r for r in blocks(review)["borrowing_log"]["rows"] if r["key"] == "2026-08-26 T-bond switch")
    assert (row["accepted_kes_m"], row["net_kes_m"], row["counted"]) == ("21,816.46", "21,816.46", "Yes")


def test_a_typed_amount_for_a_switch_is_an_analyst_input_flagged_against_cbks(root):
    target(root)
    read_cbk(root)
    save(root, tables={SWITCHES: {"rows": [{"date": "2026-08-26", "count": "yes", "amount": "22510.90"}]}})
    review = cbk_build(root)
    b = blocks(review)["borrowing"]
    assert (figures(b)["net_borrowing"], figures(b)["ratio"]) == ("594.8", "245.3%")      # as the Q3'2026 review printed
    net = next(i for i in review.review_items if "Net domestic borrowing (Kshs bn)" in i.ref)
    assert net.status == "flagged" and [f.kind for f in net.detail] == [SOURCES_DISAGREE]
    assert ("is 22510.9 in analyst input typed on the weekly form (switch auction of 2026-08-26: amount to use instead of CBK's; "
            "source: the fixed income team's own figure) but 21816.46 in CBK Treasury bond switch auction results, value date "
            "2026-08-26") in net.detail[0].message
    row = next(i for i in review.review_items if i.ref == "Net domestic borrowing log: 2026-08-26 T-bond switch")
    assert row.status == "flagged" and {s["value"] for s in row.detail[0].sources} == {22510.9, 21816.46}
    assert [s["name"] for s in b["sources"]] == ["CBK Treasury bill and bond auction results", "Weekly analyst inputs"]


def test_a_typed_start_moves_the_log_and_the_pro_rating_and_is_said_on_the_figure(root):
    target(root)
    save(root, {"fiscal_year_start": "2026-07-07"})                 # a day after the year's first T-bill settled
    review = cbk_build(root)
    b = blocks(review)["borrowing"]
    # 572.296 less the 6 July auction's 3.310 net; 90 days of 364
    assert (figures(b)["net_borrowing"], figures(b)["prorated_target"]) == ("569.0", "227.3")
    prorated = next(f for f in b["figures"] if f["key"] == "prorated_target")
    assert prorated["note"] == ("90 days from 2026-07-07 to the latest auction's value date, 2026-10-05, over a 364-day year. The "
                                "fiscal year's start, 2026-07-07, is an analyst input typed on the weekly form (Fiscal year "
                                "starts on; source: National Treasury (Kenya's fiscal year)).")
    assert len(blocks(review)["borrowing_log"]["rows"]) == 23


def test_a_ticked_switch_cbk_does_not_list_counts_for_nothing_and_is_said(root):
    target(root)
    save(root, tables={SWITCHES: {"rows": [{"date": "2026-08-27", "count": "yes"}]}})     # saved before CBK's results were read
    review = cbk_build(root)
    assert figures(blocks(review)["borrowing"])["net_borrowing"] == "572.3"
    assert any("the switch auction of 2026-08-27 is ticked under \"Weekly analyst inputs\", but CBK's results list no switch "
               "auction with that value date" in w for w in review.section["warnings"])
    # the draft read CBK's results, so the form now lists what was found
    assert [s["date"] for s in item(SWITCHES, root)["found"]] == [s["date"] for s in FOUND]


# ---------------------------------------------------------------------------
# Carrying forward, and the API
# ---------------------------------------------------------------------------

def test_the_start_and_the_switch_choices_carry_forward_and_are_used_at_once(root):
    read_cbk(root)
    save(root, {"fiscal_year_start": "2026-07-01", "borrowing_target": "919.36"},
         {SWITCHES: {"rows": [{"date": "2026-08-26", "count": "yes", "amount": "22510.90"}]}})
    out = analyst.carry_forward(NEXT, root)
    assert {"fiscal_year_start", SWITCHES, "borrowing_target"} <= set(out["carried"])
    assert out["unconfirmed"] == ["borrowing_target"]                  # the target is confirmed each week; the rest is used
    data = analyst.Analyst(inputs.WeeklyInputs(NEXT, root)).borrowing()
    assert data["fy_start_typed"] is True and list(data["switches"]) == ["2026-08-26"]
    assert data["switches"]["2026-08-26"]["override"].number == 22510.90
    carried = item(SWITCHES, root, NEXT)
    assert carried["carried"]["from"] == "2026-10-02" and carried["needs_confirmation"] is False
    # a new fiscal year starts with no switch chosen and with its own 1 July
    june, july = Week(date(2027, 6, 25)), Week(date(2027, 7, 2))        # the last week of one fiscal year, the first of the next
    analyst.save_form(june, {"fields": {"fiscal_year_start": "2026-07-01", "large_caps": "Safaricom"}, "tables": {
        SWITCHES: {"rows": [{"date": "2026-08-26", "count": "yes"}]}}}, root)
    out = analyst.carry_forward(july, root)
    assert out["carried"] == ["large_caps"]
    assert analyst.Analyst(inputs.WeeklyInputs(july, root)).borrowing()["fy_start"].day == date(2027, 7, 1)


def test_the_form_reads_cbks_results_through_the_api(tmp_path):
    seen = {}

    def fetch(start, end, folder):
        seen.update(start=start, end=end, folder=folder)
        return captured_releases(start, end, folder)

    root = tmp_path / "data" / "weekly"
    client = TestClient(create_app(db_path=tmp_path / "app.db", load_dotenv=False, inputs_root=root, fetch_releases=fetch))
    url = "/api/inputs/weekly/2026-10-02/analyst"
    form = client.get(url, params={"section": "fixed_income"}).json()
    switches = next(i for g in form["groups"] for i in g["items"] if i["key"] == SWITCHES)
    assert switches["found"] is None
    found = client.post(f"{url}/switches/find", params={"section": "fixed_income"})
    assert found.status_code == 200
    switches = next(i for g in found.json()["groups"] for i in g["items"] if i["key"] == SWITCHES)
    assert [s["date"] for s in switches["found"]] == [s["date"] for s in FOUND] and switches["rows"] is None   # nothing is ticked
    assert (seen["start"], seen["end"], seen["folder"]) == (date(2026, 7, 1), date(2026, 10, 9), root.parent / "cbk_results")
    saved = client.put(url, params={"section": "fixed_income"}, json={"tables": {SWITCHES: {"rows": [
        {"date": "2026-08-26", "count": "yes", "amount": "22510.90"}]}}})
    assert saved.status_code == 200
    refusal = client.put(url, params={"section": "fixed_income"}, json={"tables": {SWITCHES: {"rows": [
        {"date": "2026-08-26", "amount": "22510.90"}]}}})
    assert refusal.status_code == 422 and "it is not ticked" in refusal.json()["detail"]
    assert client.post("/api/inputs/weekly/2026-10-03/analyst/switches/find").status_code == 422           # not a Friday


def test_a_cbk_that_does_not_answer_is_a_502_and_changes_nothing(tmp_path):
    def down(start, end, folder):
        raise ConnectionError("no route to host")

    root = tmp_path / "data" / "weekly"
    client = TestClient(create_app(db_path=tmp_path / "app.db", load_dotenv=False, inputs_root=root, fetch_releases=down))
    answer = client.post("/api/inputs/weekly/2026-10-02/analyst/switches/find")
    assert answer.status_code == 502 and answer.json()["detail"].startswith("CBK's auction results could not be read: ")
    assert "ConnectionError" in answer.json()["detail"] and nb.read_snapshot(root.parent / "cbk_results") is None
