"""This week's inputs: the parsers, the workbook readers, the store and its API.

Workbooks and KCB report text are synthetic (tests/weekly_helpers.py).  The CBK Weekly
Bulletin, the NSE daily price list and the NSE yield curve are public documents and are
read from tests/fixtures/sources/.  A few tests read the real, confidential samples and
skip when those are absent.
"""

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly.common.http import NotFound
from cytonn_weekly.report_types import PeriodError, normalize_period, week_ending_of
from cytonn_weekly.weekly import (
    cbk_bulletin,
    cbk_rates,
    equities_workbook,
    fi_workbook,
    inputs,
    kcb,
    nse_price_list,
    nse_yield_curve,
    previous_issue,
)
from cytonn_weekly.weekly.week import NotAFriday, Week, latest_friday, ordinal, table_date
from cytonn_weekly.weekly.workbook import WorkbookError, average_range
from tests import weekly_helpers as wh
from tests.weekly_helpers import text_pdfs  # noqa: F401 - a fixture

WEEK = wh.WEEK
BULLETIN = (wh.FIXTURES / "cbk_weekly_bulletin_2026-10-02.pdf").read_bytes()


# ---------------------------------------------------------------------------
# The week
# ---------------------------------------------------------------------------

def test_a_week_is_named_by_its_friday_and_has_the_reports_windows():
    assert (WEEK.monday, WEEK.thursday, WEEK.previous_friday) == (date(2026, 9, 28), date(2026, 10, 1), date(2026, 9, 25))
    assert WEEK.trading_days == [date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 2)]
    assert WEEK.value_date_window == (date(2026, 10, 3), date(2026, 10, 9))   # a Thursday auction settles the next Monday
    assert WEEK.previous.ending == date(2026, 9, 25)
    assert latest_friday(date(2026, 10, 9)) == date(2026, 10, 9) and latest_friday(date(2026, 10, 8)) == date(2026, 10, 2)
    assert ordinal(date(2026, 10, 2)) == "2nd October 2026" and ordinal(date(2026, 9, 11)) == "11th September 2026"
    assert table_date(date(2026, 1, 2)) == "02-Jan-26"
    with pytest.raises(NotAFriday, match="is a Thursday"):
        Week(date(2026, 10, 1))


def test_a_weekly_period_can_name_its_week_ending_friday():
    assert normalize_period("weekly", "2026-10-02") == "Week ending 2026-10-02"
    assert normalize_period("weekly", "week ending 2026-10-02") == normalize_period("weekly", "W/E 2026-10-02")
    assert week_ending_of("Week ending 2026-10-02") == date(2026, 10, 2)
    assert week_ending_of("Weekly #38.2026") is None and week_ending_of("") is None
    assert normalize_period("weekly", "#38.2026") == "Weekly #38.2026" and normalize_period("weekly", "") == ""  # as before
    with pytest.raises(PeriodError, match="is a Saturday; a weekly report's week ends on a Friday"):
        normalize_period("weekly", "2026-10-03")
    with pytest.raises(PeriodError):   # only the weekly report takes a week
        normalize_period("companion", "2026-10-02")


# ---------------------------------------------------------------------------
# KCB IB reports
# ---------------------------------------------------------------------------

def test_kerned_figures_are_recovered_only_when_there_is_one_way_to_read_them():
    assert kcb.split_numbers(["1", "2,327,385", "1", "6,063,068"], 2) == [12327385.0, 16063068.0]
    assert kcb.split_numbers(["4", ",142.206", "4", ",150.521"], 2) == [4142.206, 4150.521]
    assert kcb.split_numbers(["1", "9,919,129", "8", "5,083,491", "(65,164,362)"], 3) == [19919129.0, 85083491.0, -65164362.0]
    # 251.33 and 245.60, not 251.332 and 45.60: one indicator's two figures print the same decimals
    assert kcb.split_numbers(["251.33", "2", "45.60"], 2, same_decimals=True) == [251.33, 245.6]
    with pytest.raises(kcb.KcbParseError, match="2 ways"):
        kcb.split_numbers(["251.33", "2", "45.60"], 2)
    with pytest.raises(kcb.KcbParseError, match="0 ways"):
        kcb.split_numbers(["12", "34,56"], 1)
    with pytest.raises(kcb.KcbParseError, match="expected 3 figures"):
        kcb.split_numbers(["1"], 3)


def test_a_daily_report_gives_the_indicators_and_the_trading_stats_turnover():
    r = kcb.parse_kcb_text(wh.kcb_daily_text(turnover=500_000_000, net=40_000_000))
    assert (r.kind, r.report_date, r.previous_date) == ("daily", date(2026, 10, 2), date(2026, 10, 1))
    assert r.indicators["nasi"] == {"previous": 199.0, "current": 200.0}
    assert r.indicators["market_cap_bn"] == {"previous": 3990.0, "current": 4000.0}
    assert r.indicators["net_flows"]["current"] == 40_000_000 and r.equities_turnover == 500_000_000
    assert r.securities["SCOM"] == {"price": 36.55, "change_pct": 0.41, "currency": "KES"}
    assert r.problems == [] and r.daily_foreign_flows == {}


def test_a_weekly_report_gives_both_fridays_each_weekdays_flows_and_each_stocks_move():
    r = kcb.parse_kcb_text(wh.kcb_weekly_text())
    assert (r.kind, r.report_date, r.previous_date) == ("weekly", date(2026, 10, 2), date(2026, 9, 25))
    assert r.indicators["nasi"] == {"previous": 202.0, "current": 200.0}
    assert {d: f["net"] for d, f in r.daily_foreign_flows.items()} == wh.WEEKDAY_FLOWS
    assert r.foreign_flows_total["net"] == sum(wh.WEEKDAY_FLOWS.values())
    assert r.securities["IMH"]["change_pct"] == -2.94 and r.securities["EABL"]["change_pct"] == 0.79
    assert r.equities_turnover == 2_273_368_956   # the Equities row of TRADING STATS, not the "Equities TO" indicator
    assert r.indicators["equities_to_indicator"]["current"] == 2_279_873_699
    assert r.problems == []


