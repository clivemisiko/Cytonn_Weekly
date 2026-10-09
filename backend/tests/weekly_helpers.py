"""Synthetic weekly inputs for tests: workbooks and report text built here, with invented figures.

The real workbooks and KCB IB reports are confidential and are never in the repository
(the "sample data/" folder is ignored).  These builders reproduce their *layout* (sheet
names, labels, where a week's row sits) with made-up numbers, so the readers and the
section builders are tested without them.  ``sample()`` gives the real files to the few
golden tests that use them, and skips the test when they are absent or locked.

A KCB report and the NSE yield curve are PDFs with a text layer; the tests stand in for one
with ``fake_pdf(text)`` and the ``text_pdfs`` fixture, which makes the parsers read that
text back instead of opening a PDF.
"""

from __future__ import annotations

import io
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pytest
from openpyxl import Workbook as XlsxWorkbook

from cytonn_weekly import paths
from cytonn_weekly.weekly.week import Week

WEEK = Week(date(2026, 10, 2))
FIXTURES = Path(__file__).parent / "fixtures" / "sources"
SAMPLE_DIR_ENV_VAR = "CYTONN_SAMPLE_DIR"

_MARK = b"\n%%synthetic-text\n"


def sample(name: str) -> bytes:
    """A real sample's bytes, or skip the test: the samples are confidential and not in the repository."""
    folder = Path(os.environ.get(SAMPLE_DIR_ENV_VAR) or paths.REPO_ROOT / "sample data")
    path = folder / name
    if not path.is_file():
        pytest.skip(f"real sample not present: {name}")
    try:
        return path.read_bytes()
    except PermissionError:
        pytest.skip(f"real sample is open in another program and cannot be read: {name}")


def fake_pdf(text: str) -> bytes:
    """Bytes that pass for a PDF and carry ``text`` as their text layer (see the ``text_pdfs`` fixture)."""
    return b"%PDF-1.4" + _MARK + text.encode("utf-8")


def text_of(pdf: bytes) -> str:
    return pdf.split(_MARK, 1)[1].decode("utf-8")


@pytest.fixture
def text_pdfs(monkeypatch):
    """Make the KCB and yield-curve parsers read a ``fake_pdf``'s text; real PDFs are read as usual."""
    from cytonn_weekly.weekly import kcb, nse_yield_curve

    real_text, real_curve = kcb.pdf_text, nse_yield_curve.parse_yield_curve
    monkeypatch.setattr(kcb, "pdf_text", lambda b: text_of(b) if _MARK in b else real_text(b))
    monkeypatch.setattr(nse_yield_curve, "parse_yield_curve",
                        lambda b: nse_yield_curve.parse_yield_curve_text(text_of(b)) if _MARK in b else real_curve(b))


def dt(day: date) -> datetime:
    return datetime(day.year, day.month, day.day)


# ---------------------------------------------------------------------------
# KCB IB reports, as their text layer reads (kerned digits included)
# ---------------------------------------------------------------------------

def kerned(n: int) -> str:
    """A figure as the text layer breaks it: its first digit set apart ("5 00,000,000")."""
    shown = f"{n:,}"
    return f"{shown[0]} {shown[1:]}"


