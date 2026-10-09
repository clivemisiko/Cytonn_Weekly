"""The weekly Equities section, worked out from the week's inputs.

Synthetic inputs (tests/weekly_helpers.py) cover the arithmetic and the checking policy.
The golden figures are the Q3'2026 review's "during the week" figures for the week ending
Friday 2 October 2026 (cytonnreport.com issue 892); they need the real, confidential
workbook and KCB IB reports, so those tests skip when the samples are absent.  The NSE
price lists' index boxes used there are NSE's own published figures.
"""

import json
from collections import Counter
from datetime import date

import pytest

from cytonn_weekly.checkers.digital_payments import SOURCES_DISAGREE
from cytonn_weekly.equities import weekly as eqw
from cytonn_weekly.weekly import inputs, nse_price_list, previous_issue
from cytonn_weekly.weekly.week import Week
from tests import weekly_helpers as wh
from tests.test_weekly_fixed_income import ISSUE
from tests.weekly_helpers import text_pdfs  # noqa: F401 - a fixture

WEEK = wh.WEEK
BULLETIN = (wh.FIXTURES / "cbk_weekly_bulletin_2026-10-02.pdf").read_bytes()
RATES = wh.cbk_rates()
YEAR_OPEN = date(2026, 1, 2)

# The index boxes the synthetic week's price lists would print (they agree with the synthetic workbook and KCB report).
SYNTHETIC_BOXES = {
    WEEK.ending: {"nasi": 200.0, "nse_20": 4000.0, "nse_25": 7000.0, "nse_10": 2500.0, "banking": 300.0},
    WEEK.previous_friday: {"nasi": 202.0, "nse_20": 4040.0, "nse_25": 7070.0, "nse_10": 2525.0, "banking": 303.0},
    YEAR_OPEN: {"nasi": 160.0, "nse_20": 3200.0, "nse_25": 5600.0, "nse_10": 2000.0, "banking": 200.0},
}
# NSE's own published closes, as its daily price lists print them (read by OCR on 2026-10-09).
PUBLISHED_BOXES = {
    date(2026, 10, 2): {"nasi": 247.32, "nse_20": 4323.6, "nse_25": 7001.48, "nse_10": 2750.05, "banking": 289.59,
                        "equity_turnover": 622801996.0},
    date(2026, 9, 25): {"nasi": 248.51, "nse_20": 4363.67, "nse_25": 7062.15, "nse_10": 2770.34, "banking": 293.49,
                        "equity_turnover": 751227582.0},
    YEAR_OPEN: {"nasi": 187.35, "nse_20": 3140.93, "nse_25": 5119.32, "nse_10": 1975.5, "banking": 204.38},
}


def fetchers(boxes, **over):
    def price_list(day):
        if day not in boxes:
            raise LookupError(f"NSE has no daily price list for {day.isoformat()}")
        return day.isoformat().encode()

    def read_box(pdf, cache_dir=None, engine=None):
        day = date.fromisoformat(pdf.decode())
        return nse_price_list.IndexBox(day, dict(boxes[day]))

    base = dict(usd_rates=lambda: RATES, price_list=price_list, read_box=read_box, afx_page=lambda: b"",
                bulletin=lambda day: (_ for _ in ()).throw(LookupError("no bulletin")), previous_issue=lambda day, ref: ISSUE)
    return eqw.Fetchers(**{**base, **over})


def build(root, boxes=SYNTHETIC_BOXES, today=date(2026, 10, 9), **over):
    return eqw.build_equities_weekly_review(WEEK.ending, inputs=inputs.WeeklyInputs(WEEK, root), draft=wh.no_draft, today=today,
                                            fetchers=over.pop("fetchers", fetchers(boxes)), **over)


