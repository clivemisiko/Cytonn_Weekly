"""Cytonn's equities workbook: what the weekly Equities section reads from it.

Sheet names are verbatim (two end in a space).  Layout read from the 2 October 2026
workbook (v6) on 2026-10-09; every item is found by label or date:

* 'Kenyan Indices ': the "Weekly" block's header row holds "Year Open <year>", "Last week"
  and "Today"; the rows are labelled NSE 20, NASI, NSE 25, NSE 10.  The "Banking Index"
  row heads its own columns ("Year Open <year>", "Last Week", "This week") with the values
  on the row below.  All typed.
* 'Equities Turnover': column A the date, column B the day's turnover in USD mn (the day's
  equities turnover in KES divided by that day's CBK rate).  After each Friday a row with
  no date holds the week: B the sum, C the change on the previous week, F the running
  year-to-date total.
* 'Foreign Positions': the same shape for net foreign flows, with the running total in E.
* 'NASI-PE & Dividend Yield': one row per Friday, newest first: B the market P/E (typed,
  from Bloomberg), D the dividend yield.  The "AVERAGE" row above holds the averages of
  both series; the cell under the "PEG" label is the P/E divided by a fixed 8.
* 'Market PE & Dividend Yield': the large-cap list sits in the column left of the
  "Year Open" header.
* 'Universe of Coverage': row 2 heads the columns; the weekly "Price as at dd/mm/yyyy"
  columns are found by their dates and the inputs by their header text, taking the first
  one to the right of the week's price column (older blocks repeat the headers further left).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

from cytonn_weekly.weekly.week import Week
from cytonn_weekly.weekly.workbook import Cell, Sheet, Workbook, WorkbookError, average_range, norm

SOURCE_NAME = "Equities workbook"

INDICES_SHEET = "Kenyan Indices "
TURNOVER_SHEET = "Equities Turnover"
FOREIGN_SHEET = "Foreign Positions"
VALUATION_SHEET = "NASI-PE & Dividend Yield"
MARKET_PE_SHEET = "Market PE & Dividend Yield"
UNIVERSE_SHEET = "Universe of Coverage"

INDEX_LABELS = {"nse_20": "nse 20", "nasi": "nasi", "nse_25": "nse 25", "nse_10": "nse 10"}

# The market's PEG ratio is its P/E over a fixed growth rate of 8 (the workbook's "=B8/8";
# the equities team confirmed on 2026-10-09 that the 8 is fixed, not a forecast).
PEG_GROWTH = 8


def not_updated(sheet: str, day: date) -> WorkbookError:
    return WorkbookError(f"'{sheet}' has no row for {day.isoformat()}: workbook not yet updated for this week")


def open_equities_workbook(source, name: str = SOURCE_NAME) -> Workbook:
    book = Workbook(source, name)
    missing = [s for s in (INDICES_SHEET, TURNOVER_SHEET, FOREIGN_SHEET, VALUATION_SHEET, UNIVERSE_SHEET)
               if s not in book.sheet_names]
    if missing:
        raise WorkbookError(f"{name} is not the equities workbook: it has no sheet {missing[0]!r}")
    return book


# ---------------------------------------------------------------------------
# Indices
# ---------------------------------------------------------------------------

def read_indices(book: Workbook, year: int) -> dict[str, dict[str, Cell]]:
    """{index: {year_open, last_week, today}} from the Weekly block, plus "banking" from its own row."""
    sheet = book.sheet(INDICES_SHEET)
    head = sheet.find("last week", rows=range(1, 8), what="'Last week' header in its Weekly block")
    today = sheet.find("today", rows=range(head.row, head.row + 1), what="'Today' header")
    opened = sheet.find(f"year open {year}", rows=range(head.row, head.row + 1), what=f"'Year Open {year}' header")
    out: dict[str, dict[str, Cell]] = {}
    for key, label in INDEX_LABELS.items():
        row = sheet.find(label, rows=range(head.row + 1, head.row + 6), cols=range(1, 2), what=f"{label.upper()} row").row
        out[key] = {
            "year_open": sheet.number(row, opened.col, f"{label.upper()} Year Open {year}"),
            "last_week": sheet.number(row, head.col, f"{label.upper()} last week"),
            "today": sheet.number(row, today.col, f"{label.upper()} today"),
        }
    bank = sheet.find("banking index", cols=range(1, 2), what="'Banking Index' row")
    cols = range(2, 16)
    b_open = sheet.find(f"year open {year}", rows=range(bank.row, bank.row + 1), cols=cols, what=f"Banking 'Year Open {year}'")
    b_last = sheet.find("last week", rows=range(bank.row, bank.row + 1), cols=cols, what="Banking 'Last Week'")
    b_this = sheet.find("this week", rows=range(bank.row, bank.row + 1), cols=cols, what="Banking 'This week'")
    out["banking"] = {
        "year_open": sheet.number(bank.row + 1, b_open.col, f"Banking index Year Open {year}"),
        "last_week": sheet.number(bank.row + 1, b_last.col, "Banking index last week"),
        "today": sheet.number(bank.row + 1, b_this.col, "Banking index this week"),
    }
    return out


# ---------------------------------------------------------------------------
# Turnover and foreign flows (daily rows with a weekly row after each Friday)
# ---------------------------------------------------------------------------

@dataclass
class WeeklySeries:
    """One week of a daily USD series: the days that have a row, and the week's own row."""

    days: dict[date, Cell] = field(default_factory=dict)
    total: Optional[Cell] = None      # the weekly SUM row's figure
    ytd: Optional[Cell] = None        # the running year-to-date figure on that row
    # (the week's last day, its total, the running figure, that figure's cell), oldest first
    history: list[tuple[date, float, Optional[float], Optional[Cell]]] = field(default_factory=list)