def test_flows_that_do_not_add_up_are_named_not_used():
    text = wh.kcb_weekly_text().replace("(60,000,000)", "(61,000,000)")
    r = kcb.parse_kcb_text(text)
    assert "Monday" not in r.daily_foreign_flows
    assert any("Monday: inflows less outflows does not equal the printed net" in p for p in r.problems)


def test_a_file_that_is_not_a_kcb_report_is_refused():
    with pytest.raises(kcb.KcbParseError, match="not a KCB IB market report"):
        kcb.parse_kcb_text("CENTRAL BANK OF KENYA\nWeekly Bulletin")
    with pytest.raises(kcb.KcbParseError, match="no 'Indicator <date> <date>' header row"):
        kcb.parse_kcb_text("DAILY MARKET REPORT\nFriday, 02 October 2026\nnothing else")


def test_the_real_kcb_samples_read_cleanly():
    daily = kcb.parse_kcb_pdf(wh.sample("KCB IB Daily Trading Market Report - 02Oct2026.pdf"))
    weekly = kcb.parse_kcb_pdf(wh.sample("KCB IB Weekly Trading Market Report - Week 40 - 02Oct2026.pdf"))
    assert daily.problems == [] and weekly.problems == []
    assert (daily.report_date, weekly.report_date, weekly.previous_date) == (date(2026, 10, 2), date(2026, 10, 2), date(2026, 9, 25))
    # NSE's own published figures for the day, which the reports repeat
    assert daily.equities_turnover == 622_801_996 and daily.indicators["nasi"]["current"] == 247.32
    assert weekly.indicators["nse_20"] == {"previous": 4363.67, "current": 4323.6}
    assert len(weekly.daily_foreign_flows) == 5


# ---------------------------------------------------------------------------
# CBK Weekly Bulletin (a public document)
# ---------------------------------------------------------------------------

def test_the_bulletin_reads_tables_1_to_6():
    b = cbk_bulletin.parse_bulletin(BULLETIN)
    assert (b.issue_date, b.last_day, b.problems) == (date(2026, 10, 2), date(2026, 10, 1), [])
    # Table 1
    assert b.exchange_rates[date(2026, 10, 1)] == 129.71 and b.exchange_rates[date(2026, 9, 25)] == 129.62
    # Table 2
    assert b.reserves[-1] == {"date": date(2026, 10, 1), "usd_mn": 14930.0, "months": 6.1}
    assert b.reserves[-2]["usd_mn"] == 15042.0
    # Table 3: the weekly rows are Friday to Thursday
    assert [(w["last_day"], w["value_mn"], w["kesonia"]) for w in b.interbank_weeks] == [
        (date(2026, 9, 24), 14472.0, 8.75), (date(2026, 10, 1), 9500.0, 8.75)]
    assert b.interbank[-1] == {"date": date(2026, 10, 1), "deals": 9.0, "value_mn": 4300.0, "kesonia": 8.75}
    # Table 4
    assert b.tbills["91-day"][-1] == {"date": date(2026, 10, 1), "offered": 8000.0, "bids": 17983.23, "accepted": 12875.06,
                                      "rate": 8.769}
    assert b.tbills["364-day"][-2]["rate"] == 9.043
    # Table 5, as printed
    assert b.tbonds["codes"][-2:] == ["FXD3/2019/015", "FXD1/2019/020"] and b.tbonds["bids"][-2:] == [34559.26, 46003.11]
    assert b.tbonds["offered"] == [60000.0, 10000.0, 60000.0, 50000.0]
    # Table 6: each Eurobond yield is under the year printed above its column
    last = b.market[-1]
    assert last["date"] == date(2026, 10, 1) and last["nasi"] == 246.82 and last["equity_turnover_mn"] == 432.95988
    assert last["eurobond_yields"] == {2028: 7.626, 2031: 8.309, 2032: 8.752, 2034: 9.202, 2036: 9.672, 2038: 9.952,
                                       2039: 9.924, 2048: 9.799}
    assert len(b.market) == 10 and b.market[0]["date"] == date(2026, 9, 18)


def test_a_pdf_that_is_not_the_bulletin_is_refused():
    with pytest.raises(cbk_bulletin.BulletinParseError, match="not a CBK Weekly Bulletin"):
        cbk_bulletin.parse_bulletin((wh.FIXTURES / "nse_yield_curve_07-10-2026.pdf").read_bytes())


LISTING = """
<a href="/uploads/weekly_bulletin/1216473036_Weekly CBK Bulletin Feb 6 2026.pdf">x</a>
<a href="/uploads/weekly_bulletin/502949172_Weekly CBK Bulletin April 24, 2026.pdf">x</a>
<a href="/uploads/weekly_bulletin/1596007887_Weekly CBK Bulletin 18 September 2026_260918_161546.pdf">x</a>
<a href="/uploads/weekly_bulletin/1344231437_Weekly CBK Bulletin, 2 October, 2026.pdf">x</a>
<a href="/uploads/weekly_bulletin/2100282233_07-10-2016.pdf">x</a>
"""