@pytest.fixture
def root(tmp_path, text_pdfs):
    """The synthetic week: the workbook, KCB's weekly report and Friday's daily report, and the real (public) bulletin."""
    inputs.store(WEEK, "equities_workbook", wh.equities_workbook_bytes(), "Equities.xlsx", tmp_path)
    inputs.store(WEEK, "kcb_weekly", wh.fake_pdf(wh.kcb_weekly_text()), "weekly.pdf", tmp_path)
    inputs.store(WEEK, "kcb_daily", wh.fake_pdf(wh.kcb_daily_text(WEEK.ending, turnover=500_000_000)), "fri.pdf", tmp_path)
    inputs.store(WEEK, "cbk_bulletin", BULLETIN, "bulletin.pdf", tmp_path)
    return tmp_path


def blocks(review):
    return {b["id"]: b for b in review.section["blocks"]}


def figures(block):
    return {f["key"]: f["display"] for f in block["figures"]}


def items(review, prefix):
    return [i for i in review.review_items if i.ref.startswith(prefix)]


# ---------------------------------------------------------------------------
# The section from synthetic inputs
# ---------------------------------------------------------------------------

def test_the_section_is_in_the_real_issues_order_with_no_afx_tables(root):
    review = build(root)
    assert [b["id"] for b in review.section["blocks"]] == ["indices", "large_caps", "banking", "turnover", "foreign", "valuation",
                                                          "universe_of_coverage", "outlook"]
    kinds = [b["kind"] for b in review.section["blocks"]]
    assert kinds == ["computed"] * 6 + ["table", "carried"]   # no index table, no gainers or losers table
    assert review.section["chart_notes"] == list(eqw.CHARTS) and review.section["week_ending"] == "2026-10-02"


def test_the_indices_are_ordered_by_the_size_of_their_move(root):
    by = blocks(build(root, boxes={**SYNTHETIC_BOXES, WEEK.ending: {**SYNTHETIC_BOXES[WEEK.ending], "nse_10": 2490.0}}))
    f = figures(by["indices"])
    assert (f["nse_10_wow"], f["nasi_wow"], f["nse_20_wow"], f["nse_25_wow"]) == ("1.4%", "1.0%", "1.0%", "1.0%")
    assert (f["nasi_ytd"], f["nse_10_ytd"]) == ("25.0%", "24.5%")
    assert by["indices"]["body_md"] == (
        "During the week, the equities market was on a downward trajectory, with NSE 10, NSE 25, NSE 20 and NASI losing by "
        "1.4%, 1.0%, 1.0% and 1.0%, respectively, taking the YTD performance to gains of 25.0%, 25.0%, 25.0% and 24.5% for "
        "NSE 25, NSE 20, NASI and NSE 10 respectively.")


def test_a_mixed_week_names_each_indexs_direction(root):
    boxes = {**SYNTHETIC_BOXES, WEEK.ending: {**SYNTHETIC_BOXES[WEEK.ending], "nse_10": 2550.0}}
    text = blocks(build(root, boxes=boxes))["indices"]["body_md"]
    assert text.startswith("During the week, the equities market recorded a mixed performance, with ")
    assert "NSE 10 gaining by 1.0%" in text and "NASI losing by 1.0%" in text


def test_kcbs_levels_are_clean_and_ocr_levels_confirmed_only_by_the_workbook_are_not(root):
    review = build(root)
    status = {i.ref.split(": ", 1)[1].split(" (")[0]: i.status for i in items(review, "Market Performance: N")}
    assert status["NASI week-on-week change"] == "clean" and status["NSE 20 week-on-week change"] == "clean"
    assert status["NSE 10 week-on-week change"] == "not_auto_verified"   # OCR, agreed only by the typed workbook
    assert status["NASI year-to-date change"] == "not_auto_verified"     # the year open is OCR against a typed cell
    nse10 = items(review, "Market Performance: NSE 10 week-on-week change")[0]
    assert "read by OCR from NSE daily price list of 2026-10-02" in nse10.detail and "no published second source" in nse10.detail
    banking = items(review, "Market Performance: Banking Sector index:")
    assert {i.status for i in banking} == {"not_auto_verified"}
    assert blocks(review)["banking"]["body_md"] == ("During the week, the banking sector index decreased by 1.0% to 300.0 from "
                                                    "303.0 recorded the previous week.")


