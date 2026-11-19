import threading
import time

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly import jobs, report_sections
from cytonn_weekly.digital_payments import review_run
from tests.agent_helpers import agent_for, call, say
from tests.review_helpers import ROWS, TODAY, FakeProvider
from tests.test_runs_api import REAL_DP, finished, start
from tests.weekly_helpers import WEEK

PERIOD = "Week ending 2026-10-02"
EQUITIES = {"section": "equities", "period": PERIOD}


class Gated:
    """A chat model that waits at a gate before each call, so a test can hold an answer open."""

    model = "test-model"

    def __init__(self, inner):
        self.inner, self.gate, self.reached = inner, threading.Event(), threading.Event()

    def converse(self, *args):
        self.reached.set()
        assert self.gate.wait(10), "the test never opened the gate"
        return self.inner.converse(*args)


class Env:
    def __init__(self, tmp_path, *replies, gated=False):
        self.db = tmp_path / "app.db"
        self.agent, self.client_calls = agent_for(*replies)
        self.model = Gated(self.agent) if gated else self.agent
        self.app = create_app(db_path=self.db, load_dotenv=False, inputs_root=tmp_path / "inputs", sources_root=tmp_path / "sources",
                              chat_agent=lambda: self.model)
        self.client = TestClient(self.app)

    def open(self, **body):
        r = self.client.post("/api/jobs", json=body or EQUITIES)
        assert r.status_code == 200, r.text
        return r.json()["job"]["job_id"]

    def say(self, job_id, text="hello"):
        return self.client.post(f"/api/jobs/{job_id}/messages", json={"content": text})

    def messages(self, job_id, after=0):
        return self.client.get(f"/api/jobs/{job_id}/messages", params={"after": after}).json()

    def idle(self, job_id, timeout=10.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            got = self.messages(job_id)
            if got["job"]["status"] != "working":
                return got
            time.sleep(0.01)
        raise AssertionError("the answer did not end")


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path, say("Hello back."))


# --- opening --------------------------------------------------------------------------------------

def test_the_first_open_saves_the_readiness_card_before_the_model_says_anything(env):
    r = env.client.post("/api/jobs", json=EQUITIES)
    assert r.status_code == 200 and r.json()["created"] is True
    job_id = r.json()["job"]["job_id"]
    got = env.messages(job_id)
    assert [(m["role"], m["cards"][0]["type"]) for m in got["messages"]] == [("assistant", "readiness")]
    card = got["messages"][0]["cards"][0]["data"]
    assert card["section"] == "equities" and card["week_ending"] == "2026-10-02"
    assert "equities_workbook" in {e["key"] for e in card["groups"]["needs_analyst"]}
    assert env.client_calls.calls == []   # no model call: code posted it


def test_the_readiness_check_runs_again_now_with_no_model_call(env):
    job_id = env.open()
    got = env.client.get(f"/api/jobs/{job_id}/readiness").json()["readiness"]
    assert got == env.messages(job_id)["messages"][0]["cards"][0]["data"]   # nothing changed since the card was saved
    assert "equities_workbook" in {e["key"] for e in got["groups"]["needs_analyst"]}
    assert env.client_calls.calls == []


def test_the_readiness_check_is_refused_for_a_report_with_no_week(env):
    job_id = env.open(report_type="quarterly", period="Q3'2026", section="equities")
    assert env.client.get(f"/api/jobs/{job_id}/readiness").status_code == 409
    assert env.client.get("/api/jobs/999/readiness").status_code == 404


def test_opening_again_returns_the_same_job_and_adds_no_second_card(env):
    first = env.client.post("/api/jobs", json=EQUITIES).json()
    again = env.client.post("/api/jobs", json=EQUITIES).json()
    assert again["created"] is False and again["job"]["job_id"] == first["job"]["job_id"]
    assert len(env.messages(first["job"]["job_id"])["messages"]) == 1
    assert env.client.get(f"/api/jobs/{first['job']['job_id']}").json()["job"]["status"] == "idle"


