"""Report jobs and their messages (jobs.py): the settings with their environment overrides, one job per report, period and section,
the limits stored on the job, its status and counters, and messages in order.  SQLite in a temp folder; no model, no network;
the loop that enforces the limits is tested in test_agent_loop.py.
"""

import json
import sqlite3

import pytest

from cytonn_weekly import db as database
from cytonn_weekly import jobs

PERIOD = "Week ending 2026-10-02"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (jobs.MAX_TOOL_CALLS_ENV, jobs.CALL_BUDGET_ENV, jobs.TOKEN_BUDGET_ENV):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "app.db"


def test_the_defaults_are_eight_tool_calls_a_message_and_a_cautious_budget():
    assert jobs.job_settings() == jobs.JobSettings(8, 30, 300_000)


def test_each_setting_can_be_overridden_and_blank_means_the_default(monkeypatch):
    monkeypatch.setenv(jobs.MAX_TOOL_CALLS_ENV, "3")
    monkeypatch.setenv(jobs.CALL_BUDGET_ENV, " 12 ")
    monkeypatch.setenv(jobs.TOKEN_BUDGET_ENV, "")
    assert jobs.job_settings() == jobs.JobSettings(3, 12, 300_000)


@pytest.mark.parametrize("bad", ["0", "-2", "many", "1.5"])
def test_a_bad_value_logs_one_warning_and_the_default_is_used(monkeypatch, caplog, bad):
    monkeypatch.setenv(jobs.CALL_BUDGET_ENV, bad)
    with caplog.at_level("WARNING"):
        assert jobs.job_settings().call_budget == 30
    assert [r.getMessage() for r in caplog.records].count(f"{jobs.CALL_BUDGET_ENV} must be a whole number of 1 or more; the default 30 is used") == 1


def test_a_job_stores_the_limits_in_force_when_it_was_opened_and_keeps_them(db, monkeypatch):
    monkeypatch.setenv(jobs.MAX_TOOL_CALLS_ENV, "5")
    monkeypatch.setenv(jobs.TOKEN_BUDGET_ENV, "1000")
    job = jobs.open_job(db, "weekly", PERIOD, "equities")
    assert (job["max_tool_calls"], job["call_budget"], job["token_budget"]) == (5, 30, 1000)
    assert (job["report_type"], job["period"], job["section"]) == ("weekly", PERIOD, "equities") and job["created_at"]
    monkeypatch.setenv(jobs.MAX_TOOL_CALLS_ENV, "9")   # tuned later: the job keeps what it was opened with
    assert jobs.open_job(db, "weekly", PERIOD, "equities") == job
    assert jobs.open_job(db, "weekly", PERIOD, "fixed_income")["max_tool_calls"] == 9


def test_there_is_one_job_per_report_period_and_section(db):
    keys = [("weekly", PERIOD, "equities"), ("weekly", PERIOD, "fixed_income"), ("weekly", "Week ending 2026-10-09", "equities"),
            ("quarterly", "Q3'2026", "equities")]
    ids = [jobs.open_job(db, *key)["job_id"] for key in keys]
    assert len(set(ids)) == 4
    assert [jobs.open_job(db, *key)["job_id"] for key in keys] == ids


def test_messages_come_back_in_order_with_their_tool_fields(db):
    job_id = jobs.open_job(db, "weekly", PERIOD, "equities")["job_id"]
    other = jobs.open_job(db, "weekly", PERIOD, "fixed_income")["job_id"]
    assert jobs.add_message(db, job_id, "user", "Why is the NASI figure flagged?") == 1
    assert jobs.add_message(db, other, "user", "Another job") == 1   # numbered within its own job
    assert jobs.add_message(db, job_id, "assistant", "Let me look at the review item.") == 2
    assert jobs.add_message(db, job_id, "tool", "item 4", tool_name="get_review_item", tool_result='{"status": "flagged"}') == 3
    got = jobs.messages(db, job_id)
    assert [(m["seq"], m["role"], m["content"], m["tool_name"], m["tool_result"]) for m in got] == [
        (1, "user", "Why is the NASI figure flagged?", None, None),
        (2, "assistant", "Let me look at the review item.", None, None),
        (3, "tool", "item 4", "get_review_item", '{"status": "flagged"}')]
    assert all(m["job_id"] == job_id and m["created_at"] for m in got)
    assert [m["content"] for m in jobs.messages(db, other)] == ["Another job"]


def test_a_message_needs_a_known_role_and_an_existing_job(db):
    job_id = jobs.open_job(db, "weekly", PERIOD, "equities")["job_id"]
    with pytest.raises(ValueError, match="role must be one of"):
        jobs.add_message(db, job_id, "system", "x")
    with pytest.raises(LookupError, match="no job 999"):
        jobs.add_message(db, 999, "user", "x")
    assert jobs.messages(db, job_id) == []


