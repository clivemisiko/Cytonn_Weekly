from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Optional, Union

from cytonn_weekly.common.formatting import round_half_up
from cytonn_weekly.history import store
from cytonn_weekly.weekly import equities_workbook as eq
from cytonn_weekly.weekly import fi_workbook as fi
from cytonn_weekly.weekly.workbook import Cell, Workbook, WorkbookError

DECIMALS = 8   # workbook floats carry noise (1234.5600000000002): a point is kept to 8 decimals, rounded half up

# key: (unit, cadence, section, label, factor).  The factor turns the workbook's fraction into the percentage as printed (0.058 -> 5.8).
CATALOG = {
    "eq.turnover.day": ("usd_mn", "day", "equities", "Equities turnover, one day", 1),
    "eq.turnover.week": ("usd_mn", "week", "equities", "Equities turnover, the week", 1),
    "eq.turnover.ytd": ("usd_mn", "week", "equities", "Equities turnover, year to date", 1),
    "eq.foreign.day": ("usd_mn", "day", "equities", "Foreign net position, one day", 1),
    "eq.foreign.week": ("usd_mn", "week", "equities", "Foreign net position, the week", 1),
    "eq.foreign.ytd": ("usd_mn", "week", "equities", "Foreign net position, year to date", 1),
    "eq.pe": ("multiple", "week", "equities", "Market P/E", 1),
    "eq.dividend_yield": ("pct", "week", "equities", "Market dividend yield", 100),
    "eq.price": ("kes", "week", "equities", "Share price, by company", 1),
    "fi.interbank.volume": ("kes_mn", "day", "fixed_income", "Interbank volume", 1),
    "fi.interbank.rate": ("pct", "day", "fixed_income", "Interbank rate", 100),
    "fi.eurobond.yield": ("pct", "day", "fixed_income", "Eurobond yield, by issue", 100),
}


def friday_of(day: date) -> date:
    return day + timedelta(days=4 - day.weekday())


