"""Stage P2, the PostgreSQL path in cytonn_weekly/db.py, with no server: psycopg.connect is replaced by a recorder.

What runs against a real server is test_postgres_smoke.py.  Here: the placeholder conversion, the SSL requirement, the
search_path statement, the schema file (row level security, the identity column), and that no URL or password reaches an
error message, a log line, a run event or a response.  The URL below is invented; its password is a fake.
"""

import contextlib
import json
import re
import traceback

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import errors as pg_errors
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from api.main import create_app, failure_message
from cytonn_weekly import db as database
from cytonn_weekly.common import run_events as ev
from cytonn_weekly.digital_payments import review_run, review_store
from cytonn_weekly.paths import BACKEND_ROOT
from tests.test_runs_api import WEEKLY_DP, finished, start

USER, PW, HOST = "postgres.fakeprojectref", "Zx9-fake-pass-word", "db.fake-host.example"
URL = f"postgresql://{USER}:{PW}@{HOST}:5432/postgres"
SCHEMA_FILE = BACKEND_ROOT / "src" / "cytonn_weekly" / "schema_postgres.sql"


class FakeConn:
    """What psycopg.connect returns here: records every statement and every transaction block."""

    def __init__(self, url, kwargs, rows=()):
        self.url, self.kwargs, self.rows = url, kwargs, list(rows)
        self.statements, self.transactions, self.closed = [], [], False

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        return self

    def fetchall(self):
        return self.rows

    @contextlib.contextmanager
    def transaction(self):
        self.transactions.append("begin")
        try:
            yield
        except BaseException:
            self.transactions.append("rollback")
            raise
        self.transactions.append("commit")

    def close(self):
        self.closed = True


@pytest.fixture
def made(monkeypatch):
    """Every connection the code under test opened, newest last; the URL and the schema memory are the test's own."""
    opened = []

    def connect(url, **kwargs):
        opened.append(FakeConn(url, kwargs))
        return opened[-1]

    monkeypatch.setattr(psycopg, "connect", connect)
    monkeypatch.setenv(database.DATABASE_URL_ENV, URL)
    monkeypatch.setattr(database, "_schema_applied", set())
    return opened


def refused(monkeypatch, error):
    def connect(url, **kwargs):
        raise error

    monkeypatch.setattr(psycopg, "connect", connect)
    monkeypatch.setenv(database.DATABASE_URL_ENV, URL)


def everything_said(exc):
    """All the text an error could show anyone: its message, its repr, and the whole chain a traceback would print."""
    return "\n".join([str(exc), repr(exc), *traceback.format_exception(exc)])


# --- the placeholder -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("sql,expected", [
    ("SELECT 1", "SELECT 1"),
    ("WHERE a = ? AND b = ?", "WHERE a = %s AND b = %s"),
    ("WHERE a LIKE '%x?%' AND b = ?", "WHERE a LIKE '%%x?%%' AND b = %s"),
    ("SELECT 'it''s ?', ?", "SELECT 'it''s ?', %s"),
    ('SELECT "odd?col" FROM t WHERE a = ?', 'SELECT "odd?col" FROM t WHERE a = %s'),
    ("SELECT 100 % 7, ?", "SELECT 100 %% 7, %s"),
])
def test_the_question_mark_becomes_the_drivers_placeholder_outside_quotes_and_a_percent_is_escaped(sql, expected):
    assert database._postgres_sql(sql) == expected


def test_only_a_postgres_connection_converts_and_sqlite_gets_the_sql_as_written(made, tmp_path):
    pg = database.connect()
    pg.execute("SELECT ? , '%'", (1,))
    assert made[0].statements[-1] == ("SELECT %s , '%%'", (1,))
    lite = database.open_db(tmp_path / "x.db")                      # an explicit path is SQLite whatever the URL says
    try:
        assert lite.execute("SELECT ?, '%'", (1,)).fetchone()[0] == 1
    finally:
        lite.close()


def test_an_insert_reads_the_new_id_by_column_name_because_a_row_is_a_dict():
    conn = FakeConn("", {}, rows=[{"run_id": 7}])
    assert database.Db(conn, "cytonn").insert("INSERT INTO t (a) VALUES (?)", (1,), "run_id") == 7
    assert conn.statements == [("INSERT INTO t (a) VALUES (%s) RETURNING run_id", (1,))]


