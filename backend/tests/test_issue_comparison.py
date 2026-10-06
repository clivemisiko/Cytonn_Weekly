"""The tool against the live Cytonn issues, as compared on 2026-10-06.

Printed values are the issues' own (Q3'2026, H1'2026, Q3'2025), captured to
tests/fixtures/sources/ on 2026-10-06 with the Yahoo Finance closes and the CBK results they
are compared with.  Nothing here reaches the network.

Three things are pinned:

* Digital Payments period tables: the quarterly table reproduces the Q3'2026 issue; the
  half-year table prints its HY change the right way up, where the H1'2026 issue printed the
  ratio inverted (the one documented exception, periodic.digital_payments.KNOWN_PRINTED_ERRORS).
* Bond issuance totals: counting tap sales reproduces Q3'2025 and Q3'2024; H1'2026 left its
  taps out.
* Quarterly T-bill figures: the amounts and rates reproduce from CBK's weekly results, and
  three ways of averaging the yields tie, which is why that part stays a stub.
"""

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from cytonn_weekly.common.formatting import PCT, fmt_value, pct_change, round_half_up
from cytonn_weekly.digital_payments import fetcher as dp_fetcher
from cytonn_weekly.digital_payments.coordinator_review import CLEAN
from cytonn_weekly.fixed_income import cbk_auctions
from cytonn_weekly.periodic import digital_payments as periodic_dp
from cytonn_weekly.periodic import fixed_income
from tests import periodic_helpers as ph

SOURCES = Path(__file__).parent / "fixtures" / "sources"
DP = json.loads((SOURCES / "cytonn_dp_period_tables_2026-10-06.json").read_text(encoding="utf-8"))
TBILLS = json.loads((SOURCES / "cbk_tbill_q3_2025_q3_2026_captured_2026-10-06.json").read_text(encoding="utf-8"))
TBONDS = json.loads((SOURCES / "cbk_tbond_periods_captured_2026-10-06.json").read_text(encoding="utf-8"))

CLOSES = DP["closes"]
TICKERS = [t for _, t in dp_fetcher.COMPANIES]


def pct(new, old):
    return fmt_value(pct_change(new, old), PCT, 1)


def printed(period):
    table = DP["printed"][period]
    return {t: dict(zip(table["keys"], row)) for t, row in table["rows"].items()}


# ---------------------------------------------------------------------------
# Digital Payments period tables
# ---------------------------------------------------------------------------


class CapturedTicker:
    """yfinance's Ticker over the captured closes, honouring the date window the fetcher asks for."""

    def __init__(self, symbol):
        self.symbol = symbol
        self.info = {"forwardPE": 26.0, "forwardEps": 5.0}

    def history(self, start=None, end=None, **kwargs):
        rows = [(d, c) for d, c in CLOSES[self.symbol].items() if start <= d < end]
        index = pd.DatetimeIndex([d for d, _ in rows], tz="America/New_York")
        return pd.DataFrame({"Open": [c for _, c in rows], "Close": [c for _, c in rows]}, index=index)


def captured_history(ticker, start, end):
    return [(date.fromisoformat(d), c) for d, c in CLOSES[ticker].items() if start <= date.fromisoformat(d) <= end]


def period_table(monkeypatch, report_type, period, today):
    """The real weekly fetcher and the real period pipeline, on the captured closes."""
    monkeypatch.setattr(dp_fetcher.yf, "Ticker", CapturedTicker)
    review = periodic_dp.build_digital_payments_review(
        ph.ctx(report_type, period, today=today), provider=ph.FakeProvider(), narrative_provider=ph.narrative(),
        fetch_table=lambda d: dp_fetcher.fetch_digital_payments(today=d), history=captured_history)
    table = next(b for b in review.section["blocks"] if b["kind"] == "table")
    return review, table, {r["ticker"]: r for r in table["rows"]}


