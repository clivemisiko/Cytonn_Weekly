"""Section configuration and permission flags.

One row per report section (Equities, Fixed Income, Digital Payments,
Real Estate, Focus).  All access settings are section-based — analysts
rotate weekly so ownership lives here, not in a user table.

Typical usage
-------------
    from cytonn_weekly.sections import get_section_config

    cfg = get_section_config("Digital Payments")
    if cfg["in_active_build"]:
        ...
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from cytonn_weekly.paths import DATA_DIR

# Resolved at import time (cytonn_weekly/paths.py).  The schema is code, so it sits beside
# this file and not in the data folder, which a Docker volume replaces.
_DEFAULT_DB = DATA_DIR / "app.db"
_SCHEMA_SQL = Path(__file__).parent / "schema.sql"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _connect(db_path: Optional[Path | str] = None) -> sqlite3.Connection:
    path = str(db_path) if db_path is not None else str(_DEFAULT_DB)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_db(db_path: Optional[Path | str] = None) -> None:
    """Create the sections table and seed it if not already present.

    Safe to call on every startup — uses CREATE TABLE IF NOT EXISTS and
    INSERT OR IGNORE, so repeated calls are idempotent.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.  Defaults to ``data/app.db``
        relative to backend/.  Pass ``":memory:"`` in tests.
    """
    schema = _SCHEMA_SQL.read_text(encoding="utf-8")
    conn = _connect(db_path)
    try:
        conn.executescript(schema)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


# Columns coordinator_reviews gained after its first release, in the order they were added,
# each with the exact ADD COLUMN clause.  SQLite's ADD COLUMN fills existing rows with the
# default, so every review saved before report types existed reads back as a weekly review
# with no period: exactly what it was.
_ADDED_REVIEW_COLUMNS = (
    ("report_type", "report_type TEXT NOT NULL DEFAULT 'weekly' "
                    "CHECK (report_type IN ('weekly', 'quarterly', 'half_year', 'annual', 'companion'))"),
    ("period", "period TEXT NOT NULL DEFAULT ''"),
)


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring an existing database up to schema.sql.  Idempotent; changes no existing value.

    CREATE TABLE IF NOT EXISTS leaves a table from an older schema as it was, so columns
    added since are added here, then the index that needs them.
    """
    have = {r["name"] for r in conn.execute("PRAGMA table_info(coordinator_reviews)")}
    for name, clause in _ADDED_REVIEW_COLUMNS:
        if name not in have:
            conn.execute(f"ALTER TABLE coordinator_reviews ADD COLUMN {clause}")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coordinator_reviews_report "
        "ON coordinator_reviews (report_type, period, section, run_id)"
    )


def get_section_config(
    name: str,
    db_path: Optional[Path | str] = None,
) -> dict:
    """Return the config dict for *name*, or raise ``KeyError`` if not found.

    Parameters
    ----------
    name:
        Section name exactly as stored: one of "Equities", "Fixed Income",
        "Digital Payments", "Real Estate", "Focus".
    db_path:
        Path to the SQLite database.  Defaults to ``data/app.db``.

    Returns
    -------
    dict with keys:
        ``name``, ``current_analyst``, ``focus_topic_source``,
        ``in_active_build``.

    Raises
    ------
    KeyError
        If *name* is not a known section.
    """
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT name, current_analyst, focus_topic_source, in_active_build "
            "FROM sections WHERE name = ?",
            (name,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise KeyError(f"Unknown section: {name!r}")

    return dict(row)


def update_section_config(
    name: str,
    *,
    current_analyst: Optional[str] = ...,  # type: ignore[assignment]
    focus_topic_source: Optional[str] = ...,  # type: ignore[assignment]
    in_active_build: Optional[int] = ...,  # type: ignore[assignment]
    db_path: Optional[Path | str] = None,
) -> None:
    """Update one or more fields for *name*.

    Only keyword arguments explicitly passed (not left as the default
    sentinel ``...``) are written; omitted fields are unchanged.

    Parameters
    ----------
    name:
        Section name to update.
    current_analyst:
        Who owns this section this week (``None`` to clear).
    focus_topic_source:
        ``"analyst"`` or ``"tool"`` (Focus section only; ``None`` to clear).
    in_active_build:
        ``1`` to mark as active pilot, ``0`` to deactivate.
    db_path:
        Path to the SQLite database.

    Raises
    ------
    KeyError
        If *name* is not a known section.
    ValueError
        If no fields are specified to update.
    """
    _SENTINEL = ...  # same object used as default above

    updates: dict[str, object] = {}
    if current_analyst is not _SENTINEL:
        updates["current_analyst"] = current_analyst
    if focus_topic_source is not _SENTINEL:
        updates["focus_topic_source"] = focus_topic_source
    if in_active_build is not _SENTINEL:
        updates["in_active_build"] = in_active_build

    if not updates:
        raise ValueError("No fields specified to update.")

    set_clause = ", ".join(f"{col} = ?" for col in updates)
    values = list(updates.values()) + [name]

    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            f"UPDATE sections SET {set_clause} WHERE name = ?",
            values,
        )
        conn.commit()
    finally:
        conn.close()

    if cursor.rowcount == 0:
        raise KeyError(f"Unknown section: {name!r}")
