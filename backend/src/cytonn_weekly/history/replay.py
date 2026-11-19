from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, NamedTuple, Optional, Union

from cytonn_weekly.history import reads, store
from cytonn_weekly.history.importer import friday_of
from cytonn_weekly.weekly import equities_workbook as eq
from cytonn_weekly.weekly.inputs import equities_workbook_date
from cytonn_weekly.weekly.week import Week
from cytonn_weekly.weekly.workbook import Workbook

DRIFT = 0.06   # USD mn: how far a running total may sit from the sum of its weekly figures, at two places, before it is a failure (the team's hand edits)


class Line(NamedTuple):
    week: str
    series: str
    check: str
    status: str            # PASS, FAIL or SKIP
    difference: Optional[float] = None   # the size of the difference, never a value
    note: str = ""


def _weeks(book: Workbook, sheet_name: str, ytd_col: int) -> dict[date, tuple[float, Optional[float]]]:
    """The workbook's own weekly rows: {the week's Friday: (the week's figure, the running total)}."""
    sheet = book.sheet(sheet_name)
    out = {}
    for last_day, r in eq._weekly_rows(sheet, ytd_col):
        week, ytd = sheet.cell(r, 2).number, sheet.cell(r, ytd_col).number
        if week is not None:
            out[friday_of(last_day)] = (week, ytd)
    return out


def _running_totals(book: Workbook, db_path: Any, key: str, sheet_name: str, ytd_col: int) -> list[Line]:
    """For each week: the store's "before" is the workbook's own total a week earlier, and before + the week's figure is the workbook's total."""
    rows = _weeks(book, sheet_name, ytd_col)
    gaps = {}   # the sum's break from the workbook's own total, per week that has a week before it
    for day, (week, ytd) in rows.items():
        was = rows.get(day - timedelta(days=7))
        if was is not None and was[1] is not None and ytd is not None:
            gaps[day] = abs(was[1] + week - ytd)
    restart = {}   # the one break per year beyond RESTART_BREAK that is the new year's restart
    for day, gap in gaps.items():
        if gap > eq.RESTART_BREAK and gap > gaps.get(restart.get(day.year), -1):
            restart[day.year] = day
    lines = []
    for day in sorted(gaps):
        week = Week(day)
        before = reads.running_before(week, key, None, db_path)
        was = rows[day - timedelta(days=7)][1]
        stamp = day.isoformat()
        lines.append(Line(stamp, key, "before is last week's total", "PASS" if before is not None and reads._same(before.number, was) else "FAIL",
                          None if before is None else abs(before.number - was), "" if before is not None else "no confirmed point in the store"))
        if restart.get(day.year) == day:
            lines.append(Line(stamp, key, "before + week against the total", "SKIP", gaps[day], "the new year's restart"))
        else:
            lines.append(Line(stamp, key, "before + week against the total", "PASS" if round(gaps[day], 2) <= DRIFT else "FAIL", gaps[day],
                              "" if gaps[day] == 0 else "the workbook's own total is not exactly its running sum"))
    return lines


def _foreign_weeks(book: Workbook, db_path: Any) -> list[Line]:
    """For each week: the store's weekly sums before it are the workbook's, week for week."""
    rows = _weeks(book, eq.FOREIGN_SHEET, 5)
    lines = []
    for day in sorted(rows):
        week = Week(day)
        theirs = {d: w for d, (w, _) in rows.items() if d < week.monday}
        found = {d: n for d, n, _ in reads.foreign_history(week, [], db_path)}
        wrong = [d for d in theirs if d not in found or not reads._same(found[d], theirs[d])]
        lines.append(Line(day.isoformat(), "eq.foreign.week", "weeks before this one", "FAIL" if wrong else "PASS", None,
                          f"{len(wrong)} of {len(theirs)} weeks differ or are missing" if wrong else f"{len(theirs)} weeks"))
    return lines


