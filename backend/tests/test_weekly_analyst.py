"""The weekly analyst inputs form: figures only the analysts hold, typed when no workbook is sent.

Three things are pinned here:

* **Equivalence.**  Typing a workbook's figures on the form, with no workbook uploaded, gives the
  section the workbook gives: the same text, figures, inputs and tables.  Only what names a
  source differs.  It is checked on the synthetic workbooks (always) and on the real,
  confidential ones for the week ending 2 October 2026 (skipped when they are absent).
* **Nothing is invented.**  An item left empty is missing: the part that needs it is an
  ``unavailable`` block naming it, and every other part is still worked out.
* **A typed value is an analyst input**, never clean, and one that differs from the uploaded
  workbook is shown to the reviewer.
"""

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly.charts.specs import SPECS
from cytonn_weekly.checkers.digital_payments import SOURCES_DISAGREE
from cytonn_weekly.weekly import analyst, inputs
from cytonn_weekly.weekly.inputs import InputError
from cytonn_weekly.weekly.week import Week
from tests import test_weekly_equities as eq
from tests import test_weekly_fixed_income as fi
from tests import weekly_helpers as wh
from tests.weekly_helpers import text_pdfs  # noqa: F401 - a fixture

WEEK = wh.WEEK
FORM = "Weekly analyst inputs"

FUNDS = """Rank\tFund Manager\tEffective Annual Rate
1\tCytonn Money Market Fund\t11.00%
2\tAlpha Money Market Fund\t10.80%
3\tBeta Money Market Fund\t10.70%
4\tGamma Money Market Fund\t10.60%
5\tDelta Money Market Fund\t10.50%
6\tEpsilon Money Market Fund\t9.00%"""


def save(root, fields=None, tables=None, week=WEEK):
    return analyst.save_form(week, {"fields": fields or {}, "tables": tables or {}}, root)


def refused(root, fields=None, tables=None) -> str:
    with pytest.raises(InputError) as caught:
        save(root, fields, tables)
    return str(caught.value)


def blocks(review):
    return {b["id"]: b for b in review.section["blocks"]}


def figures(block):
    return {f["key"]: f for f in block["figures"]}


def items(review, prefix):
    return [i for i in review.review_items if i.ref.startswith(prefix)]


def item(key, root, week=WEEK):
    return next(i for g in analyst.status(week, root)["groups"] for i in g["items"] if i["key"] == key)


# ---------------------------------------------------------------------------
# The form: what it holds, and what it refuses
# ---------------------------------------------------------------------------

def test_the_form_lists_only_what_the_analysts_alone_hold_with_units_ranges_and_sources(tmp_path):
    status = analyst.status(WEEK, tmp_path)
    assert status["form"] == FORM and status["workbooks"] == {"fixed_income": False, "equities": False}
    assert [(g["section"], g["title"]) for g in status["groups"]] == [
        ("fixed_income", "Money market"), ("fixed_income", "Liquidity"), ("fixed_income", "Kenya Eurobonds"),
        ("fixed_income", "Kenya Shilling"), ("fixed_income", "Government borrowing"), ("equities", "Market performance"),
        ("equities", "Valuation"), ("equities", "Universe of Coverage")]
    keys = {i["key"] for g in status["groups"] for i in g["items"]}
    assert keys == set(analyst.FIELDS) | set(analyst.TABLES)
    # What the tool reads from CBK, KCB IB, the NSE or the previous issue is not asked for.
    assert not keys & {"tbills", "exchange_rates", "reserves", "indices", "turnover", "bidding_range", "outlook"}
    placements, pe = item("placements", tmp_path), item("pe", tmp_path)
    assert (placements["unit"], placements["min"], placements["max"], placements["source"]) == ("%", 1, 40, "Rates offered by various banks")
    assert (pe["unit"], pe["source"], pe["used_in"]) == ("x", "Bloomberg NASI P/E", "Valuation")
    assert item("mmf", tmp_path)["source"] == "Business Daily" and item("mmf", tmp_path)["mode"] == "paste"
    assert [c["key"] for c in item("universe", tmp_path)["columns"]] == [
        "company", "last_price", "price", "month_end_price", "year_open", "target", "dps", "shares_bn", "tbv_bn"]
    # Nothing derived is on the form: no Top 5 average, no upside, yield, multiple or recommendation.
    assert not keys & {"top5", "upside", "ptbv", "recommendation", "prorated_target", "peg"}
    assert [g["title"] for g in analyst.status(WEEK, tmp_path, "equities")["groups"]] == ["Market performance", "Valuation",
                                                                                         "Universe of Coverage"]


def test_a_typed_value_is_kept_per_week_and_cleared_by_an_empty_one(tmp_path):
    save(tmp_path, {"placements": " 9.0% ", "pe": "7.6x", "foreign_ytd": "(166.1)", "turnover_ytd": "3,053.1"})
    assert analyst.read_form(WEEK, tmp_path)["fields"] == {"placements": "9.0", "pe": "7.6", "foreign_ytd": "-166.1",
                                                          "turnover_ytd": "3053.1"}
    assert (tmp_path / "2026-10-02" / "analyst.json").is_file()
    assert analyst.read_form(Week(date(2026, 9, 25)), tmp_path)["fields"] == {}   # another week has its own form
    save(tmp_path, {"pe": ""})                       # a field left out is kept, an empty one is cleared
    assert analyst.read_form(WEEK, tmp_path)["fields"].keys() == {"placements", "foreign_ytd", "turnover_ytd"}
    assert item("placements", tmp_path)["value"] == "9.0" and item("pe", tmp_path)["value"] is None


def test_a_value_outside_its_range_or_not_a_number_is_refused_and_nothing_is_stored(tmp_path):
    assert refused(tmp_path, {"placements": "0.09"}) == (
        "3-month bank placements: 0.09 is outside the expected range, 1 to 40%. Type a percentage as 9.0, not 0.09.")
    assert refused(tmp_path, {"pe": "seven"}) == "Market P/E: 'seven' is not a number"
    assert "is outside the expected range, 1 to 60x" in refused(tmp_path, {"pe": "760"})
    assert refused(tmp_path, {"nope": "1"}) == "unknown field 'nope'"
    assert "9 Oct 2026 is outside this week, 28 Sep 2026 to 2 Oct 2026" in refused(tmp_path, {"mmf_published": "2026-10-09"})
    assert "is not in the month before October 2026" in refused(tmp_path, {"universe_month_end": "2026-10-01"})
    # one bad value refuses the whole save, with every reason
    message = refused(tmp_path, {"placements": "9.0", "pe": "x", "dividend_yield": "0.058"})
    assert message.splitlines()[0] == "Market P/E: 'x' is not a number" and "Market dividend yield: 0.058" in message
    assert not (tmp_path / "2026-10-02" / "analyst.json").exists()