def kcb_daily_text(day: date = WEEK.ending, turnover: int = 500_000_000, net: int = 40_000_000) -> str:
    prev = day - timedelta(days=1)
    buy, sell = 200_000_000 + net, 200_000_000
    return "\n".join([
        "DAILY MARKET REPORT",
        day.strftime("%A, %d %B %Y"),
        "KEY NSE MARKET INDICATORS DAILY STATISTICS VWAP",
        f"Indicator {prev.day}-{prev.strftime('%b-%Y')} {day.day}-{day.strftime('%b-%Y')} % ∆ Agricultural 0.18%",
        "NASI 199.00 2 00.00 0.50% EGAD KES 2 8.70 2.32% 1 7.40 3 5.15 40.00%",
        "NSE-20 3,990.00 4,000.00 0.25% KUKZ KES 4 38.50 0.00% 3 77.50",
        "NSE-25 6,980.00 7,000.00 0.29% KAPC KES 3 39.25 -3.14% 2 01.50",
        "Mkt cap, KES Bn 3 ,990.000 4 ,000.000 0.25% LIMT KES 5 32.00 0.00%",
        "Shares traded 1 2,000,000 1 6,000,000 33.33% SASN KES 2 3.80 -2.86%",
        f"Equities TO, KES 400,000,000 {turnover:,} 25.00% WTK KES 1 60.25 -0.16%",
        f"Foreign buy, KES 150,000,000 {buy:,} 60.00% Automobiles & Accessories 0.12%",
        f"Foreign sell, KES 140,000,000 {sell:,} 42.86% CGEN KES 2 89.75 0.00%",
        f"Net flows, KES 1 0,000,000 {net:,} 300.00% 0.17Banking 64.36%",
        "TOP GAINERS NCBA KES 8 7.75 -0.85% 6 9.00",
        "Security Price, KES ∆, KES % ∆ SBIC KES 2 80.50 0.00% 1 82.75",
        "TRADING STATS FTGH KES 2.07 -0.96% 1.41",
        "Asset class Volume Deals Turnover, KES AMAC KES 3 49.75 -1.48%",
        f"Equities 1 6,000,000 12,517 {kerned(turnover)} MSC KES 0.27 0.00%",
        "ETFs 1 74 37 6 79,739 SKL KES 1 6.95 -1.74%",
        "SCOM KES 3 6.55 0.41% 2 6.00",
    ])


WEEKDAY_FLOWS = {"Monday": -60_000_000, "Tuesday": -6_000_000, "Wednesday": 80_000_000, "Thursday": 60_000_000,
                 "Friday": 40_000_000}

# Week-on-week moves of the large caps in the synthetic weekly report (ticker -> %).
LARGE_CAP_MOVES = {"SCOM": 0.27, "EQTY": -1.40, "KCB": -1.07, "COOP": -0.54, "ABSA": -1.05, "SCBK": -1.54, "IMH": -2.94,
                   "SBIC": -0.71, "DTK": -0.13, "NCBA": -2.23, "HFCK": -1.60, "EABL": 0.79}


def kcb_weekly_text(week: Week = WEEK, nasi=(202.00, 200.00), nse20=(4040.00, 4000.00), nse25=(7070.00, 7000.00),
                    flows: Optional[dict[str, int]] = None) -> str:
    flows = flows or WEEKDAY_FLOWS
    last, day = week.previous_friday, week.ending
    lines = [
        "WEEKLY MARKET REPORT",
        day.strftime("%A, %d %B %Y"),
        "KEY NSE MARKET INDICATORS WEEKLY STATISTICS VWAP",
        f"Indicator {last.day}-{last.strftime('%b-%Y')} {day.day}-{day.strftime('%b-%Y')} % ∆ Agricultural 0.40%",
        f"NASI {nasi[0]:.2f} {nasi[1]:.2f} -0.99% EGAD KES 28.70 -0.86% 26.10",
        f"NSE-20 {nse20[0]:,.2f} {nse20[1]:,.2f} -0.99% KUKZ KES 4 38.50 0.00%",
        f"NSE-25 {nse25[0]:,.2f} {nse25[1]:,.2f} -0.99% KAPC KES 3 39.25 -3.69%",
        "Mkt cap, KES Bn 4,040.000 4,000.000 -0.99% LIMT KES 5 32.00 4.31%",
        "Shares traded 1 12,403,602 6 3,673,363 -43.35% SASN KES 23.80 -3.25%",
        "Equities TO, KES 4,640,950,375 2,279,873,699 -50.87% WTK KES 1 60.25 0.31%",
        "Foreign buy, KES 1,041,564,700 9 86,000,000 -5.31% Automobiles & Accessories 0.33%",
        "Foreign sell, KES 9 67,648,663 8 72,000,000 -13.62% CGEN KES 2 89.75 -0.60%",
        "Net flows, KES 7 3,916,037 1 14,000,000 103.51% Banking 49.85%",
    ]
    lines += [f"{ticker} KES 100.00 {move:.2f}% 80.00" for ticker, move in LARGE_CAP_MOVES.items()]
    lines += ["DAILY FOREIGN FLOWS JUB KES 3 99.00 -1.12%", "Week day Inflows, KES Outflows, KES Net flows, KES KNRE KES 4.40 -0.68%"]
    total_in = total_out = 0
    for name, net in flows.items():
        inflow, outflow = 200_000_000 + max(net, 0), 200_000_000 + max(-net, 0)
        total_in, total_out = total_in + inflow, total_out + outflow
        shown = f"({abs(net):,})" if net < 0 else f"{net:,}"
        lines.append(f"{name} {inflow:,} {outflow:,} {shown} LBTY KES 9.36 1.74%")
    lines.append(f"Total {total_in:,} {total_out:,} {total_in - total_out:,} KURV KES 1,355.00 0.00%")
    lines += ["TRADING STATS AMAC KES 3 49.75 -1.69%", "Asset class Volume Deals Turnover, KES MSC KES 0.27 0.00%",
              "Equities 6 3,673,363 66,117 2 ,273,368,956 UNGA KES 39.80 -3.28%", "ETFs 2 ,106 269 6 ,504,743 Telecommunication 23.32%"]
    return "\n".join(lines)