def test_an_ocr_level_with_nothing_to_compare_or_that_disagrees_is_flagged(tmp_path, text_pdfs):
    inputs.store(WEEK, "kcb_weekly", wh.fake_pdf(wh.kcb_weekly_text()), "weekly.pdf", tmp_path)   # no workbook this time
    review = build(tmp_path)
    nse10 = items(review, "Market Performance: NSE 10 week-on-week change")[0]
    assert nse10.status == "flagged" and "no second source confirms it" in nse10.detail[0].message
    assert items(review, "Market Performance: NASI week-on-week change")[0].status == "clean"   # KCB's own levels
    # with the workbook, a typed level that differs from the OCR reading is a sources-disagree flag
    inputs.store(WEEK, "equities_workbook", wh.equities_workbook_bytes(), "Equities.xlsx", tmp_path)
    boxes = {**SYNTHETIC_BOXES, WEEK.ending: {**SYNTHETIC_BOXES[WEEK.ending], "banking": 301.0}}
    banking = items(build(tmp_path, boxes=boxes), "Market Performance: Banking Sector index: Banking Sector index, Friday")[0]
    assert banking.status == "flagged" and banking.detail[0].kind == SOURCES_DISAGREE


AFX_PAGE = (
    '<time datetime="2026-10-02T16:00:00+03:00">x</time> '
    "The NSE All Share Index (NASI) moved down 2.00 (0.99%) points to close at 200.00, representing a one-week loss of 0.99% "
    "and a year-to-date gain of 25.00%. NSE 10 Share Index (-0.10%; -0.99% 1WK; +25.00% YTD) "
    "NSE 20 Share Index (-0.10%; -0.99% 1WK; +25.00% YTD) NSE 25 Share Index (-0.10%; -0.99% 1WK; +25.00% YTD) "
    "NSE Banking Sector Index (-0.10%; -0.99% 1WK; +50.00% YTD)"
)


def test_afx_confirms_the_ocr_indices_only_while_its_page_is_the_fridays(root, monkeypatch):
    monkeypatch.setattr(eqw.afx, "parse_as_of", lambda html: "2026-10-02T16:00:00+03:00")
    with_afx = fetchers(SYNTHETIC_BOXES, afx_page=lambda: AFX_PAGE.encode())
    weekend = build(root, today=date(2026, 10, 3), fetchers=with_afx)
    assert items(weekend, "Market Performance: NSE 10 week-on-week change")[0].status == "clean"   # afx's own -0.99% agrees
    assert items(weekend, "Market Performance: Banking Sector index: Banking Sector index week-on-week change")[0].status == "clean"
    later = build(root, today=date(2026, 10, 9), fetchers=with_afx)    # by then afx shows a later close: not asked
    assert items(later, "Market Performance: NSE 10 week-on-week change")[0].status == "not_auto_verified"
    assert any("afx.kwayisi.org shows only the latest close" in n for n in blocks(later)["indices"]["notes"])
    monkeypatch.setattr(eqw.afx, "parse_as_of", lambda html: "2026-10-05T16:00:00+03:00")
    assert items(build(root, today=date(2026, 10, 3), fetchers=with_afx),
                 "Market Performance: NSE 10 week-on-week change")[0].status == "not_auto_verified"   # the page is not the Friday's


