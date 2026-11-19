"""Draft runs written through to the database (run_store.py, api/runs.py): events as they happen, runs read back after a restart,
queued and running runs marked interrupted at startup, and the Bedrock usage kept against the run.

SQLite in a temp folder, fake providers, no network.  The run tables themselves are in schema.sql and schema_postgres.sql.
"""

import json
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from api.main import create_app
from api.runs import RunRegistry
from cytonn_weekly import db as database
from cytonn_weekly import run_store
from cytonn_weekly.common import run_events as ev
from cytonn_weekly.digital_payments import review_run
from cytonn_weekly.run_store import INTERRUPTED_MESSAGE, RunStore
from tests import test_bedrock_usage as bu
from tests.review_helpers import make_review
from tests.test_runs_api import WEEKLY_DP, GatedProvider, app, client, clock, db, dp_pipeline, finished, start  # noqa: F401 - fixtures and helpers

COUNTS = {"clean": 1, "flagged": 0, "not_auto_verified": 0}
T0 = 1_790_000_000.0


def rows(path, sql, params=()):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def events_of(path, run_id):
    return rows(path, "SELECT * FROM run_events WHERE run_id = ? ORDER BY seq", (run_id,))


def registry_run(registry, section="equities", title="Equities", **kw):
    return registry.start("weekly", "Week ending 2026-10-02", section, title, "Weekly report", T0, **kw)


# --- write-through ---------------------------------------------------------------------------------------------------------

def test_a_finished_run_and_every_event_it_showed_are_in_storage(client, db):
    run_id = start(client, **WEEKLY_DP)
    run = finished(client, run_id)
    assert run["status"] == "finished" and len(run["events"]) > 2
    (row,) = rows(db, "SELECT * FROM draft_runs")
    assert (row["run_id"], row["status"], row["report_type"], row["section"]) == (run_id, "finished", "weekly", "digital_payments")
    assert row["review_id"] == run["review_id"] and row["error"] is None and row["is_dev_draft"] == 0
    assert row["finished_at"] == run["events"][-1]["at"] and row["started_at"]
    stored = events_of(db, run_id)
    assert [(e["seq"], e["kind"], e["label"], e["detail"], e["at"], e["counts"]) for e in run["events"]] == [
        (s["seq"], s["kind"], s["label"], s["detail"], s["event_at"], json.loads(s["counts_json"]) if s["counts_json"] else None)
        for s in stored]


def test_a_run_is_in_storage_while_it_is_still_running(app, db, monkeypatch):
    provider = GatedProvider()
    dp_pipeline(monkeypatch, provider=provider)
    client = TestClient(app)
    run_id = start(client, **WEEKLY_DP)
    try:
        assert provider.entered.wait(timeout=10)
        (row,) = rows(db, "SELECT * FROM draft_runs")
        assert row["status"] == "running" and row["finished_at"] is None and row["review_id"] is None
        saved = [e["kind"] for e in events_of(db, run_id)]
        assert saved[0] == ev.RUN_STARTED and ev.RUN_FINISHED not in saved
        assert saved == [e["kind"] for e in client.get(f"/api/runs/{run_id}").json()["events"]]
    finally:
        provider.release.set()
    assert finished(client, run_id)["status"] == "finished"
    assert rows(db, "SELECT status FROM draft_runs") == [{"status": "finished"}]


def test_a_failed_run_keeps_its_reason(app, db, monkeypatch):
    monkeypatch.setattr(review_run, "build_digital_payments_review", lambda on_event=None: (_ for _ in ()).throw(RuntimeError("boom")))
    client = TestClient(app)
    run = finished(client, start(client, **WEEKLY_DP))
    assert run["status"] == "failed"
    (row,) = rows(db, "SELECT * FROM draft_runs")
    assert row["status"] == "failed" and row["error"] == run["events"][-1]["detail"] and row["finished_at"] == run["events"][-1]["at"]