def yield_curve_text(day: date = date(2026, 10, 2)) -> str:
    lines = ["NAIROBI SECURITIES EXCHANGE YIELD CURVE", day.strftime("%d-%m-%Y"), "17.0000", "TENOR (years)",
             day.strftime("%d-%b-%Y"), "Indicative yields", "Year YIELDS 3 64", "91 day 8.7000 1 3 64 06-Oct-27 9 .0000",
             "182 day 8.9000 2 7 28 04-Oct-28"]
    lines += [f"{n} {9.0 + n * 0.1:.4f} {n + 2} 1 ,092 03-Oct-29" for n in range(1, 30)]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The equities workbook
# ---------------------------------------------------------------------------

UNIVERSE = [  # company, last Friday, month end, this Friday, year open, target, DPS, shares (bn), tangible book (bn)
    ("Alpha Bank", 40.00, 39.00, 42.00, 30.00, 55.00, 3.00, 2.0, 60.0),      # upside well over 20%: Buy
    ("Beta Bank", 100.00, 98.00, 99.00, 80.00, 108.00, 5.00, 1.0, 90.0),     # about 14%: Accumulate
    ("Gamma Insurance", 400.00, 400.00, 399.00, 320.00, 410.00, 15.00, 0.1, 70.0),   # about 6.5%: Hold; m/m is -0.25%
    ("Delta Holdings", 10.00, 10.00, 10.00, 9.00, 10.00, 0.005, 2.5, 30.0),  # upside 0.05%: the rule gives nothing
    ("Epsilon Group", 20.00, 21.00, 20.00, 10.00, 19.00, 0.00, 2.0, 30.0),   # below zero: Sell
]
LARGE_CAPS = ["Safaricom", "Equity Group", "KCB", "Co-operative", "ABSA Bank", "Standard Chartered", "I&M Holdings",
              "Stanbic", "DTBK", "NCBA", "HFCB Group"]


