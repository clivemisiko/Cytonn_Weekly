"""Stage P3, the held PostgreSQL connection in cytonn_weekly/db.py, with no server: psycopg.connect is a recorder.

What is pinned here: one connection is reused; one caller at a time; an idle connection is tested before use; a read that
loses the connection is retried once and a write never; a call that fails always gives the lock back; and on SQLite each
call still opens and closes its own.  The URL and password are invented.
"""

import threading
import time

import psycopg
import pytest
from psycopg import errors as pg_errors

from cytonn_weekly import db as database
from cytonn_weekly import sections
from cytonn_weekly.digital_payments import review_store
from cytonn_weekly.notable import store as notable_store
from cytonn_weekly.report_sections import latest_runs
from tests.review_helpers import make_review
from tests.test_db_postgres import FakeConn, URL, made  # noqa: F401 - `made` is the fixture


class Conn(FakeConn):
    """A recorded connection that can be told to fail, and that reads like a cursor."""

    fail = None            # called with the SQL; returns an exception to raise, or None
    row_count = 1

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        error = self.fail(sql) if self.fail else None
        if error:
            raise error
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)

    rowcount = 1


@pytest.fixture
def conns(monkeypatch):
    """Like ``made`` but the connections are Conn, and ``fail_next`` makes the next connection's non-SET statements fail."""
    opened = []

    def connect(url, **kwargs):
        opened.append(Conn(url, kwargs, rows=[{"run_id": 1, "section": "x", "run_date": "", "decision": None, "decided_at": None}]))
        return opened[-1]

    monkeypatch.setattr(psycopg, "connect", connect)
    monkeypatch.setenv(database.DATABASE_URL_ENV, URL)
    monkeypatch.setattr(database, "_schema_applied", set())
    return opened


def statements(conn):
    return [s for s, _ in conn.statements]


def lost(sql):
    return None if sql.startswith("SET") else psycopg.OperationalError("server closed the connection unexpectedly")


# --- reuse ---------------------------------------------------------------------------------------------------------------

def test_calls_reuse_one_connection_and_a_close_gives_it_back_without_closing_it(conns):
    for _ in range(5):
        c = database.open_db()
        assert not conns[0].closed
        c.close()
    assert len(conns) == 1 and not conns[0].closed


def test_a_screens_worth_of_store_calls_opens_one_connection_on_postgres(conns):
    for _ in range(4):
        latest_runs()                                                     # the overview's reads
    assert len(conns) == 1


def test_closing_twice_gives_the_lock_back_once_and_does_not_raise(conns):
    c = database.connect()
    c.close()
    c.close()
    assert can_lock_from_another_thread()


def test_sqlite_still_opens_and_closes_its_own_connection_each_call(tmp_path, conns):
    first = database.open_db(tmp_path / "a.db")
    first.close()
    with pytest.raises(Exception):
        first.execute("SELECT 1")                                         # closed: SQLite is not held
    assert conns == []


def test_close_all_closes_the_held_connection_and_the_next_call_opens_a_new_one(conns):
    database.connect().close()
    database.close_all()
    assert conns[0].closed
    database.connect().close()
    assert len(conns) == 2


def test_a_new_url_or_schema_replaces_the_held_connection(conns, monkeypatch):
    database.connect().close()
    monkeypatch.setenv(database.DATABASE_SCHEMA_ENV, "another")
    database.connect().close()
    assert len(conns) == 2 and conns[0].closed


def test_the_app_closes_the_held_connection_at_shutdown():
    from api.main import create_app

    assert database.close_all in create_app(load_dotenv=False).router.on_shutdown


# --- one caller at a time ------------------------------------------------------------------------------------------------

def can_lock_from_another_thread() -> bool:
    got = []
    t = threading.Thread(target=lambda: got.append(database._held_lock.acquire(blocking=False)) or (got[0] and database._held_lock.release()))
    t.start()
    t.join()
    return got == [True]