def test_a_storage_failure_does_not_fail_a_draft_and_is_logged_by_class_only(client, monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise RuntimeError("host db.example.com user postgres")

    monkeypatch.setattr(run_store, "db", SimpleNamespace(open_db=boom))
    with caplog.at_level("WARNING"):
        run = finished(client, start(client, **WEEKLY_DP))
    assert run["status"] == "finished"
    assert "RuntimeError" in caplog.text and "db.example.com" not in caplog.text


# --- reading back ----------------------------------------------------------------------------------------------------------

def test_a_finished_run_and_its_event_replay_come_from_storage_after_a_restart(client, db, clock):
    before = finished(client, start(client, **WEEKLY_DP))
    restarted = TestClient(create_app(db_path=db, load_dotenv=False, clock=clock))   # a new process: nothing in memory
    again = restarted.get(f"/api/runs/{before['run_id']}")
    assert again.status_code == 200 and again.json() == before
    replay = restarted.get(f"/api/runs/{before['run_id']}/events")
    assert [json.loads(m) for m in re.findall(r"^data: (.*)$", replay.text, re.M)] == before["events"]
    assert restarted.get("/api/runs/nope").status_code == 404


def test_a_run_dropped_from_memory_is_read_back_and_a_discarded_one_is_gone(db):
    registry = RunRegistry(keep_ended=0, store=RunStore(db))
    first = registry_run(registry)
    first.record(ev.PIECE_STARTED, "T-bills")
    first.finish(7, COUNTS, False, None)
    second = registry_run(registry, "real_estate", "Real Estate")   # keeps no ended run, so the first is dropped from memory now
    read = registry.get(first.run_id)
    assert read is not first and read.status == "finished" and read.review_id == 7 and read.is_dev_draft is False
    assert [e.to_dict() for e in read.events] == [e.to_dict() for e in first.events]
    registry.discard(second)
    assert registry.get(second.run_id) is None and [r["run_id"] for r in rows(db, "SELECT run_id FROM draft_runs")] == [first.run_id]


def test_a_run_stored_as_running_that_this_process_does_not_hold_reads_as_interrupted(db):
    registry_run(RunRegistry(store=RunStore(db)))
    (row,) = rows(db, "SELECT run_id FROM draft_runs")
    assert RunRegistry(store=RunStore(db)).get(row["run_id"]).status == "interrupted"


# --- a restart ------------------------------------------------------------------------------------------------------------

def test_a_restart_marks_queued_and_running_runs_interrupted_with_a_final_event_that_says_so(db, clock):
    old = RunRegistry(store=RunStore(db))
    queued = registry_run(old, "fixed_income", "Fixed Income", status="queued")
    running = registry_run(old, "equities", "Equities")
    running.record(ev.RUN_STARTED, "Equities")
    done = registry_run(old, "focus", "Focus of the Week")
    done.finish(3, COUNTS, False, None)
    kept = [e.to_dict() for e in done.events]
    with TestClient(create_app(db_path=db, load_dotenv=False, clock=clock)) as restarted:   # entering it runs the startup hook
        for run, last in ((queued, 1), (running, 2)):
            got = restarted.get(f"/api/runs/{run.run_id}").json()
            assert got["status"] == "interrupted"
            final = got["events"][-1]
            assert (final["seq"], final["kind"], final["label"], final["detail"]) == (last, ev.RUN_FAILED, run.section_title, INTERRUPTED_MESSAGE)
        assert restarted.get(f"/api/runs/{done.run_id}").json()["events"] == kept
    by_id = {r["run_id"]: r for r in rows(db, "SELECT * FROM draft_runs")}
    for run in (queued, running):
        row = by_id[run.run_id]
        assert row["status"] == "interrupted" and row["error"] == INTERRUPTED_MESSAGE and row["finished_at"]
    assert by_id[done.run_id]["status"] == "finished"
    assert RunStore(db).interrupt_active() == 0   # nothing is left to mark, so a second start changes nothing


def test_a_start_with_no_runs_stored_marks_nothing_and_a_broken_store_does_not_stop_the_app(tmp_path, monkeypatch):
    with TestClient(create_app(db_path=tmp_path / "fresh.db", load_dotenv=False)) as fresh:
        assert fresh.get("/api/health").status_code == 200
    monkeypatch.setattr(run_store, "db", SimpleNamespace(open_db=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))))
    with TestClient(create_app(db_path=tmp_path / "other.db", load_dotenv=False)) as broken:
        assert broken.get("/api/health").status_code == 200


# --- usage -----------------------------------------------------------------------------------------------------------------

def test_the_usage_of_a_saved_draft_is_kept_against_its_run_and_a_draft_with_none_has_no_row(tmp_path, monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "us.anthropic.claude-test")
    path = tmp_path / "app.db"

    def drafted(on_event=None):
        bu.ask(bu.provider(bu.Client()), 2)
        return make_review()

    monkeypatch.setattr(review_run, "build_digital_payments_review", drafted)
    api = TestClient(create_app(db_path=path, load_dotenv=False))
    first = finished(api, start(api, section="digital_payments"))
    (row,) = rows(path, "SELECT * FROM draft_usage")
    assert (row["run_id"], row["model"], row["calls"], row["input_tokens"], row["output_tokens"], row["calls_without_token_counts"]) == (
        first["run_id"], "us.anthropic.claude-test", 2, 200, 40, 0)
    monkeypatch.setattr(review_run, "build_digital_payments_review", lambda on_event=None: make_review())   # no Bedrock call
    second = finished(api, start(api, section="digital_payments"))
    assert second["status"] == "finished" and [r["run_id"] for r in rows(path, "SELECT run_id FROM draft_usage")] == [first["run_id"]]


# --- the two schema files stay in step ---------------------------------------------------------------------------------------

def columns(sql_file, table):
    text = re.sub(r"--[^\n]*", "", (Path(database.__file__).parent / sql_file).read_text(encoding="utf-8"))
    body = re.search(rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);", text, re.S).group(1)
    return [line.split()[0] for line in body.splitlines() if line.strip() and line.split()[0] not in ("PRIMARY", "UNIQUE", "CHECK")]


def test_sqlite_and_postgres_define_the_same_columns_for_each_new_table():
    for table in ("draft_runs", "run_events", "draft_usage", "report_jobs", "job_messages"):
        assert columns("schema.sql", table) == columns("schema_postgres.sql", table) != [], table
