"""The net borrowing part of the weekly analyst inputs form: the full-year target and the fiscal year's start.

CBK's results are the captured value file of test_net_borrowing.py (public figures); what is
typed is synthetic.  Switch auctions are not on the form: by the investments team's rule
(settled 2026-10-12) they are not new debt and never count, so there is nothing to choose.
"""

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly.weekly import analyst, inputs
from cytonn_weekly.weekly.inputs import InputError
from cytonn_weekly.weekly.week import Week
from tests import weekly_helpers as wh
from tests.test_net_borrowing import captured_releases
from tests.test_weekly_fixed_income import blocks, build, fetchers, figures

WEEK = wh.WEEK
NEXT = Week(date(2026, 10, 9))
SWITCHES = "borrowing_switches"    # the table the form held until the rule was settled


@pytest.fixture
def root(tmp_path):
    """A weekly inputs folder of its own, so the CBK results kept beside it are this test's alone."""
    return tmp_path / "data" / "weekly"


def save(root, fields=None, tables=None, week=WEEK):
    return analyst.save_form(week, {"fields": fields or {}, "tables": tables or {}}, root)


def refused(root, fields=None, tables=None, week=WEEK) -> str:
    with pytest.raises(InputError) as exc:
        save(root, fields, tables, week)
    return str(exc.value)


def item(key, root, week=WEEK):
    return next(i for g in analyst.status(week, root, "fixed_income")["groups"] for i in g["items"] if i["key"] == key)


def cbk_build(root):
    return build(root, fetchers=fetchers(releases=captured_releases))


def target(root, week=WEEK):
    save(root, {"borrowing_target": "919.36"}, week=week)


# ---------------------------------------------------------------------------
# What the form holds
# ---------------------------------------------------------------------------

def test_the_borrowing_group_asks_for_the_target_and_the_start_and_no_switch(root):
    group = next(g for g in analyst.status(WEEK, root, "fixed_income")["groups"] if g["key"] == "borrowing")
    assert [i["key"] for i in group["items"]] == ["borrowing_target", "fiscal_year_start", "borrowing_log",
                                                  "borrowing_redemptions"]
    start = item("fiscal_year_start", root)
    assert (start["kind"], start["value"], start["default"]) == ("date", None, "2026-07-01") and "1 July is used" in start["help"]
    assert item("borrowing_target", root)["default"] is None
    log = item("borrowing_log", root)
    assert log["help"].startswith("Optional. Leave this empty") and "the log is built from CBK's auction results" in log["help"]
    # nothing on the whole form offers a switch to count, an amount for one, or a list of the ones found
    whole = json.dumps(analyst.status(WEEK, root))
    assert SWITCHES not in analyst.TABLES and "switch" not in whole.lower() and '"found"' not in whole
    assert {t["mode"] for g in analyst.status(WEEK, root)["groups"] for t in g["items"] if t["type"] == "table"} == {"paste", "grid"}


def test_a_switch_choice_cannot_be_saved_and_one_saved_before_the_rule_is_ignored(root):
    assert "borrowing_switches" in refused(root, tables={SWITCHES: {"rows": [{"date": "2026-08-26", "count": "yes",
                                                                              "amount": "22510.90"}]}})
    target(root)
    path = inputs.week_dir(WEEK, root) / analyst.FILE
    held = json.loads(path.read_text(encoding="utf-8"))
    held["tables"][SWITCHES] = [{"date": "2026-08-26", "count": "yes", "amount": "22510.90"}]      # as an older build stored it
    path.write_text(json.dumps(held), encoding="utf-8")
    assert SWITCHES not in analyst.read_form(WEEK, root)["tables"]
    assert "switches" not in analyst.Analyst(inputs.WeeklyInputs(WEEK, root)).borrowing()
    review = cbk_build(root)
    b = blocks(review)["borrowing"]
    assert (figures(b)["net_borrowing"], figures(b)["ratio"]) == ("572.3", "236.0%")       # not the 594.8 a counted switch gave
    row = next(r for r in blocks(review)["borrowing_log"]["rows"] if r["key"] == "2026-08-26 T-bond switch")
    assert (row["accepted_kes_m"], row["net_kes_m"], row["counted"]) == ("21,816.46", "-", "No")


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


# ---------------------------------------------------------------------------
# Carrying forward, and the API
# ---------------------------------------------------------------------------

def test_the_start_carries_forward_and_is_used_at_once_and_the_target_waits_to_be_confirmed(root):
    save(root, {"fiscal_year_start": "2026-07-01", "borrowing_target": "919.36"})
    out = analyst.carry_forward(NEXT, root)
    assert set(out["carried"]) == {"fiscal_year_start", "borrowing_target"}
    assert out["unconfirmed"] == ["borrowing_target"]                  # the target is confirmed each week; the start is used
    data = analyst.Analyst(inputs.WeeklyInputs(NEXT, root)).borrowing()
    assert data["fy_start_typed"] is True and data["fy_start"].day == date(2026, 7, 1) and data["target_bn"] is None
    assert item("fiscal_year_start", root, NEXT)["carried"]["from"] == "2026-10-02"
    # a new fiscal year starts with its own 1 July
    june, july = Week(date(2027, 6, 25)), Week(date(2027, 7, 2))        # the last week of one fiscal year, the first of the next
    analyst.save_form(june, {"fields": {"fiscal_year_start": "2026-07-01", "large_caps": "Safaricom"}}, root)
    out = analyst.carry_forward(july, root)
    assert out["carried"] == ["large_caps"]
    assert analyst.Analyst(inputs.WeeklyInputs(july, root)).borrowing()["fy_start"].day == date(2027, 7, 1)


def test_the_api_serves_no_switch_table_and_no_route_to_look_for_switches(tmp_path):
    root = tmp_path / "data" / "weekly"
    client = TestClient(create_app(db_path=tmp_path / "app.db", load_dotenv=False, inputs_root=root))
    url = "/api/inputs/weekly/2026-10-02/analyst"
    form = client.get(url, params={"section": "fixed_income"}).json()
    keys = [i["key"] for g in form["groups"] for i in g["items"]]
    assert "fiscal_year_start" in keys and "borrowing_target" in keys and SWITCHES not in keys
    assert client.post(f"{url}/switches/find", params={"section": "fixed_income"}).status_code in (404, 405)
    refusal = client.put(url, params={"section": "fixed_income"}, json={"tables": {SWITCHES: {"rows": [
        {"date": "2026-08-26", "count": "yes", "amount": "22510.90"}]}}})
    assert refusal.status_code == 422
    saved = client.put(url, params={"section": "fixed_income"}, json={"fields": {"fiscal_year_start": "2026-07-01"}})
    assert saved.status_code == 200
    with pytest.raises(TypeError):                                     # the fetch the removed route used is no longer injected
        create_app(db_path=tmp_path / "app.db", load_dotenv=False, inputs_root=root, fetch_releases=captured_releases)
