"""Report jobs and their messages (jobs.py): the settings with their environment overrides, one job per report, period and section,
the limits stored on the job, and messages in order.  SQLite in a temp folder; no model, no network, nothing enforces a limit.
"""

import pytest

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