def test_q3_table_reproduces_the_printed_q3_2026_issue(monkeypatch):
    """w/w, Q/Q and YTD for all seven companies, and every price the tool also prints.

    Result on 2026-10-06: every figure is the printed one, with no row a rounding step away.  The
    only differences are Global Payments' Year Open and YTD, the known difference from the issue
    (CLAUDE.md, Open items: the issue's 77.0 is its 5 January close, the tool uses 2 January's 75.5).
    """
    review, table, rows = period_table(monkeypatch, "quarterly", "Q3'2026", date(2026, 10, 4))
    # The issue heads its last price "10/03/2026", a Saturday; the prices under it are Friday's closes.
    assert [c["label"] for c in table["columns"]] == [
        "Company", "Year Open 2026", "Price 6/30/2026", "Price 9/25/2026", "Price 9/30/2026", "Price 10/02/2026",
        "w/w change", "Q/Q change", "YTD change", "Forward P/E"]
    issue = printed("Q3'2026")
    assert set(issue) == set(TICKERS)
    for t in TICKERS:
        got, want = rows[t], issue[t]
        assert (got["period_start_close"], got["prior_close"], got["period_end_close"], got["current_price"]) == \
            (want["p_0630"], want["p_0925"], want["p_0930"], want["p_1003"]), t
        assert (got["wow_pct"], got["period_pct"]) == (want["wow"], want["qoq"]), t
        if t != "GPN":
            assert (got["ytd_open"], got["ytd_pct"]) == (want["year_open"], want["ytd"]), t
    assert (rows["GPN"]["ytd_open"], rows["GPN"]["ytd_pct"]) == ("75.5", "3.8%")    # the issue: 77.0 and 1.8%
    assert (issue["GPN"]["year_open"], issue["GPN"]["ytd"]) == ("77.0", "1.8%")
    assert all(i.status == CLEAN for i in review.review_items if i.kind == "table_row")
    assert "month_change" in [b["id"] for b in review.section["blocks"]]        # m/m stays a stub


def test_q3_printed_columns_follow_the_formulas_the_tool_uses():
    """From the issue's own printed prices: w/w = 10/03 over 9/25, Q/Q = 9/30 over 6/30, YTD = 10/03 over Year Open.

    The printed prices are rounded to 1 dp, so a change recomputed from them can land one rounding
    step (0.1) from the printed change, which Cytonn took from unrounded prices; never further.
    Rows a step away, recorded 2026-10-06: Circle Q/Q and YTD, Block YTD, PayPal w/w, Q/Q (two steps:
    21.5% from 52.5 / 43.2, the issue's 21.7% is the unrounded 52.53 / 43.18) and YTD, Global Payments Q/Q.
    The m/m column is the 10/03 price over the 8/03 price, exactly, for every row, the misprint included.
    """
    for t, p in printed("Q3'2026").items():
        price = {k: float(v) for k, v in p.items() if k.startswith("p_") or k == "year_open"}
        steps = 2 if t == "PYPL" else 1
        for label, new, old in (("wow", "p_1003", "p_0925"), ("qoq", "p_0930", "p_0630"), ("ytd", "p_1003", "year_open")):
            recomputed = round_half_up(pct_change(price[new], price[old]), 1)
            shown = round_half_up(-float(p[label].strip("()%")) if p[label].startswith("(") else float(p[label].strip("%")), 1)
            assert abs(recomputed - shown) * 10 <= steps, (t, label, recomputed, shown)
        assert pct(price["p_1003"], price["p_0803"]) == p["mom"], t
    visa = printed("Q3'2026")["V"]
    assert (visa["p_0803"], visa["mom"]) == ("3665.7", "(90.2%)")               # the misprint, and what it produced
    assert round_half_up(CLOSES["V"]["2026-08-03"], 1) == round_half_up(365.7, 1)   # the 3 August close it should be


def test_the_printed_10_03_price_is_the_friday_2_october_close():
    """10/03/2026 is a Saturday.  Every price printed under it is the 2 October close at 1 dp."""
    assert date(2026, 10, 3).weekday() == 5
    for t, p in printed("Q3'2026").items():
        assert fmt_value(CLOSES[t]["2026-10-02"], "price", 1) == p["p_1003"], t
    assert fmt_value(CLOSES["AXP"]["2026-10-01"], "price", 1) != printed("Q3'2026")["AXP"]["p_1003"]