def test_the_bulletin_is_found_by_its_issue_date_however_cbk_names_the_file():
    assert cbk_bulletin.link_date("/x/1216473036_Weekly CBK Bulletin Feb 6 2026.pdf") == date(2026, 2, 6)
    assert cbk_bulletin.link_date("/x/502949172_Weekly CBK Bulletin April 24, 2026.pdf") == date(2026, 4, 24)
    assert cbk_bulletin.link_date("/x/1596007887_Weekly CBK Bulletin 18 September 2026_260918_161546.pdf") == date(2026, 9, 18)
    assert cbk_bulletin.link_date("/x/2100282233_07-10-2016.pdf") is None   # no month name: not guessed
    url = cbk_bulletin.bulletin_url(LISTING, date(2026, 10, 2))
    assert url == "https://www.centralbank.go.ke/uploads/weekly_bulletin/1344231437_Weekly%20CBK%20Bulletin%2C%202%20October%2C%202026.pdf"
    assert cbk_bulletin.bulletin_url(LISTING, date(2026, 10, 9)) is None


def test_fetching_the_bulletin_asks_cbk_for_that_fridays_issue():
    asked = []

    def get(url):
        asked.append(url)
        return LISTING.encode() if url == cbk_bulletin.LISTING else BULLETIN

    data, url = cbk_bulletin.fetch_bulletin(date(2026, 10, 2), get)
    assert data == BULLETIN and asked == [cbk_bulletin.LISTING, url]
    with pytest.raises(LookupError, match="lists no issue dated 2026-10-09"):
        cbk_bulletin.fetch_bulletin(date(2026, 10, 9), get)


# ---------------------------------------------------------------------------
# CBK daily rates, the NSE yield curve
# ---------------------------------------------------------------------------

def test_cbk_rates_are_read_from_the_tables_answer():
    payload = json.dumps({"data": [["02/10/2026", "US DOLLAR", "129.7600"], ["02/01/2026", "US DOLLAR", "129.0500"]]}).encode()
    posted = []
    rates = cbk_rates.fetch_usd_rates(lambda url, form: posted.append((url, form)) or payload)
    assert rates == {date(2026, 10, 2): 129.76, date(2026, 1, 2): 129.05}
    assert posted[0][0] == cbk_rates.URL and posted[0][1]["columns[1][search][value]"] == "US DOLLAR"
    with pytest.raises(ValueError, match="'EURO' where 'US DOLLAR' was asked for"):
        cbk_rates.parse_rates(json.dumps({"data": [["02/10/2026", "EURO", "145.0"]]}).encode())
    with pytest.raises(ValueError, match="no US dollar rows"):
        cbk_rates.parse_rates(b'{"data": []}')


def test_the_yield_curve_reads_every_tenor_and_interpolates_between_whole_years():
    curve = nse_yield_curve.parse_yield_curve((wh.FIXTURES / "nse_yield_curve_07-10-2026.pdf").read_bytes())
    assert curve.curve_date == date(2026, 10, 7) and curve.days == {91: 8.7694, 182: 8.8856}
    assert (curve.years[1], curve.years[7], curve.years[8], curve.years[29]) == (9.0397, 12.4671, 12.4437, 13.0749)
    assert len(curve.years) == 29
    assert curve.at(7.0) == 12.4671 and round(curve.at(7.8), 4) == round(12.4671 + (12.4437 - 12.4671) * 0.8, 4)
    assert curve.at(0.5) is None and curve.at(29.5) is None   # never extrapolated


def test_a_curve_that_skips_a_tenor_or_has_no_title_is_refused():
    text = wh.yield_curve_text()
    assert nse_yield_curve.parse_yield_curve_text(text).curve_date == date(2026, 10, 2)
    with pytest.raises(nse_yield_curve.YieldCurveParseError, match=r"skips tenor\(s\) \[5\]"):
        nse_yield_curve.parse_yield_curve_text("\n".join(line for line in text.splitlines() if not line.startswith("5 ")))
    with pytest.raises(nse_yield_curve.YieldCurveParseError, match="title is missing"):
        nse_yield_curve.parse_yield_curve_text("SOMETHING ELSE\n02-10-2026\n1 9.1000")


# ---------------------------------------------------------------------------
# NSE daily price list (OCR)
# ---------------------------------------------------------------------------

def _box_words(turnover: str = "429,514,861", nasi: str = "245.34"):
    """OCR words laid out like the index box (left: the indices; right: the day's statistics)."""
    y = iter(range(100, 2000, 34))
    left = [
        "NSE ALL SHARE INDEX (NASI) - 01st Jan 2008 = 100", f"Down 0.32 points to closo at {nasi}",
        "NSE 20-SHARE INDEX - (1966 = 100 )", "Up 10.23 points to close at 4323.26",
        "NSE25-SHAREINDEX-(01st Sep 2015 = 4101.67)", "Up 1.18 polnts to olose at 6967.38",   # OCR drops spaces and misreads letters
        "NSE 10-SHARE INDEX - (30th Aug 2023 = 1000)", "Down 0.90 points to close at 2737.01",
        "BANKING SECTOR INDEX - (1st Sep 2025 = 173.64)", "Up 0.33 points to close at 288.71",
    ]
    words = [(500.0, float(top), 1100.0, float(top) + 24, text) for text, top in zip(left, y)]
    right = [(100, "Market Capitalization in Kes. Billion", None), (134, "Today", "Previous"), (168, "4,117.371", "4,122.718"),
             (236, "Numbcr of SharesTraded", None), (270, "Today", "Previous"), (304, "11,862,339", "7,569,604"),
             (372, "Equity Turnc", None), (406, "Today", "Previous"), (440, turnover, "223,637,662")]
    for top, a, b in right:
        words.append((1800.0, float(top), 1990.0, top + 22.0, a))
        if b:
            words.append((2000.0, float(top), 2130.0, top + 22.0, b))
    return words


