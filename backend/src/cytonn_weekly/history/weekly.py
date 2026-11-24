from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional, Union

from cytonn_weekly.history import store
from cytonn_weekly.history.importer import CATALOG, friday_of
from cytonn_weekly.weekly import analyst, fi_workbook
from cytonn_weekly.weekly.week import Week

log = logging.getLogger(__name__)

# Form field -> the series it feeds.  The averages, the settings (large caps, targets, dates) and the typed text are not series.
FIELD_SERIES = {"pe": "eq.pe", "dividend_yield": "eq.dividend_yield", "turnover_ytd": "eq.turnover.ytd", "foreign_ytd": "eq.foreign.ytd",
                "placements": "fi.placements"}
TABLE_SERIES = ("mmf", "interbank", "eurobond_yields", "foreign_history", "universe", "remittances")
TYPED_BESIDE = {"origin": "typed", "source_kind": "form_field", "source_ref": "mmf, typed beside the Daily Nation snip", "confirmed_by": store.FORM}
_ISSUES = tuple(spec[0] for spec in fi_workbook.EUROBOND_ISSUES)
# "Other bond redemptions" (analyst.TABLES): each row is a point of this series, the bond its subject, on its value date.
REDEMPTION, REDEMPTIONS_TABLE = "fi.bond_redemption", "borrowing_redemptions"
MAX_REASON = 200

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
        elif key == "remittances":
            day = date(int(r["month"][:4]), int(r["month"][5:]), 1)
            end = (day.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            out += [_spec(series, "", end.isoformat(), week, r[col]) for col, series in
                    (("total", "fi.remittances.total"), ("north_america", "fi.remittances.north_america")) if r.get(col)]
        elif key == "eurobond_yields" and r.get("date"):
            out += [_spec("fi.eurobond.yield", issue, r["date"], week, r[issue]) for issue in _ISSUES if r.get(issue)]
    return out


def _how(form: dict[str, Any], key: str, value: Any) -> dict[str, Any]:
    """Where the item's value came from, and whether it counts yet: a carried or suggested weekly item waits for confirmation."""
    mark = form["carried"].get(key)
    came = (mark or {}).get("from")
    if came == analyst.SNIP and mark.get("value") == value:   # confirmed by the analyst from the image: typed, with the image as the source
        return {"origin": "typed", "source_kind": "source", "source_ref": mark["note"], "confirmed_by": store.FORM}
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
            mark = after["carried"].get(key) or {}
            if mark.get("from") == analyst.FETCHED and mark.get("value") == value:
                continue   # record_fetch wrote these, once, with the source
            how = _how(after, key, value)
            typed = set(mark.get("typed") or []) if mark.get("from") == analyst.SNIP else set()   # rows typed beside a snip
            items += [{**p, **(TYPED_BESIDE if p["subject"] in typed else how)} for p in _points(week, key, value, after)]
        rows, had = now.get(REDEMPTIONS_TABLE) or [], was.get(REDEMPTIONS_TABLE) or []
        if rows != had:
            items += [_redemption(week, r) for r in rows]
        if items:
            store.record_many(db_path, items)
        if rows != had:
            _retire_dropped(week, had, rows, db_path)
    except Exception as exc:  # noqa: BLE001 - the store must never fail a save
        _fail(items, exc)


def _retire_dropped(week: Week, had: list[dict[str, str]], rows: list[dict[str, str]], db_path: Optional[Union[Path, str]]) -> None:
    """A redemption taken off (or re-dated on) the form of the week that typed it is retired, so the old row stops counting.
    One typed in an earlier week stays: only the Retire button on the form takes it out."""
    kept = {(r["date"], bond_subject(r["bond"])) for r in rows}
    for day, bond in {(r["date"], bond_subject(r["bond"])) for r in had} - kept:
        for p in store.current(db_path, REDEMPTION, bond, since=day, through=day):
            if p["week_ending"] == week.ending.isoformat():
                store.retire(db_path, p["point_id"], REDEMPTION, f"taken off the form for the week ending {week.ending.isoformat()}")


def bond_subject(bond: str) -> str:
    """A bond's name as the store and the comparisons hold it: upper case, no spaces (``xyz1/2099/001`` is ``XYZ1/2099/001``)."""
    return "".join(str(bond).split()).upper()


def _redemption(week: Week, r: dict[str, str]) -> dict[str, Any]:
    # A row saved before source, confirmed by and confirmed on were asked for (2026-11-24) says so instead.
    return {**_spec(REDEMPTION, bond_subject(r["bond"]), r["date"], week, r["amount"]), "origin": "typed", "source_kind": "source",
            "source_ref": r.get("source") or f"{REDEMPTIONS_TABLE}, typed for the week ending {week.ending.isoformat()} (no source given)",
            "confirmed_by": r.get("confirmed_by") or store.FORM, "confirmed_at": r.get("confirmed_on")}


def stored_redemptions(start: date, end: date, db_path: Optional[Union[Path, str]] = None) -> tuple[list[dict[str, Any]], Optional[str]]:
    """The active stored bond redemptions with a value date from ``start`` to ``end``, oldest first, and the reason the store
    could not be read (then the list is empty).  Each: {point_id, date, bond, kes_m, source, confirmed_by, confirmed_on, week_ending}.

    Read whatever CYTONN_HISTORY_READS says: a redemption typed once must count in every later week, and nothing else keeps it.
    """
    # ponytail: the draft and the form status read the default database (as history/reads.py does), while a save writes to the
    # API's db_path; they are the same unless create_app is given another db_path.  Thread db_path through if that ever differs.
    try:
        points = store.current(db_path, REDEMPTION, None, since=start.isoformat(), through=end.isoformat())
    except Exception as exc:  # noqa: BLE001 - the draft goes on; the borrowing figure is flagged with the reason
        log.warning("history store: bond redemptions not read: %s", type(exc).__name__)
        return [], f"the history store could not be read ({type(exc).__name__}), so no bond redemption kept there is counted"
    return [{"point_id": p["point_id"], "date": p["as_of"], "bond": p["subject"], "kes_m": float(Decimal(p["value"])),
             "source": p["source_ref"], "confirmed_by": p["confirmed_by"], "confirmed_on": str(p["confirmed_at"])[:10],
             "week_ending": p["week_ending"]} for p in points], None


def retire_redemption(week: Week, point_id: Any, reason: Any, root: Optional[Path] = None,
                      db_path: Optional[Union[Path, str]] = None) -> dict[str, Any]:
    """Retire one stored bond redemption with the analyst's reason.  Later drafts leave it out; a saved run keeps what it printed.

    The same row typed on this week's form is taken off it too, so this week's draft leaves it out as well.  Raises
    analyst.InputError when the reason is missing or too long, or the point is not an active stored redemption.
    """
    text = " ".join(str(reason or "").split())
    if not text or len(text) > MAX_REASON:
        raise analyst.InputError(f"Give the reason for retiring the redemption, in one line of at most {MAX_REASON} characters.")
    if not isinstance(point_id, int) or isinstance(point_id, bool):
        raise analyst.InputError("No stored bond redemption was named.")
    gone = store.retire(db_path, point_id, REDEMPTION, text)
    if gone is None:
        raise analyst.InputError("That bond redemption is not kept in the history store, or was already retired.")
    rows = analyst.read_form(week, root)["tables"].get(REDEMPTIONS_TABLE) or []
    rest = [r for r in rows if (r["date"], bond_subject(r["bond"])) != (gone["as_of"], gone["subject"])]
    if len(rest) != len(rows):
        analyst.save_form(week, {"tables": {REDEMPTIONS_TABLE: {"rows": rest} if rest else None}}, root, db_path)
    return {"date": gone["as_of"], "bond": gone["subject"]}


def record_fetch(week: Week, key: str, rows: list[dict[str, Any]], note: str, db_path: Optional[Union[Path, str]] = None) -> None:
    """Write the points of a fetched table, one per series and date, never over a point already held.  Never raises."""
    items: list[dict[str, Any]] = []
    try:
        how = {"origin": "fetched", "source_kind": "source", "source_ref": note, "confirmed_by": store.FETCHED}
        items = [{**p, **how, "week_ending": friday_of(date.fromisoformat(p["as_of"])).isoformat()} for p in _points(week, key, rows, {"fields": {}})]
        if items:
            store.record_many(db_path, items, only_new=True)
    except Exception as exc:  # noqa: BLE001 - the store must never fail a fetch
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
            # Every KES security again under its KCB ticker (upper case, unlike a company key), for the price blocks of the rows export.
            items += [{**_spec("eq.price", ticker, parsed.report_date.isoformat(), week, _text(s["price"])), **how}
                      for ticker, s in parsed.securities.items() if s.get("currency") == "KES" and s.get("price") is not None]
        elif slug == "cbk_bulletin":
            items = [{**_spec("fi.kesonia", "", r["date"].isoformat(), week, _text(r["kesonia"])), **how} for r in parsed.interbank if r.get("kesonia") is not None]
        if items:
            store.record_many(db_path, items, only_new=True)
    except Exception as exc:  # noqa: BLE001 - the store must never fail an upload
        _fail(items, exc)