def test_h1_table_prints_the_half_year_change_the_right_way_up(monkeypatch):
    """HY change = the 6/30 close over Year Open, minus 1; w/w = the latest close over the week-ago close, minus 1."""
    review, table, rows = period_table(monkeypatch, "half_year", "H1'2026", date(2026, 7, 5))
    labels = [c["label"] for c in table["columns"]]
    # The tool's own dates: 3 July 2026 was a market holiday, so the latest close is 2 July's, and the
    # weekly fetcher's week-ago close is the one on or before seven days earlier, 25 June (the issue used 26 June).
    assert labels == ["Company", "Year Open 2026", "Price 6/25/2026", "Price 6/30/2026", "Price 7/02/2026",
                      "HY’2026 change", "w/w change", "YTD change", "P/E"]
    issue = printed("H1'2026")
    for t in TICKERS:
        c = CLOSES[t]
        assert rows[t]["period_pct"] == pct(c["2026-06-30"], c["2026-01-02"]), t
        assert rows[t]["wow_pct"] == pct(c["2026-07-02"], c["2026-06-25"]), t
        if t in issue:  # what the two tables share is the same: Year Open, the 6/30 and latest prices, and YTD
            assert (rows[t]["ytd_open"], rows[t]["period_end_close"], rows[t]["current_price"], rows[t]["ytd_pct"]) == \
                (issue[t]["year_open"], issue[t]["p_0630"], issue[t]["p_0703"], issue[t]["ytd"]), t
    assert rows["AXP"]["period_pct"] == "(9.3%)"   # 338.25 / 372.73 - 1; (9.2%) from the issue's 1 dp prices
    assert all(i.status == CLEAN for i in review.review_items if i.kind == "table_row")   # exact against its own source
    assert not [b for b in review.section["blocks"] if b["kind"] == "unavailable"]        # no stubbed column is left
    # The difference from the issue is said on the review, on the column, and nowhere else.
    assert periodic_dp.HALF_CHANGE_WARNING in review.section["warnings"]
    assert "ratio inverted" in periodic_dp.HALF_CHANGE_WARNING and "+10.2%" in periodic_dp.HALF_CHANGE_WARNING
    assert "-9.2%" in periodic_dp.HALF_CHANGE_WARNING
    noted = [c["key"] for c in table["columns"] if c.get("note")]
    assert noted == ["period_pct"]
    quarterly, _, _ = period_table(monkeypatch, "quarterly", "Q3'2026", date(2026, 10, 4))
    assert periodic_dp.HALF_CHANGE_WARNING not in quarterly.section["warnings"]


def test_h1_2026_issue_printed_two_columns_with_the_ratio_inverted():
    """PINNED PUBLISHED ERROR, not a regression: the H1'2026 issue's HY change and w/w are upside down.

    From the issue's own printed prices, for all six companies: its "HY'2026 change" is Year Open
    over the 6/30 price, minus 1, and its w/w is the 6/26 price over the 7/3 price, minus 1 (to
    within one rounding step of the 1 dp prices).  The right way up they are the other sign
    (American Express: (9.2%) and 3.4%).  Its YTD is the right way up.  This is why the half-year
    table is never compared with those two printed columns (KNOWN_PRINTED_ERRORS).
    """
    def close(a, b):
        value = lambda s: -float(s.strip("()%")) if s.startswith("(") else float(s.strip("%"))
        return abs(round_half_up(value(a), 1) - round_half_up(value(b), 1)) * 10 <= 1

    issue = printed("H1'2026")
    assert len(issue) == 6
    for t, p in issue.items():
        year_open, p26, p30, p03 = (float(p[k]) for k in ("year_open", "p_0626", "p_0630", "p_0703"))
        assert close(pct(year_open, p30), p["hy"]), t          # inverted: what the issue printed
        assert close(pct(p26, p03), p["wow"]), t               # inverted: what the issue printed
        assert not close(pct(p30, year_open), p["hy"]), t      # the right way up is not what it printed
        assert not close(pct(p03, p26), p["wow"]), t
        assert close(pct(p03, year_open), p["ytd"]), t         # YTD is the right way up
    amex = issue["AXP"]
    assert (amex["hy"], amex["wow"]) == ("10.2%", "(3.3%)")
    assert (pct(338.3, 372.7), pct(352.0, 340.4)) == ("(9.2%)", "3.4%")
    known = periodic_dp.KNOWN_PRINTED_ERRORS[("half_year", "H1'2026")]
    assert set(known) == {"period_pct", "wow_pct"} and len(periodic_dp.KNOWN_PRINTED_ERRORS) == 1


