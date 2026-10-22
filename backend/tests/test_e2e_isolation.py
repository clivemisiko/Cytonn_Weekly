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


def test_main_gives_create_app_the_demo_sqlite_file_and_no_dotenv(hostile, monkeypatch):
    """main() runs for real up to the server: create_app and uvicorn.run are the only things replaced."""
    import uvicorn

    import api.main
    from cytonn_weekly import paths
    from cytonn_weekly.digital_payments import review_run as digital_payments
    from cytonn_weekly.equities import weekly as equities
    from cytonn_weekly.narrative import drafter
    from cytonn_weekly.real_estate import review_run as real_estate
    from tests import periodic_helpers

    pristine, data, _, attempts = hostile
    serve = _serve()
    monkeypatch.setattr(serve, "REAL", data.parent.parent)  # main() refuses a folder that is not <real>/demo-e2e/<name>
    monkeypatch.setattr(serve, "DATA", data)
    monkeypatch.setattr(serve, "PRISTINE", pristine)
    monkeypatch.setattr(serve, "VARIANT", "")
    monkeypatch.setattr(paths, "DATA_DIR", data)
    monkeypatch.syspath_prepend(str(REPO_ROOT / "e2e"))  # chart_demo and notable_demo sit beside serve_e2e.py
    for name in ("CYTONN_DATA_DIR", "CYTONN_WEB_ORIGINS", "CYTONN_LLM_PROVIDER", "ANTHROPIC_API_KEY", "EXA_API_KEY"):
        monkeypatch.setenv(name, "x")  # main() sets these; this makes the test put them back
    # main() replaces builders for the whole process; put each one back afterwards
    for module, attribute in [(drafter, "get_narrative_provider"), (real_estate, "build_real_estate_review"),
                              (digital_payments, "build_digital_payments_review"), (equities, "build_equities_weekly_review")]:
        monkeypatch.setattr(module, attribute, getattr(module, attribute))
    for slug in periodic_helpers.BUILDERS:
        module = __import__(f"cytonn_weekly.periodic.{slug}", fromlist=["_"])
        monkeypatch.setattr(module, f"build_{slug}_review", getattr(module, f"build_{slug}_review"))

    made, served = [], []
    sentinel = object()

    def fake_create_app(*args, **kwargs):
        made.append((args, kwargs))
        return sentinel

    monkeypatch.setattr(api.main, "create_app", fake_create_app)
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: served.append(app))

    serve.main()

    assert len(made) == 1
    args, kwargs = made[0]
    given = args[0] if args else kwargs.get("db_path")
    assert given is not None and Path(given) == data / "e2e.db"
    assert kwargs.get("load_dotenv") is False
    assert served == [sentinel]
    assert attempts == []
