from __future__ import annotations

import logging
import os
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional, Union

from cytonn_weekly.common.formatting import round_half_up
from cytonn_weekly.history import store
from cytonn_weekly.history.importer import CATALOG
from cytonn_weekly.weekly import analyst, equities_workbook
from cytonn_weekly.weekly.week import Week

log = logging.getLogger(__name__)

MODE_ENV = "CYTONN_HISTORY_READS"
OFF, COMPARE, ON = "off", "compare", "on"

# The first day of the equities workbook's AVERAGE range for the market P/E (read from the formulas of the 2 Oct, 30 Oct and
# 13 Nov 2026 workbooks: row 8, the current week, down to the row dated 12 Dec 2008; the earlier 2008 rows are outside it).
PE_AVERAGE_FROM = date(2008, 12, 12)

_LOGGED = 20   # lines one comparison writes to the log; every difference is counted
counts: Counter = Counter()   # compared, differences, failed_reads: for this process, read by the status tool later
_warned_mode = False


def mode() -> str:
    global _warned_mode
    value = os.environ.get(MODE_ENV, "").strip().lower()
    if value in ("", OFF):
        return OFF
    if value in (COMPARE, ON):
        return value
    if not _warned_mode:
        _warned_mode = True
        log.warning("%s is not off, compare or on; the form is read, as with off", MODE_ENV)
    return OFF


def _same(a: Optional[float], b: Optional[float], places: int = 8) -> bool:
    """Equal once both are cut to the store's own precision (8 places, half up: how a workbook float is stored), so float noise never counts."""
    return a is not None and b is not None and round_half_up(Decimal(repr(a)), places) == round_half_up(Decimal(repr(b)), places)


def resolve(series: str, form_value: Any, read: Callable[[], Any], differ: Callable[[Any, Any], list[str]]) -> Any:
    """off: the form's figure, the store untouched.  compare: the form's figure, and each difference with the store is logged (series and
    date, never a value) and counted.  on: the store's figure, and the form's only when the store has no point.  A store that cannot be
    read is a warning and a count in both modes, and the form's figure is used."""
    m = mode()
    if m == OFF:
        return form_value
    try:
        found = read()
        lines = differ(form_value, found) if m == COMPARE else []
    except Exception as exc:  # noqa: BLE001 - the store never fails a draft
        counts["failed_reads"] += 1
        log.warning("history store: %s could not be read (%s); the form's figure is used", series, type(exc).__name__)
        return form_value
    if m == COMPARE:
        counts["compared"] += 1
        counts["differences"] += len(lines)
        for line in lines[:_LOGGED]:
            log.warning("history compare: %s", line)
        if len(lines) > _LOGGED:
            log.warning("history compare: %s: %d more differences, all counted", series, len(lines) - _LOGGED)
        return form_value
    return found if found is not None else form_value


def scalar_diff(series: str, day: str) -> Callable[[Any, Any], list[str]]:
    def differ(form: Any, found: Any) -> list[str]:
        if form is None and found is None:
            return []
        if found is None:
            return [f"{series} {day}: the store has no point"]
        if form is None:
            return [f"{series} {day}: the form side has no figure"]
        return [] if _same(form.number, found.number) else [f"{series} {day}: the form and the store differ"]

    return differ


def _number(key: str, point: dict[str, Any]) -> float:
    """The point as the builders hold it: a percentage as a fraction, as the form's own cells are."""
    d = Decimal(point["value"])
    return float(d / 100 if CATALOG[key][0] == "pct" else d)


def _cell(key: str, point: dict[str, Any]) -> Any:
    """A point as a cell a builder can read.  A point from a workbook import is a Reading (the workbook's history is complete); a point
    typed on the form is a Typed, so a builder that is careful with typed weekly sums stays careful."""
    label = f"{CATALOG[key][3].split(',')[0]}, {point['subject']}" if point["subject"] else CATALOG[key][3]
    number = _number(key, point)
    if point["origin"] == "workbook_import":
        return analyst.Reading(number, f"history store, {label}, {point['as_of']} (from the team's workbook, imported)")
    return analyst.Typed(number, f"{label}, {point['as_of']}", "the history store")


def _dates(week: Week) -> list[str]:
    return [d.isoformat() for d in week.report_dates]


def _last_on(points: list[dict[str, Any]], days: list[str]) -> Optional[dict[str, Any]]:
    return next((p for p in reversed(points) if p["as_of"] in days), None)


# -- the running totals' "before" ---------------------------------------------------------------------------------------------

def running_before(week: Week, key: str, form_value: Any, db_path: Optional[Union[Path, str]] = None) -> Any:
    """Last week's confirmed year-to-date total (``eq.turnover.ytd`` or ``eq.foreign.ytd``) for the figure's suggestion."""
    prev = week.previous

    def read() -> Any:
        found = _last_on(store.current(db_path, key, since=prev.monday.isoformat(), through=prev.ending.isoformat()), _dates(prev))
        return None if found is None else _cell(key, found)

    return resolve(key, form_value, read, scalar_diff(key, prev.as_at.isoformat()))


# -- foreign: the weekly sums, and the total the year before ---------------------------------------------------------------------

def foreign_history(week: Week, form_value: list, db_path: Optional[Union[Path, str]] = None) -> list:
    """The weekly net positions before this week, oldest first: (the Friday, USD mn, its cell)."""
    def read() -> Optional[list]:
        points = store.current(db_path, "eq.foreign.week", through=(week.monday - timedelta(days=1)).isoformat())
        return [(date.fromisoformat(p["as_of"]), _number("eq.foreign.week", p), _cell("eq.foreign.week", p)) for p in points] or None

    def differ(form: list, found: Optional[list]) -> list[str]:
        if found is None:
            return ["eq.foreign.week: the store holds no weekly sums"] if form else []
        theirs = {d: n for d, n, _ in found}
        return [f"eq.foreign.week {d.isoformat()}: " + ("the store has no point" if d not in theirs else "the form and the store differ")
                for d, n, _ in form if not _same(n, theirs.get(d))]

    return resolve("eq.foreign.week", form_value, read, differ)