def test_month_change_stays_a_stub_with_the_evidence():
    with pytest.raises(NotImplementedError) as exc:
        periodic_dp.fetch_month_change(ph.ctx())
    assert str(exc.value) == periodic_dp.MONTH_CHANGE_BLOCKED_REASON
    assert "8/03/2026" in periodic_dp.MONTH_CHANGE_BLOCKED_REASON and "two months" in periodic_dp.MONTH_CHANGE_BLOCKED_REASON
    assert [s.id for s in periodic_dp.STUBS] == ["month_change"]
    for issue in ("#37.2026", "#38.2026"):  # the weekly table has no m/m column
        assert "m/m change" not in DP["printed"]["weekly"][issue]


def test_quarter_change_uses_the_previous_quarter_end_for_other_quarters():
    """Q1: the 31 March close over the previous 31 December close; the day before a period is found by date."""
    series = {"V": [(date(2025, 12, 30), 99.0), (date(2025, 12, 31), 100.0), (date(2026, 3, 30), 109.0),
                    (date(2026, 3, 31), 110.0), (date(2026, 4, 1), 120.0)]}
    base = [{"company": "Visa", "ticker": "V", "error": None, "ytd_open": 101.0}]
    rows, _ = periodic_dp.period_rows(ph.ctx("quarterly", "Q1'2026", today=date(2026, 4, 5)), base,
                                      lambda t, start, end: [x for x in series[t] if start <= x[0] <= end])
    assert (rows[0]["period_start_date"], rows[0]["period_end_date"]) == ("2025-12-31", "2026-03-31")
    assert rows[0]["period_pct"] == pytest.approx(10.0)
    rows, _ = periodic_dp.period_rows(ph.ctx("half_year", "H1'2026", today=date(2026, 7, 5)), base,
                                      lambda t, start, end: [(date(2026, 6, 30), 90.9)])
    assert rows[0]["period_pct"] == pytest.approx(-10.0) and rows[0]["period_start_close"] is None

# ---------------------------------------------------------------------------
# Bond issuance totals
# ---------------------------------------------------------------------------


def summary(period, taps=True):
    auctions = [a for a in TBONDS["periods"][period] if taps or a["kind"] != "tap"]
    (total, average), _ = fixed_income.summary_rows(period, auctions)
    one = lambda v: str(round_half_up(v, 1)) if v is not None else None
    return {"offered": one(total["offered_kes_bn"]), "accepted": one(total["accepted_kes_bn"]),
            "bids": one(total["bids_kes_bn"]), "tenor": one(average["years_to_maturity"]),
            "coupon": one(average["coupon_pct"]), "yield": one(average["avg_rate_pct"]),
            "subscription": one(average["subscription_pct"]), "acceptance": one(average["acceptance_pct"])}


def test_counting_tap_sales_reproduces_the_printed_q3_totals():
    """Q3'2025 (as the Q3'2025 issue prints it and as the Q3'2026 issue repeats it) and Q3'2024."""
    for label in ("Q3'2025", "Q3'2025 as repeated in the Q3'2026 issue"):
        want, got = TBONDS["printed"][label], summary("Q3'2025")
        assert [got[k] for k in ("offered", "accepted", "bids", "yield", "subscription", "acceptance")] == \
            [want[k] for k in ("offered", "accepted", "bids", "yield", "subscription", "acceptance")] == \
            ["250.0", "405.3", "713.1", "13.8", "285.3", "56.8"]
    assert [a["kind"] for a in TBONDS["periods"]["Q3'2025"]].count("tap") == 1
    assert summary("Q3'2025", taps=False)["offered"] == "200.0"            # without the tap the totals are not the issue's
    want, got = TBONDS["printed"]["Q3'2024"], summary("Q3'2024")
    assert [got[k] for k in ("offered", "accepted", "bids", "yield")] == [want[k] for k in ("offered", "accepted", "bids", "yield")] == \
        ["145.0", "150.3", "199.3", "17.5"]
    assert [a["kind"] for a in TBONDS["periods"]["Q3'2024"]].count("tap") == 2