def test_a_transaction_block_is_the_drivers_own_and_the_connection_is_not_closed_by_it():
    conn = FakeConn("", {})
    pg = database.Db(conn, "cytonn")
    with pg.transaction():
        pg.execute("UPDATE t SET a = ?", (1,))
    with pytest.raises(RuntimeError):
        with pg.transaction():
            raise RuntimeError("boom")
    assert conn.transactions == ["begin", "commit", "begin", "rollback"] and not conn.closed


# --- SSL ----------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    (URL, URL + "?sslmode=require"),
    (URL + "?application_name=x", URL + "?application_name=x&sslmode=require"),
    (URL + "?sslmode=require", URL + "?sslmode=require"),
    (URL + "?sslmode=verify-ca", URL + "?sslmode=verify-ca"),
    (URL + "?sslmode=verify-full&application_name=x", URL + "?sslmode=verify-full&application_name=x"),
    ("postgres://u:p%40ss%2Fw@h:5432/d", "postgres://u:p%40ss%2Fw@h:5432/d?sslmode=require"),  # the password is not re-encoded
])
def test_ssl_is_required_added_when_the_url_says_nothing_and_kept_when_it_asks_for_more(url, expected):
    assert database._postgres_url(url) == expected


@pytest.mark.parametrize("weak", ["disable", "allow", "prefer", "", "Require", "required"])
def test_a_weaker_sslmode_is_refused(weak):
    for url in (f"{URL}?sslmode={weak}", f"{URL}?sslmode=require&sslmode={weak}"):
        with pytest.raises(database.DatabaseNotAvailable, match="weaker than require") as err:
            database._postgres_url(url)
        assert PW not in everything_said(err.value) and HOST not in everything_said(err.value)


@pytest.mark.parametrize("url", ["host=h user=u password=" + PW, f"mysql://{USER}:{PW}@{HOST}/d",
                                 f"postgresql://{USER}:{PW}@/d", f"postgresql://{USER}:pa[ss@{HOST}/d"])
def test_what_is_not_a_postgres_url_is_refused_without_echoing_it(url):
    with pytest.raises(database.DatabaseNotAvailable, match="not a valid postgresql://") as err:
        database._postgres_url(url)
    assert PW not in everything_said(err.value) and HOST not in everything_said(err.value)


def test_a_password_with_a_raw_at_sign_is_refused_before_the_driver_can_read_part_of_it_as_a_host(made, monkeypatch):
    for url in (f"postgresql://{USER}:pa@ss&word@{HOST}:5432/postgres", f"postgresql://{USER}:p@a@s@{HOST}/postgres"):
        monkeypatch.setenv(database.DATABASE_URL_ENV, url)
        with pytest.raises(database.DatabaseNotAvailable, match="Percent-encode the password") as err:
            database.connect()
        assert "pa@ss" not in everything_said(err.value) and HOST not in everything_said(err.value)
    assert made == []                                               # nothing was opened, so nothing was resolved or sent
    # encoded, the same password is one @ and parses to the same user and password in libpq
    encoded = database._postgres_url(f"postgresql://{USER}:pa%40ss%26word@{HOST}:5432/postgres")
    assert conninfo_to_dict(encoded)["password"] == "pa@ss&word" and conninfo_to_dict(encoded)["host"] == HOST


def test_a_connection_gets_the_url_with_ssl_required_and_a_dict_row_autocommit_connection(made):
    database.connect().close()
    conn = made[0]
    assert conn.url == URL + "?sslmode=require"
    assert conn.kwargs == {"row_factory": dict_row, "autocommit": True, "connect_timeout": database.CONNECT_TIMEOUT_SECONDS}


def test_a_user_name_with_a_dot_reaches_the_driver_parsed_as_written():
    parsed = conninfo_to_dict(database._postgres_url(URL))        # the driver's own parser, no connection made
    assert (parsed["user"], parsed["password"], parsed["host"], parsed["port"], parsed["dbname"], parsed["sslmode"]) == (
        USER, PW, HOST, "5432", "postgres", "require")


# --- the schema and search_path -----------------------------------------------------------------------------------------