def equities_workbook_bytes(week: Week = WEEK, updated: bool = True) -> bytes:
    """A workbook laid out like the equities team's.  ``updated=False`` leaves this week's rows out."""
    wb = XlsxWorkbook()
    wb.remove(wb.active)
    year = week.ending.year

    ws = wb.create_sheet("Kenyan Indices ")
    ws.append([None])
    ws.append(["Weekly", "last year", f"Year Open {year - 2}", f"Year Open {year - 1}", f"Year Open {year}", "Last week", "Today",
               "W/W", f"YTD {year}"])
    ws.append(["NSE 20", 1675.4, 1508.83, 2058.67, 3200.00, 4040.00, 4000.00])
    ws.append(["NASI", 127.34, 91.97, 125.34, 160.00, 202.00, 200.00])
    ws.append(["NSE 25", 3138.24, 2387.3, 3457.87, 5600.00, 7070.00, 7000.00])
    ws.append(["NSE 10", None, 911.24, 1327.4, 2000.00, 2525.00, 2500.00])
    for _ in range(15):
        ws.append([None])
    ws.append(["Banking Index", dt(date(year, 4, 30)), f"Year Open {year}", "Last Week", "This week", "w/w", "m/m", "YTD "])
    ws.append([None, 236.13, 200.00, 303.00, 300.00])

    for name, ytd_col, daily in (("Equities Turnover", 6, 5.0), ("Foreign Positions", 5, 0.2)):
        ws = wb.create_sheet(name)
        ws.append(["Date", "Turnover(USD Mn)" if ytd_col == 6 else "Flows (USD mn)", "Change"])
        running = 0.0
        # The last weeks of the previous year, then this year's weeks up to the report week.
        friday = date(year - 1, 12, 5)
        while friday.weekday() != 4:
            friday += timedelta(days=1)
        last = week.ending if updated else week.previous_friday
        restarted = False
        while friday <= last:
            wk = Week(friday)
            total = 0.0
            for n, day in enumerate(wk.trading_days):
                value = daily * (1 + n * 0.1) * (1 if name == "Equities Turnover" else (-1 if friday < week.previous_friday else 1))
                ws.append([dt(day), value])
                total += value
            if friday.year == year and friday.day > 7 and not restarted:
                running, restarted = 0.0, True    # the analysts restart the running total early in the new year
            running += total
            row = [None, total, None, None, None, None]
            row[ytd_col - 1] = running
            ws.append(row)
            friday += timedelta(days=7)

    ws = wb.create_sheet("NASI-PE & Dividend Yield")
    for _ in range(5):
        ws.append([None])
    ws.append(["Price to Earnings", None, "Dividend Yield"])
    ws.append(["AVERAGE", 10.0, "AVERAGE", 0.05])
    friday = week.ending if updated else week.previous_friday
    for n in range(30):
        ws.append([dt(friday - timedelta(days=7 * n)), 8.0 + n * 0.01, dt(friday - timedelta(days=7 * n)), 0.06 - n * 0.0001])
    ws["F26"], ws["F27"] = "PEG", 1.0

    ws = wb.create_sheet("Market PE & Dividend Yield")
    ws.append(["Stock", "Dividends", "EPS", dt(week.ending), "Div Yield", "P/E", "Outstanding Shares", "Market Cap", "Weight",
               "Div-Market Cap Weighted", "P/E-Market Cap Weighted", None, None, None, None, "Year Open"])
    for name in LARGE_CAPS:
        ws.append([name, 1.0, 2.0, 30.0, None, None, 1000, None, None, None, None, None, None, None, name, 20.0])

    ws = wb.create_sheet("Universe of Coverage")
    month_end = week.ending.replace(day=1) - timedelta(days=1)
    while month_end.weekday() >= 5:
        month_end -= timedelta(days=1)
    heads = [None, "Company", "Country Currency", f"Price as at {week.previous.previous_friday:%d/%m/%Y}",
             f"Price as at {week.previous_friday:%d/%m/%Y}", f"Price as at {month_end:%d/%m/%Y}"]
    if updated:
        heads.append(f"Price as at {week.ending:%d/%m/%Y}")
    heads += ["w/w change", "m/m change", "YTD Change", f"Year Open {year - 1}", f"Year Open {year}", "`", "Target Price*",
              "Dividend Yield", "Upside/ Downside**", "TBV/Share", "P/TBv Multiple", "Recommendation", "No. of Shares(bn)",
              "Current Tangible Book Value (bn) FY'2025", "DPS", "EPS", "Tangible Book Value (bn) FY'2025"]
    ws.append([None, None, "Kenya Shilling"])
    ws.append(heads)
    for company, last_p, month_p, price, opened, target, dps, shares, tbv in UNIVERSE:
        row = [None, company, "Kenya Shilling", last_p - 1, last_p, month_p]
        if updated:
            row.append(price)
        row += [None, None, None, opened - 5, opened, 1.0, target, None, None, None, None, None, shares, tbv, dps, 2.0, tbv]
        ws.append(row)
    ws.append([None, None])
    ws.append([None, "High"])

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ---------------------------------------------------------------------------
# The fixed income workbook
# ---------------------------------------------------------------------------

FUNDS = [("Cytonn Money Market Fund ( Dial *809# or download Cytonn App)", 0.1100), ("Alpha Money Market Fund", 0.1080),
         ("Beta Money Market Fund", 0.1070), ("Gamma Money Market Fund", 0.1060), ("Delta Money Market Fund", 0.1050),
         ("Epsilon Money Market Fund", 0.0900), ("Zeta Money Market Fund", 0.0500)]