def test_where_the_bond_averages_and_other_periods_differ_from_the_issues():
    """Recorded 2026-10-06 so a change in any of these is noticed; none is copied from the issues."""
    q3 = summary("Q3'2025")
    # Coupon: the tool's mean of all nine bonds is 13.0; the Q3'2025 issue printed 13.1 (the mean of
    # the seven non-tap bonds) and the Q3'2026 issue repeats it as 13.2.  The two issues disagree.
    assert (q3["coupon"], summary("Q3'2025", taps=False)["coupon"]) == ("13.0", "13.1")
    assert (TBONDS["printed"]["Q3'2025"]["coupon"], TBONDS["printed"]["Q3'2025 as repeated in the Q3'2026 issue"]["coupon"]) == ("13.1", "13.2")
    # Tenor: CBK prints a remaining life for five of the nine bonds, so the tool's 14.7 is flagged
    # incomplete; the issues print 14.6 and then 14.4.
    assert q3["tenor"] == "14.7"
    (_, average), _ = fixed_income.summary_rows("Q3'2025", TBONDS["periods"]["Q3'2025"])
    assert average["incomplete"]["years_to_maturity"].startswith("average of 5 of 9 bonds")
    # Q3'2024's printed subscription (144.5%) and acceptance (80.5%) are not its own totals' ratios
    # (199.3 / 145.0 = 137.5%, 150.3 / 199.3 = 75.4%), which is what the tool gives.
    q24 = summary("Q3'2024")
    assert (q24["subscription"], q24["acceptance"], q24["coupon"]) == ("137.5", "75.4", "15.4")
    assert TBONDS["printed"]["Q3'2024"]["subscription"] == "144.5"
    # H1'2026 is inconsistent with itself: its text says one tap sale, its table and totals have none.
    # Its totals are the nine primary auctions alone (accepted 509.9 against the printed 510.0);
    # counted with CBK's two June 2026 tap sales, as the tool counts, they are 495.0 / 547.6 / 820.9.
    assert summary("H1'2026", taps=False) == {**summary("H1'2026", taps=False), "offered": "460.0", "accepted": "509.9",
                                              "bids": "781.1", "subscription": "169.8", "acceptance": "65.3"}
    assert [summary("H1'2026")[k] for k in ("offered", "accepted", "bids")] == ["495.0", "547.6", "820.9"]
    assert [TBONDS["printed"]["H1'2026"][k] for k in ("offered", "accepted", "bids")] == ["460.0", "510.0", "781.1"]
    # H1'2025 as printed in the H1'2026 issue: the offer and the accepted amount are CBK's with the
    # April 2025 tap sale counted and the February buyback left out; the printed bids (691.7) are
    # 94.0 above CBK's 597.7, which no listed result explains.
    h25 = summary("H1'2025")
    assert (h25["offered"], h25["accepted"], h25["bids"], h25["coupon"], h25["yield"]) == ("335.0", "464.1", "597.7", "13.4", "14.1")
    assert summary("H1'2025", taps=False)["offered"] == "325.0"
    assert TBONDS["printed"]["H1'2025"]["bids"] == "691.7"


def test_buyback_results_are_not_bond_issuances():
    name = "x/819608628_FEBRUARY BUYBACK AUCTION FXD1-2022-003, FXD1-2020-005 AND IFB1-2016-009 DATED 17-02-2025.pdf"
    assert cbk_auctions.link_kind(name) == "buyback"
    assert cbk_auctions.link_kind("x/RESULTS IFB1-2022-014 AND IFB1-2023-017 DATED 17-02-2025.pdf") == "primary"
    assert cbk_auctions.link_kind("x/SWITCH RESULTS FXD4-2019-010 DATED 09-09-2026 -.pdf") == "switch"
    assert cbk_auctions.link_kind("x/July 2024 TAP SALE FXD1-2023-002 DATED 08-07-2024.pdf") == "tap"
    listing = f'<a href="/uploads/historical_treasury_bond_results/{name[2:]}">r</a>'.encode()

    def get(url):
        if url == cbk_auctions.TBOND_LISTING:
            return listing
        raise AssertionError("a buyback result must not be fetched")

    assert cbk_auctions.fetch_period_tbonds(date(2025, 1, 1), date(2025, 6, 30), get=get)["auctions"] == []
    with pytest.raises(LookupError):
        cbk_auctions.fetch_latest_tbond_results(get=get)
    assert all(a["kind"] != "buyback" for auctions in TBONDS["periods"].values() for a in auctions)