def test_the_index_box_is_read_by_its_labels_despite_ocr_spelling():
    words = _box_words()
    assert nse_price_list.read_indices(words) == {"nasi": 245.34, "nse_20": 4323.26, "nse_25": 6967.38, "nse_10": 2737.01,
                                                  "banking": 288.71}
    assert nse_price_list.read_stats(words) == {"market_cap_bn": 4117.371, "shares_traded": 11862339.0,
                                                "equity_turnover": 429514861.0}
    assert nse_price_list.read_list_date([(0, 0, 10, 10, "October8,2026")]) == date(2026, 10, 8)
    assert nse_price_list.price_list_url(date(2026, 10, 8)) == "https://www.nse.co.ke/wp-content/uploads/08-OCT-26.pdf"


class _Page:
    """Stands in for a rendered page: only its size and slicing are used."""

    shape = (3300, 2550, 3)

    def __getitem__(self, _):
        return self


def test_a_figure_is_kept_only_when_two_readings_of_the_box_agree(monkeypatch):
    monkeypatch.setattr(nse_price_list, "_enlarge", lambda image, scale: image)
    readings = iter([[(0, 0, 10, 10, "October8,2026")],        # the top of page 1: the date
                     _box_words(),                              # the whole page: finds the box
                     _box_words(),                              # the box, first reading
                     _box_words(turnover="420,514,861")])       # the box, second reading: one figure differs
    box = nse_price_list.read_index_box(b"%PDF", engine=lambda image: next(readings), render=lambda pdf: [_Page()])
    assert box.list_date == date(2026, 10, 8)
    assert box.values["nasi"] == 245.34 and box.values["banking"] == 288.71 and box.values["market_cap_bn"] == 4117.371
    assert "equity_turnover" not in box.values
    assert box.problems == ["equity_turnover: two OCR readings disagree (429514861.0, 420514861.0); left out"]


def test_a_list_with_no_index_box_is_an_error_and_a_missing_list_is_a_lookup_error():
    with pytest.raises(nse_price_list.PriceListError, match="no index box"):
        nse_price_list.read_index_box(b"%PDF", engine=lambda image: [(0, 0, 9, 9, "nothing here")], render=lambda pdf: [_Page()])

    def missing(url):
        raise NotFound(url)

    with pytest.raises(LookupError, match="no daily price list for 2026-10-04"):
        nse_price_list.fetch_price_list(date(2026, 10, 4), missing)