def test_the_fund_table_is_pasted_any_number_of_rows_and_its_ranks_and_rates_are_checked(tmp_path):
    save(tmp_path, tables={"mmf": {"text": FUNDS}})
    rows = analyst.read_form(WEEK, tmp_path)["tables"]["mmf"]
    assert len(rows) == 6 and rows[0] == {"rank": "1", "fund": "Cytonn Money Market Fund", "rate": "11.00"}   # the heading is skipped
    # as a paper prints it, cut on spaces: rank, a name of several words, the rate
    spaced = "\n".join(f"{n}.  Fund {n:02d} Money Market Fund   {12 - n * 0.25:.2f} %" for n in range(1, 41))
    save(tmp_path, tables={"mmf": {"text": spaced}})
    rows = analyst.read_form(WEEK, tmp_path)["tables"]["mmf"]
    assert len(rows) == 40 and rows[39] == {"rank": "40", "fund": "Fund 40 Money Market Fund", "rate": "2.00"}   # not 34 rows
    assert item("mmf", tmp_path)["text"].splitlines()[0] == "1\tFund 01 Money Market Fund\t11.75"
    assert "has rank 3; ranks must run 1, 2, 3 in order" in refused(tmp_path, tables={"mmf": {"text": FUNDS.replace("2\tAlpha", "3\tAlpha")}})
    assert "line 3: 'ten' is not a number" in refused(tmp_path, tables={"mmf": {"text": FUNDS.replace("10.80%", "ten")}})
    assert "line 4: 1080 is outside the expected range" in refused(tmp_path, tables={"mmf": {"text": FUNDS.replace("10.70%", "1080")}})
    assert "appears twice" in refused(tmp_path, tables={"mmf": {"text": FUNDS.replace("Alpha", "Beta")}})
    assert "4 funds read; the Top 5 average needs at least 5" in refused(tmp_path, tables={"mmf": {"text": "\n".join(FUNDS.splitlines()[:5])}})
    assert "line 2: expected rank, fund manager, effective annual rate; read 2 values" in refused(tmp_path, tables={"mmf": {"text": "1 11.0\n2 10.9"}})
    assert len(analyst.read_form(WEEK, tmp_path)["tables"]["mmf"]) == 40   # a refused paste leaves the saved table alone
    # ranks in order but a higher rate lower down: saved (it may be what the paper prints), with a warning to check it
    save(tmp_path, tables={"mmf": {"text": FUNDS.replace("10.70%", "10.90%")}})
    assert item("mmf", tmp_path)["warnings"] == ["Beta Money Market Fund (rank 3) has a higher rate than Alpha Money Market Fund "
                                                 "(rank 2): check the ranks and rates against the paper."]
    save(tmp_path, tables={"mmf": None})
    assert "mmf" not in analyst.read_form(WEEK, tmp_path)["tables"]


def test_each_table_is_checked_as_a_whole(tmp_path):
    assert "is not a weekday from 2026-09-18 to 2026-10-01" in refused(tmp_path, tables={"interbank": {"text": "2026-10-02 8.80"}})
    save(tmp_path, tables={"interbank": {"text": "01-Oct-26  8.8012%\n30 September 2026\t8.79"}})
    assert analyst.read_form(WEEK, tmp_path)["tables"]["interbank"] == [{"date": "2026-10-01", "rate": "8.8012"},
                                                                        {"date": "2026-09-30", "rate": "8.79"}]
    months = "\n".join(f"2026-{m:02d}  210.5  420.0" for m in (8, 7, 5))
    assert "2026-05 is followed by 2026-07; the months must run with none skipped" in refused(tmp_path, tables={"remittances": {"text": months}})
    assert "needs its North America figure" in refused(tmp_path, tables={"remittances": {"rows": [{"month": "Aug 2026", "total": "420"}]}})
    assert "2026-10-12 is not between the start of the fiscal year (2026-07-01) and 2026-10-09" in refused(
        tmp_path, tables={"borrowing_log": {"text": "2026-10-12 30000 (20000)"}})
    assert "20000 is outside the expected range, -2000000 to 0 Kshs mn" in refused(tmp_path, tables={"borrowing_log": {"text": "2026-10-05 30000 20000"}})
    save(tmp_path, tables={"borrowing_log": {"text": "2026-10-05 30,000.00 (20,000.00)\n2026-10-05 1,000 0"}})   # a bill and a bond auction
    assert analyst.read_form(WEEK, tmp_path)["tables"]["borrowing_log"][0] == {"date": "2026-10-05", "accepted": "30000.00",
                                                                             "redemptions": "-20000.00"}
    assert "2026-10-02 is not a trading day before this week" in refused(tmp_path, tables={"foreign_history": {"text": "2026-10-02 1.2"}})
    assert "is not in the first week of January 2026" in refused(
        tmp_path, tables={"eurobond_yields": {"rows": [{"row": "year_open", "date": "2026-02-02", "2018_10y": "6.1"}]}})
    assert "give the date and at least one yield" in refused(tmp_path, tables={"eurobond_yields": {"rows": [{"row": "month_open", "2018_10y": "7.6"}]}})
    assert "the maturity date 2026-02-28 is not after this week" in refused(
        tmp_path, tables={"eurobond_issues": {"rows": [{"row": "2018_10y", "maturity": "2026-02-28"}]}})
    assert "alpha bank appears twice; each company is listed once" in refused(tmp_path, tables={"universe": {"rows": [{"company": "Alpha Bank"}, {"company": "alpha  bank"}]}})
    assert "this table is typed cell by cell" in refused(tmp_path, tables={"universe": {"text": "Alpha 1 2 3"}})


# ---------------------------------------------------------------------------
# Equivalence: the workbook's figures, typed, give the workbook's section
# ---------------------------------------------------------------------------

CHART_TITLES = tuple(spec.title for spec in SPECS.values())


def same_print(by_workbook, by_form):
    """The two runs print the same thing; returns the items whose review status differs.

    The one designed difference is the charts: they are drawn from the workbook's history, which the form does
    not hold, so with only the form each is an unavailable part naming the workbook.  That is asserted here and
    then the charts are left out of the comparison.
    """
    a, b = wh.printed(by_workbook), wh.printed(by_form)
    a_charts = [x for x in a["blocks"] if x["id"].startswith("chart_")]
    b_charts = [x for x in b["blocks"] if x["id"].startswith("chart_")]
    if a_charts or b_charts:
        assert [x["id"] for x in a_charts] == [x["id"] for x in b_charts] == ["chart_nasi_pe", "chart_nasi_yield"]
        assert {x["kind"] for x in b_charts} == {"chart"} and {x["reason"] for x in b_charts} == {eq.eqw.NEED_WORKBOOK_FOR_CHARTS[0]}
        a = {**a, "blocks": [x for x in a["blocks"] if x not in a_charts], "items": [i for i in a["items"] if not i[0].startswith(CHART_TITLES)]}
        b = {**b, "blocks": [x for x in b["blocks"] if x not in b_charts], "items": [i for i in b["items"] if not i[0].startswith(CHART_TITLES)]}
    assert [x["id"] for x in a["blocks"]] == [x["id"] for x in b["blocks"]]
    for x, y in zip(a["blocks"], b["blocks"]):
        assert x == y, x["id"]
    assert a["summary"] == b["summary"]
    assert [ref for ref, _ in a["items"]] == [ref for ref, _ in b["items"]]
    return {ref.split(" (")[0]: (was, dict(b["items"])[ref]) for ref, was in a["items"] if dict(b["items"])[ref] != was}


def stores(root, typed_from=None, *, real=False):
    """The week's public and KCB inputs under ``root``; the analysts' figures typed from ``typed_from``'s workbooks."""
    if real:
        inputs.store(WEEK, "kcb_weekly", wh.sample("KCB IB Weekly Trading Market Report - Week 40 - 02Oct2026.pdf"), "w.pdf", root)
        inputs.store(WEEK, "kcb_daily", wh.sample("KCB IB Daily Trading Market Report - 02Oct2026.pdf"), "d.pdf", root)
    else:
        inputs.store(WEEK, "kcb_weekly", wh.fake_pdf(wh.kcb_weekly_text()), "weekly.pdf", root)
        inputs.store(WEEK, "kcb_daily", wh.fake_pdf(wh.kcb_daily_text(WEEK.ending, turnover=500_000_000)), "fri.pdf", root)
    inputs.store(WEEK, "cbk_bulletin", fi.BULLETIN, "bulletin.pdf", root)
    if typed_from is not None:
        analyst.save_form(WEEK, wh.typed_from_workbooks(WEEK, typed_from), root)