def test_a_report_with_no_week_opens_with_no_card(env):
    job_id = env.open(report_type="quarterly", period="Q3'2026", section="equities")
    assert env.messages(job_id)["messages"] == []


def test_opening_refuses_what_a_draft_refuses(env):
    assert env.client.post("/api/jobs", json={"section": "nope", "period": PERIOD}).status_code == 404
    assert env.client.post("/api/jobs", json={"section": "equities", "period": "Week ending 2026-10-03"}).status_code == 422
    stub = report_sections.sections_for("companion", "ssa_eurobonds")[0]
    assert not stub.available
    unavailable = {"report_type": "companion", "kind": "ssa_eurobonds", "period": "Weekly #37.2026", "section": stub.slug}
    assert env.client.post("/api/jobs", json=unavailable).status_code == 409
    assert env.client.get("/api/jobs/999").status_code == 404 and env.client.get("/api/jobs/999/messages").status_code == 404


# --- messages: 202, 409, 429 -------------------------------------------------------------------------

def test_a_message_is_202_and_the_answer_arrives_through_polling(env):
    job_id = env.open()
    r = env.say(job_id, "  What is missing?  ")
    # the scripted answer can finish before the response reads the job, so "idle" is as valid as "working" here
    assert r.status_code == 202 and r.json()["seq"] == 2 and r.json()["job"]["status"] in ("working", "idle")
    got = env.idle(job_id)
    assert [(m["role"], m["content"][:18]) for m in got["messages"][1:]] == [("user", "What is missing?"), ("assistant", "Hello back.")]
    assert [m["seq"] for m in env.messages(job_id, after=2)["messages"]] == [3]   # the poll cursor: only what is new
    assert got["job"]["status"] == "idle" and got["job"]["calls_used"] == 1


def test_a_tool_turn_shows_its_name_and_nothing_else(tmp_path):
    env = Env(tmp_path, call(("inputs_list", {})), say("Done."))
    job_id = env.open()
    env.say(job_id)
    shown = env.idle(job_id)["messages"]
    tool = next(m for m in shown if m["role"] == "tool")
    assert (tool["content"], tool["tool_name"], tool["cards"]) == ("", "inputs_list", None)
    assert set(tool) == {"seq", "role", "content", "tool_name", "cards", "created_at"}   # no tool input, result or usage
    assert not any(m["role"] == "assistant" and not m["content"] and not m["cards"] for m in shown)   # a tools-only model turn has no bubble


def test_a_second_message_while_the_assistant_is_working_is_409_and_saves_nothing(tmp_path):
    env = Env(tmp_path, say("First."), say("Second."), gated=True)
    job_id = env.open()
    assert env.say(job_id, "one").status_code == 202
    assert env.model.reached.wait(10)
    blocked = env.say(job_id, "two")
    assert blocked.status_code == 409 and "still answering" in blocked.json()["detail"]
    assert env.client.get(f"/api/jobs/{job_id}").json()["job"]["status"] == "working"
    assert [m["content"] for m in env.messages(job_id)["messages"] if m["role"] == "user"] == ["one"]
    env.model.gate.set()
    env.idle(job_id)
    assert env.say(job_id, "two").status_code == 202   # free again


def test_an_empty_chat_concurrency_setting_counts_as_unset(monkeypatch):
    from api.chat import DEFAULT_CONCURRENCY, chat_concurrency

    for empty in ("", "  "):
        monkeypatch.setenv("CYTONN_CHAT_CONCURRENCY", empty)
        assert chat_concurrency() == DEFAULT_CONCURRENCY == 2


def test_chat_seats_are_their_own_and_a_full_house_is_429(tmp_path, monkeypatch):
    monkeypatch.setenv("CYTONN_CHAT_CONCURRENCY", "1")
    env = Env(tmp_path, say("A."), say("B."), gated=True)
    a, b = env.open(), env.open(section="fixed_income", period=PERIOD)
    assert env.say(a).status_code == 202 and env.model.reached.wait(10)
    full = env.say(b)
    assert full.status_code == 429 and "busy" in full.json()["detail"]
    assert env.client.get(f"/api/jobs/{b}").json()["job"]["status"] == "idle"   # not left working
    assert [m for m in env.messages(b)["messages"] if m["role"] == "user"] == []   # and its message was not saved
    env.model.gate.set()
    env.idle(a)
    assert env.say(b).status_code == 202   # the seat came back


