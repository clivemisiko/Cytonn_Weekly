"""Cytonn's fixed income workbook (the "FI mastersheet"): what the weekly Fixed Income section reads.

Layout read from the 5 October 2026 workbook on 2026-10-09; everything is found by label
or date, since rows are added daily:

* 'Treasury Bills ': the "T-Bills Results" block.  The cell under the title is the
  auction's value date (the Monday after a Thursday auction); the rows are labelled
  ("Amount offered (Kshs Mn)", "Bids received (Kshs Mn)", "Amount accepted", "Weighted
  Average rate of accepted bids", "Previous Weighted Average rate of accepted bids").
* 'Money Market Performance': "3-Months Bank Placements" (typed); the ranked fund table
  under "Money Market Fund Yield for Fund Managers as published on <date>" (Rank, Fund
  Manager, Effective Annual Rate), source Business Daily.
* 'Liquidity Indicators': column A the date, B the interbank volume (KSh mn), C the rate.
* 'Eurobond': each issue has its own date column and yield column, side by side; the
  blocks are not row-aligned with one another, so each is read by its own dates.  The
  issue list is the table headed "Eurobond Issuance".
* 'Exchange rates': the daily CBK US dollar rate, newest first (date, rate).
* 'Import Cover': weekly reserves (USD bn) and months of import cover.
* 'Diaspora Remittances': monthly, by region.
* 'Government Borrowing': the fiscal year's auction log (Date, Offer, Accepted,
  Redemptions) and the "Budget Borrowing target (Kshs bn)" under it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional

from cytonn_weekly.weekly.week import Week
from cytonn_weekly.weekly.workbook import Cell, Sheet, Workbook, WorkbookError, norm

SOURCE_NAME = "Fixed income workbook"

TBILLS_SHEET = "Treasury Bills "
MMF_SHEET = "Money Market Performance"
LIQUIDITY_SHEET = "Liquidity Indicators"
EUROBOND_SHEET = "Eurobond"
RATES_SHEET = "Exchange rates"
RESERVES_SHEET = "Import Cover"
DIASPORA_SHEET = "Diaspora Remittances"
BORROWING_SHEET = "Government Borrowing"

TENORS = ("91-day", "182-day", "364-day")

# The five issues the report's table prints, with how each is found in the 'Eurobond' sheet:
# the text that heads its yield (or coupon) column, and where the yield column sits from it.
# The 2025 11-year issue is in the workbook and the CBK bulletin but is not printed (the fixed
# income team's answer, 2026-10-09).
EUROBOND_ISSUES = (
    # key, the report's column head, group header (row 1-3), column header, yield column offset, maturity year, issue-list name
    ("2018_10y", ("2018", "10-year issue"), "2018 issue", "10-year coupon", -1, 2028, "10-year 2018"),
    ("2018_30y", ("2018", "30-year issue"), "2018 issue", "30-year coupon", -1, 2048, "30-year 2018"),
    ("2019_12y", ("2019", "12-year issue"), "2019 issue", "12-yr (2019)", 0, 2032, "12-year 2019"),
    ("2021_13y", ("2021", "13-year issue"), "2021 issue", "13-yr (2021)", 0, 2034, "13-year 2021"),
    ("2024_7y", ("2024", "7-year issue"), "2024 issue", "7-yr (2024)", 0, 2031, "7-year 2024"),
)


def open_fi_workbook(source, name: str = SOURCE_NAME) -> Workbook:
    book = Workbook(source, name)
    missing = [s for s in (TBILLS_SHEET, MMF_SHEET, EUROBOND_SHEET) if s not in book.sheet_names]
    if missing:
        raise WorkbookError(f"{name} is not the fixed income workbook: it has no sheet {missing[0]!r}")
    return book


# ---------------------------------------------------------------------------
# T-bills
# ---------------------------------------------------------------------------

_TBILL_ROWS = {
    "offered": "amount offered (kshs mn)",
    "bids": "bids received (kshs mn)",
    "accepted": "amount accepted",
    "rate": "weighted average rate of accepted bids",
    "previous_rate": "previous weighted average rate of accepted bids",
}


def read_tbills(book: Workbook, week: Week) -> dict[str, Any]:
    """This week's auction from the "T-Bills Results" block: {value_date, tenor: {offered, bids, accepted, rate, previous_rate}}."""
    sheet = book.sheet(TBILLS_SHEET)
    title = sheet.find("t-bills results", what="'T-Bills Results' block")
    head = title.row + 1
    value_date = sheet.cell(head, title.col)
    first, last = week.value_date_window
    if value_date.day is None or not first <= value_date.day <= last:
        shown = value_date.day.isoformat() if value_date.day else repr(value_date.value)
        raise WorkbookError(
            f"'{TBILLS_SHEET}' T-Bills Results block is for value date {shown} ({value_date.ref}), not the week ending "
            f"{week.ending.isoformat()} (expected {first.isoformat()} to {last.isoformat()}): workbook not yet updated for this week")
    cols = {}
    for tenor in TENORS:
        cols[tenor] = sheet.find(tenor, rows=range(head, head + 1), cols=range(title.col, title.col + 8),
                                 what=f"'{tenor}' column in the T-Bills Results block").col
    out: dict[str, Any] = {"value_date": value_date}
    rows = range(head, head + 25)
    label_col = range(title.col, title.col + 1)
    for key, label in _TBILL_ROWS.items():
        row = sheet.find(label, rows=rows, cols=label_col, what=f"'{label}' row in the T-Bills Results block").row
        for tenor in TENORS:
            out.setdefault(tenor, {})[key] = sheet.number(row, cols[tenor], f"T-bills {tenor} {key}")
    return out