def test_the_large_cap_sentence_follows_the_teams_rule_and_is_always_flagged(root):
    review = build(root)
    b = blocks(review)["large_caps"]
    assert b["body_md"] == (
        "The equities market performance was mainly driven by losses recorded by large-cap stocks such as I&M Holdings, NCBA "
        "and HFCB Group of 2.9%, 2.2% and 1.6% respectively. However, the performance was supported by gains recorded by "
        "large-cap stocks such as Safaricom of 0.3%.")
    assert "EABL" not in b["body_md"]   # EABL moved, but it is not on the workbook's large-cap list
    flagged = [i for i in items(review, "Market Performance: large-cap movers:") if i.status == "flagged"]
    assert len(flagged) == 1 and flagged[0].detail[0].message.startswith("I&M Holdings week-on-week change: check the names")


def test_turnover_is_each_days_kes_over_that_days_cbk_rate(root):
    b = blocks(build(root))["turnover"]
    f = figures(b)
    # Monday to Thursday from the bulletin's Table 6, Friday from KCB's daily report (500,000,000), each over that day's rate
    week = (328.3484709 / 129.67 + 349.7001339 / 129.76 + 539.5584758 / 129.79 + 432.95988 / 129.71 + 500.0 / 129.76)
    last = (1018.33 / 129.49 + 1035.48 / 129.46 + 646.93 / 129.45 + 1182.42 / 129.48 + 751.2275824 / 129.62)
    assert f["turnover"] == f"{week:.1f}" == "16.6" and f["previous_turnover"] == f"{last:.1f}" == "35.8"
    assert f["turnover_change"] == f"{abs(week / last - 1) * 100:.1f}%"
    assert b["body_md"].startswith(f"During the week, equities turnover decreased by {f['turnover_change']} to USD 16.6 mn from "
                                   "USD 35.8 mn recorded the previous week, taking the YTD total turnover to USD ")
    review = build(root)
    week_item = items(review, "Market Performance: equities turnover: Equities turnover over the week")[0]
    # the synthetic workbook's own weekly sum (30.0) is not what the sources give: a human call, not a silent pick
    assert week_item.status == "flagged" and week_item.detail[0].kind == SOURCES_DISAGREE
    assert items(review, "Market Performance: equities turnover: Year-to-date equities turnover")[0].status == "not_auto_verified"


def test_a_day_with_no_turnover_source_makes_the_paragraph_unavailable_naming_the_day(tmp_path, text_pdfs):
    inputs.store(WEEK, "cbk_bulletin", BULLETIN, "bulletin.pdf", tmp_path)   # Monday to Thursday only; no Friday report
    b = blocks(build(tmp_path, boxes={}))["turnover"]
    assert b["kind"] == "unavailable" and b["reason"].startswith("No equities turnover was found for Friday 02 October")
    assert "KCB IB's daily trading report for each missing day" in b["unblock"]
    # the Friday's NSE price list fills the gap, as an OCR reading with no second source: flagged, not silently used
    review = build(tmp_path, boxes={WEEK.ending: {"equity_turnover": 500_000_000.0}})
    assert blocks(review)["turnover"]["kind"] == "computed"
    item = items(review, "Market Performance: equities turnover: Equities turnover over the week")[0]
    assert item.status == "flagged" and "read by OCR" in item.detail[0].message


def test_foreign_flows_come_from_kcbs_weekdays_and_the_streak_from_the_workbook(root):
    review = build(root)
    b = blocks(review)["foreign"]
    f = figures(b)
    flows, days = wh.WEEKDAY_FLOWS, WEEK.trading_days
    net = sum(v / RATES[d] for v, d in zip(flows.values(), days)) / 1e6
    assert f["net_flow"] == f"{net:.1f}" == "0.9" and f["previous_net_flow"] == "1.2"
    assert b["body_md"].startswith("Foreign investors remained net buyers for the second consecutive week with a net buying "
                                   "position of USD 0.9 mn, from a net buying position of USD 1.2 mn recorded the previous week")
    assert "compared to a net selling position of USD 6.0 mn recorded in 2025" in b["body_md"]
    assert "Streak: 2 consecutive weeks of net buying" in " ".join(b["notes"])
    # a change of direction is "for the first time in N weeks"
    selling = {k: -abs(v) for k, v in flows.items()}
    inputs.store(WEEK, "kcb_weekly", wh.fake_pdf(wh.kcb_weekly_text(flows=selling)), "weekly.pdf", root)
    text = blocks(build(root))["foreign"]["body_md"]
    assert text.startswith("Foreign investors became net sellers for the first time in two weeks with a net selling position of USD ")