def test_a_second_thread_waits_until_the_first_has_given_the_connection_back(conns):
    entered, release, order = threading.Event(), threading.Event(), []

    def first():
        c = database.connect()
        order.append("first has it")
        entered.set()
        release.wait(5)
        order.append("first gives it back")
        c.close()

    def second():
        entered.wait(5)
        c = database.connect()
        order.append("second has it")
        c.close()

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for t in threads:
        t.start()
    entered.wait(5)
    time.sleep(0.2)
    assert order == ["first has it"]                                      # the second is still waiting
    release.set()
    for t in threads:
        t.join(5)
    assert order == ["first has it", "first gives it back", "second has it"] and len(conns) == 1


def test_a_call_that_waits_longer_than_the_limit_is_unreachable_and_logs_a_fixed_word(conns, monkeypatch, caplog):
    monkeypatch.setattr(database, "LOCK_TIMEOUT_SECONDS", 0.2)
    held = threading.Event(), threading.Event()

    def holder():
        c = database.connect()
        held[0].set()
        held[1].wait(5)
        c.close()

    t = threading.Thread(target=holder)
    t.start()
    held[0].wait(5)
    with caplog.at_level("DEBUG"), pytest.raises(database.DatabaseNotAvailable) as err:
        database.connect()
    held[1].set()
    t.join(5)
    assert str(err.value) == database.UNREACHABLE and database.is_connection_error(err.value)
    assert "lock wait" in caplog.text and "example" not in caplog.text
    assert can_lock_from_another_thread()


# --- the idle check ------------------------------------------------------------------------------------------------------