# What an OCR'd index level loses without the workbook: the analysts' typed level was its only second reading, and
# index levels are not on the form (the tool reads them from KCB IB and the NSE).  Unconfirmed OCR is flagged.
OCR_ONLY = {"Market Performance: NSE 10 week-on-week change", "Market Performance: NSE 10 year-to-date change",
            "Market Performance: NSE 25 year-to-date change", "Market Performance: NSE 20 year-to-date change",
            "Market Performance: NASI year-to-date change",
            "Market Performance: Banking Sector index: Banking Sector index week-on-week change",
            "Market Performance: Banking Sector index: Banking Sector index, Friday",
            "Market Performance: Banking Sector index: Banking Sector index, previous Friday"}


def test_typing_the_synthetic_workbooks_figures_gives_the_same_sections(tmp_path, text_pdfs):
    with_books, typed = tmp_path / "books", tmp_path / "typed"
    stores(with_books)
    inputs.store(WEEK, "fi_workbook", wh.fi_workbook_bytes(), "FI.xlsx", with_books)
    inputs.store(WEEK, "equities_workbook", wh.equities_workbook_bytes(), "Equities.xlsx", with_books)
    stores(typed, typed_from=with_books)
    form = inputs.WeeklyInputs(WEEK, typed)
    assert form.fi_book is None and form.equities_book is None           # no workbook upload
    by_books = fi.build(with_books)
    changed = same_print(by_books, fi.build(typed))
    # The synthetic workbook's invented yields and volumes disagree with the real bulletin's, which the workbook run
    # flags ("sources disagree").  Typed, there is no workbook to disagree: the published figure stands alone, clean.
    assert set(changed.values()) == {("flagged", "clean")}
    for i in by_books.review_items:
        if i.ref.split(" (")[0] in changed:
            assert {f.kind for f in i.detail} == {SOURCES_DISAGREE}
    equities = eq.build(with_books)
    changed = same_print(equities, eq.build(typed))
    assert {ref for ref, change in changed.items() if change == ("not_auto_verified", "flagged")} == OCR_ONLY
    # The rest are the synthetic workbook's own weekly sums, which disagree with what KCB's figures give: flagged with
    # the workbook, and with nothing to disagree once the workbook is gone.
    others = {ref: change for ref, change in changed.items() if ref not in OCR_ONLY}
    assert set(others) == {"Market Performance: equities turnover: Equities turnover over the week",
                           "Market Performance: foreign investors: Foreign investors' net position over the week"}
    assert all(was == "flagged" for was, _ in others.values())
    for i in equities.review_items:
        if i.ref.split(" (")[0] in others:
            assert {f.kind for f in i.detail} == {SOURCES_DISAGREE}
    # every typed figure says so, in the same place a workbook cell does
    money = figures(blocks(fi.build(typed))["money_market"])
    assert money["placements"]["inputs"]["placements"] == {
        "value": 9.5, "origin": "analyst_input",
        "source": "analyst input typed on the weekly form (3-month bank placements; source: Rates offered by various banks)"}


def test_typing_the_real_workbooks_figures_gives_the_published_week(tmp_path):
    """The golden week (ending 2 October 2026), from the form alone: no workbook is uploaded."""
    with_books, typed = tmp_path / "books", tmp_path / "typed"
    stores(with_books, real=True)
    inputs.store(WEEK, "fi_workbook", wh.sample("FI_MASTERSHEET_05.10.2026.v1.xlsx"), "FI.xlsx", with_books)
    inputs.store(WEEK, "equities_workbook", wh.sample("Equities Workbook 02.10.2026.v6 (1).xlsx"), "Equities.xlsx", with_books)
    stores(typed, typed_from=with_books, real=True)
    assert sorted(p.name for p in (typed / "2026-10-02").iterdir() if p.suffix == ".xlsx") == []
    by_form = fi.build(typed)
    assert same_print(fi.build(with_books), by_form) == {}
    by = blocks(by_form)
    assert figures(by["money_market"])["top5"]["display"] == "10.77%" and len(by["mmf_table"]["rows"]) == 34
    assert by["borrowing"]["body_md"] == ("The government is at 245.3% of its pro-rated net domestic borrowing target of Kshs 242.5 bn, "
                                          "with a net borrowing position of Kshs 594.8 bn (inclusive of T-bills).")
    equities = eq.build(typed, boxes=eq.PUBLISHED_BOXES)
    changed = same_print(eq.build(with_books, boxes=eq.PUBLISHED_BOXES), equities)
    assert set(changed) == OCR_ONLY and set(changed.values()) == {("not_auto_verified", "flagged")}
    by = blocks(equities)
    assert "31.9% below the historical average of 11.2x" in by["valuation"]["body_md"] and len(by["universe_of_coverage"]["rows"]) == 13
    assert by["foreign"]["body_md"].startswith("Foreign investors remained net buyers for the second consecutive week")


# ---------------------------------------------------------------------------
# Typed values in the draft and the review
# ---------------------------------------------------------------------------

@pytest.fixture
def typed_week(tmp_path, text_pdfs):
    """The synthetic week with no workbook: the form holds what the workbooks would."""
    books = tmp_path / "books"
    books.mkdir()
    inputs.store(WEEK, "fi_workbook", wh.fi_workbook_bytes(), "FI.xlsx", books)
    inputs.store(WEEK, "equities_workbook", wh.equities_workbook_bytes(), "Equities.xlsx", books)
    root = tmp_path / "typed"
    stores(root, typed_from=books)
    return root


def test_every_typed_value_is_an_analyst_input_never_clean(typed_week):
    review = fi.build(typed_week)
    table = items(review, "Money Market Fund Yield for Fund Managers")
    assert len(table) == len(wh.FUNDS) and {i.status for i in table} == {"not_auto_verified"}
    assert table[0].detail == ("Not auto-verified: analyst input typed on the weekly form (money market fund table; source: "
                               "Business Daily). The tool cannot read Business Daily (login pending), so check the row against "
                               "the paper.")
    top5 = items(review, "Money Market Performance: Average yield of the Top 5")[0]
    assert top5.status == "not_auto_verified" and "(10.72%)" in top5.ref                     # worked out, never typed
    assert "analyst input typed on the weekly form (money market fund table, Alpha Money Market Fund" in top5.detail
    assert items(review, "Money Market Performance: 3-month bank placements")[0].status == "flagged"   # its standing flag
    ratio = items(review, "Net domestic borrowing against the pro-rated target: Net domestic borrowing")[0]
    assert ratio.status == "not_auto_verified" and "auction log, 2026-10-05: accepted; source: The fixed income team's borrowing log" in ratio.detail
    sources = blocks(review)["money_market"]["sources"]
    assert sources[0] == {"name": FORM}                                                       # not the workbook
    equities = eq.build(typed_week)
    assert {i.status for i in items(equities, "Market Performance: valuation:")} == {"not_auto_verified"}
    pe = items(equities, "Market Performance: valuation: Market P/E")[0]
    assert "analyst input typed on the weekly form (Market P/E; source: Bloomberg NASI P/E)" in pe.detail
    rows = [i for i in items(equities, "Cytonn Report: Equities Universe of Coverage:") if "Delta" not in i.ref]
    assert {i.status for i in rows} == {"not_auto_verified"}
    assert rows[0].detail.startswith("Not auto-verified: analyst input typed on the weekly form (Universe of Coverage, Alpha Bank; "
                                     "source: Cytonn analyst estimates and company filings; prices from the NSE). The changes, yield")
    # the checker still works every figure out again: a derived figure cannot be typed, and a tampered one is caught
    assert blocks(equities)["universe_of_coverage"]["source"]["name"] == "Weekly analyst inputs, Universe of Coverage"
    assert not review.is_approvable and not equities.is_approvable