def test_search_path_is_set_by_a_statement_first_on_every_new_connection_and_not_as_a_startup_option(made):
    for _ in range(3):
        database.connect().close()
    assert len(made) == 3
    for conn in made:
        assert conn.statements[0] == ('SET search_path TO "cytonn"', None)
        assert "options" not in conn.url and "options" not in conn.kwargs


def test_the_schema_comes_from_the_environment_and_is_always_set_on_the_connection(made, monkeypatch):
    monkeypatch.setenv(database.DATABASE_SCHEMA_ENV, "my_schema_2")
    pg = database.connect()
    assert made[0].statements[0][0] == 'SET search_path TO "my_schema_2"' and pg.schema == "my_schema_2"


@pytest.mark.parametrize("name", ["public", "information_schema", "pg_catalog", "Cytonn", "a-b", "1abc", "a b", 'a"b', "x" * 64, "a;drop"])
def test_a_schema_name_that_is_not_a_plain_private_name_is_refused_before_any_connection(made, monkeypatch, name):
    monkeypatch.setenv(database.DATABASE_SCHEMA_ENV, name)
    with pytest.raises(database.DatabaseNotAvailable, match=database.DATABASE_SCHEMA_ENV):
        database.connect()
    assert made == []


def test_a_failing_search_path_statement_closes_the_connection_and_says_only_the_fixed_sentence(made, monkeypatch):
    real = FakeConn.execute

    def fails(self, sql, params=None):
        raise pg_errors.InsufficientPrivilege(f"permission denied for {HOST} {PW}")

    monkeypatch.setattr(FakeConn, "execute", fails)
    with pytest.raises(database.DatabaseNotAvailable) as err:
        database.connect()
    monkeypatch.setattr(FakeConn, "execute", real)
    assert made[0].closed and str(err.value) == database.UNREACHABLE
    assert PW not in everything_said(err.value) and HOST not in everything_said(err.value)


def test_the_schema_script_runs_once_per_process_in_one_transaction_after_an_advisory_lock(made):
    for _ in range(3):
        database.open_db().close()
    assert len(made) == 3
    first, later = made[0], made[1:]
    sql = [s for s, _ in first.statements]
    assert sql[0].startswith("SET search_path") and sql[1].startswith("SELECT pg_advisory_xact_lock(")
    assert 'CREATE SCHEMA IF NOT EXISTS "cytonn";' in sql[2] and "{schema}" not in sql[2]
    assert first.transactions == ["begin", "commit"]
    assert all(len(c.statements) == 1 and c.transactions == [] for c in later)   # the rest only set the search_path


def test_a_different_schema_gets_its_own_script(made, monkeypatch):
    database.open_db().close()
    monkeypatch.setenv(database.DATABASE_SCHEMA_ENV, "another")
    database.open_db().close()
    assert 'CREATE SCHEMA IF NOT EXISTS "another";' in made[1].statements[2][0]


def test_a_failing_schema_script_closes_its_connection_and_is_tried_again_next_time(made, monkeypatch):
    real = FakeConn.execute
    calls = []

    def fails_on_the_script(self, sql, params=None):
        calls.append(sql)
        if sql.lstrip().startswith("--"):
            raise pg_errors.SyntaxError("boom")
        return real(self, sql, params)

    monkeypatch.setattr(FakeConn, "execute", fails_on_the_script)
    with pytest.raises(pg_errors.SyntaxError):
        database.open_db()
    assert made[0].closed and made[0].transactions == ["begin", "rollback"]
    monkeypatch.setattr(FakeConn, "execute", real)
    database.open_db().close()
    assert any("CREATE SCHEMA" in s for s, _ in made[1].statements)


def schema_text():
    return SCHEMA_FILE.read_text(encoding="utf-8")


def test_every_table_has_row_level_security_enabled_with_no_policy_and_not_forced():
    text = re.sub(r"--[^\n]*", "", schema_text())
    tables = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", text)
    secured = re.findall(r"ALTER TABLE (\w+)\s+ENABLE ROW LEVEL SECURITY;", text)
    assert sorted(tables) == sorted(secured) == ["coordinator_reviews", "sections", "suggestion_decisions"]
    assert "CREATE POLICY" not in text.upper() and "FORCE" not in text.upper()   # the app is the owner and must keep its access


def test_the_run_id_is_a_bigint_identity_column_and_nothing_is_a_serial_or_autoincrement():
    text = re.sub(r"--[^\n]*", "", schema_text())
    assert re.search(r"run_id\s+BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY", text)
    assert not re.search(r"SERIAL|AUTOINCREMENT", text, re.I)