def test_2024_layouts_keep_each_bonds_figures_under_its_own_name():
    """Two real 2024 results that used to lose their first bond and shift the second under its figures."""
    def parse(name):
        tables, text = cbk_auctions._tables_and_text((SOURCES / name).read_bytes())
        return cbk_auctions.parse_tbond_results(tables, text)

    merged = parse("cbk_tbond_2024-07-22.pdf")      # "TENOR FXD1/2024/010" merged into the label cell
    assert [(r["issue"], r["bids_kes_bn"], r["accepted_kes_bn"], r["avg_rate_pct"], r["coupon_pct"]) for r in merged["rows"]] == [
        ("FXD1/2024/010", 7.06773, 6.75215, 16.5923, 16.0), ("FXD1/2008/020", 7.61451, 3.01408, 18.2904, 13.75)]
    assert merged["total_offered_kes_bn"] == 30.0
    half_year_bond = parse("cbk_tbond_2024-08-19.pdf")  # "IFB1/2023/6.5": a tenor with a decimal point
    assert [(r["issue"], r["bids_kes_bn"], r["accepted_kes_bn"], r["avg_rate_pct"]) for r in half_year_bond["rows"]] == [
        ("IFB1/2023/6.5", 96.86191, 74.1676, 18.2989), ("IFB1/2023/17", 29.46052, 14.53092, 17.7279)]
    # The fixture's Q3'2024 auctions are these PDFs as parsed.
    captured = {a["value_date"]: a for a in TBONDS["periods"]["Q3'2024"]}
    assert [r["issue"] for r in captured["2024-08-19"]["rows"]] == ["IFB1/2023/6.5", "IFB1/2023/17"]
    assert captured["2024-07-22"]["rows"][0]["accepted_kes_bn"] == merged["rows"][0]["accepted_kes_bn"]


def test_figures_that_do_not_line_up_with_the_issue_numbers_are_an_error_not_a_shift():
    tables = [[[None, "TENOR", "FXD1/2024/010", "UNREADABLE", ""],
               [None, "Total Amount Offered (Kshs. M)", "", "", "30,000.00"],
               [None, "Total bids Received at cost (Kshs. M)", "7,067.73", "7,614.51", "14,682.24"],
               [None, "Amount Accepted (Kshs. M)", "6,752.15", "3,014.08", "9,766.23"]]]
    with pytest.raises(ValueError, match="3 bid figures under 1 recognised issue number"):
        cbk_auctions.parse_tbond_results(tables)


def test_the_captured_bond_periods_agree_with_the_pdf_fixtures():
    """The 25-08-2025 tap sale is held both as a PDF and in the captured periods; they must be the same figures."""
    tables, text = cbk_auctions._tables_and_text((SOURCES / "cbk_tbond_2025-08-25_tap.pdf").read_bytes())
    pdf = cbk_auctions.parse_tbond_results(tables, text)
    captured = next(a for a in TBONDS["periods"]["Q3'2025"] if a["kind"] == "tap")
    assert captured["total_offered_kes_bn"] == pdf["total_offered_kes_bn"] == 50.0
    assert [(r["issue"], r["accepted_kes_bn"], r["bids_kes_bn"]) for r in captured["rows"]] == \
        [(r["issue"], r["accepted_kes_bn"], r["bids_kes_bn"]) for r in pdf["rows"]]

# ---------------------------------------------------------------------------
# Quarterly T-bill figures from CBK's weekly results
# ---------------------------------------------------------------------------

QUARTERS = {"Q3'2026": (date(2026, 7, 1), date(2026, 9, 30)), "Q3'2025": (date(2025, 7, 1), date(2025, 9, 30))}
YIELD_METHODS = ("plain", "accepted_weighted", "bid_weighted")


