from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional, Union

from cytonn_weekly import db
from cytonn_weekly.notable.detectors.series import UNITS as NOTABLE_UNITS

ORIGINS = ("fetched", "typed", "worked_out", "carried", "workbook_import")
SOURCE_KINDS = ("source", "form_field", "workbook_cell", "working")
CADENCES = ("day", "week", "month")
UNITS = NOTABLE_UNITS + ("kes",)   # a price in shillings: the notable library has no unit for it yet

ADDED, UNCHANGED, SUPERSEDED = "added", "unchanged", "superseded"

FORM = "analyst (form)"
IMPORT = "workbook import"

_POINT = ", ".join(f"p.{c}" for c in ("point_id", "as_of", "week_ending", "value", "origin", "source_kind", "source_ref", "confirmed_by", "confirmed_at"))


class HistoryError(ValueError):
    """A refusal.  The text names the series and the date, never a value."""


def _day(text: Any, what: str, where: str) -> str:
    try:
        return date.fromisoformat(text).isoformat()
    except (TypeError, ValueError):
        raise HistoryError(f"{where}: {what} is not an ISO date (YYYY-MM-DD)") from None


def _decimal(value: Any, where: str) -> str:
    """The value as exact decimal text.  A float, a bool or anything that is not a finite number is refused."""
    try:
        d = Decimal(value.strip() if isinstance(value, str) else value) if isinstance(value, (str, Decimal)) else None
    except InvalidOperation:
        d = None
    if d is None or not d.is_finite():
        raise HistoryError(f"{where}: the value is not a finite decimal number given as text")
    return format(d, "f")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _series_id(conn: Any, key: str, subject: str, unit: str, section: str, cadence: str, label: str) -> int:
    where = f"series {key!r} {subject!r}"
    if not key.strip() or unit not in UNITS or cadence not in CADENCES or not section.strip() or not label.strip():
        raise HistoryError(f"{where}: needs a key, a section, a label, a cadence in {list(CADENCES)} and a unit in {list(UNITS)}")
    conn.execute("INSERT INTO series (key, subject, unit, section, cadence, label, created_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                 "ON CONFLICT (key, subject) DO NOTHING", (key, subject, unit, section, cadence, label, _now()))
    row = conn.execute("SELECT series_id, unit FROM series WHERE key = ? AND subject = ?", (key, subject)).fetchone()
    if row["unit"] != unit:
        raise HistoryError(f"{where}: the series is held in {row['unit']!r}; a series' unit is fixed for good, so start a new series")
    return row["series_id"]


def _checked(key: str, subject: str, as_of: str, week_ending: str, value: Any, origin: str, source_kind: str, source_ref: str) -> tuple[str, str, str]:
    """(the date, the week ending, the value as decimal text), or a refusal."""
    where = f"series {key!r} {subject!r} on {as_of}"
    as_of, week_ending = _day(as_of, "the date", where), _day(week_ending, "the week ending", where)
    text = _decimal(value, where)
    if origin not in ORIGINS or source_kind not in SOURCE_KINDS or not str(source_ref).strip():
        raise HistoryError(f"{where}: needs an origin in {list(ORIGINS)}, a source kind in {list(SOURCE_KINDS)} and a source")
    return as_of, week_ending, text


def _record(conn: Any, *, key: str, unit: str, section: str, cadence: str, label: str, as_of: str, week_ending: str, value: Any,
            origin: str, source_kind: str, source_ref: str, subject: str = "", confirmed_by: Optional[str] = None) -> tuple[int, str]:
    as_of, week_ending, text = _checked(key, subject, as_of, week_ending, value, origin, source_kind, source_ref)
    series_id = _series_id(conn, key, subject, unit, section, cadence, label)
    old = conn.execute("SELECT point_id, value, confirmed_at FROM series_points WHERE series_id = ? AND as_of = ? AND superseded_by IS NULL",
                       (series_id, as_of)).fetchone()
    if old is not None:
        # The same number is no change, unless it is now confirmed and the old point is not: that is a new point (typed over a suggestion).
        if Decimal(old["value"]) == Decimal(text) and (old["confirmed_at"] is not None or confirmed_by is None):
            return old["point_id"], UNCHANGED
        # Free the unique "current" slot with a pointer to itself, add the new point, then point the old one at it.  One transaction.
        conn.execute("UPDATE series_points SET superseded_by = point_id WHERE point_id = ?", (old["point_id"],))
    now = _now()
    new_id = conn.insert(
        "INSERT INTO series_points (series_id, as_of, week_ending, value, origin, source_kind, source_ref, confirmed_by, confirmed_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (series_id, as_of, week_ending, text, origin, source_kind, str(source_ref), confirmed_by, now if confirmed_by else None, now), "point_id")
    if old is None:
        return new_id, ADDED
    conn.execute("UPDATE series_points SET superseded_by = ? WHERE point_id = ?", (new_id, old["point_id"]))
    return new_id, SUPERSEDED


def record_many(db_path: Optional[Union[Path, str]], items: list[dict[str, Any]]) -> list[tuple[int, str]]:
    """Add each point (the keyword arguments of ``_record``), all in one transaction: (point id, added | unchanged | superseded).

    A confirmed point is given ``confirmed_by`` (FORM or IMPORT); without it the point waits and no reader sees it.
    """
    conn = db.open_db(db_path)
    try:
        with conn.transaction():
            return [_record(conn, **item) for item in items]
    finally:
        conn.close()


_CHUNK = 500   # rows a statement: 10 values each, well inside SQLite's and PostgreSQL's limits


def add_new(db_path: Optional[Union[Path, str]], items: list[dict[str, Any]]) -> int:
    """Insert points for dates that have no current point, many to a statement (the importer's bulk path: a round trip to a remote
    database costs 200 ms, so a point at a time would take hours).  A date that already has one fails on the unique index and the
    whole batch is rolled back; nothing is superseded.  Returns how many were added."""
    conn = db.open_db(db_path)
    try:
        with conn.transaction():
            ids: dict[tuple[str, str], int] = {}
            rows: list[tuple] = []
            now = _now()
            for it in items:
                key, subject, by = it["key"], it.get("subject", ""), it.get("confirmed_by")
                as_of, week, text = _checked(key, subject, it["as_of"], it["week_ending"], it["value"], it["origin"], it["source_kind"], it["source_ref"])
                if (key, subject) not in ids:
                    ids[(key, subject)] = _series_id(conn, key, subject, it["unit"], it["section"], it["cadence"], it["label"])
                rows.append((ids[(key, subject)], as_of, week, text, it["origin"], it["source_kind"], str(it["source_ref"]), by, now if by else None, now))
            for i in range(0, len(rows), _CHUNK):
                chunk = rows[i:i + _CHUNK]
                conn.execute("INSERT INTO series_points (series_id, as_of, week_ending, value, origin, source_kind, source_ref, confirmed_by, "
                             "confirmed_at, created_at) VALUES " + ", ".join(["(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"] * len(chunk)),
                             [v for r in chunk for v in r])
        return len(rows)
    finally:
        conn.close()


def record(db_path: Optional[Union[Path, str]], **point: Any) -> tuple[int, str]:
    return record_many(db_path, [point])[0]


def confirm(db_path: Optional[Union[Path, str]], point_id: int, by: str) -> bool:
    """Confirm a point as it stands.  False when it is already confirmed, or is not a current point."""
    conn = db.open_db(db_path)
    try:
        with conn.transaction():
            cur = conn.execute("UPDATE series_points SET confirmed_by = ?, confirmed_at = ? "
                               "WHERE point_id = ? AND confirmed_at IS NULL AND superseded_by IS NULL", (by, _now(), point_id))
        return cur.rowcount > 0
    finally:
        conn.close()


def current(db_path: Optional[Union[Path, str]], key: str, subject: str = "", *, confirmed_only: bool = True,
            through: Optional[str] = None) -> list[dict[str, Any]]:
    """The series' current points, oldest first, up to ``through`` (a date) when given.  Unconfirmed points only with confirmed_only=False."""
    conn = db.open_db(db_path)
    try:
        sql = (f"SELECT {_POINT} FROM series_points p JOIN series s ON s.series_id = p.series_id "
               "WHERE s.key = ? AND s.subject = ? AND p.superseded_by IS NULL")
        params: list[Any] = [key, subject]
        if confirmed_only:
            sql += " AND p.confirmed_at IS NOT NULL"
        if through is not None:
            sql += " AND p.as_of <= ?"
            params.append(_day(through, "through", f"series {key!r} {subject!r}"))
        return [dict(r) for r in conn.execute(sql + " ORDER BY p.as_of", params)]
    finally:
        conn.close()
