"""Stage P1, the database seam (cytonn_weekly/db.py): every runtime SQL call goes through one module.

SQLite only.  Nothing here connects to PostgreSQL, imports psycopg or opens backend/data/app.db: conftest points the
default file at a temp file, and the tests that need a path pass their own.
"""

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from cytonn_weekly import db as database
from cytonn_weekly import sections
from cytonn_weekly.charts import store as chart_store
from cytonn_weekly.digital_payments import coordinator_review as cr
from cytonn_weekly.digital_payments import review_store as rs
from cytonn_weekly.paths import BACKEND_ROOT, REPO_ROOT
from tests.review_helpers import make_review
from tests.test_charts_store_api import chart_review

URL = "postgresql://someone:hunter2-not-a-real-password@localhost:5432/cytonn"


@pytest.fixture
def path(tmp_path):
    return tmp_path / "seam.db"


def stored(path, run_id):
    conn = database.connect(path)
    try:
        return dict(conn.execute("SELECT * FROM coordinator_reviews WHERE run_id = ?", (run_id,)).fetchone())
    finally:
        conn.close()


def decided(review, how=cr.APPROVED):
    review.accept_all_clean()
    for i in review.review_items:
        if i.resolution is None:
            i.resolve(cr.ACCEPT)
    review.decide(how)
    return review


# --- (a) the approval-freezing guard, now written with IS NOT DISTINCT FROM -------------------------------------------

def test_a_decided_review_stays_frozen_against_a_stale_undecided_copy(path):
    review = make_review()
    run_id = rs.save_review(review, db_path=path)
    stale = rs.load_review(run_id, db_path=path)               # decision None, decided_at None: both NULL
    rs.save_review(decided(review), db_path=path)
    before = stored(path, run_id)
    stale.review_items[0].resolve(cr.FIX_NEEDED, "late edit")
    with pytest.raises(rs.ReviewAlreadyDecided, match="already approved"):
        rs.save_review(stale, db_path=path)                     # NULL is not distinct from NULL, but 'approved' is
    assert stored(path, run_id) == before


def test_a_retry_with_the_same_decision_and_time_is_allowed(path):
    review = decided(make_review(), cr.REJECTED)
    run_id = rs.save_review(review, db_path=path)
    before = stored(path, run_id)
    assert rs.save_review(review, db_path=path) == run_id       # identical values: the guard lets it through
    after = stored(path, run_id)
    assert (after["decision"], after["decided_at"]) == (before["decision"], before["decided_at"]) == (cr.REJECTED, review.decided_at)
    assert after["content_json"] == before["content_json"]


@pytest.mark.parametrize("change", ["other decision", "other time", "no decision"])
def test_an_update_to_a_different_decision_is_refused_and_changes_nothing(path, change):
    review = decided(make_review())
    run_id = rs.save_review(review, db_path=path)
    before = stored(path, run_id)
    other = rs.load_review(run_id, db_path=path)
    if change == "other decision":
        other.decision = cr.REJECTED
    elif change == "other time":
        other.decided_at = "2099-01-01T00:00:00+00:00"
    else:
        other.decision = other.decided_at = None
    with pytest.raises(rs.ReviewAlreadyDecided):
        rs.save_review(other, db_path=path)
    assert stored(path, run_id) == before


def test_an_undecided_review_still_takes_every_update_and_then_its_decision(path):
    review = make_review()
    run_id = rs.save_review(review, db_path=path)
    review.review_items[0].resolve(cr.ACCEPT, "first")
    rs.save_review(review, db_path=path)
    rs.save_review(decided(review), db_path=path)
    assert rs.load_review(run_id, db_path=path).decision == cr.APPROVED


def test_a_missing_run_id_is_still_a_lookup_error_and_not_a_frozen_review(path):
    review = make_review()
    review.run_id = 404
    with pytest.raises(LookupError, match="no saved review with run_id 404"):
        rs.save_review(review, db_path=path)


# --- (b) the inserted row's id --------------------------------------------------------------------------------------