def test_the_model_is_handed_nothing_from_the_form(typed_week):
    seen = []

    def drafting(briefs, target, **kwargs):
        seen.append((briefs, target, kwargs))
        return wh.no_draft(briefs, target)

    fi.fiw.build_fixed_income_review(WEEK.ending, inputs=inputs.WeeklyInputs(WEEK, typed_week), fetchers=fi.fetchers(), draft=drafting)
    briefs, target, kwargs = seen[0]
    assert set(kwargs) == {"provider", "today", "window", "on_event"} and briefs is fi.fiw.BRIEFS
    typed = json.dumps(analyst.read_form(WEEK, typed_week))
    assert "10.8" in typed and not any("10.8" in str(b) for b in briefs)   # no typed figure is in what the drafter is given


def test_an_empty_form_and_no_workbook_leaves_only_what_truly_needs_them_unavailable(tmp_path, text_pdfs):
    stores(tmp_path)
    by = blocks(fi.build(tmp_path))
    kinds = {k: b["kind"] for k, b in by.items()}
    # worked out from CBK alone: the auctions, liquidity (KESONIA and volumes), the Eurobond days, the shilling, reserves
    assert [k for k, v in kinds.items() if v != "unavailable"] == ["tbills", "tbonds", "liquidity", "eurobonds", "eurobonds_table",
                                                                  "shilling", "shilling_support", "shilling_pressure", "outlook"]
    assert [k for k, v in kinds.items() if v == "unavailable"] == ["bidding_range", "money_market", "borrowing"]
    assert by["money_market"]["reason"].startswith("The money market fund table and the 3-month bank placements rate have not "
                                                   "been typed under \"Weekly analyst inputs\"")
    assert "KESONIA" in by["liquidity"]["body_md"] and "eurobonds_issues" not in by and "mmf_table" not in by
    by = blocks(eq.build(tmp_path))
    kinds = {k: b["kind"] for k, b in by.items()}
    assert [k for k, v in kinds.items() if v == "unavailable"] == ["large_caps", "valuation", "universe_of_coverage"]
    assert [(k, by[k]["status"]) for k, v in kinds.items() if k.startswith("chart_")] == [("chart_nasi_pe", "no_workbook"),
                                                                                       ("chart_nasi_yield", "no_workbook")]
    assert by["large_caps"]["reason"] == ("The large-cap list has not been typed under \"Weekly analyst inputs\", and the equities "
                                          "workbook for this week is not among this week's inputs.")
    assert by["turnover"]["kind"] == "computed" and "YTD" not in by["turnover"]["body_md"]     # the running total is left out
    assert "The year-to-date total is left out" in " ".join(by["turnover"]["notes"])
    assert by["foreign"]["body_md"] == "During the week, foreign investors recorded a net buying position of USD 0.9 mn."


def test_a_part_names_exactly_what_is_still_missing(tmp_path, text_pdfs):
    stores(tmp_path)
    save(tmp_path, {"placements": "9.5", "pe": "8.0", "dividend_yield": "6.0", "borrowing_target": "910"})
    by = blocks(fi.build(tmp_path))
    assert by["money_market"]["reason"] == ("The money market fund table has not been typed under \"Weekly analyst inputs\", and "
                                            "the fixed income workbook for this week is not among this week's inputs.")
    assert by["money_market"]["unblock"] == ("Type it under \"Weekly analyst inputs\" on the start screen, or upload the fixed "
                                             "income workbook updated for this week, and draft again.")
    assert by["borrowing"]["reason"].startswith("The fiscal year's auction log has not been typed")
    assert blocks(eq.build(tmp_path))["valuation"]["reason"].startswith(
        "The historical average P/E and the historical average dividend yield have not been typed")
    # the table without its date is still missing, and says which of the two
    save(tmp_path, tables={"mmf": {"text": FUNDS}})
    assert blocks(fi.build(tmp_path))["money_market"]["reason"].startswith(
        "The money market fund table is typed under \"Weekly analyst inputs\", but the date it was published on is not.")
    save(tmp_path, {"mmf_published": "2026-10-02"})
    by = blocks(fi.build(tmp_path))
    assert by["money_market"]["kind"] == "computed" and by["mmf_table"]["title"].endswith("as published on 2nd October 2026")
    assert figures(by["money_market"])["top5"]["display"] == "10.72%"
    assert "closed the week at 11.0%." in by["money_market"]["body_md"]     # no previous week's yield typed: none is compared


def test_a_typed_log_that_stops_short_and_typed_sums_that_do_not_reach_a_turn_make_nothing_up(tmp_path, text_pdfs):
    stores(tmp_path)
    save(tmp_path, {"borrowing_target": "910", "foreign_ytd": "-150.2"},
         {"borrowing_log": {"text": "2026-09-28 30000 (20000)"}, "foreign_history": {"text": "2026-09-25 1.2\n2026-09-18 0.4"}})
    borrowing = blocks(fi.build(tmp_path))["borrowing"]
    assert borrowing["kind"] == "unavailable" and borrowing["reason"] == (
        "The auction log typed under \"Weekly analyst inputs\" has no auction settling in the week after 2026-10-02 (latest value "
        "date: 2026-09-28).")
    foreign = blocks(eq.build(tmp_path))["foreign"]
    assert foreign["body_md"] == ("During the week, foreign investors recorded a net buying position of USD 0.9 mn, from a net "
                                  "buying position of USD 1.2 mn recorded the previous week, taking the YTD foreign net selling "
                                  "position to USD 150.2 mn.")
    assert "The streak is left out" in " ".join(foreign["notes"])
    save(tmp_path, tables={"foreign_history": {"text": "2026-09-25 1.2\n2026-09-18 0.4\n2026-09-11 (2.0)"}})
    assert blocks(eq.build(tmp_path))["foreign"]["body_md"].startswith("Foreign investors remained net buyers for the third consecutive week")


# ---------------------------------------------------------------------------
# A workbook is a shortcut: it prefills, a typed value overrides, a difference is shown
# ---------------------------------------------------------------------------

@pytest.fixture
def with_books(tmp_path, text_pdfs):
    stores(tmp_path)
    inputs.store(WEEK, "fi_workbook", wh.fi_workbook_bytes(), "FI.xlsx", tmp_path)
    inputs.store(WEEK, "equities_workbook", wh.equities_workbook_bytes(), "Equities.xlsx", tmp_path)
    return tmp_path


def test_an_uploaded_workbook_prefills_the_form(with_books):
    status = analyst.status(WEEK, with_books)
    assert status["workbooks"] == {"fixed_income": True, "equities": True}
    placements = item("placements", with_books)
    assert placements["value"] is None and placements["workbook"] == {"value": "9.5", "ref": "'Money Market Performance'!C6"}
    assert item("mmf_published", with_books)["workbook"]["value"] == "2026-10-02"
    assert item("pe", with_books)["workbook"] == {"value": "8", "ref": "'NASI-PE & Dividend Yield'!B8"}
    assert item("dividend_yield", with_books)["workbook"]["value"] == "6"           # shown as a percentage
    assert item("large_caps", with_books)["workbook"]["value"] == wh.LARGE_CAPS
    funds = item("mmf", with_books)
    assert funds["rows"] is None and len(funds["workbook_rows"]) == len(wh.FUNDS)
    assert funds["workbook_rows"][1] == {"rank": "2", "fund": "Alpha Money Market Fund", "rate": "10.8"}
    assert funds["workbook_ref"] == "Fixed income workbook 'Money Market Performance'"
    universe = item("universe", with_books)["workbook_rows"]
    assert universe[0] == {"company": "Alpha Bank", "last_price": "40", "price": "42", "month_end_price": "39", "year_open": "30",
                           "target": "55", "dps": "3", "shares_bn": "2", "tbv_bn": "60"}
    assert item("eurobond_yields", with_books)["workbook_rows"][0]["date"] == "2026-01-02"
    # nothing typed: the section is the workbook's, labelled as the workbook's, exactly as before the form existed
    review = fi.build(with_books)
    assert "'Money Market Performance'!S12:U18" in items(review, "Money Market Fund Yield for Fund Managers")[0].detail
    assert not any(w.startswith(FORM) for w in review.section["warnings"])


