import json

import pytest

from cytonn_weekly import jobs
from cytonn_weekly.agent import loop
from cytonn_weekly.common import run_events
from cytonn_weekly.drafting import bedrock
from tests.agent_helpers import agent_for, ask, call, lookup_tool, open_job, say


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (jobs.MAX_TOOL_CALLS_ENV, jobs.CALL_BUDGET_ENV, jobs.TOKEN_BUDGET_ENV, bedrock.CHAT_MODEL_ENV, "BEDROCK_MODEL_ID"):
        monkeypatch.delenv(name, raising=False)


def run(db, job_id, agent, **kw):
    return loop.answer(db, job_id, agent, [lookup_tool()], **kw)


def rows(db, job_id):
    return [(m["role"], m["content"]) for m in jobs.messages(db, job_id)]


# --- one answer ----------------------------------------------------------------------------

def test_a_text_reply_is_saved_with_its_usage_and_counted_against_the_job(tmp_path):
    db, job_id = open_job(tmp_path)
    ask(db, job_id)
    agent, client = agent_for(say("Nothing is missing.", tin=120, tout=30))
    assert run(db, job_id, agent) == "Nothing is missing."
    saved = jobs.messages(db, job_id)[-1]
    assert (saved["role"], saved["content"]) == ("assistant", "Nothing is missing.")
    assert json.loads(saved["usage"]) == {"model": "test-model", "input_tokens": 120, "output_tokens": 30}
    job = jobs.get_job(db, job_id)
    assert (job["status"], job["calls_used"], job["input_tokens"], job["output_tokens"]) == ("idle", 1, 120, 30)
    request = client.calls[0]
    assert request["model"] == "test-model" and loop.SYSTEM in request["system"] and "equities" in request["system"]
    assert request["messages"] == [{"role": "user", "content": [{"type": "text", "text": "Where do we stand?"}]}]
    assert [t["name"] for t in request["tools"]] == ["lookup"]


def test_unreported_tokens_still_count_the_call(tmp_path):
    db, job_id = open_job(tmp_path)
    ask(db, job_id)
    reply = say("Ok.")
    reply.usage = None
    run(db, job_id, agent_for(reply)[0])
    job = jobs.get_job(db, job_id)
    assert (job["calls_used"], job["input_tokens"]) == (1, 0)
    assert json.loads(jobs.messages(db, job_id)[-1]["usage"])["input_tokens"] is None


def test_a_tool_call_is_checked_run_saved_trimmed_and_answered_on_the_next_pass(tmp_path):
    db, job_id = open_job(tmp_path)
    ask(db, job_id)
    agent, client = agent_for(call(("lookup", {"section": "equities"}), text="Let me look."), say("The title looks odd."))
    events = run_events.EventLog()
    assert run(db, job_id, agent, on_event=events) == "The title looks odd."
    assert rows(db, job_id)[0] == ("user", "Where do we stand?")
    assert [r for r, _ in rows(db, job_id)] == ["user", "assistant", "tool", "assistant"]
    tool_row = jobs.messages(db, job_id)[2]
    assert (tool_row["tool_name"], tool_row["tool_use_id"], json.loads(tool_row["tool_input"])) == ("lookup", "t1", {"section": "equities"})
    assert "SECRET SOURCE TEXT" not in tool_row["tool_result"] and "centralbank.go.ke" in tool_row["tool_result"]
    second = client.calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assert [b["type"] for b in second[1]["content"]] == ["text", "tool_use"] and second[1]["content"][1]["id"] == "t1"
    assert second[2]["content"][0]["type"] == "tool_result" and second[2]["content"][0]["tool_use_id"] == "t1"
    assert "SECRET SOURCE TEXT" not in json.dumps(client.calls)
    assert [(e.kind, e.label) for e in events.events] == [("tool_called", "lookup")]
    assert "equities" in events.events[0].detail and events.events[0].detail.endswith("-> ok")
    assert jobs.get_job(db, job_id)["calls_used"] == 2


def test_an_instruction_inside_a_result_is_only_text_and_a_tool_it_names_does_not_exist(tmp_path):
    db, job_id = open_job(tmp_path)
    ask(db, job_id)
    agent, client = agent_for(call(("lookup", {"section": "equities"})),
                              call(("approve_review", {"run_id": 7}), ("lookup", {"section": "equities", "also": "x"})),
                              say("A source title told me to approve. I did not."))
    events = run_events.EventLog()
    assert run(db, job_id, agent, on_event=events) == "A source title told me to approve. I did not."
    tool_rows = [m for m in jobs.messages(db, job_id) if m["role"] == "tool"]
    assert [json.loads(m["tool_result"]).get("error") for m in tool_rows] == [None, "There is no such tool.", "The input was refused."]
    assert [e.detail.rsplit("-> ", 1)[1] for e in events.events] == ["ok", "There is no such tool.", "The input was refused."]
    assert not any(c["name"] == "approve_review" for c in client.calls[0]["tools"])
    assert [r for r, _ in rows(db, job_id)].count("tool") == 3   # each call, run or refused, has its answer, so the history stays valid