def _weekly_rows(sheet: Sheet, ytd_col: int) -> list[tuple[date, int]]:
    """(the last dated day above it, row number) for every weekly row: no date in A, a number in B."""
    out, last = [], None
    for r in range(2, sheet.max_row + 1):
        a, b = sheet.value(r, 1), sheet.value(r, 2)
        if isinstance(a, datetime):
            last = a.date()
        elif a is None and isinstance(b, (int, float)) and last is not None:
            out.append((last, r))
    return out


def read_daily_series(book: Workbook, sheet_name: str, week: Week, ytd_col: int, weeks_back: int = 60) -> WeeklySeries:
    sheet = book.sheet(sheet_name)
    series = WeeklySeries()
    for day in week.trading_days:
        row = sheet.row_for_date(day, 1)
        if row is not None and isinstance(sheet.value(row, 2), (int, float)):
            series.days[day] = sheet.cell(row, 2)
    weekly = _weekly_rows(sheet, ytd_col)
    for last_day, row in weekly[-weeks_back:]:
        ytd = sheet.value(row, ytd_col)
        has = isinstance(ytd, (int, float))
        series.history.append((last_day, float(sheet.value(row, 2)), float(ytd) if has else None,
                               sheet.cell(row, ytd_col) if has else None))
    this = next((row for last_day, row in weekly if week.monday <= last_day <= week.ending), None)
    if this is not None:
        series.total = sheet.cell(this, 2)
        if isinstance(sheet.value(this, ytd_col), (int, float)):
            series.ytd = sheet.cell(this, ytd_col)
    return series


def read_turnover(book: Workbook, week: Week) -> WeeklySeries:
    return read_daily_series(book, TURNOVER_SHEET, week, ytd_col=6)


def read_foreign_flows(book: Workbook, week: Week) -> WeeklySeries:
    return read_daily_series(book, FOREIGN_SHEET, week, ytd_col=5)


RESTART_BREAK = 1.0  # USD mn: a break in the running total larger than this is a restart, not a typing slip


def prior_year_total(series: WeeklySeries, year: int) -> Optional[Cell]:
    """The running total the year before ``year`` closed on: the figure on the row before the restart.

    Each weekly row's running figure is the row before plus the week's own figure, except
    where the analysts restart the count for a new year.  The restart is the row of ``year``
    where that sum breaks by the most (and by more than RESTART_BREAK; smaller breaks are
    hand edits: in the 2026 workbook the week ending 2 January 2026 is still in 2025's total
    and is 0.06 off).  None if ``year`` shows no restart.
    """
    best: Optional[tuple[float, Cell]] = None
    for n in range(1, len(series.history)):
        day, total, ytd, _ = series.history[n]
        _, _, prev_ytd, prev_cell = series.history[n - 1]
        if day.year != year or ytd is None or prev_ytd is None or prev_cell is None:
            continue
        gap = abs((ytd - prev_ytd) - total)
        if gap > RESTART_BREAK and (best is None or gap > best[0]):
            best = (gap, prev_cell)
    return best[1] if best else None


# ---------------------------------------------------------------------------
# Valuation
# ---------------------------------------------------------------------------

def _series_average(book: Workbook, sheet: Sheet, stated: Cell) -> Optional[tuple[float, int, str]]:
    """(the average recomputed over the formula's own range, how many figures, the range) or None."""
    rng = average_range(book.formula(stated))
    if rng is None:
        return None
    col_letter, first, last = rng
    col = stated.col
    values = [v for v in (sheet.value(r, col) for r in range(first, last + 1)) if isinstance(v, (int, float))]
    if not values:
        return None
    return sum(values) / len(values), len(values), f"{col_letter}{first}:{col_letter}{last}"