def test_a_typed_value_overrides_the_workbook_and_the_difference_is_shown_to_the_reviewer(with_books):
    save(with_books, {"placements": "9.75", "pe": "8.4", "cmmf_last_week": "10.9"},      # 10.9 is what the workbook has
         {"universe": {"rows": [{"company": "Alpha Bank", "target": "60"}]}})
    placements = item("placements", with_books)
    assert placements["value"] == "9.75" and placements["workbook"]["value"] == "9.5" and placements["differences"] == [
        "3-month bank placements: typed as 9.75%, but the uploaded fixed income workbook has 9.5% ('Money Market Performance'!C6). "
        "The typed value is used."]
    assert item("cmmf_last_week", with_books)["differences"] == []      # typed the same: nothing to show
    review = fi.build(with_books)
    money = blocks(review)["money_market"]
    assert "3-month bank placements ended the week at 9.8%" in money["body_md"]            # the typed value is what is printed
    flagged = items(review, "Money Market Performance: 3-month bank placements")[0]
    assert flagged.status == "flagged" and SOURCES_DISAGREE in {f.kind for f in flagged.detail}
    disagreement = next(f for f in flagged.detail if f.kind == SOURCES_DISAGREE)
    assert "is 9.75 in analyst input typed on the weekly form" in disagreement.message
    assert "but 9.5 in analyst input from Fixed income workbook 'Money Market Performance'!C6" in disagreement.message
    assert "Weekly analyst inputs: 3-month bank placements: typed as 9.75%, but the uploaded fixed income workbook has 9.5%" in " ".join(
        review.section["warnings"])
    last = figures(money)["cmmf_last"]["inputs"]["cmmf_last"]
    assert "typed on the weekly form" in last["source"] and "second" not in last              # agrees: no second reading
    equities = eq.build(with_books)
    assert figures(blocks(equities)["valuation"])["pe"]["display"] == "8.4x"
    table = blocks(equities)["universe_of_coverage"]
    alpha = next(r for r in table["rows"] if r["company"] == "Alpha Bank")
    assert (alpha["target"], alpha["upside"], alpha["price"]) == ("60.0", "50.0%", "42.0")   # upside worked out from the typed target
    row = items(equities, "Cytonn Report: Equities Universe of Coverage: Alpha Bank")[0]
    assert row.status == "flagged" and row.detail[0].kind == SOURCES_DISAGREE                 # 60.0 typed, 55.0 in the workbook
    assert len(table["rows"]) == len(wh.UNIVERSE)                                             # the other companies are the workbook's
    beta = items(equities, "Cytonn Report: Equities Universe of Coverage: Beta Bank")[0]
    assert "'Universe of Coverage' row 4" in beta.detail
    assert any("Universe of Coverage, Alpha Bank: target price: typed as 60" in w for w in equities.section["warnings"])


def test_a_pasted_table_replaces_the_workbooks_and_says_which_rows_differ(with_books):
    save(with_books, {"mmf_published": "2026-10-02"}, {"mmf": {"text": FUNDS.replace("10.80%", "10.85%")}})   # six funds; the workbook has seven
    differences = item("mmf", with_books)["differences"]
    assert differences[0].startswith("money market fund table, Alpha Money Market Fund: effective annual rate: typed as 10.85%, "
                                     "but the uploaded fixed income workbook has 10.8%")
    # the paper's "Cytonn Money Market Fund" is the workbook's "Cytonn Money Market Fund ( Dial *809# ...)": one fund
    assert differences[-1] == ("Money market fund table: the typed rows are not the uploaded fixed income workbook's rows: 1 in "
                               "the workbook only (Zeta Money Market Fund). The typed table is used.")
    assert analyst.fund_key("Cytonn Money Market Fund ( Dial *809# or download Cytonn App)") == analyst.fund_key("cytonn  money market fund")
    assert analyst.fund_key("Alpha Money Market Fund") != analyst.fund_key("Alpha Money Market Fund (USD)")   # only Cytonn's is aliased
    review = fi.build(with_books)
    assert len(blocks(review)["mmf_table"]["rows"]) == 6
    top5 = items(review, "Money Market Performance: Average yield of the Top 5")[0]
    assert "(10.73%)" in top5.ref and top5.status == "flagged" and top5.detail[0].kind == SOURCES_DISAGREE


# ---------------------------------------------------------------------------
# The API
# ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(db_path=tmp_path / "app.db", load_dotenv=False, inputs_root=tmp_path / "weekly"))


def test_the_form_is_read_and_saved_through_the_api(client, tmp_path):
    empty = client.get("/api/inputs/weekly/2026-10-02/analyst?section=fixed_income").json()
    assert empty["form"] == FORM and {g["section"] for g in empty["groups"]} == {"fixed_income"} and empty["saved_at"] is None
    r = client.put("/api/inputs/weekly/2026-10-02/analyst?section=fixed_income",
                   json={"fields": {"placements": "9.0", "mmf_published": "2026-10-02"}, "tables": {"mmf": {"text": FUNDS}}})
    assert r.status_code == 200 and r.json()["saved_at"]
    saved = {i["key"]: i for g in r.json()["groups"] for i in g["items"]}
    assert saved["placements"]["value"] == "9.0" and len(saved["mmf"]["rows"]) == 6
    assert (tmp_path / "weekly" / "2026-10-02" / "analyst.json").is_file()
    r = client.put("/api/inputs/weekly/2026-10-02/analyst", json={"fields": {"placements": "90"}, "tables": {"mmf": {"text": "1 x 2"}}})
    assert r.status_code == 422 and r.json()["detail"].splitlines() == [
        "3-month bank placements: 90 is outside the expected range, 1 to 40%.",
        "Money market fund table: 1 fund read; the Top 5 average needs at least 5"]
    assert client.get("/api/inputs/weekly/2026-10-02/analyst").json()["groups"][0]["items"][0]["value"] == "9.0"   # nothing was stored
    assert client.get("/api/inputs/weekly/2026-10-03/analyst").status_code == 422          # not a Friday
    assert client.get("/api/inputs/weekly/2026-10-02/analyst?section=focus").status_code == 422
    # the form is not one of the upload slots, and saving it leaves the files' status alone
    assert [s["slug"] for s in client.get("/api/inputs/weekly/2026-10-02").json()["slots"]] == [s.slug for s in inputs.SLOTS]


# ---------------------------------------------------------------------------
# Starting from last week's form
# ---------------------------------------------------------------------------

NEXT = Week(date(2026, 10, 9))
SLOW = {"large_caps", "foreign_prior_year", "universe_month_end", "fiscal_year_start", "eurobond_issues", "eurobond_yields", "remittances", "universe", "cmmf_last_week"}
WEEKLY = {"placements", "pe", "pe_average", "dividend_yield", "dividend_yield_average", "borrowing_target", "mmf", "interbank",
          "borrowing_log", "foreign_history"}


def save_week(root, week, fields=None, tables=None, confirm=None):
    return analyst.save_form(week, {"fields": fields or {}, "tables": tables or {}, "confirm": confirm or []}, root)


def refused_carry(week, root) -> str:
    with pytest.raises(InputError) as caught:
        analyst.carry_forward(week, root)
    return str(caught.value)


