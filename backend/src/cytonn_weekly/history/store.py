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
FETCHED = "published source"

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


def _checked(key: str, subject: str, as_of: str, week_ending: str, value: Any, origin: str, source_kind: str, source_ref: str) -> tuple[str, str, str]:
    """(the date, the week ending, the value as decimal text), or a refusal."""
    where = f"series {key!r} {subject!r} on {as_of}"
    as_of, week_ending = _day(as_of, "the date", where), _day(week_ending, "the week ending", where)
    text = _decimal(value, where)
    if origin not in ORIGINS or source_kind not in SOURCE_KINDS or not str(source_ref).strip():
        raise HistoryError(f"{where}: needs an origin in {list(ORIGINS)}, a source kind in {list(SOURCE_KINDS)} and a source")
    return as_of, week_ending, text


def _ids(conn: Any, specs: dict[tuple[str, str], tuple[str, str, str, str]]) -> dict[tuple[str, str], int]:
    """The series_id of each (key, subject), creating what is missing.  specs: (key, subject) -> (unit, section, cadence, label)."""
    for (key, subject), (unit, section, cadence, label) in specs.items():
        if not key.strip() or unit not in UNITS or cadence not in CADENCES or not section.strip() or not label.strip():
            raise HistoryError(f"series {key!r} {subject!r}: needs a key, a section, a label, a cadence in {list(CADENCES)} and a unit in {list(UNITS)}")
    keys = sorted({k for k, _ in specs})
    have = {(r["key"], r["subject"]): r for r in conn.execute(
        f"SELECT series_id, key, subject, unit FROM series WHERE key IN ({', '.join('?' * len(keys))})", keys)}
    out = {}
    for (key, subject), (unit, section, cadence, label) in specs.items():
        row = have.get((key, subject))
        if row is None:
            conn.execute("INSERT INTO series (key, subject, unit, section, cadence, label, created_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                         "ON CONFLICT (key, subject) DO NOTHING", (key, subject, unit, section, cadence, label, _now()))
            row = conn.execute("SELECT series_id, unit FROM series WHERE key = ? AND subject = ?", (key, subject)).fetchone()
        if row["unit"] != unit:
            raise HistoryError(f"series {key!r} {subject!r}: the series is held in {row['unit']!r}; a series' unit is fixed for good, so start a new series")
        out[(key, subject)] = row["series_id"]
    return out


def _prepare(conn: Any, items: list[dict[str, Any]]) -> list[tuple[int, str, str, str, dict[str, Any]]]:
    """Check each item and resolve its series: (series_id, date, week ending, value text, the item)."""
    checked, specs = [], {}
    for it in items:
        subject = it.get("subject", "")
        as_of, week, text = _checked(it["key"], subject, it["as_of"], it["week_ending"], it["value"], it["origin"], it["source_kind"], it["source_ref"])
        spec = (it["unit"], it["section"], it["cadence"], it["label"])
        if specs.setdefault((it["key"], subject), spec)[0] != spec[0]:
            raise HistoryError(f"series {it['key']!r} {subject!r}: given two different units")
        checked.append((it["key"], subject, as_of, week, text, it))
    ids = _ids(conn, specs)
    return [(ids[(key, subject)], as_of, week, text, it) for key, subject, as_of, week, text, it in checked]


_CHUNK = 500   # points a statement (10 values each) and items a lookup: well inside SQLite's and PostgreSQL's limits


def _insert(conn: Any, rows: list[tuple]) -> dict[tuple[int, str], int]:
    """Insert points, many to a statement (a round trip to a remote database costs 200 ms): {(series_id, date): point_id}."""
    got = {}
    for i in range(0, len(rows), _CHUNK):
        chunk = rows[i:i + _CHUNK]
        cur = conn.execute("INSERT INTO series_points (series_id, as_of, week_ending, value, origin, source_kind, source_ref, confirmed_by, "
                           "confirmed_at, created_at) VALUES " + ", ".join(["(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"] * len(chunk))
                           + " RETURNING point_id, series_id, as_of", [v for r in chunk for v in r])
        got.update({(r["series_id"], r["as_of"]): r["point_id"] for r in cur.fetchall()})
    return got


def _row(sid: int, as_of: str, week: str, text: str, it: dict[str, Any], now: str) -> tuple:
    by = it.get("confirmed_by")
    return (sid, as_of, week, text, it["origin"], it["source_kind"], str(it["source_ref"]), by, now if by else None, now)


def _record_chunk(conn: Any, items: list[dict[str, Any]], only_new: bool = False) -> list[tuple[int, str]]:
    prepared = _prepare(conn, items)
    last = {(sid, as_of): n for n, (sid, as_of, *_rest) in enumerate(prepared)}   # the last item for a series and date wins
    sids, days = sorted({k[0] for k in last}), sorted({k[1] for k in last})
    current = {(r["series_id"], r["as_of"]): r for r in conn.execute(
        "SELECT point_id, series_id, as_of, value, confirmed_at FROM series_points WHERE superseded_by IS NULL "
        f"AND series_id IN ({', '.join('?' * len(sids))}) AND as_of IN ({', '.join('?' * len(days))})", sids + days)}
    now, results, fresh = _now(), [None] * len(items), []
    for (sid, as_of), n in last.items():
        _, _, week, text, it = prepared[n]
        old = current.get((sid, as_of))
        # The same number is no change, unless it is now confirmed and the old point is not: that is a new point (typed over a suggestion).
        if old is not None and (only_new or (Decimal(old["value"]) == Decimal(text) and (old["confirmed_at"] is not None or it.get("confirmed_by") is None))):
            results[n] = (old["point_id"], UNCHANGED)
        elif old is None:
            fresh.append((n, _row(sid, as_of, week, text, it, now)))
        else:
            # Free the unique "current" slot with a pointer to itself, add the new point, then point the old one at it.  One transaction.
            conn.execute("UPDATE series_points SET superseded_by = point_id WHERE point_id = ?", (old["point_id"],))
            new_id = _insert(conn, [_row(sid, as_of, week, text, it, now)])[(sid, as_of)]
            conn.execute("UPDATE series_points SET superseded_by = ? WHERE point_id = ?", (new_id, old["point_id"]))
            results[n] = (new_id, SUPERSEDED)
    added = _insert(conn, [row for _, row in fresh])
    for n, row in fresh:
        results[n] = (added[(row[0], row[1])], ADDED)
    return [results[last[(prepared[n][0], prepared[n][1])]] if r is None else r for n, r in enumerate(results)]


def record_many(db_path: Optional[Union[Path, str]], items: list[dict[str, Any]], only_new: bool = False) -> list[tuple[int, str]]:
    """Add each point (``key``, ``unit``, ``section``, ``cadence``, ``label``, ``as_of``, ``week_ending``, ``value``, ``origin``, ``source_kind``,
    ``source_ref``, optional ``subject`` and ``confirmed_by``), all in one transaction and a handful of statements:
    (point id, added | unchanged | superseded).  A confirmed point is given ``confirmed_by`` (FORM or IMPORT); without it the point waits and
    no reader sees it.  Twice the same series and date in one call: the last wins.  ``only_new``: a date that already has a current point is
    left as it is (a fetched figure never replaces what an analyst typed or confirmed)."""
    conn = db.open_db(db_path)
    try:
        with conn.transaction():
            out: list[tuple[int, str]] = []
            for i in range(0, len(items), _CHUNK):
                out += _record_chunk(conn, items[i:i + _CHUNK], only_new)
            return out
    finally:
        conn.close()


def add_new(db_path: Optional[Union[Path, str]], items: list[dict[str, Any]]) -> int:
    """Insert points for dates that have no current point (the importer's bulk path).  A date that already has one fails on the unique
    index and the whole batch is rolled back; nothing is superseded.  Returns how many were added."""
    conn = db.open_db(db_path)
    try:
        with conn.transaction():
            now = _now()
            _insert(conn, [_row(sid, as_of, week, text, it, now) for sid, as_of, week, text, it in _prepare(conn, items)])
        return len(items)
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


def current(db_path: Optional[Union[Path, str]], key: str, subject: Optional[str] = "", *, confirmed_only: bool = True,
            through: Optional[str] = None, since: Optional[str] = None) -> list[dict[str, Any]]:
    """The series' current points, oldest first, from ``since`` to ``through`` (dates) when given.  Unconfirmed points only with
    confirmed_only=False.  ``subject=None`` takes every subject of the key (each point then carries its ``subject``)."""
    where = f"series {key!r} {subject!r}"
    conn = db.open_db(db_path)
    try:
        sql = (f"SELECT s.subject, {_POINT} FROM series_points p JOIN series s ON s.series_id = p.series_id "
               "WHERE s.key = ? AND p.superseded_by IS NULL")
        params: list[Any] = [key]
        if subject is not None:
            sql += " AND s.subject = ?"
            params.append(subject)
        if confirmed_only:
            sql += " AND p.confirmed_at IS NOT NULL"
        for bound, op in ((since, ">="), (through, "<=")):
            if bound is not None:
                sql += f" AND p.as_of {op} ?"
                params.append(_day(bound, "the date bound", where))
        return [dict(r) for r in conn.execute(sql + " ORDER BY p.as_of, s.subject", params)]
    finally:
        conn.close()