def test_valuation_is_analyst_input_with_the_fixed_peg_rule(root):
    review = build(root)
    b = blocks(review)["valuation"]
    f = figures(b)
    assert (f["pe"], f["pe_vs_average"], f["pe_average"]) == ("8.0x", "20.0%", "10.0x")
    assert (f["dividend_yield"], f["dividend_yield_vs_average"], f["dividend_yield_average"], f["peg"]) == (
        "6.0%", "1.0% points", "5.0%", "1.0x")   # PEG is the P/E over a fixed 8
    assert b["body_md"] == (
        "The market is currently trading at a price to earnings ratio (P/E) of 8.0x, 20.0% below the historical average of "
        "10.0x, and a dividend yield of 6.0%, 1.0% points above the historical average of 5.0%. Key to note, NASI’s PEG ratio "
        "currently stands at 1.0x. A PEG ratio greater than 1.0x indicates the market may be overvalued while a PEG ratio less "
        "than 1.0x indicates that the market is undervalued.")
    assert {i.status for i in items(review, "Market Performance: valuation:")} == {"not_auto_verified"}
    assert "analyst input from Equities workbook 'NASI-PE & Dividend Yield'!B8" in items(review, "Market Performance: valuation: Market P/E")[0].detail


def test_the_universe_of_coverage_is_worked_out_from_the_workbook_and_sorted_by_upside(root):
    review = build(root)
    table = blocks(review)["universe_of_coverage"]
    assert [c["label"] for c in table["columns"]] == [
        "Company", "Price as at 25/09/2026", "Price as at 02/10/2026", "w/w change", "m/m change", "YTD Change", "Year Open 2026",
        "Target Price*", "Dividend Yield***", "Upside/ Downside**", "P/TBv Multiple", "Recommendation"]
    rows = {r["company"]: r for r in table["rows"]}
    assert [r["company"] for r in table["rows"]] == ["Alpha Bank", "Beta Bank", "Gamma Insurance", "Delta Holdings", "Epsilon Group"]
    alpha = rows["Alpha Bank"]   # 40.0 -> 42.0; month end 39.0; year open 30.0; target 55.0; DPS 3.0; TBV 60.0 bn over 2.0 bn shares
    assert [alpha[k] for k in ("last_price", "price", "wow", "mom", "ytd", "year_open", "target", "dividend_yield", "upside", "ptbv",
                               "recommendation")] == ["40.0", "42.0", "5.0%", "7.7%", "40.0%", "30.0", "55.0", "7.1%", "38.1%", "1.4x", "Buy"]
    assert (rows["Beta Bank"]["recommendation"], rows["Gamma Insurance"]["recommendation"], rows["Epsilon Group"]["recommendation"]) == (
        "Accumulate", "Hold", "Sell")
    assert rows["Gamma Insurance"]["mom"] == "(0.3%)"   # 399.0 against 400.0 is -0.25%: half up, as the checker works it out
    assert rows["Epsilon Group"]["upside"] == "(5.0%)" and table["footnotes"] == list(eqw.FOOTNOTES)
    # between 0% and 0.1% the workbook's rule gives nothing: no recommendation is invented, and the row is flagged
    assert rows["Delta Holdings"]["recommendation"] == "-" and rows["Delta Holdings"]["upside"] == "0.1%"
    delta = items(review, "Cytonn Report: Equities Universe of Coverage: Delta Holdings")[0]
    assert delta.status == "flagged" and "gives no recommendation for an upside between 0% and 0.1%" in delta.detail[0].message
    others = [i for i in items(review, "Cytonn Report: Equities Universe of Coverage:") if "Delta" not in i.ref]
    assert {i.status for i in others} == {"not_auto_verified"} and "'Universe of Coverage' row 3" in others[0].detail


