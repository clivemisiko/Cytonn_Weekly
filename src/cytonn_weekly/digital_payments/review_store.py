"""SQLite persistence for CoordinatorReview (table ``coordinator_reviews``).

Same pattern as sections.py: the schema lives in data/schema.sql and is applied
by sections.init_db(), the database defaults to data/app.db, and every call takes
an optional ``db_path`` (tests pass a temp file).  The draft content and the
review items are stored as JSON blobs; section, run date and decision are real,
indexed columns for lookup.

A review is inserted the first time it is saved (which gives it a ``run_id``) and
updated in place on every save after that, so the screen can save on each
resolution change.  Once a decision is recorded the row is frozen: a later save
from a stale copy that disagrees raises ReviewAlreadyDecided instead of silently
reopening an approved review.

Typical usage
-------------
    run_id = save_review(review)                 # insert, sets review.run_id
    save_review(review)                          # update, e.g. after a resolution
    review = load_latest_review(run_date=date.today())
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional, Union

from cytonn_weekly import sections
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview, ReviewItem

SECTION = "digital_payments"


class ReviewAlreadyDecided(Exception):
    """A save would change a review that already has a different recorded decision."""


def _open(db_path: Optional[Union[Path, str]]) -> sqlite3.Connection:
    sections.init_db(db_path)  # idempotent: creates the table on first use
    return sections._connect(db_path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _iso_date(d: Union[date, str, None]) -> str:
    if d is None:
        return date.today().isoformat()
    return date.fromisoformat(d).isoformat() if isinstance(d, str) else d.isoformat()


def save_review(
    review: CoordinatorReview,
    run_date: Union[date, str, None] = None,
    *,
    section: str = SECTION,
    db_path: Optional[Union[Path, str]] = None,
) -> int:
    """Insert the review, or update it in place if it was saved before; return its run_id.

    ``run_date`` (default today) and ``section`` apply on the first save only; the
    draft content is never rewritten.  An update rewrites the items, the decision
    and ``updated_at``.  Raises ReviewAlreadyDecided if the stored row has a
    decision this review does not match, and LookupError if ``review.run_id``
    points at no row.
    """
    items = json.dumps([i.to_dict() for i in review.review_items])
    now = _now()
    conn = _open(db_path)
    try:
        with conn:
            if review.run_id is None:
                cur = conn.execute(
                    "INSERT INTO coordinator_reviews (section, run_date, created_at, updated_at, "
                    "decision, decided_at, content_json, items_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (section, _iso_date(run_date), now, now, review.decision, review.decided_at,
                     json.dumps(review.section), items),
                )
                review.run_id = cur.lastrowid
            else:
                cur = conn.execute(
                    "UPDATE coordinator_reviews SET items_json = ?, decision = ?, decided_at = ?, updated_at = ? "
                    "WHERE run_id = ? AND (decision IS NULL OR (decision IS ? AND decided_at IS ?))",
                    (items, review.decision, review.decided_at, now,
                     review.run_id, review.decision, review.decided_at),
                )
                if cur.rowcount == 0:
                    row = conn.execute(
                        "SELECT decision FROM coordinator_reviews WHERE run_id = ?", (review.run_id,)
                    ).fetchone()
                    if row is None:
                        raise LookupError(f"no saved review with run_id {review.run_id}")
                    raise ReviewAlreadyDecided(
                        f"run {review.run_id} was already {row['decision']}; it cannot be changed"
                    )
    finally:
        conn.close()
    return review.run_id


def _row_to_review(row: sqlite3.Row) -> CoordinatorReview:
    return CoordinatorReview(
        section=json.loads(row["content_json"]),
        review_items=[ReviewItem.from_dict(d) for d in json.loads(row["items_json"])],
        decision=row["decision"],
        decided_at=row["decided_at"],
        run_id=row["run_id"],
    )


def load_review(run_id: int, *, db_path: Optional[Union[Path, str]] = None) -> CoordinatorReview:
    """The saved review with this run_id; KeyError if there is none."""
    conn = _open(db_path)
    try:
        row = conn.execute("SELECT * FROM coordinator_reviews WHERE run_id = ?", (run_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise KeyError(f"no saved review with run_id {run_id}")
    return _row_to_review(row)


def load_latest_review(
    section: str = SECTION,
    *,
    run_date: Union[date, str, None] = None,
    db_path: Optional[Union[Path, str]] = None,
) -> Optional[CoordinatorReview]:
    """The most recently saved review for ``section`` (optionally only of ``run_date``), or None.

    Decided or not: the caller checks ``.decision``.  Tasks that need the
    approved values read it from here.
    """
    sql, params = "SELECT * FROM coordinator_reviews WHERE section = ?", [section]
    if run_date is not None:
        sql += " AND run_date = ?"
        params.append(_iso_date(run_date))
    conn = _open(db_path)
    try:
        row = conn.execute(sql + " ORDER BY run_id DESC LIMIT 1", params).fetchone()
    finally:
        conn.close()
    return _row_to_review(row) if row else None