def test_a_reading_is_remembered_per_pdf(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(nse_price_list, "read_index_box",
                        lambda pdf, engine=None: calls.append(pdf) or nse_price_list.IndexBox(date(2026, 10, 8), {"nasi": 245.34}))
    first = nse_price_list.read_index_box_cached(b"%PDF one", tmp_path)
    again = nse_price_list.read_index_box_cached(b"%PDF one", tmp_path)
    assert first.to_dict() == again.to_dict() and calls == [b"%PDF one"]
    nse_price_list.read_index_box_cached(b"%PDF two", tmp_path)
    assert len(calls) == 2


def test_the_8_october_2026_price_list_ocrs_to_the_published_figures():
    """The real, public NSE list (a scanned image).  Takes about 40 seconds: it runs the OCR engine."""
    pytest.importorskip("rapidocr_onnxruntime")
    box = nse_price_list.read_index_box((wh.FIXTURES / "nse_daily_price_list_08-OCT-26.pdf").read_bytes())
    assert box.list_date == date(2026, 10, 8) and box.problems == []
    assert box.values == {"nasi": 245.34, "nse_20": 4323.26, "nse_25": 6967.38, "nse_10": 2737.01, "banking": 288.71,
                          "market_cap_bn": 4117.371, "shares_traded": 11862339.0, "equity_turnover": 429514861.0}


# ---------------------------------------------------------------------------
# Workbook readers (synthetic workbooks)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def eq_book():
    return equities_workbook.open_equities_workbook(wh.equities_workbook_bytes())


@pytest.fixture(scope="module")
def fi_book():
    return fi_workbook.open_fi_workbook(wh.fi_workbook_bytes())


def test_index_levels_are_found_by_their_labels_with_the_cell_they_came_from(eq_book):
    idx = equities_workbook.read_indices(eq_book, 2026)
    assert {k: v["today"].value for k, v in idx.items()} == {"nse_20": 4000.0, "nasi": 200.0, "nse_25": 7000.0, "nse_10": 2500.0,
                                                           "banking": 300.0}
    assert idx["nasi"]["year_open"].ref == "'Kenyan Indices '!E4" and idx["banking"]["last_week"].ref == "'Kenyan Indices '!D23"
    with pytest.raises(WorkbookError, match="'Year Open 2027' header"):
        equities_workbook.read_indices(eq_book, 2027)


def test_the_weeks_turnover_and_flows_are_found_by_date(eq_book):
    turnover = equities_workbook.read_turnover(eq_book, WEEK)
    assert sorted(turnover.days) == WEEK.trading_days and round(turnover.total.number, 6) == 30.0
    assert turnover.ytd.sheet == "Equities Turnover" and turnover.history[-1][0] == WEEK.ending
    flows = equities_workbook.read_foreign_flows(eq_book, WEEK)
    assert round(flows.total.number, 6) == 1.2 and flows.history[-2][1] > 0 and flows.history[-3][1] < 0
    # the year before's close is the running total on the row before the count restarted
    prior = equities_workbook.prior_year_total(flows, 2026)
    assert prior is not None and round(prior.number, 6) == -6.0
    assert equities_workbook.prior_year_total(flows, 2030) is None


def test_valuation_large_caps_and_the_universe_are_read_for_the_week(eq_book):
    v = equities_workbook.read_valuation(eq_book, WEEK)
    assert (v["pe"].number, v["pe_average"].number, v["dividend_yield"].number, v["peg_sheet"].number) == (8.0, 10.0, 0.06, 1.0)
    assert v["pe"].ref == "'NASI-PE & Dividend Yield'!B8" and v["previous_pe"].number == 8.01
    assert [c.value for c in equities_workbook.read_large_caps(eq_book)] == wh.LARGE_CAPS
    u = equities_workbook.read_universe(eq_book, WEEK)
    assert u["month_end"] == date(2026, 9, 30) and [c["company"].value for c in u["companies"]] == [r[0] for r in wh.UNIVERSE]
    alpha = u["companies"][0]
    assert {k: alpha[k].number for k in ("last_price", "month_end_price", "price", "year_open", "target", "dps", "shares_bn",
                                         "tbv_bn")} == {"last_price": 40.0, "month_end_price": 39.0, "price": 42.0,
                                                        "year_open": 30.0, "target": 55.0, "dps": 3.0, "shares_bn": 2.0,
                                                        "tbv_bn": 60.0}


def test_a_workbook_not_yet_updated_for_the_week_says_so():
    stale = equities_workbook.open_equities_workbook(wh.equities_workbook_bytes(updated=False))
    with pytest.raises(WorkbookError, match="'NASI-PE & Dividend Yield' has no row for 2026-10-02: workbook not yet updated for this week"):
        equities_workbook.read_valuation(stale, WEEK)
    with pytest.raises(WorkbookError, match=r"no 'Price as at 02/10/2026' column: workbook not yet updated for this week"):
        equities_workbook.read_universe(stale, WEEK)
    assert equities_workbook.read_turnover(stale, WEEK).total is None
    stale_fi = fi_workbook.open_fi_workbook(wh.fi_workbook_bytes(updated=False))
    with pytest.raises(WorkbookError, match="is for value date 2026-09-28 .* workbook not yet updated for this week"):
        fi_workbook.read_tbills(stale_fi, WEEK)
    with pytest.raises(WorkbookError, match="is as published on 2026-09-25, not 2026-10-02: workbook not yet updated"):
        fi_workbook.read_mmf_table(stale_fi, WEEK)


def test_the_fixed_income_workbook_is_read_by_label_and_date(fi_book):
    tb = fi_workbook.read_tbills(fi_book, WEEK)
    assert tb["value_date"].day == date(2026, 10, 5) and tb["91-day"]["bids"].number == 17983.23
    assert tb["364-day"]["previous_rate"].ref == "'Treasury Bills '!AC394"
    assert fi_workbook.read_placements(fi_book).ref == "'Money Market Performance'!C6"
    table = fi_workbook.read_mmf_table(fi_book, WEEK)
    assert table["published"] == WEEK.ending and [f["rate"].number for f in table["funds"]] == [r for _, r in wh.FUNDS]
    assert fi_workbook.read_mmf_last_week(fi_book).number == 0.109
    days = fi_workbook.read_interbank(fi_book, WEEK.previous_friday, WEEK.thursday)
    assert [d["date"] for d in days] == [date(2026, 9, 25), date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 1)]
    assert fi_workbook.read_exchange_rates(fi_book)[WEEK.ending].number == 129.76   # CBK's published rate, as typed
    assert fi_workbook.read_reserves(fi_book)[0]["usd_bn"].number == 14.93
    months = fi_workbook.read_remittances(fi_book)
    assert (months[0]["year"], months[0]["month"], months[0]["north_america"].number) == (2026, 8, 200.0)
    loans = fi_workbook.read_borrowing(fi_book)
    assert loans["fy_start"].day == date(2026, 7, 1) and loans["target_bn"].number == 910.0
    assert loans["log"][0]["date"] == date(2026, 7, 6) and loans["log"][-1]["date"] == date(2026, 10, 5)


def test_each_eurobond_issue_is_read_from_its_own_dated_column(fi_book):
    series = fi_workbook.read_eurobonds(fi_book)
    assert [s.key for s in series] == ["2018_10y", "2018_30y", "2019_12y", "2021_13y", "2024_7y"]   # the 2025 11-year is not printed
    ten = series[0]
    assert ten.yields[date(2026, 10, 1)].number == wh.eurobond_yield(0.070, date(2026, 10, 1))
    assert ten.issue["maturity"].day == date(2028, 2, 28) and ten.issue["amount_before"].number == 1000
    assert series[2].issue["amount_before"].number == 1200 and series[4].maturity_year == 2031


def test_a_file_that_is_not_the_workbook_is_refused():
    with pytest.raises(WorkbookError, match="is not the equities workbook: it has no sheet 'Kenyan Indices '"):
        equities_workbook.open_equities_workbook(wh.fi_workbook_bytes())
    with pytest.raises(WorkbookError, match="is not the fixed income workbook"):
        fi_workbook.open_fi_workbook(wh.equities_workbook_bytes())
    with pytest.raises(WorkbookError, match="could not be opened as an Excel workbook"):
        equities_workbook.open_equities_workbook(b"PK\x03\x04 not really a zip")
    assert average_range("=AVERAGE(B8:B938)") == ("B", 8, 938) and average_range("=SUM(B8:B938)") is None


