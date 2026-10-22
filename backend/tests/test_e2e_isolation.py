"""The end-to-end instance (e2e/serve_e2e.py) can never reach the real database, even when .env and the environment name one.

On 2026-10-22, after the PostgreSQL go-live, the instance wrote synthetic reviews into the real database because only its
data folder was throwaway.  These tests run the instance's set-up with a PostgreSQL-looking URL in the environment and in a
.env file and require that the target is the SQLite file in the demo folder and that the driver is never asked to connect.
"""
import importlib.util
import os
from pathlib import Path

import pytest

from cytonn_weekly import db, env
from cytonn_weekly.paths import REPO_ROOT

URL = "postgresql://x:y@127.0.0.1:1/z?sslmode=require"
NAMES = ("CYTONN_DATABASE_URL", "CYTONN_TEST_DATABASE_URL", "CYTONN_DATABASE_SCHEMA")


def _serve():
    spec = importlib.util.spec_from_file_location("serve_e2e_under_test", REPO_ROOT / "e2e" / "serve_e2e.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # defines the functions; serves nothing (main() runs only as a script)
    return module


@pytest.fixture
def hostile(tmp_path, monkeypatch):
    """A pristine copy, a demo data folder, a PostgreSQL-looking URL in the environment and in a .env file, and a driver that raises."""
    import psycopg

    pristine = tmp_path / "pristine"
    (pristine / "inputs").mkdir(parents=True)
    data = tmp_path / "demo-e2e" / "data"
    env_file = tmp_path / ".env"
    env_file.write_text(f"CYTONN_DATABASE_URL={URL}\nCYTONN_DATABASE_SCHEMA=cytonn\n")
    for name in NAMES:
        monkeypatch.setenv(name, URL if name.endswith("URL") else "cytonn")
    monkeypatch.setattr(db, "_DEFAULT_DB", data / "app.db")  # where a call given no path goes, as with CYTONN_DATA_DIR set
    attempts = []

    def refuse(*args, **kwargs):
        attempts.append(1)
        raise AssertionError("psycopg.connect was called")

    monkeypatch.setattr(psycopg, "connect", refuse)
    yield pristine, data, env_file, attempts
    for name in NAMES:  # a .env load below sets variables monkeypatch does not know of
        os.environ.pop(name, None)


def test_the_instance_is_on_sqlite_in_the_demo_folder_and_never_connects(hostile):
    pristine, data, env_file, attempts = hostile
    serve = _serve()

    db_path = serve.prepare(data, pristine)
    assert not any(os.environ.get(n) for n in NAMES)
    assert db_path.parent == data and db_path.name == "e2e.db"

    env.load_env(env_file, quiet=True)  # what create_app(load_dotenv=True) would do: it puts the URL back
    assert os.environ.get("CYTONN_DATABASE_URL") == URL
    serve.verify_isolated(db_path, data)  # clears it again and checks the target
    assert not any(os.environ.get(n) for n in NAMES)
    assert attempts == []
    assert not (data / "app.db").exists() and not db_path.exists()  # checking the target opens nothing


def test_a_database_file_outside_the_demo_folder_is_refused(hostile, tmp_path):
    pristine, data, _, attempts = hostile
    serve = _serve()
    serve.prepare(data, pristine)
    with pytest.raises(SystemExit) as stopped:
        serve.verify_isolated(tmp_path / "elsewhere.db", data)
    assert "demo data folder" in str(stopped.value) and "postgresql" not in str(stopped.value).lower()
    assert attempts == []


def test_a_call_with_no_path_that_would_leave_the_demo_folder_is_refused(hostile, tmp_path, monkeypatch):
    pristine, data, _, attempts = hostile
    serve = _serve()
    db_path = serve.prepare(data, pristine)
    monkeypatch.setattr(db, "_DEFAULT_DB", tmp_path / "elsewhere" / "app.db")  # e.g. the real backend/data/app.db
    with pytest.raises(SystemExit) as stopped:
        serve.verify_isolated(db_path, data)
    assert "no database path" in str(stopped.value)
    assert attempts == []
