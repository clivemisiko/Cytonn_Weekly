from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional, Union

from cytonn_weekly.history import store
from cytonn_weekly.history.importer import CATALOG
from cytonn_weekly.weekly import analyst, fi_workbook
from cytonn_weekly.weekly.week import Week

log = logging.getLogger(__name__)

# Form field -> the series it feeds.  The averages, the settings (large caps, targets, dates) and the typed text are not series.
FIELD_SERIES = {"pe": "eq.pe", "dividend_yield": "eq.dividend_yield", "turnover_ytd": "eq.turnover.ytd", "foreign_ytd": "eq.foreign.ytd",
                "placements": "fi.placements"}
TABLE_SERIES = ("mmf", "interbank", "eurobond_yields", "foreign_history", "universe")
_ISSUES = tuple(spec[0] for spec in fi_workbook.EUROBOND_ISSUES)

_failed = 0


def failed_writes() -> int:
    """How many store writes have failed in this process.  The form file was saved each time."""
    return _failed


def _fail(items: list[dict[str, Any]], exc: Exception) -> None:
    global _failed
    _failed += 1
    named = ", ".join(sorted({f"{i['key']} {i['as_of']}" for i in items})[:6]) or "no point built"
    # The class only, never the driver's message: a PostgreSQL error can quote the row that failed.  A HistoryError is ours and holds no value.
    log.warning("history store: %d point(s) not written (%s); the saved form or upload is unaffected: %s%s", len(items), named,
                type(exc).__name__, f": {exc}" if isinstance(exc, store.HistoryError) else "")


def _spec(key: str, subject: str, day: str, week: Week, value: Any, week_ending: Optional[str] = None) -> dict[str, Any]:
    unit, cadence, section, label, _ = CATALOG[key]
    return {"key": key, "subject": subject, "unit": unit, "section": section, "cadence": cadence, "label": label, "as_of": day,
            "week_ending": week_ending or week.ending.isoformat(), "value": value}


def _points(week: Week, key: str, value: Any, form: dict[str, Any]) -> list[dict[str, Any]]:
    """The points one form item holds: the form's own text, a percentage as typed."""
    this = week.as_at.isoformat()
    if key in FIELD_SERIES:
        return [_spec(FIELD_SERIES[key], "", this, week, value)]
    out = []
    for r in value:
        if key == "mmf":
            out.append(_spec("fi.mmf.rate", analyst.fund_key(r["fund"]), form["fields"].get("mmf_published") or this, week, r["rate"]))
        elif key == "interbank":
            out.append(_spec("fi.interbank.rate", "", r["date"], week, r["rate"]))
        elif key == "foreign_history":
            out.append(_spec("eq.foreign.week", "", r["week_ending"], week, r["net"], r["week_ending"]))
        elif key == "universe":
            if r.get("price"):   # last Friday's price is last week's point, already stored
                out.append(_spec("eq.price", analyst._key(r["company"]), this, week, r["price"]))
        elif key == "eurobond_yields" and r.get("date"):
            out += [_spec("fi.eurobond.yield", issue, r["date"], week, r[issue]) for issue in _ISSUES if r.get(issue)]
    return out


def _how(form: dict[str, Any], key: str, value: Any) -> dict[str, Any]:
    """Where the item's value came from, and whether it counts yet: a carried or suggested weekly item waits for confirmation."""
    mark = form["carried"].get(key)
    came = (mark or {}).get("from")
    if key in form["unconfirmed"]:
        if came == analyst.SUGGESTED:
            return {"origin": "worked_out", "source_kind": "working", "source_ref": mark.get("note") or key}
        return {"origin": "carried", "source_kind": "form_field", "source_ref": f"{key}, carried from the week ending {came}"}
    if mark and mark.get("value") == value:   # confirmed as it stands (a suggestion), or a slow-changing item used as carried
        if came == analyst.SUGGESTED:
            return {"origin": "worked_out", "source_kind": "working", "source_ref": mark.get("note") or key, "confirmed_by": store.FORM}
        return {"origin": "carried", "source_kind": "form_field", "source_ref": f"{key}, carried from the week ending {came}", "confirmed_by": store.FORM}
    return {"origin": "typed", "source_kind": "form_field", "source_ref": key, "confirmed_by": store.FORM}


def sync(week: Week, before: dict[str, Any], after: dict[str, Any], db_path: Optional[Union[Path, str]] = None) -> None:
    """Write the points of every item the save changed (its value, or whether it still waits to be confirmed) to the store.

    Called by weekly/analyst.py after the form file is written, outside its lock.  It never raises: the file is the truth and the
    store is written beside it, so a failure is a warning (series and date, no value) and a count, and the save has still succeeded.
    """
    items: list[dict[str, Any]] = []
    try:
        was, now = {**before["fields"], **before["tables"]}, {**after["fields"], **after["tables"]}
        for key in (*FIELD_SERIES, *TABLE_SERIES):
            value = now.get(key)
            if value is None or (value == was.get(key) and (key in after["unconfirmed"]) == (key in before["unconfirmed"])):
                continue
            how = _how(after, key, value)
            items += [{**p, **how} for p in _points(week, key, value, after)]
        if items:
            store.record_many(db_path, items)
    except Exception as exc:  # noqa: BLE001 - the store must never fail a save
        _fail(items, exc)


def _text(number: float) -> str:
    return format(Decimal(repr(number)).normalize(), "f")


def record_upload(week: Week, slug: str, parsed: Any, entry: dict[str, Any], db_path: Optional[Union[Path, str]] = None) -> None:
    """Write the published figures of a stored KCB weekly report or CBK bulletin: one point per series and date, with the file's name and hash.

    Called by weekly/inputs.store with what the upload was read as.  A report for another week is not written.  Never raises.
    """
    items: list[dict[str, Any]] = []
    try:
        if not entry.get("matches"):
            return
        how = {"origin": "fetched", "source_kind": "source", "source_ref": f"{entry['stored_name']} sha256 {entry['sha256']}", "confirmed_by": store.FETCHED}
        if slug == "kcb_weekly":
            items = [{**_spec("eq.price", company, parsed.report_date.isoformat(), week, _text(price)), **how}
                     for company, ticker in analyst.COVERAGE_TICKERS.items() if (price := (parsed.securities.get(ticker) or {}).get("price")) is not None]
        elif slug == "cbk_bulletin":
            items = [{**_spec("fi.kesonia", "", r["date"].isoformat(), week, _text(r["kesonia"])), **how} for r in parsed.interbank if r.get("kesonia") is not None]
        if items:
            store.record_many(db_path, items, only_new=True)
    except Exception as exc:  # noqa: BLE001 - the store must never fail an upload
        _fail(items, exc)