EUROBOND_HEADS = (  # date column, yield column, group header (row, col, text), column header (row, col, text), fraction base
    (13, 14, (2, 12, "2018 Issue"), (4, 15, "10-year coupon"), 0.070),
    (19, 20, (2, 18, "2018 Issue"), (4, 21, "30-year coupon"), 0.095),
    (26, 29, (1, 26, "2019 Issue"), (3, 29, "12-yr (2019)"), 0.082),
    (35, 36, (2, 34, "2021 Issue"), (3, 36, "13-yr (2021)"), 0.087),
    (42, 43, (2, 41, "2024 Issue"), (3, 43, "7-yr (2024)"), 0.079),
)
ISSUES = [("10-year 2018", date(2018, 2, 28), date(2028, 2, 28), 0.0725, 1000, 1000),
          ("30-year 2018", date(2018, 2, 28), date(2048, 2, 28), 0.0825, 1000, 1000),
          ("7-year 2019", date(2019, 5, 22), date(2027, 5, 22), 0.07, 900, 320.3),
          ("12-year 2019", date(2019, 5, 22), date(2032, 5, 22), 0.08, 1200, 1200),
          ("13-year 2021", date(2021, 6, 23), date(2034, 6, 23), 0.063, 1000, 1000),
          ("7-year 2024", date(2024, 2, 13), date(2031, 2, 13), 0.0975, 1500, 1500),
          ("11-year 2025", date(2025, 2, 27), date(2036, 2, 27), 0.095, 0, 1500)]


def cbk_rates() -> dict[date, float]:
    """CBK's published US dollar rates for the golden weeks (a public fixture)."""
    import json

    data = json.loads((FIXTURES / "cbk_usd_rates_captured_2026-10-09.json").read_text())
    return {date.fromisoformat(d): v for d, v in data["rates"].items()}


def weekdays(first: date, last: date) -> list[date]:
    out, day = [], first
    while day <= last:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def eurobond_yield(base: float, day: date) -> float:
    """A deterministic made-up yield (a fraction), rising a little each day of the year."""
    return round(base + day.timetuple().tm_yday * 0.00002, 5)