class Plan:
    """What a workbook would add: the points ready to record, and every row set aside with its reason (never a value)."""

    def __init__(self, today: date) -> None:
        self.today = today
        self.seen: Counter[str] = Counter()
        self.skipped: Counter[tuple[str, str]] = Counter()
        self.errors: list[str] = []
        self.sheets: list[str] = []
        self.points: list[dict[str, Any]] = []
        self._found: dict[tuple[str, str, date], list[tuple[Decimal, Cell, date]]] = defaultdict(list)

    def skip(self, key: str, reason: str, n: int = 1) -> None:
        self.skipped[(key, reason)] += n

    def add(self, key: str, cell: Cell, day: date, *, subject: str = "", week_ending: Optional[date] = None, weekend_ok: bool = False) -> None:
        self.seen[key] += 1
        number = cell.number
        if day.weekday() > 4 and not weekend_ok:
            return self.skip(key, "a weekend date")
        if day > self.today:
            return self.skip(key, "dated after today")
        if number is None or not math.isfinite(number):
            return self.skip(key, "no number in the cell")
        self._found[(key, subject, day)].append((round_half_up(Decimal(repr(number)) * CATALOG[key][4], DECIMALS), cell, week_ending or friday_of(day)))

    def finish(self) -> "Plan":
        self.points = []
        for (key, subject, day), found in sorted(self._found.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
            if len({v for v, _, _ in found}) > 1:
                self.skip(key, "the same date twice with different numbers (neither kept)")
                continue
            if len(found) > 1:
                self.skip(key, "the same date twice with the same number (one kept)", len(found) - 1)
            value, cell, week = found[0]
            unit, cadence, section, label, _ = CATALOG[key]
            self.points.append({"key": key, "subject": subject, "unit": unit, "section": section, "cadence": cadence, "label": label,
                                "as_of": day.isoformat(), "week_ending": week.isoformat(), "value": format(value.normalize(), "f"),
                                "origin": "workbook_import", "source_kind": "workbook_cell", "source_ref": cell.ref})
        return self


def _daily_and_weekly(plan: Plan, book: Workbook, sheet_name: str, prefix: str, ytd_col: int) -> None:
    sheet = book.sheet(sheet_name)
    for r in range(2, sheet.max_row + 1):
        if isinstance(sheet.value(r, 1), datetime):
            plan.add(f"{prefix}.day", sheet.cell(r, 2), sheet.value(r, 1).date())
    for last_day, r in eq._weekly_rows(sheet, ytd_col):
        friday = friday_of(last_day)
        plan.add(f"{prefix}.week", sheet.cell(r, 2), friday, week_ending=friday)
        plan.add(f"{prefix}.ytd", sheet.cell(r, ytd_col), friday, week_ending=friday)


def _valuation(plan: Plan, book: Workbook) -> None:
    sheet = book.sheet(eq.VALUATION_SHEET)
    for r in range(1, sheet.max_row + 1):
        if isinstance(sheet.value(r, 1), datetime):
            day = sheet.value(r, 1).date()
            # A Saturday-dated row still counts: the workbook's AVERAGE row includes it (two such rows in 2015), and the average must match.
            plan.add("eq.pe", sheet.cell(r, 2), day, weekend_ok=True)
            plan.add("eq.dividend_yield", sheet.cell(r, 4), day, weekend_ok=True)


def _prices(plan: Plan, book: Workbook) -> None:
    sheet = book.sheet(eq.UNIVERSE_SHEET)
    columns = eq._price_columns(sheet)   # one column a date; where a date repeats, the right-most
    company = sheet.find("company", rows=range(eq.HEADER_ROW, eq.HEADER_ROW + 1), cols=range(1, 6), what="'Company' header").col
    for r in range(eq.HEADER_ROW + 1, sheet.max_row + 1):
        name = sheet.value(r, company)
        if not isinstance(name, str) or not name.strip():
            break
        for day, col in columns.items():
            plan.add("eq.price", sheet.cell(r, col), day, subject=" ".join(name.split()))


def _interbank(plan: Plan, book: Workbook) -> None:
    sheet = book.sheet(fi.LIQUIDITY_SHEET)
    for r in range(4, sheet.max_row + 1):
        if isinstance(sheet.value(r, 1), datetime):
            plan.add("fi.interbank.volume", sheet.cell(r, 2), sheet.value(r, 1).date())
            plan.add("fi.interbank.rate", sheet.cell(r, 3), sheet.value(r, 1).date())


def _eurobonds(plan: Plan, book: Workbook) -> None:
    for series in fi.read_eurobonds(book):
        for day, cell in series.yields.items():
            plan.add("fi.eurobond.yield", cell, day, subject=series.key)


# (the sheet that tells which workbook this is, what is read from it)
READERS: list[tuple[str, Callable[[Plan, Workbook], None]]] = [
    (eq.TURNOVER_SHEET, lambda p, b: _daily_and_weekly(p, b, eq.TURNOVER_SHEET, "eq.turnover", 6)),
    (eq.FOREIGN_SHEET, lambda p, b: _daily_and_weekly(p, b, eq.FOREIGN_SHEET, "eq.foreign", 5)),
    (eq.VALUATION_SHEET, _valuation),
    (eq.UNIVERSE_SHEET, _prices),
    (fi.LIQUIDITY_SHEET, _interbank),
    (fi.EUROBOND_SHEET, _eurobonds),
]


def read_workbook(book: Workbook, today: Optional[date] = None) -> Plan:
    """Every history sheet the workbook has, read by sheet name and label or date.  A sheet that cannot be read is an error line; the rest go on."""
    plan = Plan(today or date.today())
    for sheet_name, read in READERS:
        if sheet_name not in book.sheet_names:
            continue
        try:
            read(plan, book)
            plan.sheets.append(sheet_name)
        except WorkbookError as exc:
            plan.errors.append(f"'{sheet_name}' not read: {exc}")
    if not plan.sheets and not plan.errors:
        plan.errors.append("none of the history sheets is in this workbook")
    return plan.finish()


def classify(db_path: Optional[Union[Path, str]], plan: Plan) -> tuple[dict[str, Counter], list[dict[str, Any]]]:
    """Per series key, how many points are new, already stored with the same number, or stored with another number (never overwritten); and the new ones."""
    counts: dict[str, Counter] = defaultdict(Counter)
    held: dict[tuple[str, str], dict[str, str]] = {}
    new = []
    for p in plan.points:
        k = (p["key"], p["subject"])
        if k not in held:
            held[k] = {c["as_of"]: c["value"] for c in store.current(db_path, k[0], k[1], confirmed_only=False)}
        was = held[k].get(p["as_of"])
        counts[p["key"]]["new" if was is None else "same" if Decimal(was) == Decimal(p["value"]) else "different"] += 1
        if was is None:
            new.append(p)
    return counts, new


def apply(db_path: Optional[Union[Path, str]], plan: Plan) -> int:
    """Add the points the store does not hold, as confirmed imports, in one transaction.  Existing points are never touched."""
    new = classify(db_path, plan)[1]
    return store.add_new(db_path, [{**p, "confirmed_by": store.IMPORT} for p in new])


def report(plan: Plan, counts: Optional[dict[str, Counter]] = None) -> list[str]:
    """The dry run's lines: counts, date ranges and reasons only, never a value."""
    lines = [f"sheets read: {', '.join(plan.sheets) or 'none'}", *plan.errors]
    for key in CATALOG:
        mine = [p for p in plan.points if p["key"] == key]
        if not mine and not plan.seen[key]:
            continue
        days = sorted(p["as_of"] for p in mine)
        line = (f"{key}: {plan.seen[key]} rows seen, {len(mine)} points" + (f" over {len({p['subject'] for p in mine})} subject(s), "
                f"{days[0]} to {days[-1]}" if mine else ""))
        if counts is not None and key in counts:
            line += ", " + ", ".join(f"{n} {what}" for what, n in sorted(counts[key].items()))
        lines.append(line)
        lines += [f"    set aside: {n} x {reason}" for (k, reason), n in sorted(plan.skipped.items()) if k == key]
    return lines