def _prior_years(book: Workbook, db_path: Any) -> list[Line]:
    """For each year the workbook restarts the foreign total in: the store's total for the year before is the workbook's."""
    series = eq.read_daily_series(book, eq.FOREIGN_SHEET, Week(date(2000, 1, 7)), 5, weeks_back=100_000)
    lines = []
    for year in sorted({d.year for d, *_ in series.history}):
        theirs = eq.prior_year_total(series, year)
        if theirs is None:
            continue
        last = max(d for d, *_ in series.history if d.year == year)
        mine = reads.foreign_prior_year(Week(friday_of(last)), None, db_path)
        lines.append(Line(f"{year}", "eq.foreign.ytd", "total the year before closed on",
                          "PASS" if mine is not None and reads._same(mine.number, theirs.number) else "FAIL",
                          None if mine is None else abs(mine.number - theirs.number), "" if mine is not None else "no total in the store"))
    return lines


def _prices(book: Workbook, db_path: Any) -> list[Line]:
    """For each price column that is a report date: the store's last Friday's price per company is the workbook's cell."""
    sheet = book.sheet(eq.UNIVERSE_SHEET)
    company = sheet.find("company", rows=range(eq.HEADER_ROW, eq.HEADER_ROW + 1), cols=range(1, 6), what="'Company' header").col
    names = []
    for r in range(eq.HEADER_ROW + 1, sheet.max_row + 1):
        name = sheet.value(r, company)
        if not isinstance(name, str) or not name.strip():
            break
        names.append((" ".join(name.split()).lower(), r))
    lines = []
    for day, col in sorted(eq._price_columns(sheet).items()):
        week = Week(friday_of(day) + timedelta(days=7))
        if day not in week.previous.report_dates:
            continue
        stored = reads.last_prices(week, db_path)
        gaps = [n for n, r in names if sheet.cell(r, col).number is not None and (n not in stored or not reads._same(stored[n].number, sheet.cell(r, col).number))]
        counted = sum(1 for _, r in names if sheet.cell(r, col).number is not None)
        lines.append(Line(week.ending.isoformat(), "eq.price", "last Friday's price per company", "FAIL" if gaps else "PASS", None,
                          f"{len(gaps)} of {counted} companies differ or are missing" if gaps else f"{counted} companies"))
    return lines


def _average_pe(book: Workbook, db_path: Any) -> list[Line]:
    """The workbook states its AVERAGE once, for its own latest week: the store's mean over the same window is that cell."""
    newest = equities_workbook_date(book)
    if newest is None:
        return []
    week = Week(friday_of(newest))
    theirs = eq.read_valuation(book, week)["pe_average"]
    mine = reads.pe_average(week, None, db_path)
    same = mine is not None and reads._same(mine.number, theirs.number, 6)   # the builder's own precision for this average
    return [Line(week.ending.isoformat(), "eq.pe", "historical average over the workbook's window", "PASS" if same else "FAIL",
                 None if mine is None else abs(mine.number - theirs.number), mine.source if mine is not None else "no confirmed P/E point for this week")]


def run(book: Workbook, db_path: Union[Path, str]) -> list[Line]:
    """Every check of the equities workbook's history against the store at ``db_path`` (a scratch database), with the reads switched on."""
    old = os.environ.get(reads.MODE_ENV)
    os.environ[reads.MODE_ENV] = reads.ON
    try:
        lines = _running_totals(book, db_path, "eq.turnover.ytd", eq.TURNOVER_SHEET, 6)
        lines += _running_totals(book, db_path, "eq.foreign.ytd", eq.FOREIGN_SHEET, 5)
        return lines + _foreign_weeks(book, db_path) + _prior_years(book, db_path) + _prices(book, db_path) + _average_pe(book, db_path)
    finally:
        if old is None:
            os.environ.pop(reads.MODE_ENV, None)
        else:
            os.environ[reads.MODE_ENV] = old


def summary(lines: list[Line]) -> list[str]:
    by: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for line in lines:
        by[(line.series, line.check)][line.status].append(line.week)
    return [f"{series} | {check}: {len(s['PASS'])} PASS, {len(s['FAIL'])} FAIL, {len(s['SKIP'])} SKIP"
            + (f" (weeks {min(sum(s.values(), []))} to {max(sum(s.values(), []))})" if s else "") for (series, check), s in by.items()]