def test_a_connection_idle_over_30_seconds_is_tested_with_select_1_and_a_busy_one_is_not(conns, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(database.time, "monotonic", lambda: now[0])
    database.connect().close()
    now[0] += 29
    database.connect().close()
    assert "SELECT 1" not in statements(conns[0])
    now[0] += 31
    database.connect().close()
    assert statements(conns[0]).count("SELECT 1") == 1 and len(conns) == 1


def test_a_connection_that_does_not_answer_the_idle_check_is_replaced(conns, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(database.time, "monotonic", lambda: now[0])
    database.connect().close()
    conns[0].fail = lambda sql: psycopg.OperationalError("gone") if sql == "SELECT 1" else None
    now[0] += 31
    database.connect().close()
    assert len(conns) == 2 and conns[0].closed and not conns[1].closed


def test_a_connection_the_driver_says_is_broken_is_replaced_without_asking_it(conns):
    database.connect().close()
    conns[0].broken = True
    database.connect().close()
    assert len(conns) == 2 and "SELECT 1" not in statements(conns[0])


# --- retry: reads once, writes never -------------------------------------------------------------------------------------

def test_a_read_that_loses_the_connection_is_run_again_once_on_a_new_connection(conns):
    c = database.connect()
    conns[0].fail = lost
    cur = c.execute("SELECT 1 FROM t WHERE a = ?", (1,))
    c.close()
    assert len(conns) == 2 and conns[0].closed and cur is conns[1]
    assert statements(conns[1])[-1] == "SELECT 1 FROM t WHERE a = %s"


def test_a_read_that_loses_the_connection_twice_fails_and_is_not_tried_a_third_time(conns):
    c = database.connect()
    conns[0].fail = lost
    Conn.fail = staticmethod(lost)                                        # every later connection fails too
    try:
        with pytest.raises(psycopg.OperationalError):
            c.execute("SELECT 1")
    finally:
        Conn.fail = None
        c.close()
    assert len(conns) == 2


def test_a_write_that_loses_the_connection_is_never_run_again(conns):
    c = database.connect()
    conns[0].fail = lost
    for sql in ("INSERT INTO t (a) VALUES (?)", "UPDATE t SET a = ?", "DELETE FROM t WHERE a = ?"):
        with pytest.raises(psycopg.OperationalError):
            c.execute(sql, (1,))
    c.close()
    assert len(conns) == 1 and conns[0].closed                            # dropped, so the next call opens a new one
    assert [s for s in statements(conns[0]) if s.startswith(("INSERT", "UPDATE", "DELETE"))] == [
        "INSERT INTO t (a) VALUES (%s)", "UPDATE t SET a = %s", "DELETE FROM t WHERE a = %s"]   # each tried once
    database.connect().close()
    assert len(conns) == 2


def test_a_read_inside_a_transaction_is_never_run_again(conns):
    c = database.connect()
    conns[0].fail = lost
    with pytest.raises(psycopg.OperationalError):
        with c.transaction():
            c.execute("SELECT 1")
    c.close()
    assert len(conns) == 1 and statements(conns[0]).count("SELECT 1") == 1


def test_a_saved_review_whose_connection_drops_is_not_saved_twice(conns):
    review_store.save_review(make_review())                               # applies the schema, saves
    conns[0].fail = lambda sql: psycopg.OperationalError("gone") if sql.startswith("INSERT") else None
    with pytest.raises(psycopg.OperationalError):
        review_store.save_review(make_review())
    assert sum(s.startswith("INSERT INTO coordinator_reviews") for s in statements(conns[0])) == 2   # one earlier save, one try
    assert len(conns) == 1


def test_a_refused_request_is_not_retried_and_keeps_the_connection(conns):
    c = database.connect()
    conns[0].fail = lambda sql: pg_errors.DeadlockDetected("x") if sql.startswith("SELECT") else None
    with pytest.raises(pg_errors.DeadlockDetected):
        c.execute("SELECT 1")
    c.close()
    assert len(conns) == 1 and not conns[0].closed


# --- the lock is always given back ---------------------------------------------------------------------------------------

CALLS = {
    "save_review": lambda: review_store.save_review(make_review()),
    "load_review": lambda: review_store.load_review(1),
    "load_latest_review": lambda: review_store.load_latest_review(),
    "load_previous_review": lambda: review_store.load_previous_review(1),
    "notable load": lambda: notable_store.load(None, "2026-10-02", "fixed_income"),
    "notable save": lambda: notable_store.save(None, "2026-10-02", "fixed_income", "abc", "selected", None, None),
    "notable delete": lambda: notable_store.delete(None, "2026-10-02", "fixed_income", "abc"),
    "latest_runs": lambda: latest_runs(),
    "get_section_config": lambda: sections.get_section_config("Digital Payments"),
    "update_section_config": lambda: sections.update_section_config("Digital Payments", in_active_build=1),
}


@pytest.mark.parametrize("error", [psycopg.OperationalError("gone"), pg_errors.UniqueViolation("dup"), RuntimeError("boom")],
                         ids=["connection lost", "refused", "not the driver's"])
@pytest.mark.parametrize("name", list(CALLS))
def test_after_a_store_function_raises_the_lock_can_be_taken_without_waiting(conns, name, error):
    database.open_db().close()                                            # the schema is applied; the connection is held
    conns[0].fail = lambda sql: error
    try:
        CALLS[name]()                                                     # a read that lost the connection is retried and may succeed
    except Exception:  # noqa: BLE001
        pass
    assert can_lock_from_another_thread()


def test_a_connection_that_cannot_be_opened_does_not_keep_the_lock(conns, monkeypatch):
    def refuse(url, **kwargs):
        raise psycopg.OperationalError("refused")

    monkeypatch.setattr(psycopg, "connect", refuse)
    with pytest.raises(database.DatabaseNotAvailable):
        database.connect()
    assert can_lock_from_another_thread()


def test_a_schema_that_fails_gives_the_lock_back_and_drops_the_connection(conns):
    conns_before = len(conns)
    Conn.fail = staticmethod(lambda sql: RuntimeError("no") if "advisory" in sql else None)
    try:
        with pytest.raises(RuntimeError):
            database.open_db()
    finally:
        Conn.fail = None
    assert can_lock_from_another_thread() and conns[conns_before].closed