def test_a_chat_does_not_take_a_drafting_seat(tmp_path, monkeypatch):
    monkeypatch.setenv("CYTONN_DRAFT_CONCURRENCY", "1")
    env = Env(tmp_path, say("A."), gated=True)
    job_id = env.open()
    env.say(job_id)
    assert env.model.reached.wait(10)
    assert env.client.get("/api/sections").json()["drafting_list"] == []   # no seat held, no draft shown
    env.model.gate.set()
    env.idle(job_id)


def test_chat_needs_bedrock_and_says_so_in_local_mode(env, monkeypatch):
    job_id = env.open()
    monkeypatch.setenv("CYTONN_LLM_PROVIDER", "local")
    r = env.say(job_id)
    assert r.status_code == 409 and "Amazon Bedrock" in r.json()["detail"]
    assert env.client_calls.calls == []


def test_a_blank_or_oversized_message_is_refused(env):
    job_id = env.open()
    assert env.say(job_id, "   ").status_code == 422 and env.say(job_id, "x" * 2001).status_code == 422
    assert env.say(job_id, "").status_code == 422


def test_a_model_that_cannot_be_built_ends_the_answer_with_a_sentence_and_an_idle_job(tmp_path):
    client = TestClient(create_app(db_path=tmp_path / "app.db", load_dotenv=False,
                                   chat_agent=lambda: (_ for _ in ()).throw(RuntimeError("secret detail"))))
    job_id = client.post("/api/jobs", json={"section": "equities", "period": "Week ending 2026-10-02"}).json()["job"]["job_id"]
    assert client.post(f"/api/jobs/{job_id}/messages", json={"content": "hi"}).status_code == 202
    deadline = time.monotonic() + 10
    while client.get(f"/api/jobs/{job_id}").json()["job"]["status"] == "working" and time.monotonic() < deadline:
        time.sleep(0.01)
    shown = client.get(f"/api/jobs/{job_id}/messages").json()
    assert shown["job"]["status"] == "idle" and shown["messages"][-1]["content"].startswith("I could not answer")
    assert "secret detail" not in str(shown)


# --- the raise button ------------------------------------------------------------------------------------

def test_raise_budget_works_only_when_the_job_stopped_at_a_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("CYTONN_JOB_CALL_BUDGET", "1")
    env = Env(tmp_path, call(("inputs_list", {})), say("Back again."), gated=True)
    job_id = env.open()
    assert env.client.post(f"/api/jobs/{job_id}/raise-budget").status_code == 409   # idle: not at a budget
    env.say(job_id)
    assert env.model.reached.wait(10)
    assert env.client.post(f"/api/jobs/{job_id}/raise-budget").status_code == 409   # working
    env.model.gate.set()
    stopped = env.idle(job_id)
    assert (stopped["job"]["status"], stopped["job"]["paused_reason"]) == ("paused", "call_budget")
    refused = env.say(job_id, "again")
    assert refused.status_code == 409 and "used up its budget" in refused.json()["detail"]
    raised = env.client.post(f"/api/jobs/{job_id}/raise-budget")
    assert raised.status_code == 200 and raised.json()["job"]["call_budget"] == 1 + jobs.RAISE_CALLS
    assert (raised.json()["job"]["status"], raised.json()["job"]["budget_raises"]) == ("idle", 1)
    assert "raised by" in env.messages(job_id)["messages"][-1]["content"]
    assert env.say(job_id, "again").status_code == 202
    assert env.idle(job_id)["messages"][-1]["content"] == "Back again."
    assert env.client.post(f"/api/jobs/{job_id}/raise-budget").status_code == 409   # a second press with no new stop