# ---------------------------------------------------------------------------
# Money market
# ---------------------------------------------------------------------------

_PUBLISHED = re.compile(r"as published on\s+(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)\s+(\d{4})")
CYTONN_FUND = "cytonn money market fund"


def read_placements(book: Workbook) -> Cell:
    sheet = book.sheet(MMF_SHEET)
    label = sheet.find(lambda s: s.replace(" ", "") in ("3-monthsbankplacements", "3-monthbankplacements"),
                       rows=range(1, 30), what="'3-Months Bank Placements' row")
    return sheet.number(label.row, label.col + 1, "3-month bank placements")


def read_mmf_table(book: Workbook, week: Week) -> dict[str, Any]:
    """The ranked fund table published on the week's Friday: {published, title, funds: [{rank, fund, rate}]}."""
    sheet = book.sheet(MMF_SHEET)
    title = sheet.find(lambda s: s.startswith("money market fund yield for fund managers as published on"),
                       what="'Money Market Fund Yield for Fund Managers as published on ...' table")
    m = _PUBLISHED.search(norm(title.value))
    try:
        published = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y").date() if m else None
    except ValueError:
        published = None
    if published != week.ending:
        shown = published.isoformat() if published else f"an unreadable date ({title.value!r})"
        raise WorkbookError(f"'{MMF_SHEET}' fund table ({title.ref}) is as published on {shown}, not "
                            f"{week.ending.isoformat()}: workbook not yet updated for this week")
    head = title.row + 1
    rank = sheet.find("rank", rows=range(head, head + 2), what="'Rank' header of the fund table")
    fund = sheet.find("fund manager", rows=range(rank.row, rank.row + 1), what="'Fund Manager' header")
    rate = sheet.find("effective annual rate", rows=range(rank.row, rank.row + 1), what="'Effective Annual Rate' header")
    funds = []
    for r in range(rank.row + 1, sheet.max_row + 1):
        name = sheet.value(r, fund.col)
        if not isinstance(name, str) or not name.strip():
            break
        funds.append({"rank": sheet.cell(r, rank.col), "fund": sheet.cell(r, fund.col),
                      "rate": sheet.number(r, rate.col, f"rate of {name.strip()}")})
    if not funds:
        raise WorkbookError(f"'{MMF_SHEET}' fund table at {title.ref} has no rows")
    return {"published": published, "title": " ".join(str(title.value).split()), "funds": funds}


def read_mmf_last_week(book: Workbook) -> Optional[Cell]:
    """The Cytonn fund's rate in the sheet's "Last Week" column, if the sheet still carries it."""
    sheet = book.sheet(MMF_SHEET)
    heads = sheet.find_all("last week", rows=range(1, 6))
    if not heads:
        return None
    head = heads[0]
    for r in range(head.row + 1, head.row + 12):
        label = sheet.value(r, head.col - 1)
        if isinstance(label, str) and norm(label).startswith(CYTONN_FUND):
            c = sheet.cell(r, head.col)
            return c if c.number is not None else None
    return None


# ---------------------------------------------------------------------------
# Liquidity
# ---------------------------------------------------------------------------