def test_the_schema_file_makes_the_schema_the_only_place_tables_go():
    text = re.sub(r"--[^\n]*", "", schema_text())
    assert text.count("{schema}") == 1 and "CREATE SCHEMA IF NOT EXISTS {schema};" in text
    assert "public" not in text and "ON CONFLICT (name) DO NOTHING" in text
    assert text.count("CREATE TABLE IF NOT EXISTS") == 3 and text.count("CREATE INDEX IF NOT EXISTS") == 2


# --- nothing secret in an error, a log line, an event or a response ---------------------------------------------------------

def test_an_error_built_from_a_url_with_a_password_never_reaches_the_one_raised(monkeypatch, caplog):
    boom = psycopg.OperationalError(f'connection to server at "{HOST}" (10.0.0.1), port 5432 failed: FATAL: password '
                                    f'authentication failed for user "{USER}" ({URL}, password {PW})')
    refused(monkeypatch, boom)
    with caplog.at_level("DEBUG"):
        with pytest.raises(database.DatabaseNotAvailable) as err:
            database.connect()
    said = everything_said(err.value) + caplog.text
    for secret in (PW, HOST, USER, URL, "10.0.0.1"):
        assert secret not in said, secret
    assert str(err.value) == database.UNREACHABLE and err.value.__cause__ is None and err.value.__context__ is None


def test_a_failed_connection_logs_a_fixed_word_the_class_and_sqlstate_and_nothing_the_driver_said(monkeypatch, caplog):
    refused(monkeypatch, pg_errors.InvalidPassword(f"password authentication failed for user {USER} {PW}"))
    with caplog.at_level("DEBUG"), pytest.raises(database.DatabaseNotAvailable):
        database.connect()
    assert "authentication (InvalidPassword, SQLSTATE 28P01)" in caplog.text
    assert PW not in caplog.text and USER not in caplog.text and "password authentication" not in caplog.text


@pytest.mark.parametrize("said,word", [
    (f'connection failed: connection to server at "{HOST}", port 5432 failed: FATAL: password authentication failed for user "{USER}"', "authentication"),
    (f"connection failed: could not translate host name \"{HOST}\" to address: Name or service not known", "name lookup"),
    ("[Errno 11001] getaddrinfo failed", "name lookup"),
    (f"network access in a test: {HOST!r}", "name lookup"),
    (f'connection failed: connection to server at "{HOST}", port 5432 failed: timeout expired', "timeout"),
    ("connection refused", "refused"),
    ("SSL error: certificate verify failed", "ssl"),
    (f"something else about {HOST}", "other"),
])
def test_a_failed_connection_is_told_apart_by_a_fixed_word(monkeypatch, caplog, said, word):
    refused(monkeypatch, psycopg.OperationalError(said))
    with caplog.at_level("DEBUG"), pytest.raises(database.DatabaseNotAvailable):
        database.connect()
    assert f"connection: {word} (OperationalError" in caplog.text and HOST not in caplog.text and USER not in caplog.text


def test_a_driver_error_of_any_kind_is_one_fixed_sentence_for_the_screen():
    for error in (psycopg.OperationalError(f"{HOST} {USER}"), psycopg.InterfaceError(URL), psycopg.ProgrammingError(PW),
                  pg_errors.UniqueViolation(f"Key ({USER}) already exists"), pg_errors.InvalidPassword(URL)):
        assert ev.user_message(error) == "Could not reach the database. Check CYTONN_DATABASE_URL and the network."
        assert failure_message(error) == ev.user_message(error)
    assert ev.user_message(KeyError("x")) == "KeyError: 'x'"            # anything else is worded as before


def test_a_failure_message_blanks_the_database_url_and_any_url_that_carries_credentials(monkeypatch):
    monkeypatch.setenv(database.DATABASE_URL_ENV, URL)
    monkeypatch.setenv("SOME_OTHER_DSN", "postgresql://svc:Other-fake-secret@elsewhere.example/db")   # not named like a secret
    said = failure_message(RuntimeError(f"bad: {URL} and postgresql://svc:Other-fake-secret@elsewhere.example/db "
                                        f"and a lone {PW} and Other-fake-secret"))
    assert said == "RuntimeError: bad: [redacted] and [redacted] and a lone [redacted] and [redacted]"
    assert "fake" not in said


