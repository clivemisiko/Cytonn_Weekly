"""The one place a database is opened.

Every runtime SQL call goes through here (sections.py, digital_payments/review_store.py, notable/store.py and
report_sections.py); no other file imports sqlite3 or opens a connection.  This module owns the connection, rows by
column name, the transaction, the schema run, the placeholder style and the id of an inserted row.

Which database: an explicit ``db_path`` is a SQLite file (tests, scripts and ``create_app(db_path=...)``).  With no
``db_path`` and CYTONN_DATABASE_URL set, PostgreSQL is selected and, until Stage P2, refused with DatabaseNotAvailable;
psycopg is imported lazily, when P2 connects, never when this module is imported.  With neither, ``data/app.db``.

SQL is written once, with ``?`` placeholders, and only in forms SQLite (3.39 or newer) and PostgreSQL both accept:
RETURNING for an inserted row's id, IS NOT DISTINCT FROM for a comparison that may be NULL, ON CONFLICT for an upsert.
The schema (schema.sql) and the migration below are SQLite's; PostgreSQL gets its own schema in P2.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from cytonn_weekly.paths import DATA_DIR

DATABASE_URL_ENV = "CYTONN_DATABASE_URL"
MIN_SQLITE = (3, 39, 0)  # IS NOT DISTINCT FROM; RETURNING needs 3.35 and ON CONFLICT 3.24

# Resolved at import time (cytonn_weekly/paths.py).  The schema is code, so it sits beside this file and not in the
# data folder, which a Docker volume replaces.
_DEFAULT_DB = DATA_DIR / "app.db"
_SCHEMA_SQL = Path(__file__).parent / "schema.sql"

Row = sqlite3.Row  # a row read by column name: row["run_id"], dict(row), row.keys()


class DatabaseNotAvailable(RuntimeError):
    """CYTONN_DATABASE_URL selects PostgreSQL, which cannot be used yet."""


class SQLiteTooOld(RuntimeError):
    """The SQLite library behind Python is older than the SQL here needs."""


def check_sqlite_version(found: Optional[tuple] = None) -> None:
    """Raise SQLiteTooOld, saying what to do, unless SQLite is 3.39 or newer.  (``found`` is for the test.)"""
    found = tuple(found or sqlite3.sqlite_version_info)
    if found < MIN_SQLITE:
        have = ".".join(str(n) for n in found)
        need = ".".join(str(n) for n in MIN_SQLITE[:2])
        raise SQLiteTooOld(
            f"SQLite {have} is too old: this app needs SQLite {need} or newer (RETURNING and IS NOT DISTINCT FROM). "
            "Use a Python build with a newer SQLite, or the Docker image."
        )


check_sqlite_version()  # at import, so the app and every script refuse to start on a SQLite too old for the SQL


class Db:
    """One open connection.  Callers write SQL with ``?`` and never see the driver."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def _run(self, sql: str, params=()) -> sqlite3.Cursor:
        # The only place SQL text reaches the driver.  SQLite takes ``?`` as written; P2 turns it into ``%s`` here.
        return self._conn.execute(sql, params)

    def execute(self, sql: str, params=()) -> sqlite3.Cursor:
        """Run one statement; the cursor gives fetchone(), fetchall(), iteration and rowcount."""
        return self._run(sql, params)

    def insert(self, sql: str, params, id_column: str) -> int:
        """Run an INSERT and return the new row's ``id_column``, read back with RETURNING."""
        rows = self._run(f"{sql} RETURNING {id_column}", params).fetchall()  # every row read, so the statement is done before the transaction ends
        return rows[0][0]

    @contextmanager
    def transaction(self) -> Iterator["Db"]:
        """Commit when the block ends, roll back if it raises; the connection stays open."""
        with self._conn:
            yield self

    def run_script(self, script: str) -> None:
        """Run a script of statements (the SQLite schema)."""
        self._conn.executescript(script)

    def close(self) -> None:
        self._conn.close()


def connect(db_path: Optional[Path | str] = None) -> Db:
    """Open the database, without touching its schema."""
    if db_path is None and os.environ.get(DATABASE_URL_ENV, "").strip():
        # The URL is not echoed: it may hold a password.
        raise DatabaseNotAvailable(
            f"{DATABASE_URL_ENV} is set, which selects PostgreSQL, but PostgreSQL is not available until Stage P2. "
            f"Unset {DATABASE_URL_ENV} to use the SQLite file, or pass an explicit db_path."
        )
    check_sqlite_version()
    conn = sqlite3.connect(str(db_path) if db_path is not None else str(_DEFAULT_DB))
    conn.row_factory = sqlite3.Row
    return Db(conn)


def open_db(db_path: Optional[Path | str] = None) -> Db:
    """Open the database with its schema applied.  Idempotent: safe on a database that already has it."""
    conn = connect(db_path)
    try:
        conn.run_script(_SCHEMA_SQL.read_text(encoding="utf-8"))
        with conn.transaction():
            _migrate(conn)
    except BaseException:
        conn.close()
        raise
    return conn


def init_db(db_path: Optional[Path | str] = None) -> None:
    """Create the tables and seed the sections if not already present.  Safe to call on every startup.

    ``db_path`` is the SQLite file; None means ``data/app.db`` relative to backend/.
    """
    open_db(db_path).close()


# Columns coordinator_reviews gained after its first release, in the order they were added,
# each with the exact ADD COLUMN clause.  SQLite's ADD COLUMN fills existing rows with the
# default, so every review saved before report types existed reads back as a weekly review
# with no period: exactly what it was.
_ADDED_REVIEW_COLUMNS = (
    ("report_type", "report_type TEXT NOT NULL DEFAULT 'weekly' "
                    "CHECK (report_type IN ('weekly', 'quarterly', 'half_year', 'annual', 'companion'))"),
    ("period", "period TEXT NOT NULL DEFAULT ''"),
)


def _migrate(conn: Db) -> None:
    """Bring an existing SQLite database up to schema.sql.  Idempotent; changes no existing value.

    SQLite only (PRAGMA, ADD COLUMN on a table that already holds rows); a PostgreSQL database is created whole.
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