@pytest.fixture
def last_week(tmp_path, text_pdfs):
    """The week ending 2 October fully typed (from the synthetic workbooks' figures), and nothing yet for 9 October."""
    books = tmp_path / "books"
    books.mkdir()
    inputs.store(WEEK, "fi_workbook", wh.fi_workbook_bytes(), "FI.xlsx", books)
    inputs.store(WEEK, "equities_workbook", wh.equities_workbook_bytes(), "Equities.xlsx", books)
    root = tmp_path / "typed"
    stores(root, typed_from=books)
    return root


def test_last_weeks_form_starts_this_weeks_and_every_carried_value_says_where_it_came_from(last_week):
    done = analyst.carry_forward(NEXT, last_week)
    assert set(done["carried"]) == SLOW | WEEKLY and set(done["unconfirmed"]) == WEEKLY
    form = analyst.read_form(NEXT, last_week)
    # never carried: the paper's date, the running totals, and the prices (KCB IB's and the stored week's)
    assert not {"mmf_published", "turnover_ytd", "foreign_ytd"} & set(form["fields"])
    assert all(not {"price", "last_price"} & set(r) for r in form["tables"]["universe"])
    assert form["tables"]["universe"][0] == {"company": "Alpha Bank", "month_end_price": "39", "year_open": "30", "target": "55",
                                             "dps": "3", "shares_bn": "2", "tbv_bn": "60"}
    assert form["fields"]["cmmf_last_week"] == "11"       # last week's fund table is "the previous week" now
    # only the interbank days still inside the two weeks compared; 1 October is still this month's first trading day
    assert [r["date"] for r in form["tables"]["interbank"]] == ["2026-09-25", "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01"]
    assert [r["row"] for r in form["tables"]["eurobond_yields"]] == ["year_open", "month_open"]
    placements = item("placements", last_week, NEXT)
    assert placements["value"] == "9.5" and placements["needs_confirmation"] is True
    assert placements["carried"] == {"from": "2026-10-02", "note": "", "whole": True, "cells": {}}
    issues = item("eurobond_issues", last_week, NEXT)
    assert issues["carried"]["from"] == "2026-10-02" and issues["needs_confirmation"] is False
    status = analyst.status(NEXT, last_week)
    assert status["previous_week"] == "2026-10-02" and status["can_carry"] is True
    assert {u["key"] for u in status["unconfirmed"]} == WEEKLY
    assert {u["label"] for u in analyst.status(NEXT, last_week, "equities")["unconfirmed"]} == {
        "Market P/E", "Historical average P/E", "Market dividend yield", "Historical average dividend yield",
        "Foreign net position, previous weeks"}
    assert "Nothing to carry from the week ending 2 Oct 2026" in refused_carry(NEXT, last_week)   # a second time: all is held
    assert "No analyst inputs are saved for the week ending 9 Oct 2026" in refused_carry(Week(date(2026, 10, 16)), tmp_root(last_week))


def tmp_root(root):
    """A root where the week ending 9 October has no form (the fixture's root, before anything is carried into it)."""
    empty = root.parent / "elsewhere"
    empty.mkdir(exist_ok=True)
    return empty


def test_a_carried_weekly_value_is_read_by_no_builder_until_it_is_confirmed(last_week):
    analyst.carry_forward(NEXT, last_week)
    waiting = inputs.WeeklyInputs(NEXT, last_week)
    form = waiting.analyst
    assert form.field("placements") is None and form.field("pe") is None and form.mmf() is None and form.interbank() == []
    assert form.borrowing()["target_bn"] is None and form.foreign_history() == []
    assert form.field("large_caps") and form.universe() is not None and any(form.eurobonds())      # slow ones are used at once
    borrowing = fi.fiw.borrowing_blocks(waiting, NEXT, None, [])[0]
    assert borrowing["kind"] == "unavailable" and borrowing["reason"] == (
        "Net domestic borrowing target for the fiscal year is carried from the week ending 2026-10-02 and has not been "
        "confirmed for this week. Auction log for the fiscal year is carried from the week ending 2026-10-02 and has not been "
        "confirmed for this week. CBK's auction results could not be fetched from centralbank.go.ke.")
    assert borrowing["unblock"] == "Complete or confirm it under \"Weekly analyst inputs\" on the start screen and draft again."
    # with CBK's results the log is not needed: only the target still waits
    from tests.test_net_borrowing import RELEASES
    settled = RELEASES + [dict(r, value_date="2026-10-12") for r in RELEASES if (r["value_date"], r["kind"]) == ("2026-10-05", "tbill")]
    with_cbk = fi.fiw.borrowing_blocks(inputs.WeeklyInputs(NEXT, last_week), NEXT, {"releases": settled, "warnings": []}, [])
    assert [b["kind"] for b in with_cbk] == ["unavailable"] and with_cbk[0]["reason"] == (
        "Net domestic borrowing target for the fiscal year is carried from the week ending 2026-10-02 and has not been "
        "confirmed for this week.")
    # confirming a value as it stands, or typing over it, makes it this week's
    save_week(last_week, NEXT, confirm=["borrowing_target", "pe"], fields={"placements": "9.25"})
    form = inputs.WeeklyInputs(NEXT, last_week).analyst
    assert form.field("borrowing_target").number == 910.0 and form.field("pe").number == 8.0 and form.field("placements").number == 0.0925
    assert item("pe", last_week, NEXT)["needs_confirmation"] is False and item("pe", last_week, NEXT)["carried"]["from"] == "2026-10-02"
    assert item("placements", last_week, NEXT)["carried"] is None            # typed over: no longer a carried value
    assert {u["key"] for u in analyst.status(NEXT, last_week)["unconfirmed"]} == WEEKLY - {"borrowing_target", "pe", "placements"}
    with pytest.raises(InputError, match="nothing waits to be confirmed for 'pe'"):
        save_week(last_week, NEXT, confirm=["pe"])


def test_carrying_never_replaces_what_is_typed_and_an_edited_grid_says_which_cells_are_still_carried(last_week):
    save_week(last_week, NEXT, fields={"placements": "9.9", "universe_month_end": "2026-09-30"})
    done = analyst.carry_forward(NEXT, last_week)
    assert "placements" not in done["carried"] and analyst.read_form(NEXT, last_week)["fields"]["placements"] == "9.9"
    rows = analyst.read_form(NEXT, last_week)["tables"]["universe"]
    assert "month_end_price" not in rows[0]      # the month-end date was typed here, not carried: its prices are not assumed
    rows[0] = {**rows[0], "target": "60"}
    save_week(last_week, NEXT, tables={"universe": {"rows": rows}})
    carried = item("universe", last_week, NEXT)["carried"]
    assert carried["whole"] is False and carried["cells"]["Alpha Bank"] == ["year_open", "dps", "shares_bn", "tbv_bn"]
    assert carried["cells"]["Beta Bank"] == ["year_open", "target", "dps", "shares_bn", "tbv_bn"]


def test_what_is_no_longer_valid_for_the_week_is_not_carried(tmp_path):
    november = Week(date(2026, 11, 6))
    save_week(tmp_path, Week(date(2026, 10, 30)), fields={"universe_month_end": "2026-09-30", "foreign_prior_year": "-6"},
              tables={"universe": {"rows": [{"company": "Alpha Bank", "target": "55", "month_end_price": "39"}]},
                      "interbank": {"text": "2026-10-16 8.80"},
                      "eurobond_yields": {"rows": [{"row": "month_open", "date": "2026-10-01", "2018_10y": "7.6"}]}})
    done = analyst.carry_forward(november, tmp_path)
    assert set(done["carried"]) == {"foreign_prior_year", "universe"}       # the month turned: last month's open, month end, days
    assert analyst.read_form(november, tmp_path)["tables"]["universe"] == [{"company": "Alpha Bank", "target": "55"}]
    january = Week(date(2027, 1, 1))
    save_week(tmp_path, Week(date(2026, 12, 25)), fields={"foreign_prior_year": "-6", "large_caps": "Safaricom"})
    assert analyst.carry_forward(january, tmp_path)["carried"] == ["large_caps"]   # "the previous year" is another year now