def test_a_configured_url_is_blanked_whole_even_when_its_password_would_end_the_url_pattern_early(monkeypatch):
    odd = "postgresql://svc:pa/ss-fake-secret@elsewhere.example/db"                 # a raw / in the password
    monkeypatch.setenv("SOME_OTHER_DSN", odd)                                       # and not named like a secret
    assert failure_message(RuntimeError(f"tried {odd} twice")) == "RuntimeError: tried [redacted] twice"


def test_a_message_the_pipeline_wrote_itself_is_redacted_too(monkeypatch):
    """A ValueError's text stands alone on the screen (it does not go through user_message), so redact has to run on it."""
    monkeypatch.setenv(database.DATABASE_URL_ENV, URL)
    assert failure_message(ValueError(f"cannot connect with {URL}")) == "cannot connect with [redacted]"
    assert failure_message(ValueError(f"the password {PW} was refused")) == "the password [redacted] was refused"


def test_a_url_with_credentials_that_is_not_configured_anywhere_is_still_removed_from_the_text():
    said = failure_message(RuntimeError(f"cannot use {URL}?sslmode=require. Next."))
    assert PW not in said and HOST not in said and said == "RuntimeError: cannot use [redacted] Next."


def test_the_database_url_is_blanked_by_its_name_even_when_it_is_not_a_url(monkeypatch):
    monkeypatch.setenv("CYTONN_TEST_DATABASE_URL", "not-a-url but a secret")
    assert failure_message(RuntimeError("saw not-a-url but a secret here")) == "RuntimeError: saw [redacted] here"


def test_ordinary_text_and_short_values_are_left_alone(monkeypatch):
    monkeypatch.setenv("SOME_PASSWORD", "short")
    assert failure_message(RuntimeError("a short answer, see http://example.com/page")) == \
        "RuntimeError: a short answer, see http://example.com/page"


def test_the_log_line_of_a_failed_run_is_redacted(tmp_path, monkeypatch, caplog):
    """api/main.py logs why a run failed; a database error there is its class alone and any other error has secrets removed."""
    monkeypatch.setenv(database.DATABASE_URL_ENV, URL)
    client = TestClient(create_app(db_path=tmp_path / "app.db", load_dotenv=False))
    for error, class_name in ((psycopg.OperationalError(f"{HOST} {USER} {URL} {PW}"), "OperationalError"),
                              (RuntimeError(f"could not use {URL} ({PW})"), "RuntimeError")):
        def build(on_event=None, _error=error):
            raise _error

        monkeypatch.setattr(review_run, "build_digital_payments_review", build)
        caplog.clear()
        with caplog.at_level("DEBUG"):
            run = finished(client, start(client, **WEEKLY_DP))
        served = json.dumps(run)
        assert run["status"] == "failed" and class_name in caplog.text
        for secret in (PW, HOST, USER, URL):
            assert secret not in caplog.text and secret not in served, (class_name, secret)


def test_a_review_that_cannot_be_saved_logs_no_traceback_for_a_database_error_and_no_secret(tmp_path, monkeypatch, caplog):
    from tests.review_helpers import ROWS, TODAY, FakeProvider

    real = review_run.build_digital_payments_review
    monkeypatch.setattr(review_run, "build_digital_payments_review", lambda on_event=None: real(
        provider=FakeProvider(), today=TODAY, fetch_table=lambda today: ROWS, on_event=on_event))
    monkeypatch.setenv(database.DATABASE_URL_ENV, URL)

    def cannot_save(*args, **kwargs):
        raise psycopg.OperationalError(f"server at {HOST} closed the connection for {USER}: {URL} {PW}")

    monkeypatch.setattr(review_store, "save_review", cannot_save)
    client = TestClient(create_app(db_path=tmp_path / "app.db", load_dotenv=False))
    with caplog.at_level("DEBUG"):
        run = finished(client, start(client, **WEEKLY_DP))
    assert run["status"] == "failed" and run["events"][-1]["detail"] == database.UNREACHABLE
    assert "could not save its review" in caplog.text and "Traceback" not in caplog.text
    for secret in (PW, HOST, USER, URL):
        assert secret not in caplog.text and secret not in json.dumps(run), secret