def fi_workbook_bytes(week: Week = WEEK, updated: bool = True, funds: Optional[list[tuple[str, float]]] = None) -> bytes:
    """A workbook laid out like the fixed income team's.  ``updated=False`` leaves it at the previous week."""
    wb = XlsxWorkbook()
    wb.remove(wb.active)
    at = week if updated else week.previous
    year = week.ending.year

    ws = wb.create_sheet("Treasury Bills ")
    ws["Z379"] = "T-Bills Results"
    ws["Z380"] = dt(at.ending + timedelta(days=3))
    for col, tenor in zip("AA AB AC AD".split(), ("91-day", "182-day", "364-day", "Totals")):
        ws[f"{col}380"] = tenor
    rows = {382: ("Amount offered (Kshs Mn)", (8000, 10000, 10000)), 383: ("Bids received (Kshs Mn)", (17983.23, 19147.41, 10586.04)),
            385: ("Amount accepted", (12875.06, 17900.87, 10420.91)),
            392: ("Weighted Average rate of accepted bids", (0.087694, 0.088856, 0.090397)),
            394: ("Previous Weighted Average rate of accepted bids", (0.087781, 0.088949, 0.090431))}
    for r, (label, values) in rows.items():
        ws[f"Z{r}"] = label
        for col, v in zip("AA AB AC".split(), values):
            ws[f"{col}{r}"] = v

    ws = wb.create_sheet("Money Market Performance")
    ws["B2"], ws["C2"] = "Money Market Performance", dt(at.ending + timedelta(days=3))
    ws["B6"], ws["C6"] = "3-Months Bank Placements", 0.095
    ws["S2"], ws["T2"] = "Last Week", "This Week"
    ws["R3"], ws["S3"], ws["T3"] = FUNDS[0][0], 0.1090, 0.1100
    day = at.ending.day
    suffix = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    ws["S10"] = f"Money Market Fund Yield for Fund Managers as published on {day}{suffix} {at.ending:%B %Y}"
    ws["S11"], ws["T11"], ws["U11"] = "Rank", "Fund Manager", "Effective Annual Rate"
    for n, (fund, rate) in enumerate(funds or FUNDS):
        ws[f"S{12 + n}"], ws[f"T{12 + n}"], ws[f"U{12 + n}"] = n + 1, fund, rate

    ws = wb.create_sheet("Liquidity Indicators")
    ws.append(["Return to Table of content"])
    ws.append(["Interbank Rate"])
    ws.append([None, "Volumes", "Interbank Rate"])
    for day in weekdays(week.previous.previous_friday - timedelta(days=7), at.thursday):
        this = week.previous_friday <= day <= week.thursday
        ws.append([dt(day), 10000 if this else 20000, 0.0880 if this else 0.0875])

    ws = wb.create_sheet("Eurobond")
    days = weekdays(date(year, 1, 2), at.thursday)
    for date_col, yield_col, group, head, base in EUROBOND_HEADS:
        ws.cell(row=group[0], column=group[1], value=group[2])
        ws.cell(row=head[0], column=head[1], value=head[2])
        ws.cell(row=5, column=date_col, value="Date")
        for n, day in enumerate(days):
            ws.cell(row=6 + n, column=date_col, value=dt(day))
            ws.cell(row=6 + n, column=yield_col, value=eurobond_yield(base, day))
    top = 6 + len(days) + 6
    ws.cell(row=top - 1, column=18, value="Cytonn Report: Kenya's Outstanding Eurobond Debt")
    for n, label in enumerate(["Eurobond Issuance", "Issue Date", "Maturity Date", "Coupon Rate ",
                               "Amount Before Buyback (USD mn)", "Amount After Buyback (USD mn)"]):
        ws.cell(row=top, column=18 + n, value=label)
    for r, (name, issued, matures, coupon, before, after) in enumerate(ISSUES):
        for n, v in enumerate([name, dt(issued), dt(matures), coupon, before, after]):
            ws.cell(row=top + 1 + r, column=18 + n, value=v)

    ws = wb.create_sheet("Exchange rates")
    ws["B2"], ws["B3"], ws["B4"], ws["C4"] = "Source-CBK", "USD/Kshs", "Date", "Exchange Rate"
    # CBK's own published rates (the public fixture), newest first, as the analysts type them in.
    for n, (day, rate) in enumerate(sorted(((d, r) for d, r in cbk_rates().items() if d <= at.ending), reverse=True)):
        ws.cell(row=5 + n, column=2, value=dt(day))
        ws.cell(row=5 + n, column=3, value=rate)

    ws = wb.create_sheet("Import Cover")
    ws.append(["Return to Table of content"])
    ws.append(["Date", "Months of Import Cover (MIC)", "Average MIC", "Forex Reserves (USD bns)"])
    for n in range(6):
        ws.append([dt(at.ending - timedelta(days=7 * n)), 6.1, 4.9, 14.93 if n == 0 else 15.042])

    ws = wb.create_sheet("Diaspora Remittances")
    ws.append(["Return to Table of content"])
    ws.append(["USD Mns"])
    ws.append(["Year", "Month", "Date", "North America", "Europe", "Rest of World", "Total Remittances"])
    y, m = year, 8
    for n in range(30):
        ws.append([y, m, dt(date(y, m, 15)), 200.0 if n == 0 else 150.0, 50.0, 50.0, 400.0 if n < 12 else 380.0])
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)

    ws = wb.create_sheet("Government Borrowing")
    ws["Z3"] = dt(date(year, 7, 1))
    for col, label in zip("X Y Z AA AB".split(), ("Date", "Offer", "Accepted", "Redemptions", "w/w change")):
        ws[f"{col}5"] = label
    ws["X6"] = f"FY'{year}/{year + 1}"
    row, monday = 7, date(year, 7, 6)
    while monday <= at.ending + timedelta(days=3):
        ws[f"X{row}"], ws[f"Y{row}"], ws[f"Z{row}"], ws[f"AA{row}"] = dt(monday), 28000, 30000.0, -20000.0
        row, monday = row + 1, monday + timedelta(days=7)
    ws["X46"] = "Total"
    ws["X47"], ws["Y47"] = "Budget Borrowing target (Kshs bn)", "Pro-rated borrowing target (Kshs bn)"
    ws["X48"] = 910.0
    ws["X51"], ws["Y51"] = "Start of FY", dt(date(year, 7, 1))

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def no_draft(briefs, target, **kwargs) -> dict[str, Any]:
    """Stands in for narrative drafting: nothing found, so no model is called."""
    return {"week_start": (WEEK.ending - timedelta(days=6)).isoformat(), "week_end": WEEK.ending.isoformat(), "pieces": [],
            "shortfall": target, "warnings": []}