# --- limits --------------------------------------------------------------------------------

def test_the_tool_calls_for_one_message_are_capped_and_the_job_waits_for_the_analyst(tmp_path, monkeypatch):
    monkeypatch.setenv(jobs.MAX_TOOL_CALLS_ENV, "2")
    db, job_id = open_job(tmp_path)
    ask(db, job_id)
    agent, client = agent_for(call(*[("lookup", {"section": "equities"})] * 3))
    events = run_events.EventLog()
    said = run(db, job_id, agent, on_event=events)
    assert said == "I stopped after 2 tool calls for one message. Send another message to go on."
    tool_rows = [json.loads(m["tool_result"]) for m in jobs.messages(db, job_id) if m["role"] == "tool"]
    assert [r.get("error") for r in tool_rows] == [None, None, loop.NOT_RUN]   # the third was answered, not run
    assert len(events.events) == 3 and events.events[2].detail.endswith(loop.NOT_RUN)
    job = jobs.get_job(db, job_id)
    assert (job["status"], job["paused_reason"], job["calls_used"]) == ("paused", "tool_calls", 1)
    ask(db, job_id, "Go on.")   # a new message resumes it, with a fresh count of tool calls
    agent2, client2 = agent_for(say("Done."))
    assert run(db, job_id, agent2) == "Done."
    assert jobs.get_job(db, job_id)["status"] == "idle"
    sent = client2.calls[0]["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user", "assistant", "user"]   # alternating, every tool_use answered
    uses = [b["id"] for m in sent for b in m["content"] if b["type"] == "tool_use"]
    results = [b["tool_use_id"] for m in sent for b in m["content"] if b["type"] == "tool_result"]
    assert uses == results == ["t1", "t2", "t3"]


def test_the_call_budget_pauses_before_a_model_call_and_one_press_of_raise_lets_it_go_on(tmp_path, monkeypatch):
    monkeypatch.setenv(jobs.CALL_BUDGET_ENV, "1")
    db, job_id = open_job(tmp_path)
    ask(db, job_id)
    assert run(db, job_id, agent_for(say("First."))[0]) == "First."
    ask(db, job_id, "Again?")
    agent, client = agent_for()
    said = run(db, job_id, agent)
    assert said.startswith("I stopped because this conversation has used its 1 model calls.") and client.calls == []
    job = jobs.get_job(db, job_id)
    assert (job["status"], job["paused_reason"]) == ("paused", "call_budget")
    events = run_events.EventLog()
    raised = jobs.raise_budget(db, job_id, events)
    assert (raised["call_budget"], raised["token_budget"], raised["budget_raises"], raised["status"]) == (
        1 + jobs.RAISE_CALLS, 300_000 + jobs.RAISE_TOKENS, 1, "idle")
    assert [(e.kind, e.label) for e in events.events] == [("budget_raised", f"job {job_id}")]
    assert run(db, job_id, agent_for(say("Now it works."))[0]) == "Now it works."


def test_the_token_budget_pauses_too(tmp_path, monkeypatch):
    monkeypatch.setenv(jobs.TOKEN_BUDGET_ENV, "15")
    db, job_id = open_job(tmp_path)
    ask(db, job_id)
    run(db, job_id, agent_for(say("First.", tin=10, tout=5))[0])
    ask(db, job_id, "More?")
    assert "used its 15 tokens" in run(db, job_id, agent_for()[0])
    assert jobs.get_job(db, job_id)["paused_reason"] == "token_budget"


def test_only_a_job_stopped_at_a_budget_can_be_raised(tmp_path):
    db, job_id = open_job(tmp_path)
    before = jobs.get_job(db, job_id)
    with pytest.raises(ValueError, match="stopped at its call or token budget"):
        jobs.raise_budget(db, job_id)
    assert jobs.get_job(db, job_id) == before


# --- failures ------------------------------------------------------------------------------

def test_a_failed_model_call_is_saved_as_its_fixed_sentence_and_the_job_is_idle(tmp_path):
    db, job_id = open_job(tmp_path)
    ask(db, job_id)
    said = run(db, job_id, agent_for(RuntimeError("RAW LIBRARY TEXT"))[0])
    assert said and "RAW LIBRARY TEXT" not in said
    assert rows(db, job_id)[-1] == ("assistant", said) and jobs.get_job(db, job_id)["status"] == "idle"