def tbill_figures(start, end):
    """The quarter's figures from the auctions with a value date in ``start``..``end``, at the printed precision."""
    auctions = [a for a in TBILLS["auctions"] if start.isoformat() <= a["value_date"] <= end.isoformat()]
    by_tenor = {t: [next(r for r in a["rows"] if r["tenor"] == t) for a in auctions] for t in cbk_auctions.TENORS}
    total = lambda key, tenors=cbk_auctions.TENORS: sum(r[key] for t in tenors for r in by_tenor[t])
    one = lambda v: str(round_half_up(v, 1))
    out = {
        "auctions": len(auctions),
        "overall_subscription_pct": one(total("bids_kes_bn") / total("offered_kes_bn") * 100),
        "subscription_pct": {t: one(total("bids_kes_bn", (t,)) / total("offered_kes_bn", (t,)) * 100) for t in by_tenor},
        "acceptance_pct": one(total("accepted_kes_bn") / total("bids_kes_bn") * 100),
        "bids_kes_bn": one(total("bids_kes_bn")), "accepted_kes_bn": one(total("accepted_kes_bn")),
        "bids_91_day_kes_bn": one(total("bids_kes_bn", ("91-day",))),
        "offered_91_day_kes_bn": one(total("offered_kes_bn", ("91-day",))),
        "yields": {},
    }
    for method, weight in zip(YIELD_METHODS, (None, "accepted_kes_bn", "bids_kes_bn")):
        out["yields"][method] = {
            t: one(sum(r["avg_rate_pct"] * (r[weight] if weight else 1) for r in rows)
                   / sum((r[weight] if weight else 1) for r in rows)) for t, rows in by_tenor.items()}
    out["yields"]["last_auction"] = {t: one(rows[-1]["avg_rate_pct"]) for t, rows in by_tenor.items()}
    return out


@pytest.mark.parametrize("quarter", list(QUARTERS))
def test_quarterly_tbill_amounts_and_rates_reproduce_from_cbks_weekly_results(quarter):
    """The 13 auctions with a value date inside the quarter; every rate a ratio of sums."""
    got, want = tbill_figures(*QUARTERS[quarter]), TBILLS["printed"][quarter]
    assert got["auctions"] == 13
    for key in ("overall_subscription_pct", "subscription_pct", "acceptance_pct", "bids_kes_bn", "accepted_kes_bn"):
        assert got[key] == want[key], key
    if quarter == "Q3'2026":
        assert (got["bids_91_day_kes_bn"], got["offered_91_day_kes_bn"]) == ("319.2", "100.0")


@pytest.mark.parametrize("quarter", list(QUARTERS))
def test_other_auction_windows_do_not_reproduce_the_printed_tbill_figures(quarter):
    start, end = QUARTERS[quarter]
    want = TBILLS["printed"][quarter]
    week = timedelta(days=7)
    for other in ((start - week, end), (start, end + week), (start - week, end - week), (start + week, end + week),
                  (start, end - week)):
        got = tbill_figures(*other)
        assert (got["overall_subscription_pct"], got["subscription_pct"]) != \
            (want["overall_subscription_pct"], want["subscription_pct"]), other


def test_three_yield_averaging_methods_tie_so_the_tbill_part_stays_a_stub():
    """A plain mean, an accepted-weighted mean and a bid-weighted mean all give the printed yields of both quarters.

    They differ only in the second decimal place (Q3'2026 91-day: 8.7862, 8.7826, 8.7867), so
    the two printed quarters cannot tell them apart.  The rule: several methods tie, do not
    choose.  If this test starts failing because a newly captured quarter separates them, the
    stub can be replaced with the one method that survives.
    """
    for quarter, window in QUARTERS.items():
        got, want = tbill_figures(*window), TBILLS["printed"][quarter]["average_yield_pct"]
        for method in YIELD_METHODS:
            assert got["yields"][method] == want, (quarter, method)
    assert tbill_figures(*QUARTERS["Q3'2025"])["yields"]["last_auction"] != TBILLS["printed"]["Q3'2025"]["average_yield_pct"]
    with pytest.raises(NotImplementedError) as exc:
        fixed_income.fetch_period_tbill_summary(ph.ctx())
    assert str(exc.value) == fixed_income.TBILLS_BLOCKED_REASON
    for evidence in ("163.9%", "110.6%", "590.1", "tie", "plain mean", "weighted by the amount accepted",
                     "weighted by the bids received"):
        assert evidence in fixed_income.TBILLS_BLOCKED_REASON, evidence


def test_the_captured_tbill_results_agree_with_the_pdf_fixture():
    """The 28-09-2026 auction is held both as a PDF and in the captured results; they must be the same figures."""
    tables, text = cbk_auctions._tables_and_text((SOURCES / "cbk_tbill_2026-09-28.pdf").read_bytes())
    pdf = cbk_auctions.parse_tbill_results(tables, text)["rows"]
    captured = next(a for a in TBILLS["auctions"] if a["value_date"] == "2026-09-28")["rows"]
    keys = ("tenor", "offered_kes_bn", "bids_kes_bn", "accepted_kes_bn", "avg_rate_pct")
    assert captured == [{k: r[k] for k in keys} for r in pdf]