@pytest.mark.parametrize("upside, expected", [(20.0, "Buy"), (19.99, "Accumulate"), (10.0, "Accumulate"), (5.0, "Hold"), (4.9, "Lighten"),
                                              (0.1, "Lighten"), (0.05, None), (0.0, "Sell"), (-3.0, "Sell")])
def test_the_recommendation_rule(upside, expected):
    assert eqw.recommendation(upside) == expected


def test_missing_inputs_leave_named_unavailable_parts(tmp_path):
    def down(*args):
        raise ConnectionError("no route to host")

    review = build(tmp_path, fetchers=eqw.Fetchers(usd_rates=down, price_list=down, read_box=down, afx_page=down, bulletin=down,
                                                   previous_issue=down))
    by = blocks(review)
    assert list(by) == ["indices", "large_caps", "banking", "turnover", "foreign", "valuation", "universe_of_coverage", "outlook"]
    assert {b["kind"] for b in by.values()} == {"unavailable"}
    assert by["large_caps"]["reason"] == "KCB IB's weekly trading report for this week is not among this week's inputs."
    assert by["valuation"]["reason"] == "The equities workbook for this week is not among this week's inputs."
    assert by["foreign"]["reason"].startswith("No foreign net flow was found for Monday 28 September")
    assert {i.status for i in review.review_items} == {"flagged"} and len(review.review_items) == 8
    assert review.section["summary"] == ""


def test_a_workbook_not_updated_for_the_week_says_so_in_each_part(tmp_path, text_pdfs):
    inputs.store(WEEK, "equities_workbook", wh.equities_workbook_bytes(updated=False), "Equities.xlsx", tmp_path)
    by = blocks(build(tmp_path))
    assert "has no row for 2026-10-02: workbook not yet updated for this week" in by["valuation"]["reason"]
    assert "no 'Price as at 02/10/2026' column: workbook not yet updated for this week" in by["universe_of_coverage"]["reason"]


def test_run_events_add_up_to_the_review(root):
    from cytonn_weekly.common.run_events import EventLog

    log = EventLog()
    review = eqw.build_equities_weekly_review(WEEK.ending, inputs=inputs.WeeklyInputs(WEEK, root), draft=wh.no_draft,
                                              today=date(2026, 10, 9), fetchers=fetchers(SYNTHETIC_BOXES), on_event=log)
    counted = Counter()
    for e in log.events:
        if e.kind == "check_finished":
            counted.update(e.counts or {})
    by_status = Counter(i.status for i in review.review_items)
    assert counted["clean"] == by_status["clean"] and counted["not_auto_verified"] == by_status["not_auto_verified"]
    assert counted["flagged"] + 1 == by_status["flagged"]   # plus the carried-forward outlook
    assert [e.label for e in log.events if e.kind == "source_finished"][:2] == [
        "NSE daily price list, 2026-10-02 (OCR)", "NSE daily price list, 2026-09-25 (OCR)"]


# ---------------------------------------------------------------------------
# The real inputs (confidential; skipped when absent): the published week
# ---------------------------------------------------------------------------

@pytest.fixture
def real_root(tmp_path):
    inputs.store(WEEK, "equities_workbook", wh.sample("Equities Workbook 02.10.2026.v6 (1).xlsx"), "Equities.xlsx", tmp_path)
    inputs.store(WEEK, "fi_workbook", wh.sample("FI_MASTERSHEET_05.10.2026.v1.xlsx"), "FI.xlsx", tmp_path)
    inputs.store(WEEK, "kcb_weekly", wh.sample("KCB IB Weekly Trading Market Report - Week 40 - 02Oct2026.pdf"), "w.pdf", tmp_path)
    inputs.store(WEEK, "kcb_daily", wh.sample("KCB IB Daily Trading Market Report - 02Oct2026.pdf"), "d.pdf", tmp_path)
    inputs.store(WEEK, "cbk_bulletin", BULLETIN, "bulletin.pdf", tmp_path)
    return tmp_path