def foreign_prior_year(week: Week, form_value: Any, db_path: Optional[Union[Path, str]] = None) -> Any:
    """The running total the year before closed on: the workbook's own rule (equities_workbook.prior_year_total) on the stored weeks."""
    year = week.as_at.year

    def read() -> Any:
        since = date(year - 1, 12, 1).isoformat()
        sums = {p["as_of"]: p for p in store.current(db_path, "eq.foreign.week", since=since, through=week.ending.isoformat())}
        rows = []
        for p in store.current(db_path, "eq.foreign.ytd", since=since, through=week.ending.isoformat()):
            if p["as_of"] in sums:
                rows.append((date.fromisoformat(p["as_of"]), _number("eq.foreign.week", sums[p["as_of"]]), _number("eq.foreign.ytd", p),
                             _cell("eq.foreign.ytd", p)))
        return equities_workbook.prior_year_total(SimpleNamespace(history=rows), year)

    return resolve("eq.foreign.ytd", form_value, read, scalar_diff("eq.foreign.ytd", f"the total for {year - 1}"))


# -- prices ----------------------------------------------------------------------------------------------------------------------

def last_prices(week: Week, db_path: Optional[Union[Path, str]] = None) -> dict[str, Any]:
    """Last Friday's price of every company the store has one for: {company key: cell}."""
    prev = week.previous
    days = _dates(prev)
    out: dict[str, dict[str, Any]] = {}
    for p in store.current(db_path, "eq.price", None, since=prev.monday.isoformat(), through=prev.ending.isoformat()):
        if p["as_of"] in days:
            out[p["subject"]] = p   # oldest first: the latest date wins
    return {name: _cell("eq.price", p) for name, p in out.items()}


def last_price(week: Week, company: Any, form_value: Any, loaded: Callable[[], dict[str, Any]]) -> Any:
    """One company's price a week ago.  ``loaded`` gives last_prices(week), read once for all the companies."""
    name = analyst._key(company)
    day = week.previous.as_at.isoformat()
    # A price an analyst typed by hand for last Friday stays: nothing writes last Friday's price to the store from a form.
    if analyst.is_typed(form_value) and mode() == ON:
        return form_value
    return resolve(f"eq.price {name}", form_value, lambda: loaded().get(name), scalar_diff(f"eq.price {name}", day))


# -- the market P/E's historical average --------------------------------------------------------------------------------------------

def pe_average(week: Week, form_value: Any, db_path: Optional[Union[Path, str]] = None) -> Any:
    """The mean of every stored P/E point from PE_AVERAGE_FROM to this week's: the workbook's AVERAGE range.  Only when this week's
    point is there, because the range ends on it; the dividend yield's average stays typed."""
    def read() -> Any:
        points = store.current(db_path, "eq.pe", since=PE_AVERAGE_FROM.isoformat(), through=week.ending.isoformat())
        if not points or points[-1]["as_of"] not in _dates(week):
            return None
        mean = sum(Decimal(p["value"]) for p in points) / len(points)
        return analyst.Reading(float(mean), f"history store, the average of the {len(points)} weekly market P/E points from "
                                            f"{points[0]['as_of']} to {points[-1]['as_of']}")

    return resolve("eq.pe average", form_value, read, scalar_diff("eq.pe average", week.as_at.isoformat()))


# -- the fund table, a week ago ----------------------------------------------------------------------------------------------------

def previous_fund_table(week: Week, form_value: Optional[dict[str, Any]], db_path: Optional[Union[Path, str]] = None) -> Optional[dict[str, Any]]:
    """The previous week's fund table: the points of the latest day that week's table was published on, best rate first."""
    prev = week.previous

    def read() -> Optional[dict[str, Any]]:
        points = store.current(db_path, "fi.mmf.rate", None, since=prev.monday.isoformat(), through=prev.ending.isoformat())
        if not points:
            return None
        day = points[-1]["as_of"]
        funds = sorted((p for p in points if p["as_of"] == day), key=lambda p: -Decimal(p["value"]))
        return {"published": date.fromisoformat(day), "title": f"Money Market Fund Yield as published on {day}",
                "funds": [{"rank": analyst.Reading(n, f"history store, rank by rate on {day}"), "fund": analyst.Reading(p["subject"], "history store"),
                           "rate": _cell("fi.mmf.rate", p)} for n, p in enumerate(funds, 1)],
                "origin": "history store, the money market fund table"}

    def differ(form: Optional[dict[str, Any]], found: Optional[dict[str, Any]]) -> list[str]:
        if found is None:
            return [f"fi.mmf.rate {prev.as_at.isoformat()}: the store holds no fund table"] if form else []
        theirs = {analyst.fund_key(f["fund"].value): f["rate"].number for f in (found or {"funds": []})["funds"]}
        return [f"fi.mmf.rate {analyst.fund_key(f['fund'].value)} {prev.as_at.isoformat()}: "
                + ("the store has no point" if analyst.fund_key(f["fund"].value) not in theirs else "the form and the store differ")
                for f in (form or {"funds": []})["funds"] if not _same(f["rate"].number, theirs.get(analyst.fund_key(f["fund"].value)))]

    return resolve("fi.mmf.rate", form_value, read, differ)