def test_a_tool_call_pause_is_not_a_budget_and_a_new_message_goes_on(tmp_path, monkeypatch):
    monkeypatch.setenv("CYTONN_JOB_MAX_TOOL_CALLS", "1")
    env = Env(tmp_path, call(("inputs_list", {}), ("inputs_list", {})), say("Resumed."))
    job_id = env.open()
    env.say(job_id)
    assert env.idle(job_id)["job"]["paused_reason"] == "tool_calls"
    assert env.client.post(f"/api/jobs/{job_id}/raise-budget").status_code == 409
    assert env.say(job_id, "go on").status_code == 202


# --- startup --------------------------------------------------------------------------------------------------

def test_a_job_left_working_is_reset_to_idle_at_startup_with_a_note(tmp_path):
    env = Env(tmp_path)
    job_id = env.open()
    assert jobs.begin(env.db, job_id)   # as if the last process died mid-answer
    other = env.open(section="fixed_income", period=PERIOD)
    jobs.finish(env.db, other, jobs.TOOL_CALLS)
    with TestClient(create_app(db_path=env.db, load_dotenv=False)) as restarted:   # entering it runs the startup hook
        got = restarted.get(f"/api/jobs/{job_id}/messages").json()
        assert got["job"]["status"] == "idle" and got["messages"][-1] == {**got["messages"][-1], "role": "assistant", "content": jobs.RESTART_NOTE}
        assert restarted.get(f"/api/jobs/{other}").json()["job"]["paused_reason"] == "tool_calls"   # a pause is not a leftover


# --- the review card after a draft ---------------------------------------------------------------------------------

def dp_pipeline(monkeypatch):
    monkeypatch.setattr(review_run, "build_digital_payments_review", lambda on_event=None, **_: REAL_DP(
        provider=FakeProvider(), today=TODAY, fetch_table=lambda today: ROWS, on_event=on_event))


def test_a_finished_draft_puts_its_review_summary_in_the_conversation(env, monkeypatch):
    dp_pipeline(monkeypatch)
    job_id = env.open(section="digital_payments", period=PERIOD)
    run_id = start(env.client, report_type="weekly", section="digital_payments", period=PERIOD)
    run = finished(env.client, run_id)
    cards = [m for m in env.messages(job_id)["messages"] if m["cards"]]
    assert [m["cards"][0]["type"] for m in cards] == ["readiness", "review_summary"]   # the card is there the moment the run reads finished
    card = cards[-1]["cards"][0]
    assert card["review_id"] == run["review_id"] and card["data"]["review_id"] == run["review_id"] and card["is_dev_draft"] is False
    assert set(card["data"]["counts"]) == {"flagged", "not_auto_verified", "clean"} and "is saved:" in cards[-1]["content"]
    assert env.client_calls.calls == []   # no model call either


def test_a_draft_of_a_section_nobody_is_chatting_about_adds_nothing_to_other_conversations(env, monkeypatch):
    dp_pipeline(monkeypatch)
    job_id = env.open(section="equities", period=PERIOD)   # a conversation about another section
    finished(env.client, start(env.client, report_type="weekly", section="digital_payments", period=PERIOD))
    assert [m["cards"][0]["type"] for m in env.messages(job_id)["messages"]] == ["readiness"]


def test_a_conversation_opened_after_the_draft_gets_no_card_for_it(env, monkeypatch):
    dp_pipeline(monkeypatch)
    finished(env.client, start(env.client, report_type="weekly", section="digital_payments", period=PERIOD))
    job_id = env.open(section="digital_payments", period=PERIOD)
    assert [m["cards"][0]["type"] for m in env.messages(job_id)["messages"]] == ["readiness"]


def test_a_card_that_cannot_be_saved_never_fails_the_draft(env, monkeypatch):
    dp_pipeline(monkeypatch)
    env.open(section="digital_payments", period=PERIOD)
    real = jobs.add_message
    monkeypatch.setattr(jobs, "add_message", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk")) if k.get("cards") else real(*a, **k))
    assert finished(env.client, start(env.client, report_type="weekly", section="digital_payments", period=PERIOD))["status"] == "finished"
