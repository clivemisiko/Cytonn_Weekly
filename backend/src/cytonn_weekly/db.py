"""The one place a database is opened.

Every runtime SQL call goes through here (sections.py, digital_payments/review_store.py, notable/store.py and
report_sections.py); no other file imports sqlite3 or psycopg or opens a connection.  This module owns the connection,
rows by column name, the transaction, the schema run, the placeholder style and the id of an inserted row.

Which database: an explicit ``db_path`` is a SQLite file (tests, scripts and ``create_app(db_path=...)``).  With no
``db_path`` and CYTONN_DATABASE_URL set, it is PostgreSQL (Supabase); psycopg is imported lazily, when that connection
is made, never when this module is imported.  With neither, ``data/app.db``.

PostgreSQL: SSL is always required (``_postgres_url``).  The tables live in their own schema, CYTONN_DATABASE_SCHEMA
(default ``cytonn``), never in ``public``, which Supabase exposes through its web API.  The schema is chosen with a SET
statement as the first thing a new connection does, not a startup option in the URL, because the Supabase pooler may
refuse options (so use the pooler's session mode, port 5432: a SET does not outlive a transaction in transaction mode).
On PostgreSQL one connection is kept for the process and lent to one caller at a time (``_held``, behind ``_held_lock``):
opening one costs about 1.5 s against Supabase and a round trip about 0.2 s.  ``Db.close()`` gives it back; it does not
close it.  SQLite is unchanged: each call opens and closes its own.  Nothing the driver says is ever passed on: its messages can name the host and the user.

SQL is written once, with ``?`` placeholders, and only in forms SQLite (3.39 or newer) and PostgreSQL both accept:
RETURNING for an inserted row's id, IS NOT DISTINCT FROM for a comparison that may be NULL, ON CONFLICT for an upsert.
Each database has its own schema file (schema.sql, schema_postgres.sql); the migration below is SQLite's.
"""

from __future__ import annotations

import atexit
import logging
import os
import re
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from cytonn_weekly.paths import DATA_DIR

log = logging.getLogger(__name__)

DATABASE_URL_ENV = "CYTONN_DATABASE_URL"
DATABASE_SCHEMA_ENV = "CYTONN_DATABASE_SCHEMA"
DEFAULT_SCHEMA = "cytonn"
MIN_SQLITE = (3, 39, 0)  # IS NOT DISTINCT FROM; RETURNING needs 3.35 and ON CONFLICT 3.24

# What a coordinator is told when PostgreSQL cannot be used, whatever the driver said.
UNREACHABLE = "Could not reach the database. Check CYTONN_DATABASE_URL and the network."
# What a coordinator is told when the server was reached and refused the request; no detail, the driver's words can name the host.
REJECTED = "The database rejected the request. See the server log."
# SQLSTATEs that mean the connection, not the request: class 08 (connection exception), 57P01 to 57P03 (shutdown, crash,
# cannot connect now) and 53300 (too many connections).  Any other state on an OperationalError (deadlock, cancelled, disk full) is a rejection.
_CONNECTION_SQLSTATES = ("57P01", "57P02", "57P03", "53300")

# Resolved at import time (cytonn_weekly/paths.py).  The schemas are code, so they sit beside this file and not in the
# data folder, which a Docker volume replaces.
_DEFAULT_DB = DATA_DIR / "app.db"
_SCHEMA_SQL = Path(__file__).parent / "schema.sql"
_POSTGRES_SCHEMA_SQL = Path(__file__).parent / "schema_postgres.sql"

