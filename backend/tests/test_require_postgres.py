"""CYTONN_REQUIRE_POSTGRES=1 (set by docker-compose.yml only) means no SQLite database is ever opened."""

import pytest

from cytonn_weekly import db


def test_without_the_marker_a_missing_url_is_sqlite(monkeypatch, tmp_path):
    monkeypatch.delenv(db.REQUIRE_POSTGRES_ENV, raising=False)
    monkeypatch.delenv(db.DATABASE_URL_ENV, raising=False)
    assert db.target(tmp_path / "x.db") == ("sqlite", tmp_path / "x.db")


@pytest.mark.parametrize("url", [None, "", "   "])
def test_with_the_marker_sqlite_is_refused_before_any_file_is_touched(monkeypatch, tmp_path, url):
    monkeypatch.setenv(db.REQUIRE_POSTGRES_ENV, "1")
    if url is None:
        monkeypatch.delenv(db.DATABASE_URL_ENV, raising=False)
    else:
        monkeypatch.setenv(db.DATABASE_URL_ENV, url)
    for path in (None, tmp_path / "x.db"):
        with pytest.raises(RuntimeError, match="refuses to use SQLite"):
            db.target(path)
        with pytest.raises(RuntimeError, match="refuses to use SQLite"):
            db.connect(path)
    assert list(tmp_path.iterdir()) == []


def test_with_the_marker_and_a_url_it_is_postgres(monkeypatch):
    monkeypatch.setenv(db.REQUIRE_POSTGRES_ENV, "1")
    monkeypatch.setenv(db.DATABASE_URL_ENV, "postgresql://u:p@example.invalid:5432/d")
    assert db.target() == ("postgres", None)


def test_the_app_refuses_to_start_with_the_marker_and_no_url(monkeypatch, tmp_path):
    from api.main import create_app

    monkeypatch.setenv(db.REQUIRE_POSTGRES_ENV, "1")
    monkeypatch.delenv(db.DATABASE_URL_ENV, raising=False)
    with pytest.raises(RuntimeError, match="refuses to use SQLite"):
        create_app(load_dotenv=False)