def read_valuation(book: Workbook, week: Week) -> dict[str, Any]:
    """The Friday's market P/E and dividend yield, their historical averages and the sheet's PEG."""
    sheet = book.sheet(VALUATION_SHEET)
    row = sheet.row_for_date(week.ending, 1)
    if row is None:
        raise not_updated(VALUATION_SHEET, week.ending)
    avg = sheet.find("average", cols=range(1, 2), rows=range(1, row), what="'AVERAGE' row")
    out: dict[str, Any] = {
        "pe": sheet.number(row, 2, f"market P/E for {week.ending.isoformat()}"),
        "dividend_yield": sheet.number(row, 4, f"dividend yield for {week.ending.isoformat()}"),
        "pe_average": sheet.number(avg.row, 2, "average P/E"),
        "dividend_yield_average": sheet.number(avg.row, 4, "average dividend yield"),
    }
    prev = sheet.row_for_date(week.previous_friday, 1)
    out["previous_pe"] = sheet.cell(prev, 2) if prev else None
    out["pe_average_recomputed"] = _series_average(book, sheet, out["pe_average"])
    out["dividend_yield_average_recomputed"] = _series_average(book, sheet, out["dividend_yield_average"])
    peg = sheet.find_all("peg")
    out["peg_sheet"] = sheet.cell(peg[0].row + 1, peg[0].col) if peg else None
    return out


def read_large_caps(book: Workbook) -> list[Cell]:
    """The large-cap list: the names in the column left of the "Year Open" header, until the first gap."""
    sheet = book.sheet(MARKET_PE_SHEET)
    head = sheet.find("year open", rows=range(1, 2), what="'Year Open' header beside the large-cap list")
    names = []
    for r in range(2, sheet.max_row + 1):
        c = sheet.cell(r, head.col - 1)
        if not isinstance(c.value, str) or not c.value.strip():
            break
        names.append(c)
    if not names:
        raise WorkbookError(f"'{MARKET_PE_SHEET}' lists no large caps beside its 'Year Open' column")
    return names


# ---------------------------------------------------------------------------
# Universe of Coverage
# ---------------------------------------------------------------------------

_PRICE_HEAD = re.compile(r"^price as at (\d{2})/(\d{2})/(\d{4})$")
HEADER_ROW = 2


def _price_columns(sheet: Sheet) -> dict[date, int]:
    """{date: column} for every "Price as at dd/mm/yyyy" header; the right-most wins for a repeated date."""
    out: dict[date, int] = {}
    for c in sheet.cells(rows=range(HEADER_ROW, HEADER_ROW + 1)):
        m = _PRICE_HEAD.match(norm(c.value))
        if m:
            try:
                out[date(int(m.group(3)), int(m.group(2)), int(m.group(1)))] = c.col
            except ValueError:
                continue
    return out


def read_universe(book: Workbook, week: Week) -> dict[str, Any]:
    """The Universe of Coverage inputs for the week: per company, the three prices and the typed inputs.

    ``month_end`` is the latest price column dated before the month the week ends in (the
    previous month's last close, the base of the m/m change).
    """
    sheet = book.sheet(UNIVERSE_SHEET)
    prices = _price_columns(sheet)
    if week.ending not in prices:
        raise WorkbookError(f"'{UNIVERSE_SHEET}' has no 'Price as at {week.ending.strftime('%d/%m/%Y')}' column: "
                            "workbook not yet updated for this week")
    if week.previous_friday not in prices:
        raise WorkbookError(f"'{UNIVERSE_SHEET}' has no 'Price as at {week.previous_friday.strftime('%d/%m/%Y')}' column")
    month_start = week.ending.replace(day=1)
    earlier = [d for d in prices if d < month_start]
    if not earlier:
        raise WorkbookError(f"'{UNIVERSE_SHEET}' has no price column before {month_start.isoformat()} for the m/m change")
    month_end = max(earlier)
    this_col = prices[week.ending]

    def right_of(label_test, what: str) -> int:
        found = [c for c in sheet.find_all(label_test, rows=range(HEADER_ROW, HEADER_ROW + 1)) if c.col > this_col]
        if not found:
            raise WorkbookError(f"'{UNIVERSE_SHEET}' has no {what} column to the right of the week's price column")
        return min(found, key=lambda c: c.col).col

    year = week.ending.year
    cols = {
        "year_open": right_of(f"year open {year}", f"'Year Open {year}'"),
        "target": right_of(lambda s: s.startswith("target price"), "'Target Price'"),
        "dps": right_of("dps", "'DPS'"),
        "shares_bn": right_of(lambda s: s.startswith("no. of shares"), "'No. of Shares(bn)'"),
        "tbv_bn": right_of(lambda s: s.startswith("tangible book value (bn)"), "'Tangible Book Value (bn)'"),
    }
    company_col = sheet.find("company", rows=range(HEADER_ROW, HEADER_ROW + 1), cols=range(1, 6), what="'Company' header").col
    companies = []
    for r in range(HEADER_ROW + 1, sheet.max_row + 1):
        name = sheet.value(r, company_col)
        if not isinstance(name, str) or not name.strip():
            break
        row = {"company": sheet.cell(r, company_col), "price": sheet.cell(r, this_col),
               "last_price": sheet.cell(r, prices[week.previous_friday]), "month_end_price": sheet.cell(r, prices[month_end])}
        row.update({key: sheet.cell(r, col) for key, col in cols.items()})
        companies.append(row)
    if not companies:
        raise WorkbookError(f"'{UNIVERSE_SHEET}' lists no companies under its 'Company' header")
    return {"companies": companies, "month_end": month_end, "week_ending": week.ending,
            "previous_friday": week.previous_friday}