# ---------------------------------------------------------------------------
# Suggested running totals
# ---------------------------------------------------------------------------

def test_a_running_total_is_suggested_as_last_weeks_plus_this_weeks_worked_out_figure(tmp_path, text_pdfs):
    stores(tmp_path)
    nothing = eq.eqw.running_total_suggestions(inputs.WeeklyInputs(WEEK, tmp_path), lambda: eq.RATES)
    assert nothing["turnover_ytd"] == {"reason": "Year-to-date equities turnover: no total is saved for the week ending "
                                                 "2026-09-25 to add this week's figure to. Neither that week's form nor an "
                                                 "equities workbook uploaded for that week holds one. Type this week's total "
                                                 "yourself; once it is saved, next week's suggestion can start from it."}
    save_week(tmp_path, Week(date(2026, 9, 25)), fields={"turnover_ytd": "3035.6", "foreign_ytd": "-167.2"})
    found = eq.eqw.running_total_suggestions(inputs.WeeklyInputs(WEEK, tmp_path), lambda: eq.RATES)
    by = blocks(eq.build(tmp_path))
    turnover, net = figures(by["turnover"])["turnover"]["value"], figures(by["foreign"])["net_flow"]["value"]
    assert found["turnover_ytd"]["value"] == f"{3035.6 + turnover:.4f}" and found["foreign_ytd"]["value"] == f"{-167.2 + net:.4f}"
    assert found["turnover_ytd"]["note"] == (
        f"Suggested: 3,035.6000 saved for the week ending 2026-09-25 + {turnover:,.4f} worked out for this week from equities "
        "turnover (KCB IB's daily reports and the CBK bulletin's Table 6), each day over that day's CBK rate = "
        f"{3035.6 + turnover:,.4f} USD mn. Check it and confirm.")
    assert analyst.read_form(WEEK, tmp_path)["fields"] == {}             # working it out stores nothing
    # a day with no source: no figure for the week, so no suggestion (and none from an OCR reading)
    inputs.remove(WEEK, "kcb_daily_2026-10-02.pdf", tmp_path)
    missing = eq.eqw.running_total_suggestions(inputs.WeeklyInputs(WEEK, tmp_path), lambda: eq.RATES)
    assert missing["turnover_ytd"]["reason"].startswith("Year-to-date equities turnover: this week's figure cannot be worked out: "
                                                        "no equities turnover or CBK rate for Friday 02 October")
    assert "value" in missing["foreign_ytd"]                             # KCB's weekly report still lists each weekday's flows
    first = Week(date(2027, 1, 1))
    assert "restarts with the year" in eq.eqw.running_total_suggestions(inputs.WeeklyInputs(first, tmp_path), lambda: eq.RATES)["turnover_ytd"]["reason"]


def test_a_suggestion_is_only_a_prefill_through_the_api_until_it_is_confirmed(tmp_path, text_pdfs):
    root = tmp_path / "weekly"
    stores(root)
    save_week(root, Week(date(2026, 9, 25)), fields={"turnover_ytd": "3035.6"})
    client = TestClient(create_app(db_path=tmp_path / "app.db", load_dotenv=False, inputs_root=root, fetch_usd_rates=lambda: eq.RATES))
    r = client.post("/api/inputs/weekly/2026-10-02/analyst/suggest/turnover_ytd?section=equities")
    assert r.status_code == 200
    field = next(i for g in r.json()["groups"] for i in g["items"] if i["key"] == "turnover_ytd")
    assert field["suggestable"] and field["needs_confirmation"] and field["carried"]["from"] == "suggested"
    assert field["carried"]["note"].startswith("Suggested: 3,035.6000 saved for the week ending 2026-09-25 + ")
    assert r.json()["unconfirmed"] == [{"key": "turnover_ytd", "label": "Year-to-date equities turnover"}]
    assert inputs.WeeklyInputs(WEEK, root).analyst.field("turnover_ytd") is None           # not read by a draft yet
    assert "taking the YTD" not in blocks(eq.build(root))["turnover"]["body_md"]
    r = client.put("/api/inputs/weekly/2026-10-02/analyst?section=equities", json={"confirm": ["turnover_ytd"]})
    assert r.status_code == 200 and r.json()["unconfirmed"] == []
    review = eq.build(root)
    assert "taking the YTD total turnover to USD 3,052.2 mn" in blocks(review)["turnover"]["body_md"]
    ytd = items(review, "Market Performance: equities turnover: Year-to-date equities turnover")[0]
    assert ytd.status == "not_auto_verified" and "analyst input typed on the weekly form" in ytd.detail   # confirmed, still an analyst input
    # a confirmed value is never replaced by a new suggestion; a field with no saved base, or not a running total, refuses
    assert client.post("/api/inputs/weekly/2026-10-02/analyst/suggest/turnover_ytd").status_code == 409
    r = client.post("/api/inputs/weekly/2026-10-02/analyst/suggest/foreign_ytd")
    assert r.status_code == 409 and "no total is saved for the week ending 2026-09-25" in r.json()["detail"]
    assert client.post("/api/inputs/weekly/2026-10-02/analyst/suggest/pe").status_code == 404
    # the carry route: nothing saved for the week before 25 September
    r = client.post("/api/inputs/weekly/2026-09-25/analyst/carry")
    assert r.status_code == 409 and "No analyst inputs are saved for the week ending 18 Sep 2026" in r.json()["detail"]
    r = client.post("/api/inputs/weekly/2026-10-09/analyst/carry?section=equities")
    assert r.status_code == 409 and "Nothing to carry" in r.json()["detail"]      # a running total is never carried
    assert client.put("/api/inputs/weekly/2026-10-02/analyst", json={"confirm": ["pe"]}).status_code == 422