def read_interbank(book: Workbook, first: date, last: date) -> list[dict[str, Any]]:
    """The daily interbank rows from ``first`` to ``last``: [{date, volume, rate}] (cells)."""
    sheet = book.sheet(LIQUIDITY_SHEET)
    out = []
    for r in range(4, sheet.max_row + 1):
        d = sheet.value(r, 1)
        if isinstance(d, datetime) and first <= d.date() <= last:
            vol, rate = sheet.cell(r, 2), sheet.cell(r, 3)
            if vol.number is not None and rate.number is not None:
                out.append({"date": d.date(), "volume": vol, "rate": rate})
    return out


# ---------------------------------------------------------------------------
# Eurobonds
# ---------------------------------------------------------------------------

@dataclass
class EurobondSeries:
    key: str
    head: tuple[str, str]                  # ("2018", "10-year issue")
    maturity_year: int
    yields: dict[date, Cell] = field(default_factory=dict)   # as fractions (0.07626)
    issue: Optional[dict[str, Cell]] = None                  # issue list row: issue_date, maturity, coupon, amount_before, amount_after


def _date_column(sheet: Sheet, yield_col: int, sample_rows: range) -> int:
    """The nearest column left of a yield column whose cells in ``sample_rows`` are dates."""
    for col in range(yield_col - 1, max(yield_col - 5, 0), -1):
        if sum(isinstance(sheet.value(r, col), datetime) for r in sample_rows) >= len(sample_rows) // 2:
            return col
    raise WorkbookError(f"'{EUROBOND_SHEET}' has no date column beside its yield column {yield_col}")


def read_eurobonds(book: Workbook) -> list[EurobondSeries]:
    """The five printed issues' daily yields (by date) and their issue-list rows."""
    sheet = book.sheet(EUROBOND_SHEET)
    heads = range(1, 6)
    issues_head = sheet.find("eurobond issuance", what="'Eurobond Issuance' issue list")
    issue_cols = {}
    for key, label in (("issue_date", "issue date"), ("maturity", "maturity date"), ("coupon", "coupon rate"),
                       ("amount_before", "amount before buyback (usd mn)"), ("amount_after", "amount after buyback (usd mn)")):
        issue_cols[key] = sheet.find(label, rows=range(issues_head.row, issues_head.row + 1),
                                     cols=range(issues_head.col, issues_head.col + 8), what=f"issue list '{label}'").col
    data_rows = range(max(issues_head.row - 40, 7), issues_head.row - 4)
    out = []
    for key, head, group, label, offset, maturity_year, list_name in EUROBOND_ISSUES:
        candidates = sheet.find_all(label, rows=heads)
        groups = sheet.find_all(group, rows=heads)
        # The column header under the nearest group header at or left of it ("10-year coupon" also
        # heads the retired 2014 issue, further left, under "10-year (2014 Issue)").
        hit = None
        for c in candidates:
            left = [g for g in groups if g.col <= c.col and c.col - g.col <= 6]
            if left:
                hit = c
        if hit is None:
            raise WorkbookError(f"'{EUROBOND_SHEET}' has no '{label}' column under a '{group}' header")
        ycol = hit.col + offset
        dcol = _date_column(sheet, ycol, data_rows)
        series = EurobondSeries(key, head, maturity_year)
        for r in range(6, issues_head.row - 2):
            d, y = sheet.value(r, dcol), sheet.value(r, ycol)
            if isinstance(d, datetime) and isinstance(y, (int, float)) and not isinstance(y, bool):
                series.yields[d.date()] = sheet.cell(r, ycol)
        row = next((c.row for c in sheet.find_all(list_name, rows=range(issues_head.row + 1, issues_head.row + 14),
                                                  cols=range(issues_head.col, issues_head.col + 1))), None)
        if row is not None:
            series.issue = {k: sheet.cell(row, col) for k, col in issue_cols.items()}
        out.append(series)
    return out


# ---------------------------------------------------------------------------
# Shilling, reserves, remittances
# ---------------------------------------------------------------------------

def read_exchange_rates(book: Workbook) -> dict[date, Cell]:
    sheet = book.sheet(RATES_SHEET)
    head = sheet.find("exchange rate", rows=range(1, 8), what="'Exchange Rate' header")
    out: dict[date, Cell] = {}
    for r in range(head.row + 1, sheet.max_row + 1):
        d = sheet.value(r, head.col - 1)
        c = sheet.cell(r, head.col)
        if isinstance(d, datetime) and c.number is not None:
            out.setdefault(d.date(), c)
    if not out:
        raise WorkbookError(f"'{RATES_SHEET}' has no dated rates under its 'Exchange Rate' header")
    return out