def test_the_real_workbooks_hold_what_the_readers_expect():
    """The confidential samples: only that each reader finds its week; no figure from them is written here."""
    eq = equities_workbook.open_equities_workbook(wh.sample("Equities Workbook 02.10.2026.v6 (1).xlsx"))
    fi = fi_workbook.open_fi_workbook(wh.sample("FI_MASTERSHEET_05.10.2026.v1.xlsx"))
    assert set(equities_workbook.read_indices(eq, 2026)) == {"nse_20", "nasi", "nse_25", "nse_10", "banking"}
    assert sorted(equities_workbook.read_turnover(eq, WEEK).days) == WEEK.trading_days
    v = equities_workbook.read_valuation(eq, WEEK)
    assert v["pe_average_recomputed"] is not None and abs(v["pe_average_recomputed"][0] - v["pe_average"].number) < 1e-9
    assert len(equities_workbook.read_large_caps(eq)) == 11 and len(equities_workbook.read_universe(eq, WEEK)["companies"]) == 13
    assert fi_workbook.read_tbills(fi, WEEK)["value_date"].day == date(2026, 10, 5)
    assert len(fi_workbook.read_mmf_table(fi, WEEK)["funds"]) == 34
    assert all(date(2026, 10, 1) in s.yields and s.issue is not None for s in fi_workbook.read_eurobonds(fi))
    assert fi_workbook.read_borrowing(fi)["log"][-1]["date"] == date(2026, 10, 5)
    assert inputs.equities_workbook_date(eq) == WEEK.ending and inputs.fi_workbook_date(fi) == WEEK.ending


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def test_an_upload_is_checked_read_and_filed_under_the_week(tmp_path, text_pdfs):
    entry = inputs.store(WEEK, "equities_workbook", wh.equities_workbook_bytes(), "Equities Workbook 02.10.2026.xlsx", tmp_path)
    assert (entry["stored_name"], entry["read_date"], entry["matches"]) == ("equities_workbook.xlsx", "2026-10-02", True)
    assert (tmp_path / "2026-10-02" / "equities_workbook.xlsx").is_file()
    stale = inputs.store(WEEK, "fi_workbook", wh.fi_workbook_bytes(updated=False), "FI.xlsx", tmp_path)
    assert (stale["read_date"], stale["matches"]) == ("2026-09-25", False)   # stored, and shown as last week's
    daily = inputs.store(WEEK, "kcb_daily", wh.fake_pdf(wh.kcb_daily_text(date(2026, 9, 30))), "KCB daily.pdf", tmp_path)
    assert daily["stored_name"] == "kcb_daily_2026-09-30.pdf" and daily["matches"] is True
    weekly = inputs.store(WEEK, "kcb_weekly", wh.fake_pdf(wh.kcb_weekly_text()), "KCB weekly.pdf", tmp_path)
    assert weekly["read_date"] == "2026-10-02"
    bulletin = inputs.store(WEEK, "cbk_bulletin", BULLETIN, "bulletin.pdf", tmp_path)
    assert bulletin["matches"] is True and bulletin["fetched_from"] is None
    curve = inputs.store(WEEK, "nse_yield_curve", wh.fake_pdf(wh.yield_curve_text(date(2026, 10, 7))), "curve.pdf", tmp_path)
    assert (curve["read_date"], curve["matches"]) == ("2026-10-07", False)


@pytest.mark.parametrize("slot, make, message", [
    ("equities_workbook", lambda: b"", "the file is empty"),
    ("equities_workbook", lambda: b"%PDF-1.4 not a workbook", "this is not an Excel workbook"),
    ("kcb_weekly", lambda: b"PK not a pdf", "this is not a PDF file"),
    ("cbk_bulletin", lambda: b"x" * (inputs.MAX_BYTES + 1), "the limit is 30 MB"),
    ("nope", lambda: b"%PDF", "unknown input 'nope'"),
], ids=["empty", "pdf-as-workbook", "zip-as-pdf", "too-big", "unknown-slot"])
def test_an_upload_of_the_wrong_kind_or_size_is_refused_and_nothing_is_stored(tmp_path, slot, make, message):
    with pytest.raises(inputs.InputError, match=message):
        inputs.store(WEEK, slot, make(), "x", tmp_path)
    assert not (tmp_path / "2026-10-02").exists() or not list((tmp_path / "2026-10-02").iterdir())


def test_an_upload_that_is_the_wrong_document_is_refused_with_the_reason(tmp_path, text_pdfs):
    with pytest.raises(inputs.InputError, match="is not the equities workbook"):
        inputs.store(WEEK, "equities_workbook", wh.fi_workbook_bytes(), "x.xlsx", tmp_path)
    with pytest.raises(inputs.InputError, match="this is KCB's weekly report, dated 2026-10-02, not a daily one"):
        inputs.store(WEEK, "kcb_daily", wh.fake_pdf(wh.kcb_weekly_text()), "x.pdf", tmp_path)
    with pytest.raises(inputs.InputError, match="dated 2026-10-05, which is not in the week 2026-09-28 to 2026-10-02"):
        inputs.store(WEEK, "kcb_daily", wh.fake_pdf(wh.kcb_daily_text(date(2026, 10, 5))), "x.pdf", tmp_path)
    with pytest.raises(inputs.InputError, match="not a CBK Weekly Bulletin"):
        inputs.store(WEEK, "cbk_bulletin", (wh.FIXTURES / "nse_yield_curve_07-10-2026.pdf").read_bytes(), "x.pdf", tmp_path)