def test_the_real_inputs_reproduce_the_published_week(real_root):
    review = build(real_root, boxes=PUBLISHED_BOXES)
    by = blocks(review)
    assert by["indices"]["body_md"] == (
        "During the week, the equities market was on a downward trajectory, with NSE 20, NSE 25, NSE 10 and NASI losing by "
        "0.9%, 0.9%, 0.7% and 0.5%, respectively, taking the YTD performance to gains of 39.2%, 37.7%, 36.8% and 32.0% for "
        "NSE 10, NSE 20, NSE 25 and NASI respectively.")
    assert by["banking"]["body_md"] == ("During the week, the banking sector index decreased by 1.3% to 289.6 from 293.5 recorded "
                                        "the previous week.")
    assert by["turnover"]["body_md"] == ("During the week, equities turnover decreased by 51.0% to USD 17.5 mn from USD 35.8 mn "
                                         "recorded the previous week, taking the YTD total turnover to USD 3,053.1 mn.")
    # The issue printed the previous week's net buying as USD 0.5 mn; the workbook's 0.570927 rounds to 0.6.
    # Standard rounding is used and the printed 0.5 is a known rounding difference in the issue, not a tool error.
    assert by["foreign"]["body_md"] == (
        "Foreign investors remained net buyers for the second consecutive week with a net buying position of USD 1.2 mn, from a "
        "net buying position of USD 0.6 mn recorded the previous week, taking the YTD foreign net selling position to USD 166.1 "
        "mn, compared to a net selling position of USD 92.9 mn recorded in 2025.")
    v = figures(by["valuation"])
    assert (v["pe"], v["pe_vs_average"], v["pe_average"], v["dividend_yield"], v["dividend_yield_vs_average"],
            v["dividend_yield_average"], v["peg"]) == ("7.6x", "31.9%", "11.2x", "5.8%", "1.0% points", "4.8%", "1.0x")
    assert "31.9% below the historical average of 11.2x" in by["valuation"]["body_md"]
    # every typed figure agrees with the published one wherever both exist
    assert not [f for i in review.review_items if isinstance(i.detail, list) for f in i.detail if f.kind == SOURCES_DISAGREE]
    assert len(by["universe_of_coverage"]["rows"]) == 13


def test_the_large_cap_rule_against_the_two_printed_sentences(real_root):
    """The team's rule (the biggest movers on the workbook's list) does not reproduce either printed sentence."""
    text = blocks(build(real_root, boxes=PUBLISHED_BOXES))["large_caps"]["body_md"]
    assert text == ("The equities market performance was mainly driven by losses recorded by large-cap stocks such as I&M Holdings, "
                    "NCBA and HFCB Group of 2.9%, 2.2% and 1.6% respectively. However, the performance was supported by gains "
                    "recorded by large-cap stocks such as Safaricom of 0.3%.")
    # The Q3'2026 review printed NCBA, Standard Chartered Bank and Equity (2.2%, 1.5%, 1.4%), passing over I&M (2.9%) and HF
    # (1.6%), and named EABL among the gainers, which is not on the workbook's list.  Hence the standing "check the names" flag.