IDLE_CHECK_SECONDS = 30    # a held connection idle longer than this is tested with SELECT 1 before it is used again
LOCK_TIMEOUT_SECONDS = 60  # how long a call waits for the held connection before it gives up as unreachable
STATEMENT_TIMEOUT = "30s"  # set on every new connection: a statement stuck on a dead socket ends instead of freezing the app
KEEPALIVES = {"keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3}  # libpq: a dead peer is noticed in about a minute
CONNECT_TIMEOUT_SECONDS = 10  # else an unreachable host holds a request for the operating system's own limit
_SSL_MODES = ("require", "verify-ca", "verify-full")  # sslmode values that encrypt; anything weaker is refused
_SCHEMA_NAME = re.compile(r"[a-z_][a-z0-9_]{0,62}")
_RESERVED_SCHEMAS = ("public", "information_schema")
_SCHEMA_LOCK = 7_368_301  # an arbitrary advisory-lock number: two processes starting together do not both create the tables
_CONNECT_CAUSES = (  # (the word logged, phrases the driver or the system uses for it)
    ("authentication", ("authentication failed", "no pg_hba", "tenant or user not found")),
    ("name lookup", ("translate host name", "name or service not known", "getaddrinfo", "gaierror", "network access in a test",
                     "no such host", "temporary failure in name resolution")),
    ("timeout", ("timeout expired", "timed out")),
    ("refused", ("connection refused", "actively refused")),
    ("ssl", ("ssl", "tls", "certificate")),
)
_PLACEHOLDER = re.compile(r"""('[^']*'|"[^"]*")|\?""")  # a quoted string or identifier, else a ?

Row = sqlite3.Row  # a row read by column name: row["run_id"], dict(row), row.keys() (a plain dict on PostgreSQL)


class DatabaseNotAvailable(RuntimeError):
    """The PostgreSQL database cannot be used.  Its message is fixed text or names a setting, never the URL or the driver's words."""


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


def is_postgres_error(exc: BaseException) -> bool:
    """True for any error psycopg raised.  Never imports the driver: if it was never loaded, nothing it raised can exist."""
    psycopg = sys.modules.get("psycopg")
    return psycopg is not None and isinstance(exc, psycopg.Error)


def is_connection_error(exc: BaseException) -> bool:
    """True when the database could not be reached or the connection was lost, False for a request the server refused.

    Never imports the driver.  psycopg's OperationalError with no SQLSTATE is a client-side failure (connect, timeout,
    closed socket) and counts; with one, only the connection states above count.  InterfaceError (a closed connection)
    and DatabaseNotAvailable count.  This is the one place that knows driver classes: another driver means one new mapping here.
    """
    if isinstance(exc, DatabaseNotAvailable):
        return True
    psycopg = sys.modules.get("psycopg")
    if psycopg is None or not isinstance(exc, psycopg.Error):
        return False
    if isinstance(exc, psycopg.InterfaceError):
        return True
    if isinstance(exc, psycopg.OperationalError):
        state = getattr(exc, "sqlstate", None)
        return state is None or state.startswith("08") or state in _CONNECTION_SQLSTATES
    return False


def _postgres_sql(sql: str) -> str:
    """The SQL as psycopg wants it: ``?`` becomes ``%s`` (not inside a quoted string) and a literal ``%`` becomes ``%%``.

    ponytail: a ``?`` in a ``--`` comment is converted too; none of this app's SQL has one.
    """
    return _PLACEHOLDER.sub(lambda m: m.group(0) if m.group(1) else "%s", sql.replace("%", "%%"))


class Db:
    """One open connection.  Callers write SQL with ``?`` and never see the driver.  ``schema`` is the PostgreSQL schema, None for SQLite.

    On PostgreSQL the connection is the process's held one, and this object holds ``_held_lock`` until ``close()``.
    """

    def __init__(self, conn, schema: Optional[str] = None, held: bool = False, url: str = "") -> None:
        self._conn = conn
        self.schema = schema
        self._held, self._url = held, url
        self._depth = 0  # transaction blocks open on this object: a statement inside one is never replayed

    def _run(self, sql: str, params=()):
        # The only place SQL text reaches the driver.  SQLite takes ``?`` as written; psycopg takes ``%s``.
        if self.schema is None:
            return self._conn.execute(sql, params)
        text = _postgres_sql(sql)
        try:
            return self._conn.execute(text, params)
        except Exception as exc:
            if not is_connection_error(exc):
                raise
            _drop_held(self._conn)  # the connection is gone: the next call opens a new one
            if self._depth or sql.lstrip()[:6].upper() != "SELECT":
                raise  # a write, or a read inside a transaction, is never replayed: it may have been applied
            log.warning("lost the PostgreSQL connection during a read (%s); reconnecting once", type(exc).__name__)
            self._conn = _held_connection(self._url, self.schema)
            return self._conn.execute(text, params)

    def execute(self, sql: str, params=()):
        """Run one statement; the cursor gives fetchone(), fetchall(), iteration and rowcount."""
        return self._run(sql, params)

    def insert(self, sql: str, params, id_column: str) -> int:
        """Run an INSERT and return the new row's ``id_column``, read back with RETURNING."""
        rows = self._run(f"{sql} RETURNING {id_column}", params).fetchall()  # every row read, so the statement is done before the transaction ends
        return rows[0][id_column]

    @contextmanager
    def transaction(self) -> Iterator["Db"]:
        """Commit when the block ends, roll back if it raises; the connection stays open.  (A PostgreSQL connection is in
        autocommit mode, so a statement outside a block commits by itself and a block is a real BEGIN to COMMIT.)"""
        if self.schema is None:
            with self._conn:
                yield self
            return
        self._depth += 1
        try:
            with self._conn.transaction():
                yield self
        except Exception as exc:
            if is_connection_error(exc):
                _drop_held(self._conn)
            raise
        finally:
            self._depth -= 1

    def run_script(self, script: str) -> None:
        """Run a script of statements with no parameters (a schema)."""
        if self.schema is None:
            self._conn.executescript(script)
        else:
            self._conn.execute(script)  # with no parameters the server takes several statements in one call

    def close(self) -> None:
        """SQLite: close the connection.  PostgreSQL: give the held connection back (it stays open).  A second call does nothing."""
        if not self._held:
            self._conn.close()
        elif self._conn is not None:
            self._conn = None
            if _held is not None:
                _held["used"] = time.monotonic()
            _held_lock.release()

    def discard(self) -> None:
        """Close the connection for good, even the held one: a schema run failed part-way and its state is unknown."""
        if self._held and self._conn is not None:
            _drop_held(self._conn)
        self.close()


def schema_name() -> str:
    """The PostgreSQL schema the tables live in: CYTONN_DATABASE_SCHEMA, else ``cytonn``; refused unless it is a plain name."""
    name = os.environ.get(DATABASE_SCHEMA_ENV, "").strip() or DEFAULT_SCHEMA
    if not _SCHEMA_NAME.fullmatch(name) or name in _RESERVED_SCHEMAS or name.startswith("pg_"):
        raise DatabaseNotAvailable(
            f"{DATABASE_SCHEMA_ENV} must be lower-case letters, digits and underscores (at most 63, not starting "
            "with a digit or pg_) and not public or information_schema, which Supabase exposes through its web API."
        )
    return name


def _postgres_url(url: str) -> str:
    """The URL with SSL required: as written when it asks for require or stronger, ``sslmode=require`` added when it says
    nothing, refused when it asks for less.  Everything else, the user and the password included, is left as written."""
    try:
        parts = urlsplit(url)
        query = parse_qsl(parts.query, keep_blank_values=True)
    except ValueError:
        parts = None
    if parts is None or parts.scheme not in ("postgresql", "postgres") or not parts.hostname:
        raise DatabaseNotAvailable(
            f"{DATABASE_URL_ENV} is not a valid postgresql:// URL (a password with special characters must be percent-encoded)."
        )
    if parts.netloc.count("@") > 1:  # libpq ends the user info at the first @, Python at the last: the rest would be sent on as a host name
        raise DatabaseNotAvailable(
            f"{DATABASE_URL_ENV} has more than one @ before the host. Percent-encode the password: an @ in it is %40 and an & is %26."
        )
    modes = [v for k, v in query if k == "sslmode"]
    if any(m not in _SSL_MODES for m in modes):
        raise DatabaseNotAvailable(
            f"{DATABASE_URL_ENV} sets an sslmode weaker than require; use require, verify-ca or verify-full, or leave it out."
        )
    if modes:
        return url
    return urlunsplit(parts._replace(query=f"{parts.query}&sslmode=require" if parts.query else "sslmode=require"))


def _why(exc: BaseException) -> str:
    """Which of a few causes a failed connection looks like, as one of these fixed words.  The log gets the word and never
    the driver's text (which names the host and the user); a SQLSTATE is rarely present on a failed connect."""
    text = str(exc).lower()
    for word, clues in _CONNECT_CAUSES:
        if any(c in text for c in clues):
            return word
    return "other"


_held_lock = threading.RLock()  # who is using the held connection; reentrant, so a store call made inside another shares it
_held: Optional[dict] = None    # {"key": (url, schema), "conn": the open connection, "used": when it was last given back}
_exit_hook_set = False


def _open_postgres(url: str, schema: str):
    """A new connection with its settings applied.  Every failure is one fixed sentence; the driver's words are never passed on."""
    import psycopg  # here and not at the top: a SQLite-only run never loads the driver
    from psycopg.rows import dict_row

    url = _postgres_url(url)
    failed = None
    try:
        conn = psycopg.connect(url, row_factory=dict_row, autocommit=True, connect_timeout=CONNECT_TIMEOUT_SECONDS, **KEEPALIVES)
        try:
            conn.execute(f'SET search_path TO "{schema}"')  # statements, not startup options: the pooler may refuse options
            conn.execute(f"SET statement_timeout = '{STATEMENT_TIMEOUT}'")
        except BaseException:
            conn.close()
            raise
    except Exception as exc:  # noqa: BLE001 - whatever the driver says can name the host and user: keep a fixed tag, its class and SQLSTATE only
        failed = (_why(exc), type(exc).__name__, getattr(exc, "sqlstate", None))
    if failed:  # raised out here, not inside the except, so the driver's error is not attached to ours
        log.warning("could not open the PostgreSQL connection: %s (%s, SQLSTATE %s)", *failed)
        raise DatabaseNotAvailable(UNREACHABLE)
    return conn


def _drop_held(conn) -> None:
    """Close the held connection if ``conn`` is it.  Called with ``_held_lock`` held."""
    global _held
    if _held is not None and _held["conn"] is conn:
        _held = None
        try:
            conn.close()
        except Exception:  # noqa: BLE001 - it is being thrown away
            pass


def _alive(conn) -> bool:
    try:
        conn.execute("SELECT 1")
        return True
    except Exception:  # noqa: BLE001 - any failure means it cannot be used
        return False


def _held_connection(url: str, schema: str):
    """The process's connection: the held one if it is open and (after a long idle) answers, else a new one.  Needs ``_held_lock``."""
    global _held, _exit_hook_set
    key = (url, schema)
    if _held is not None and _held["key"] != key:
        _drop_held(_held["conn"])  # another database was asked for (tests, a changed setting)
    if _held is not None:
        conn = _held["conn"]
        idle = time.monotonic() - _held["used"] > IDLE_CHECK_SECONDS
        if getattr(conn, "closed", False) or getattr(conn, "broken", False) or (idle and not _alive(conn)):
            _drop_held(conn)
    if _held is None:
        _held = {"key": key, "conn": _open_postgres(url, schema), "used": time.monotonic()}
        if not _exit_hook_set:
            _exit_hook_set = True
            atexit.register(close_all)
    return _held["conn"]


def _connect_postgres(url: str) -> Db:
    # ponytail: one connection per process, one caller at a time (all database work is serialised); a pool
    # (psycopg_pool) is the upgrade if more than one coordinator ever works at once.
    schema = schema_name()
    _postgres_url(url)  # refused here, before the lock, if it is not usable
    if not _held_lock.acquire(timeout=LOCK_TIMEOUT_SECONDS):
        log.warning("could not open the PostgreSQL connection: lock wait (the held connection was busy for %s s)", LOCK_TIMEOUT_SECONDS)
        raise DatabaseNotAvailable(UNREACHABLE)
    try:
        return Db(_held_connection(url, schema), schema, held=True, url=url)
    except BaseException:
        _held_lock.release()
        raise


def close_all() -> None:
    """Close the held PostgreSQL connection, if any (at exit, at shutdown, between tests).  Waits up to 5 s for a caller using it."""
    if _held_lock.acquire(timeout=5):
        try:
            if _held is not None:
                _drop_held(_held["conn"])
        finally:
            _held_lock.release()


def connect(db_path: Optional[Path | str] = None) -> Db:
    """Open the database, without touching its schema."""
    url = os.environ.get(DATABASE_URL_ENV, "").strip()
    if db_path is None and url:
        return _connect_postgres(url)
    check_sqlite_version()
    conn = sqlite3.connect(str(db_path) if db_path is not None else str(_DEFAULT_DB))
    conn.row_factory = sqlite3.Row
    return Db(conn)


_schema_applied: set[int] = set()  # a hash of (URL, schema) per database this process has set up; not the URL itself
_schema_lock = threading.Lock()


def _apply_postgres_schema(conn: Db) -> None:
    """Create the schema, its tables and the five section rows, once per process and database.

    Every store call opens the database, and the script's ALTER TABLE ... ENABLE ROW LEVEL SECURITY takes a lock on each
    table, so running it each time would queue every request behind it.  All or nothing: DDL is transactional here.
    ponytail: a schema dropped under a running process is not recreated until restart.
    """
    key = hash((os.environ.get(DATABASE_URL_ENV), conn.schema))
    with _schema_lock:
        if key in _schema_applied:
            return
        with conn.transaction():
            conn.execute(f"SELECT pg_advisory_xact_lock({_SCHEMA_LOCK})")
            conn.run_script(_POSTGRES_SCHEMA_SQL.read_text(encoding="utf-8").replace("{schema}", f'"{conn.schema}"'))
        _schema_applied.add(key)


def open_db(db_path: Optional[Path | str] = None) -> Db:
    """Open the database with its schema applied.  Idempotent: safe on a database that already has it."""
    conn = connect(db_path)
    try:
        if conn.schema is not None:
            _apply_postgres_schema(conn)
        else:
            conn.run_script(_SCHEMA_SQL.read_text(encoding="utf-8"))
            with conn.transaction():
                _migrate(conn)
    except BaseException:
        conn.discard()
        raise
    return conn


def init_db(db_path: Optional[Path | str] = None) -> None:
    """Create the tables and seed the sections if not already present.  Safe to call on every startup.

    ``db_path`` is the SQLite file; None means CYTONN_DATABASE_URL's PostgreSQL if set, else ``data/app.db`` relative to backend/.
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