def test_the_status_shows_each_slot_and_each_missing_daily(tmp_path, text_pdfs):
    empty = inputs.status(WEEK, tmp_path)
    assert [s["slug"] for s in empty["slots"]] == ["equities_workbook", "fi_workbook", "kcb_daily", "kcb_weekly", "cbk_bulletin",
                                                 "nse_yield_curve"]
    assert not any(s["received"] for s in empty["slots"]) and empty["notes"] == {}
    inputs.store(WEEK, "kcb_daily", wh.fake_pdf(wh.kcb_daily_text(date(2026, 10, 2))), "fri.pdf", tmp_path)
    inputs.store(WEEK, "fi_workbook", wh.fi_workbook_bytes(), "FI.xlsx", tmp_path)
    by = {s["slug"]: s for s in inputs.status(WEEK, tmp_path)["slots"]}
    assert [(d["weekday"], d["received"]) for d in by["kcb_daily"]["days"]] == [
        ("Monday", False), ("Tuesday", False), ("Wednesday", False), ("Thursday", False), ("Friday", True)]
    assert by["kcb_daily"]["received"] is True and by["kcb_daily"]["complete"] is False
    assert by["fi_workbook"]["file"]["read_date"] == "2026-10-02" and by["fi_workbook"]["complete"] is True
    assert by["cbk_bulletin"]["fetchable"] is True and by["nse_yield_curve"]["optional"] is True
    assert inputs.remove(WEEK, "kcb_daily_2026-10-02.pdf", tmp_path) and not inputs.remove(WEEK, "kcb_daily_2026-10-02.pdf", tmp_path)
    assert {s["slug"]: s for s in inputs.status(WEEK, tmp_path)["slots"]}["kcb_daily"]["received"] is False


def test_notes_are_kept_per_week_and_a_blank_clears_one(tmp_path):
    assert inputs.write_notes(WEEK, {"bidding_range": " FXD1/2019/020:  12.8% - 13.3% "}, tmp_path) == {
        "bidding_range": "FXD1/2019/020: 12.8% - 13.3%"}
    inputs.write_notes(WEEK, {"previous_issue": "https://cytonnreport.com/research/x"}, tmp_path)
    assert set(inputs.read_notes(WEEK, tmp_path)) == {"bidding_range", "previous_issue"}
    assert inputs.write_notes(WEEK, {"bidding_range": ""}, tmp_path) == {"previous_issue": "https://cytonnreport.com/research/x"}
    assert inputs.read_notes(WEEK.previous, tmp_path) == {}
    with pytest.raises(inputs.InputError, match="unknown note"):
        inputs.write_notes(WEEK, {"other": "x"}, tmp_path)


def test_stored_inputs_are_read_back_parsed_and_a_missing_one_is_none(tmp_path, text_pdfs):
    wi = inputs.WeeklyInputs(WEEK, tmp_path)
    assert wi.equities_book is None and wi.bulletin is None and wi.kcb_daily == {} and wi.notes == {}
    inputs.store(WEEK, "equities_workbook", wh.equities_workbook_bytes(), "e.xlsx", tmp_path)
    inputs.store(WEEK, "kcb_daily", wh.fake_pdf(wh.kcb_daily_text()), "d.pdf", tmp_path)
    inputs.store(WEEK, "cbk_bulletin", BULLETIN, "b.pdf", tmp_path)
    wi = inputs.WeeklyInputs(WEEK, tmp_path)
    assert "Kenyan Indices " in wi.equities_book.sheet_names and list(wi.kcb_daily) == [WEEK.ending]
    assert wi.bulletin.issue_date == WEEK.ending and wi.matches("cbk_bulletin.pdf") is True and wi.matches("x.pdf") is None
    assert wi.cache_dir == tmp_path.parent / "ocr_cache"


def test_inputs_default_to_a_folder_under_the_data_directory_never_the_repository(monkeypatch):
    from cytonn_weekly import paths

    monkeypatch.setattr(inputs, "_DEFAULT_ROOT", None)
    assert inputs.inputs_root() == paths.DATA_DIR / "inputs" / "weekly"
    assert inputs.week_dir(WEEK).name == "2026-10-02"


# ---------------------------------------------------------------------------
# The API
# ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    def fetch(day):
        if day != WEEK.ending:
            raise LookupError(f"CBK's weekly bulletin page lists no issue dated {day.isoformat()}")
        return BULLETIN, "https://www.centralbank.go.ke/uploads/weekly_bulletin/1344231437_Weekly CBK Bulletin, 2 October, 2026.pdf"

    return TestClient(create_app(db_path=tmp_path / "app.db", load_dotenv=False, inputs_root=tmp_path / "weekly",
                                 fetch_bulletin=fetch))


def test_the_panel_uploads_a_file_as_the_request_body_and_sees_its_date(client, tmp_path, text_pdfs):
    assert client.get("/api/inputs/weekly/2026-10-02").json()["slots"][0]["received"] is False
    r = client.put("/api/inputs/weekly/2026-10-02/equities_workbook?filename=Equities%20Workbook.xlsx",
                   content=wh.equities_workbook_bytes())
    assert r.status_code == 200
    slot = r.json()["slots"][0]
    assert slot["file"]["read_date"] == "2026-10-02" and slot["file"]["matches"] is True
    assert slot["file"]["original_name"] == "Equities Workbook.xlsx"
    assert (tmp_path / "weekly" / "2026-10-02" / "equities_workbook.xlsx").is_file()
    r = client.put("/api/inputs/weekly/2026-10-02/kcb_daily", content=wh.fake_pdf(wh.kcb_daily_text()))
    assert [d["received"] for d in r.json()["slots"][2]["days"]] == [False, False, False, False, True]
    assert client.delete("/api/inputs/weekly/2026-10-02/kcb_daily_2026-10-02.pdf").json()["slots"][2]["received"] is False
    assert client.delete("/api/inputs/weekly/2026-10-02/kcb_daily_2026-10-02.pdf").status_code == 404