def test_a_new_job_is_idle_with_nothing_used_and_the_chat_columns_round_trip(db):
    job = jobs.open_job(db, "weekly", PERIOD, "equities")
    assert (job["status"], job["paused_reason"], job["calls_used"], job["input_tokens"], job["output_tokens"], job["budget_raises"]) == (
        "idle", None, 0, 0, 0, 0)
    job_id = job["job_id"]
    jobs.add_message(db, job_id, "assistant", "Here.", usage={"model": "m", "input_tokens": 3, "output_tokens": 4},
                     cards=[{"kind": "readiness", "data": {"n": 1}}])
    jobs.add_message(db, job_id, "tool", "lookup", "lookup", "{}", tool_use_id="t1", tool_input={"section": "equities"})
    a, t = jobs.messages(db, job_id)
    assert json.loads(a["usage"]) == {"model": "m", "input_tokens": 3, "output_tokens": 4} and json.loads(a["cards"]) == [{"kind": "readiness", "data": {"n": 1}}]
    assert (t["tool_use_id"], json.loads(t["tool_input"]), t["usage"], t["cards"]) == ("t1", {"section": "equities"}, None, None)


def test_begin_takes_a_job_once_and_finish_gives_it_back_idle_or_paused(db):
    job_id = jobs.open_job(db, "weekly", PERIOD, "equities")["job_id"]
    assert jobs.begin(db, job_id) is True and jobs.begin(db, job_id) is False
    jobs.finish(db, job_id, jobs.CALL_BUDGET)
    assert (jobs.get_job(db, job_id)["status"], jobs.get_job(db, job_id)["paused_reason"]) == ("paused", "call_budget")
    assert jobs.begin(db, job_id) is True and jobs.get_job(db, job_id)["paused_reason"] is None   # a new message resumes it
    jobs.finish(db, job_id)
    assert jobs.get_job(db, job_id)["status"] == "idle"
    with pytest.raises(ValueError, match="unknown pause reason"):
        jobs.finish(db, job_id, "tired")
    with pytest.raises(LookupError, match="no job 999"):
        jobs.get_job(db, 999)


def test_usage_adds_up_one_call_at_a_time(db):
    job_id = jobs.open_job(db, "weekly", PERIOD, "equities")["job_id"]
    jobs.add_usage(db, job_id, 100, 20)
    jobs.add_usage(db, job_id, 0, 0)
    job = jobs.get_job(db, job_id)
    assert (job["calls_used"], job["input_tokens"], job["output_tokens"]) == (2, 100, 20)


def test_raising_a_budget_changes_that_job_only(db):
    a = jobs.open_job(db, "weekly", PERIOD, "equities")["job_id"]
    b = jobs.open_job(db, "weekly", PERIOD, "fixed_income")["job_id"]
    jobs.begin(db, a)
    jobs.finish(db, a, jobs.TOKEN_BUDGET)
    raised = jobs.raise_budget(db, a)
    assert (raised["call_budget"], raised["token_budget"]) == (30 + jobs.RAISE_CALLS, 300_000 + jobs.RAISE_TOKENS)
    assert (raised["status"], raised["paused_reason"], raised["budget_raises"]) == ("idle", None, 1)
    assert (jobs.get_job(db, b)["call_budget"], jobs.get_job(db, b)["budget_raises"]) == (30, 0)
    with pytest.raises(ValueError):   # the pause is gone, so a second press changes nothing
        jobs.raise_budget(db, a)


def test_a_database_made_before_the_chat_columns_gets_them_and_keeps_its_rows(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE report_jobs (job_id INTEGER PRIMARY KEY AUTOINCREMENT, report_type TEXT NOT NULL, period TEXT NOT NULL DEFAULT '', "
        "section TEXT NOT NULL, max_tool_calls INTEGER NOT NULL, call_budget INTEGER NOT NULL, token_budget INTEGER NOT NULL, "
        "created_at TEXT NOT NULL, UNIQUE (report_type, period, section));"
        "CREATE TABLE job_messages (job_id INTEGER NOT NULL, seq INTEGER NOT NULL, role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool')), "
        "content TEXT NOT NULL, tool_name TEXT, tool_result TEXT, created_at TEXT NOT NULL, PRIMARY KEY (job_id, seq));"
        "INSERT INTO report_jobs VALUES (1, 'weekly', 'Week ending 2026-10-02', 'equities', 8, 30, 300000, 'then');"
        "INSERT INTO job_messages VALUES (1, 1, 'user', 'old question', NULL, NULL, 'then');")
    conn.commit()
    conn.close()
    database.init_db(path)
    database.init_db(path)   # idempotent
    job = jobs.open_job(path, "weekly", "Week ending 2026-10-02", "equities")
    assert (job["job_id"], job["created_at"], job["status"], job["calls_used"]) == (1, "then", "idle", 0)
    assert jobs.messages(path, 1)[0]["content"] == "old question" and jobs.messages(path, 1)[0]["cards"] is None