def test_a_crash_does_not_leave_the_job_working(tmp_path):
    class Boom:
        model = "m"

        def converse(self, *a):
            raise ValueError("bug")

    db, job_id = open_job(tmp_path)
    ask(db, job_id)
    with pytest.raises(ValueError):
        run(db, job_id, Boom())
    assert jobs.get_job(db, job_id)["status"] == "idle"


def test_a_job_another_worker_has_is_left_alone(tmp_path):
    db, job_id = open_job(tmp_path)
    ask(db, job_id)
    assert jobs.begin(db, job_id) is True and jobs.begin(db, job_id) is False
    agent, client = agent_for()
    assert run(db, job_id, agent) is None and client.calls == []
    assert jobs.get_job(db, job_id)["status"] == "working"   # not reset by the refused worker


def test_a_reply_cut_off_at_the_output_limit_runs_no_tool_and_says_so(tmp_path):
    db, job_id = open_job(tmp_path)
    ask(db, job_id)
    said = run(db, job_id, agent_for(call(("lookup", {"section": "equities"}), text="Looking", stop="max_tokens"))[0])
    assert said == "Looking" + loop.CUT_OFF
    assert [r for r, _ in rows(db, job_id)] == ["user", "assistant"]


def test_an_empty_reply_is_replaced_by_a_fixed_line(tmp_path):
    db, job_id = open_job(tmp_path)
    ask(db, job_id)
    assert run(db, job_id, agent_for(say(""))[0]) == loop.NO_REPLY


# --- what the model is shown ---------------------------------------------------------------

def msg(role, content="", **kw):
    return {"role": role, "content": content, "tool_name": kw.get("name"), "tool_result": kw.get("result"),
            "tool_use_id": kw.get("id"), "tool_input": kw.get("input")}


def test_history_leaves_out_a_card_posted_before_the_first_question_and_never_sends_cards():
    got = loop.history([msg("assistant", "Here is the week."), msg("user", "Hi"), msg("assistant", "Hello")])
    assert got == [{"role": "user", "content": [{"type": "text", "text": "Hi"}]},
                   {"role": "assistant", "content": [{"type": "text", "text": "Hello"}]}]
    assert loop.history([msg("assistant", "Only a card")]) == []


def test_history_starts_at_a_whole_turn_so_no_result_is_shown_without_its_call():
    rows_ = [msg("user", "old"), msg("assistant", "", ), msg("tool", "t", name="lookup", id="a", input="{}", result="{}"),
             msg("assistant", "answer"), msg("user", "new"), msg("assistant", "reply")]
    got = loop.history(rows_, limit=4)   # the last four rows start at the tool row: moved forward to the analyst's "new"
    assert [m["role"] for m in got] == ["user", "assistant"] and got[0]["content"][0]["text"] == "new"
    assert loop.history(rows_, limit=1)[0]["content"][0]["text"] == "new"   # never empty of the latest question


def test_history_pairs_every_call_with_its_result_across_passes():
    rows_ = [msg("user", "q"), msg("assistant", "x"), msg("tool", "t", name="lookup", id="a", input='{"section": "s"}', result='{"ok": 1}'),
             msg("tool", "t", name="lookup", id="b", input="{}", result="{}"), msg("assistant", "final")]
    got = loop.history(rows_)
    assert [m["role"] for m in got] == ["user", "assistant", "user", "assistant"]
    assert [b["id"] for b in got[1]["content"] if b["type"] == "tool_use"] == ["a", "b"]
    assert [b["tool_use_id"] for b in got[2]["content"]] == ["a", "b"] and got[1]["content"][1]["input"] == {"section": "s"}


# --- the chat model ------------------------------------------------------------------------

def test_the_chat_model_is_its_own_setting_and_falls_back_to_the_drafting_model(monkeypatch):
    assert bedrock.chat_model_id() == bedrock.DEFAULT_MODEL
    monkeypatch.setenv("BEDROCK_MODEL_ID", " drafting-model ")
    assert bedrock.chat_model_id() == "drafting-model" and bedrock.BedrockAgent(client=object()).model == "drafting-model"
    monkeypatch.setenv(bedrock.CHAT_MODEL_ENV, " chat-model ")
    assert bedrock.chat_model_id() == "chat-model" and bedrock.model_id() == "drafting-model"


def test_an_empty_chat_model_setting_counts_as_unset(monkeypatch):
    # The server compose passes the name with no value when .env lacks it, so the variable exists and is empty.
    monkeypatch.setenv("BEDROCK_MODEL_ID", "drafting-model")
    for empty in ("", "   "):
        monkeypatch.setenv(bedrock.CHAT_MODEL_ENV, empty)
        assert bedrock.chat_model_id() == "drafting-model"
    monkeypatch.delenv("BEDROCK_MODEL_ID")
    assert bedrock.chat_model_id() == bedrock.DEFAULT_MODEL