def read_reserves(book: Workbook) -> list[dict[str, Any]]:
    """Weekly reserves, newest first: [{date, months, usd_bn}] (cells)."""
    sheet = book.sheet(RESERVES_SHEET)
    # Anchored on the "Date" header in column A: an older block further right repeats both labels.
    head = sheet.find("date", rows=range(1, 6), cols=range(1, 2), what="'Date' header in column A")
    row, near = range(head.row, head.row + 1), range(2, 8)
    months = sheet.find(lambda s: s.startswith("months of import cover"), rows=row, cols=near, what="'Months of Import Cover' header")
    usd = sheet.find(lambda s: s.startswith("forex reserves"), rows=row, cols=near, what="'Forex Reserves' header")
    out = []
    for r in range(head.row + 1, sheet.max_row + 1):
        d = sheet.value(r, 1)
        if isinstance(d, datetime) and sheet.cell(r, usd.col).number is not None:
            out.append({"date": d.date(), "months": sheet.cell(r, months.col), "usd_bn": sheet.cell(r, usd.col)})
    return out


def read_remittances(book: Workbook) -> list[dict[str, Any]]:
    """Monthly remittances, newest first: [{year, month, north_america, total}] (cells), USD mn."""
    sheet = book.sheet(DIASPORA_SHEET)
    year = sheet.find("year", rows=range(1, 6), cols=range(1, 2), what="'Year' header")
    month = sheet.find("month", rows=range(year.row, year.row + 1), what="'Month' header")
    north = sheet.find("north america", rows=range(year.row, year.row + 1), what="'North America' header")
    total = sheet.find("total remittances", rows=range(year.row, year.row + 1), what="'Total Remittances' header")
    out = []
    for r in range(year.row + 1, sheet.max_row + 1):
        y, m = sheet.value(r, year.col), sheet.value(r, month.col)
        if isinstance(y, (int, float)) and isinstance(m, (int, float)) and sheet.cell(r, total.col).number is not None:
            out.append({"year": int(y), "month": int(m), "north_america": sheet.cell(r, north.col),
                        "total": sheet.cell(r, total.col)})
    return out


# ---------------------------------------------------------------------------
# Government borrowing
# ---------------------------------------------------------------------------

def read_borrowing(book: Workbook) -> dict[str, Any]:
    """The fiscal year's auction log and the typed net domestic borrowing target.

    {fy_start (cell), target_bn (cell), log: [{date, offer, accepted, redemptions}]} with
    amounts in KSh mn as typed (redemptions are negative).
    """
    sheet = book.sheet(BORROWING_SHEET)
    target_label = sheet.find(lambda s: s.startswith("budget borrowing target"), what="'Budget Borrowing target (Kshs bn)'")
    target = sheet.number(target_label.row + 1, target_label.col, "net domestic borrowing target")
    start_label = sheet.find("start of fy", rows=range(target_label.row, target_label.row + 8), what="'Start of FY'")
    fy_start = sheet.cell(start_label.row, start_label.col + 1)
    if fy_start.day is None:
        raise WorkbookError(f"'{BORROWING_SHEET}' 'Start of FY' ({fy_start.ref}) is not a date")
    heads = [c for c in sheet.find_all("accepted", rows=range(1, target_label.row)) if c.col >= target_label.col]
    head = next((c for c in heads if norm(sheet.value(c.row, c.col - 1)) == "offer" and norm(sheet.value(c.row, c.col - 2)) == "date"
                 and norm(sheet.value(c.row, c.col + 1)) == "redemptions"), None)
    if head is None:
        raise WorkbookError(f"'{BORROWING_SHEET}' has no Date / Offer / Accepted / Redemptions log above its borrowing target")
    log = []
    for r in range(head.row + 1, target_label.row):
        d = sheet.value(r, head.col - 2)
        if isinstance(d, datetime) and d.date() >= fy_start.day:
            acc, red = sheet.cell(r, head.col), sheet.cell(r, head.col + 1)
            if acc.number is None or red.number is None:
                raise WorkbookError(f"'{BORROWING_SHEET}' log row {r} has a date but no accepted or redemptions amount")
            log.append({"date": d.date(), "offer": sheet.cell(r, head.col - 1), "accepted": acc, "redemptions": red})
    if not log:
        raise WorkbookError(f"'{BORROWING_SHEET}' log has no auctions since {fy_start.day.isoformat()}")
    return {"fy_start": fy_start, "target_bn": target, "log": log}