def test_the_api_refuses_what_the_store_refuses_in_its_words(client, text_pdfs):
    assert client.get("/api/inputs/weekly/2026-10-01").status_code == 422
    assert "is a Thursday" in client.get("/api/inputs/weekly/2026-10-01").json()["detail"]
    assert client.get("/api/inputs/weekly/not-a-date").status_code == 422
    assert client.put("/api/inputs/weekly/2026-10-02/nope", content=b"%PDF").status_code == 404
    r = client.put("/api/inputs/weekly/2026-10-02/kcb_weekly", content=b"PK\x03\x04")
    assert r.status_code == 422 and r.json()["detail"] == "KCB IB weekly trading report: this is not a PDF file"
    r = client.put("/api/inputs/weekly/2026-10-02/kcb_daily", content=wh.fake_pdf(wh.kcb_daily_text(date(2026, 10, 9))))
    assert r.status_code == 422 and "not in the week 2026-09-28 to 2026-10-02" in r.json()["detail"]
    big = client.put("/api/inputs/weekly/2026-10-02/cbk_bulletin", content=b"%PDF" + b"x" * inputs.MAX_BYTES)
    assert big.status_code == 413 and "over the 30 MB limit" in big.json()["detail"]


def test_the_bulletin_is_fetched_from_cbk_when_asked_and_notes_are_saved(client):
    r = client.post("/api/inputs/weekly/2026-10-02/cbk_bulletin/fetch")
    assert r.status_code == 200
    slot = next(s for s in r.json()["slots"] if s["slug"] == "cbk_bulletin")
    assert slot["file"]["matches"] is True and slot["file"]["fetched_from"].startswith("https://www.centralbank.go.ke/")
    missing = client.post("/api/inputs/weekly/2026-10-09/cbk_bulletin/fetch")
    assert missing.status_code == 404 and "Upload the bulletin once CBK has published it" in missing.json()["detail"]
    notes = client.put("/api/inputs/weekly/2026-10-02/notes", json={"bidding_range": "12.4%-12.8%"}).json()["notes"]
    assert notes == {"bidding_range": "12.4%-12.8%"}
    assert client.put("/api/inputs/weekly/2026-10-02/notes", json={"bidding_range": ""}).json()["notes"] == {}


def test_the_overview_names_the_week_a_weekly_period_ends_on(client):
    plain = client.get("/api/sections").json()["report"]
    assert plain["week_ending"] is None and date.fromisoformat(plain["suggested_week_ending"]).weekday() == 4
    named = client.get("/api/sections", params={"period": "2026-10-02"}).json()["report"]
    assert (named["period"], named["week_ending"]) == ("Week ending 2026-10-02", "2026-10-02")
    refused = client.get("/api/sections", params={"period": "2026-10-03"})
    assert refused.status_code == 422 and "week ends on a Friday" in refused.json()["detail"]


# ---------------------------------------------------------------------------
# The previous issue
# ---------------------------------------------------------------------------

def _site(issues: dict[int, str], newest_slug: str = "newest-issue"):
    """A fake cytonnreport.com: {id: created_at}, every issue with one Fixed Income section."""
    slugs = {f"issue-{i}": i for i in issues} | {newest_slug: max(issues)}

    def get(url: str) -> bytes:
        if url.endswith("/series/1"):
            return f'<a href="/research/{newest_slug}" class="whites"></a>'.encode()
        if "/api/global/search/" in url:
            slug = url.rsplit("/", 1)[-1]
            rows = [{"id": slugs[slug], "title": "t", "url": f"/research/{slug}"}] if slug in slugs else []
            return json.dumps({"data": rows}).encode()
        issue_id = int(url.rsplit("/", 1)[-1])
        if issue_id not in issues:
            raise NotFound(url)
        return json.dumps([{"name": "Fixed Income", "slug": "fixed-income", "summary": "<p>s</p>",
                            "body": f"<p>Issue {issue_id} body.</p><ul><li>one</li><li>two</li></ul>",
                            "created_at": issues[issue_id]}]).encode()

    return get


def test_the_previous_issue_is_the_newest_one_published_by_the_weeks_friday():
    get = _site({890: "2026-09-27 10:00:00", 891: "2026-09-27 14:48:10", 892: "2026-10-04 10:23:49"})
    issue = previous_issue.find_previous_issue(date(2026, 10, 2), get)
    assert (issue.issue_id, issue.published) == (891, date(2026, 9, 27))   # 892 is this week's own issue
    assert previous_issue.html_paragraphs(issue.section("fixed-income")["body"]) == ["Issue 891 body.", "one", "two"]
    assert previous_issue.find_previous_issue(date(2026, 10, 9), get).issue_id == 892
    with pytest.raises(previous_issue.PreviousIssueError, match="no issue published on or before 2026-09-01"):
        previous_issue.find_previous_issue(date(2026, 9, 1), get)


def test_a_pasted_address_or_id_names_the_issue():
    get = _site({891: "2026-09-27 14:48:10"})
    assert previous_issue.resolve_issue_id("891", get) == 891
    assert previous_issue.resolve_issue_id("https://cytonnreport.com/api/series/1/research-reports/891", get) == 891
    assert previous_issue.resolve_issue_id("https://cytonnreport.com/research/issue-891", get) == 891
    assert previous_issue.find_previous_issue(date(2026, 10, 2), get, reference="issue-891").issue_id == 891
    with pytest.raises(previous_issue.PreviousIssueError, match="is not a cytonnreport.com address"):
        previous_issue.resolve_issue_id("https://example.com/research/issue-891", get)
    with pytest.raises(previous_issue.PreviousIssueError, match="does not find the issue page 'unknown'"):
        previous_issue.resolve_issue_id("https://cytonnreport.com/research/unknown", get)
