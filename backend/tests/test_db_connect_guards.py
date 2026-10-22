"""The call _open_postgres makes, against the real psycopg; non-driver failures logged redacted; the URL kept out of tracebacks.

No server and no network.  The URL and its password are invented.
"""

import inspect
from importlib.metadata import version

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from cytonn_weekly import db as database
from tests.test_db_postgres import FakeConn, HOST, PW, URL, USER, refused

SECRETS = (PW, USER, URL)


def test_the_connect_call_binds_to_the_real_signature_and_its_keywords_make_valid_conninfo(monkeypatch):
    """A fake driver accepts any keyword; the real signature and libpq's keyword list do not."""
    real = inspect.signature(psycopg.connect)
    seen = []

    def connect(*args, **kwargs):
        seen.append(real.bind(*args, **kwargs))  # a wrong keyword or type fails here
        return FakeConn(args[0], kwargs)

    monkeypatch.setattr(psycopg, "connect", connect)
    database._open_postgres(URL, "s")
    args = seen[0].arguments
    conninfo = args["conninfo"]
    extra = {k: v for k, v in args["kwargs"].items()}
    parsed = conninfo_to_dict(make_conninfo(conninfo, **extra))  # libpq refuses a keyword it does not know
    assert parsed["connect_timeout"] == str(database.CONNECT_TIMEOUT_SECONDS) and parsed["keepalives"] == "1"
    assert parsed["sslmode"] == "require"


def test_a_failure_that_is_not_a_driver_error_logs_its_class_and_message_with_the_secrets_taken_out(monkeypatch, caplog):
    refused(monkeypatch, TypeError(f"bad call for {URL}, user {USER}, password {PW}"))
    with caplog.at_level("DEBUG"), pytest.raises(database.DatabaseNotAvailable) as err:
        database.connect()
    assert "unexpected TypeError: bad call for ***, user ***, password ***" in caplog.text
    assert not any(s in caplog.text + str(err.value) for s in SECRETS)


def test_a_driver_error_still_logs_only_the_word_the_class_and_the_sqlstate(monkeypatch, caplog):
    refused(monkeypatch, psycopg.OperationalError(f"{HOST} {USER} {PW}"))
    with caplog.at_level("DEBUG"), pytest.raises(database.DatabaseNotAvailable):
        database.connect()
    assert "other (OperationalError, SQLSTATE None)" in caplog.text and "unexpected" not in caplog.text
    assert not any(s in caplog.text for s in SECRETS + (HOST,))


def test_the_secret_url_prints_as_stars_but_is_the_real_value_everywhere_else():
    url = database._SecretUrl(URL)
    assert repr(url) == "'***'" and repr((url, "s")) == "('***', 's')"
    assert str(url) == URL and url == URL and f"{url}" == URL and hash(url) == hash(URL)


def long_repr(err):
    return err.getrepr(style="long", funcargs=True, showlocals=False).__str__()


def test_a_traceback_of_a_failed_connect_never_shows_the_url_user_or_password(monkeypatch):
    refused(monkeypatch, RuntimeError("boom"))
    with pytest.raises(database.DatabaseNotAvailable) as err:
        database.connect()
    text = long_repr(err)
    assert "_open_postgres" in text and not any(s in text for s in SECRETS)


def test_a_traceback_of_a_refused_url_never_shows_it(monkeypatch):
    monkeypatch.setenv(database.DATABASE_URL_ENV, URL + "?sslmode=disable")
    with pytest.raises(database.DatabaseNotAvailable) as err:
        database.connect()
    text = long_repr(err)
    assert "_postgres_url" in text and not any(s in text for s in SECRETS)


def test_a_traceback_of_the_held_connection_path_never_shows_the_url(monkeypatch):
    refused(monkeypatch, RuntimeError("boom"))
    with database._held_lock, pytest.raises(database.DatabaseNotAvailable) as err:
        database._held_connection(URL, "s")
    text = long_repr(err)
    assert "_held_connection" in text and not any(s in text for s in SECRETS)


def test_a_traceback_of_a_failed_schema_creation_never_shows_the_url(monkeypatch):
    class Failing(FakeConn):
        def execute(self, sql, params=None):
            if "CREATE SCHEMA" in sql:
                raise RuntimeError("boom")
            return super().execute(sql, params)

    monkeypatch.setattr(psycopg, "connect", lambda url, **kw: Failing(url, kw))
    monkeypatch.setenv(database.DATABASE_URL_ENV, URL)
    monkeypatch.setattr(database, "_schema_applied", set())
    with pytest.raises(RuntimeError) as err:
        database.open_db()
    text = long_repr(err)
    assert "_apply_postgres_schema" in text and not any(s in text for s in SECRETS)


def test_the_installed_driver_and_its_binary_are_the_same_version():
    """A psycopg 3.2 beside psycopg-binary 3.3 fails every connect with "connect() takes no keyword arguments", whatever we pass."""
    assert version("psycopg") == version("psycopg-binary"), "run `pip install -e .` in backend/: pyproject pins both"