def test_every_refusal_of_a_suggestion_says_what_is_missing_and_what_to_do(tmp_path, text_pdfs):
    """Each reason the suggest route gives, through the route, with its exact status; nothing is stored by any of them."""
    root = tmp_path / "weekly"
    stores(root)
    client = TestClient(create_app(db_path=tmp_path / "app.db", load_dotenv=False, inputs_root=root, fetch_usd_rates=lambda: eq.RATES))
    suggest = lambda field, week="2026-10-02", q="?section=equities": client.post(f"/api/inputs/weekly/{week}/analyst/suggest/{field}{q}")
    # the request itself: not a Friday, not a section of the form, not a running total
    assert suggest("turnover_ytd", "2026-10-01").status_code == 422
    assert suggest("turnover_ytd", q="?section=real_estate").status_code == 422
    r = suggest("pe")
    assert r.status_code == 404 and r.json()["detail"] == "no suggestion is worked out for 'pe'"
    # nothing for the week before at all
    r = suggest("turnover_ytd")
    assert r.status_code == 409 and r.json()["detail"].endswith(
        "Neither that week's form nor an equities workbook uploaded for that week holds one. Type this week's total "
        "yourself; once it is saved, next week's suggestion can start from it.")
    # one held for the week before, but suggested there and never confirmed: said so, and not used
    analyst.suggest(Week(date(2026, 9, 25)), "turnover_ytd", "3035.6", "seeded", root)
    r = suggest("turnover_ytd")
    assert r.status_code == 409 and r.json()["detail"] == (
        "Year-to-date equities turnover: no total is saved for the week ending 2026-09-25 to add this week's figure to. "
        "That week's form holds one, but it was never confirmed, so it is not used: confirm it on that week's form, or "
        "type this week's total yourself.")
    # confirmed there, it is the base; a day with no source then refuses with what to upload
    save_week(root, Week(date(2026, 9, 25)), confirm=["turnover_ytd"])
    inputs.remove(WEEK, "kcb_daily_2026-10-02.pdf", root)
    r = suggest("turnover_ytd")
    assert r.status_code == 409 and r.json()["detail"].startswith(
        "Year-to-date equities turnover: this week's figure cannot be worked out: no equities turnover or CBK rate for Friday 02 October")
    assert r.json()["detail"].endswith("Upload what is missing under \"This week's inputs\" and try again, or type this week's total yourself.")
    # the year turned: last year's total is never the base
    r = suggest("turnover_ytd", "2027-01-01")
    assert r.status_code == 409 and r.json()["detail"] == (
        "Year-to-date equities turnover: the running total restarts with the year, so last week's is not carried into it. "
        "Type this week's total, the year so far, yourself.")
    # typed for this week already: never replaced (with this week's figure workable again, so this is the reason left)
    inputs.store(WEEK, "kcb_daily", wh.fake_pdf(wh.kcb_daily_text(WEEK.ending, turnover=500_000_000)), "fri.pdf", root)
    save_week(root, WEEK, fields={"turnover_ytd": "3050"})
    r = suggest("turnover_ytd")
    assert r.status_code == 409 and r.json()["detail"] == (
        "Year-to-date equities turnover is already typed for this week. Clear it first to have a suggestion worked out.")
    assert analyst.read_form(WEEK, root)["fields"] == {"turnover_ytd": "3050"} and analyst.read_form(WEEK, root)["unconfirmed"] == []


def test_the_carry_button_is_offered_only_when_last_week_holds_something_confirmed(tmp_path):
    """can_carry agrees with carry_forward: a week holding only values never confirmed has nothing to start from."""
    before, now = Week(date(2026, 9, 25)), WEEK
    assert analyst.status(now, tmp_path)["can_carry"] is False
    analyst.suggest(before, "turnover_ytd", "3035.6", "seeded", tmp_path)        # held, but never confirmed
    assert analyst.status(now, tmp_path)["can_carry"] is False
    assert "No analyst inputs are saved for the week ending 25 Sep 2026" in refused_carry(now, tmp_path)
    save_week(tmp_path, before, fields={"large_caps": "Safaricom"})
    assert analyst.status(now, tmp_path)["can_carry"] is True
    assert analyst.carry_forward(now, tmp_path)["carried"] == ["large_caps"]


# ---------------------------------------------------------------------------
# Universe of Coverage prices: KCB IB's for this Friday, the stored week's for last Friday
# ---------------------------------------------------------------------------

NCBA = {"company": "NCBA", "month_end_price": "97", "year_open": "85", "target": "120", "dps": "5", "shares_bn": "1.6", "tbv_bn": "110"}


def test_the_friday_price_is_kcbs_and_last_fridays_is_the_price_stored_for_last_week(tmp_path, text_pdfs):
    stores(tmp_path)
    save_week(tmp_path, WEEK.previous, tables={"universe": {"rows": [{"company": "NCBA", "price": "98"}]}})
    save_week(tmp_path, WEEK, fields={"universe_month_end": "2026-09-30"}, tables={"universe": {"rows": [NCBA]}})
    auto = item("universe", tmp_path)
    assert auto["auto_rows"] == [{"company": "NCBA", "price": "100", "last_price": "98"}] and "KCB IB's weekly report" in auto["auto_note"]
    review = eq.build(tmp_path)
    row = blocks(review)["universe_of_coverage"]["rows"][0]
    assert (row["last_price"], row["price"], row["wow"], row["ytd"], row["upside"]) == ("98.0", "100.0", "2.0%", "17.6%", "25.0%")
    note = items(review, "Cytonn Report: Equities Universe of Coverage: NCBA")[0]
    assert note.status == "not_auto_verified"
    assert "price, this friday from KCB IB weekly report of 2026-10-02, NCBA" in note.detail
    assert "price, last friday from the price stored for the week ending 2026-09-25 (analyst input typed on the weekly form" in note.detail
    # a typed Friday price is used, and KCB IB's differing price is shown beside it
    save_week(tmp_path, WEEK, tables={"universe": {"rows": [{**NCBA, "price": "101.5"}]}})
    review = eq.build(tmp_path)
    assert blocks(review)["universe_of_coverage"]["rows"][0]["price"] == "101.5"
    flagged = items(review, "Cytonn Report: Equities Universe of Coverage: NCBA")[0]
    assert flagged.status == "flagged" and flagged.detail[0].kind == SOURCES_DISAGREE
    assert any("NCBA: price: typed as 101.5, but the KCB IB weekly report of 2026-10-02, NCBA has 100" in w for w in review.section["warnings"])
    # a company KCB's report is not matched to, with no typed price: the row says what is missing; nothing is filled in
    save_week(tmp_path, WEEK, tables={"universe": {"rows": [{**NCBA, "company": "Unlisted Co"}]}})
    missing = items(eq.build(tmp_path), "Cytonn Report: Equities Universe of Coverage: Unlisted Co")[0]
    assert missing.status == "flagged" and "no usable price, this friday, price, last friday for Unlisted Co" in missing.detail[0].message


def test_kcbs_friday_price_equals_the_workbooks_for_all_thirteen_companies(tmp_path):
    inputs.store(WEEK, "equities_workbook", wh.sample("Equities Workbook 02.10.2026.v6 (1).xlsx"), "Equities.xlsx", tmp_path)
    inputs.store(WEEK, "kcb_weekly", wh.sample("KCB IB Weekly Trading Market Report - Week 40 - 02Oct2026.pdf"), "w.pdf", tmp_path)
    form = inputs.WeeklyInputs(WEEK, tmp_path).analyst
    companies = form.wb_universe()["companies"]
    assert len(companies) == 13
    for c in companies:
        kcb = form.kcb_price(c["company"].value)
        assert kcb is not None and kcb.number == c["price"].number, c["company"].value
    # so KCB's published price stands beside the workbook's typed one on every row, and agrees
    table = eq.universe_block_for(WEEK, tmp_path)
    assert len(table["second_sources"]) == 13
    review = fi.build_review(*checked(table))
    assert SOURCES_DISAGREE not in {f.kind for i in review.review_items if isinstance(i.detail, list) for f in i.detail}


def checked(table):
    from cytonn_weekly.common.review import check_section, numbered

    content = {"section": "equities", "blocks": numbered([table])}
    return content, check_section(content)


def test_a_single_ocr_reading_says_what_to_check_it_against(tmp_path, text_pdfs):
    inputs.store(WEEK, "kcb_weekly", wh.fake_pdf(wh.kcb_weekly_text()), "weekly.pdf", tmp_path)     # no workbook, no afx
    nse10 = items(eq.build(tmp_path), "Market Performance: NSE 10 week-on-week change")[0]
    assert nse10.status == "flagged" and nse10.detail[0].message.endswith(
        "was read by OCR from NSE daily price list of 2026-10-02 and no second source confirms it. Open the NSE daily price list "
        "of 2026-10-02 (https://www.nse.co.ke/wp-content/uploads/02-OCT-26.pdf) and read the NSE 10 Share Index in its index box, "
        "or check it against the equities team's own figure for that day, before accepting.")
    assert not {"nse_10", "banking", "indices"} & {i["key"] for g in analyst.status(WEEK, tmp_path)["groups"] for i in g["items"]}