# #38.2026's Universe of Coverage table (week ending 25 September 2026), as published on cytonnreport.com (issue 891).
PRINTED_38 = {
    "Co-op Bank": ("34.8", "37.3", "7.0%", "0.8%", "55.9%", "23.9", "46.1", "6.7%", "30.5%", "1.4x", "Buy"),
    "NCBA": ("86.3", "89.8", "4.1%", "0.6%", "5.6%", "85.0", "108.9", "7.9%", "29.3%", "1.2x", "Buy"),
    "Family Bank": ("28.0", "29.5", "5.4%", "(6.4%)", "63.6%", "18.0", "34.0", "4.1%", "19.5%", "1.5x", "Accumulate"),
    "KCB Group": ("87.0", "93.5", "7.5%", "(0.5%)", "42.2%", "65.8", "104.4", "7.5%", "19.1%", "1.0x", "Accumulate"),
    "ABSA Bank": ("31.1", "33.4", "7.4%", "(3.2%)", "34.4%", "24.9", "36.8", "6.1%", "16.4%", "1.8x", "Accumulate"),
    "Standard Chartered Bank": ("330.8", "324.5", "(1.9%)", "(2.3%)", "8.3%", "299.8", "345.8", "9.6%", "16.1%", "2.0x", "Accumulate"),
    "Stanbic Holdings": ("278.0", "282.5", "1.6%", "0.7%", "42.9%", "197.8", "300.3", "7.9%", "14.2%", "1.6x", "Accumulate"),
    "Jubilee Holdings": ("400.3", "403.5", "0.8%", "(1.5%)", "25.1%", "322.5", "420.5", "3.7%", "7.9%", "0.6x", "Hold"),
    "Equity Group": ("98.5", "107.0", "8.6%", "13.8%", "59.7%", "67.0", "108.8", "5.4%", "7.0%", "1.4x", "Hold"),
    "Diamond Trust Bank": ("179.5", "189.3", "5.4%", "(2.9%)", "64.9%", "114.8", "190.2", "4.8%", "5.3%", "0.5x", "Hold"),
    "CIC Group": ("4.7", "5.1", "7.9%", "5.6%", "11.5%", "4.5", "5.0", "2.6%", "0.6%", "1.3x", "Lighten"),
    "I&M Group": ("80.3", "85.0", "5.9%", "6.9%", "98.6%", "42.8", "81.1", "4.4%", "(0.2%)", "1.4x", "Sell"),
    "Britam": ("17.5", "18.9", "8.0%", "2.2%", "108.6%", "9.1", "18.5", "0.0%", "(2.4%)", "1.4x", "Sell"),
}
COLUMNS = ("last_price", "price", "wow", "mom", "ytd", "year_open", "target", "dividend_yield", "upside", "ptbv", "recommendation")
# The sample workbook is the 2 October version: by then the analysts had revised these four target prices, so their
# Target Price, Upside and Recommendation no longer equal what #38 printed a week earlier.
TARGETS_REVISED_SINCE_38 = {"Family Bank", "Equity Group", "Diamond Trust Bank", "I&M Group"}


def test_the_universe_of_coverage_reproduces_issue_38(tmp_path):
    week = Week(date(2026, 9, 25))
    inputs.store(week, "equities_workbook", wh.sample("Equities Workbook 02.10.2026.v6 (1).xlsx"), "Equities.xlsx", tmp_path)
    market = eqw.Market(week=week, inputs=inputs.WeeklyInputs(week, tmp_path), bulletin=None, rates={}, boxes={}, year_open_day=None,
                        afx=None, typed_indices=None)
    rows = {r["company"]: r for r in eqw.universe_block(market, [])["rows"]}
    assert set(rows) == set(PRINTED_38)
    untouched = ("last_price", "price", "wow", "mom", "ytd", "year_open", "dividend_yield", "ptbv")
    for company, printed in PRINTED_38.items():
        expected = dict(zip(COLUMNS, printed))
        keys = untouched if company in TARGETS_REVISED_SINCE_38 else COLUMNS
        assert {k: rows[company][k] for k in keys} == {k: expected[k] for k in keys}, company
    # nine of the thirteen rows match every printed cell; the other four match everything the revised targets do not touch
    assert len(PRINTED_38) - len(TARGETS_REVISED_SINCE_38) == 9
    for company in TARGETS_REVISED_SINCE_38:
        assert rows[company]["target"] != dict(zip(COLUMNS, PRINTED_38[company]))["target"], company