def test_an_insert_gives_back_the_new_rows_id_read_with_returning(path):
    conn = database.open_db(path)
    try:
        sql = ("INSERT INTO coordinator_reviews (section, report_type, period, run_date, created_at, updated_at, "
               "decision, decided_at, content_json, items_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
        row = ("equities", "weekly", "", "2026-10-22", "t", "t", None, None, "{}", "[]")
        with conn.transaction():
            first = conn.insert(sql, row, "run_id")
            second = conn.insert(sql, row, "run_id")
        assert (first, second) == (1, 2)
        assert [r["run_id"] for r in conn.execute("SELECT run_id FROM coordinator_reviews ORDER BY run_id")] == [1, 2]
    finally:
        conn.close()


def test_the_run_id_a_save_returns_is_the_charts_folder_name(path, tmp_path):
    root = tmp_path / "charts-here"
    ids = []
    for _ in range(2):
        review = chart_review()
        run_id = rs.save_review(review, db_path=path)
        assert review.run_id == run_id
        chart_store.persist(review, root)
        ids.append(run_id)
    assert ids[0] != ids[1]
    assert sorted(p.name for p in root.iterdir()) == sorted(str(i) for i in ids)          # one folder per run, named by its id
    for run_id in ids:
        assert (root / str(run_id) / "nasi_pe.png").is_file()
        assert stored(path, run_id)["run_id"] == run_id                                   # and that id is a stored row


def test_rows_are_read_by_column_name(path):
    rs.save_review(make_review(), db_path=path)
    conn = database.open_db(path)
    try:
        row = conn.execute("SELECT run_id, section FROM coordinator_reviews").fetchone()
        assert (row["run_id"], row["section"]) == (1, "digital_payments")
        assert dict(row) == {"run_id": 1, "section": "digital_payments"} and list(row.keys()) == ["run_id", "section"]
    finally:
        conn.close()


def test_a_transaction_commits_when_it_ends_and_rolls_back_when_it_raises(path):
    conn = database.open_db(path)
    try:
        with conn.transaction():
            conn.execute("UPDATE sections SET current_analyst = ? WHERE name = ?", ("A. Analyst", "Equities"))
        with pytest.raises(RuntimeError, match="boom"):
            with conn.transaction():
                conn.execute("UPDATE sections SET current_analyst = ? WHERE name = ?", ("B. Analyst", "Equities"))
                raise RuntimeError("boom")
        # still open after both blocks, and only the first change is there
        assert conn.execute("SELECT current_analyst FROM sections WHERE name = 'Equities'").fetchone()[0] == "A. Analyst"
    finally:
        conn.close()
    assert sections.get_section_config("Equities", path)["current_analyst"] == "A. Analyst"


# --- (c) nothing outside the connection module reaches the driver ----------------------------------------------------

SCANNED = [*(BACKEND_ROOT / "src").rglob("*.py"), *(BACKEND_ROOT / "api").rglob("*.py"),
           *(BACKEND_ROOT / "scripts").rglob("*.py"), *(REPO_ROOT / "e2e").glob("*.py")]
THE_MODULE = BACKEND_ROOT / "src" / "cytonn_weekly" / "db.py"
DRIVER_CALLS = {"connect", "executescript", "executemany", "cursor", "commit", "rollback"}


def driver_use(source: str) -> list[str]:
    """What in this source touches the driver: an import of sqlite3 or psycopg, any use of the name sqlite3, lastrowid,
    or a call to connect, executescript, executemany, cursor, commit or rollback that is not ``db.connect``."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [f"import {a.name}" for a in node.names if a.name.split(".")[0] in ("sqlite3", "psycopg")]
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in ("sqlite3", "psycopg"):
            found.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Name) and node.id == "sqlite3":
            found.append("the name sqlite3")
        elif isinstance(node, ast.Attribute) and node.attr == "lastrowid":
            found.append("lastrowid")
        elif isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None
            if name in DRIVER_CALLS and not (isinstance(f, ast.Attribute) and name == "connect"
                                             and isinstance(f.value, ast.Name) and f.value.id == "db"):
                found.append(f"a call to {name}")
    return found


def test_no_file_outside_the_connection_module_touches_the_driver():
    assert THE_MODULE in SCANNED and len(SCANNED) > 100                                 # the scan is not empty
    offenders = {str(p.relative_to(REPO_ROOT)): hits for p in SCANNED
                 if p != THE_MODULE and (hits := driver_use(p.read_text(encoding="utf-8")))}
    assert offenders == {}


@pytest.mark.parametrize("source", [
    "import sqlite3",
    "import psycopg",
    "from psycopg import connect",
    "from sqlite3 import connect",
    "x = sqlite3.connect('a.db')",
    "conn.executescript(schema)",
    "cur.lastrowid",
    "conn.cursor()",
    "conn.commit()",
    "connect('a.db')",
    "other.connect('a.db')",
])
def test_the_scanner_catches_each_way_of_reaching_the_driver(source):
    assert driver_use(source)


def test_the_scanner_lets_the_helper_through():
    assert driver_use("conn = db.connect(db_path)\nrows = conn.execute('SELECT 1').fetchall()") == []


def test_the_old_sql_forms_are_gone_from_the_code_and_the_schema():
    text = {p: p.read_text(encoding="utf-8") for p in [*SCANNED, BACKEND_ROOT / "src" / "cytonn_weekly" / "schema.sql"]
            if p != THE_MODULE}
    assert [p.name for p, t in text.items() if re.search(r"INSERT\s+OR\s+(IGNORE|REPLACE)", t, re.I)] == []
    assert [p.name for p, t in text.items() if re.search(r"\bIS\s+\?", t)] == []
    assert "IS NOT DISTINCT FROM" in text[BACKEND_ROOT / "src" / "cytonn_weekly" / "digital_payments" / "review_store.py"]
    assert "ON CONFLICT (name) DO NOTHING" in text[BACKEND_ROOT / "src" / "cytonn_weekly" / "schema.sql"]


def test_the_connection_module_reads_the_new_id_with_returning_and_runs_the_schema_in_one_place():
    text = THE_MODULE.read_text(encoding="utf-8")
    assert "RETURNING" in text and "lastrowid" not in text
    assert text.count(".executescript(") == 1 and "INSERT OR " not in text.upper()


def test_reseeding_leaves_an_edited_section_alone(path):
    sections.init_db(path)
    sections.update_section_config("Equities", current_analyst="A. Analyst", db_path=path)
    sections.init_db(path)                                                              # ON CONFLICT DO NOTHING, not DO UPDATE
    assert sections.get_section_config("Equities", path)["current_analyst"] == "A. Analyst"


# --- which database, and the SQLite floor ---------------------------------------------------------------------------

def test_an_explicit_path_is_sqlite_even_when_a_database_url_is_set(path, monkeypatch):
    monkeypatch.setenv(database.DATABASE_URL_ENV, URL)
    rs.save_review(make_review(), db_path=path)
    assert path.is_file() and rs.load_latest_review(db_path=path) is not None


@pytest.mark.parametrize("call", [
    lambda: database.connect(),
    lambda: database.open_db(),
    lambda: database.init_db(),
    lambda: rs.load_latest_review(),
    lambda: rs.save_review(make_review()),
    lambda: sections.get_section_config("Equities"),
])
def test_no_path_and_a_database_url_selects_postgres_which_waits_for_stage_p2(call, monkeypatch):
    monkeypatch.setenv(database.DATABASE_URL_ENV, URL)
    default = Path(database._DEFAULT_DB)
    with pytest.raises(database.DatabaseNotAvailable) as err:
        call()
    assert "Stage P2" in str(err.value) and database.DATABASE_URL_ENV in str(err.value)
    assert "hunter2" not in str(err.value) and "localhost" not in str(err.value)       # the URL is never echoed
    assert not default.exists()                                                         # and no SQLite file was made instead


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_database_url_is_no_url(blank, monkeypatch):
    monkeypatch.setenv(database.DATABASE_URL_ENV, blank)
    rs.save_review(make_review())                                                       # the default file, which conftest points at a temp file
    assert Path(database._DEFAULT_DB).is_file()


def test_the_postgres_refusal_imports_no_driver():
    # In a fresh interpreter: psycopg is installed here and some pytest plugin imports it, so sys.modules cannot say.
    code = "\n".join([
        "import sys",
        "from cytonn_weekly import db",
        "try:",
        "    db.connect()",
        "except db.DatabaseNotAvailable:",
        "    print('refused')",
        "print('psycopg' in sys.modules, 'sqlite3' in sys.modules)",
    ])
    env = {**os.environ, database.DATABASE_URL_ENV: URL}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=BACKEND_ROOT, check=True).stdout.split()
    assert out == ["refused", "False", "True"]


def test_psycopg_is_not_imported_at_module_level_by_the_connection_module():
    tree = ast.parse(THE_MODULE.read_text(encoding="utf-8"))
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    names = [a.name for n in top if isinstance(n, ast.Import) for a in n.names] + [n.module for n in top if isinstance(n, ast.ImportFrom)]
    assert not [n for n in names if n and n.split(".")[0] == "psycopg"]


def test_the_default_database_is_still_backend_data_app_db():
    env = {k: v for k, v in os.environ.items() if k not in ("CYTONN_DATA_DIR", database.DATABASE_URL_ENV)}
    out = subprocess.run([sys.executable, "-c", "from cytonn_weekly import db; print(db._DEFAULT_DB)"],
                         capture_output=True, text=True, env=env, cwd=BACKEND_ROOT, check=True).stdout.strip()
    assert Path(out) == BACKEND_ROOT / "data" / "app.db"                                # only imported, never opened


def test_the_installed_sqlite_is_new_enough():
    database.check_sqlite_version()
    assert database.MIN_SQLITE == (3, 39, 0)


@pytest.mark.parametrize("found,ok", [((3, 38, 5), False), ((3, 38, 99, 1), False), ((3, 39, 0), True), ((3, 42, 0), True),
                                      ((3, 100, 0), True), ((2, 99, 0), False)])
def test_sqlite_before_3_39_is_refused_with_what_to_do(found, ok):
    if ok:
        database.check_sqlite_version(found)
        return
    with pytest.raises(database.SQLiteTooOld) as err:
        database.check_sqlite_version(found)
    assert ".".join(map(str, found)) in str(err.value) and "3.39 or newer" in str(err.value) and "Use a Python build" in str(err.value)


def test_an_old_sqlite_stops_every_connection(path, monkeypatch):
    monkeypatch.setattr(database.sqlite3, "sqlite_version_info", (3, 38, 5))
    with pytest.raises(database.SQLiteTooOld):
        database.connect(path)
    with pytest.raises(database.SQLiteTooOld):
        rs.save_review(make_review(), db_path=path)
    assert not path.exists()                                                            # refused before any file was made


def test_an_old_sqlite_stops_the_app_from_starting():
    # The check runs when the module is imported, so importing the API in a fresh interpreter on an old SQLite fails with it.
    code = "; ".join(["import sqlite3", "sqlite3.sqlite_version_info = (3, 38, 5)", "import api.main"])
    run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=BACKEND_ROOT)
    assert run.returncode != 0
    assert "SQLiteTooOld" in run.stderr and "SQLite 3.38.5 is too old" in run.stderr and "3.39 or newer" in run.stderr
    ok = subprocess.run([sys.executable, "-c", "import api.main"], capture_output=True, text=True, cwd=BACKEND_ROOT)
    assert ok.returncode == 0, ok.stderr


def test_a_schema_that_fails_closes_the_connection_it_opened(path, monkeypatch):
    closed = []
    real_close = database.Db.close
    monkeypatch.setattr(database.Db, "close", lambda self: (closed.append(self), real_close(self))[1])
    monkeypatch.setattr(database, "_migrate", lambda conn: (_ for _ in ()).throw(RuntimeError("migration failed")))
    with pytest.raises(RuntimeError, match="migration failed"):
        database.open_db(path)
    assert len(closed) == 1                                                             # the one connection open_db made
