import logging
import time
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly.digital_payments import review_run
from cytonn_weekly.review import store as review_store
from cytonn_weekly.narrative import bedrock_provider as bp
from tests.review_helpers import make_review

VAR = "CYTONN_BEDROCK_MAX_CALLS_PER_DRAFT"


class Client:
    """``messages.create`` answering with plain text and the given token counts; remembers each call."""

    def __init__(self, usage=NS(input_tokens=100, output_tokens=20)):
        self.calls, self.messages, self.usage = [], self, usage

    def create(self, **kw):
        self.calls.append(kw)
        return NS(stop_reason="end_turn", content=[NS(type="text", text="ok")], usage=self.usage)


@pytest.fixture(autouse=True)
def aws(monkeypatch):
    monkeypatch.delenv(VAR, raising=False)
    monkeypatch.setenv("AWS_REGION", "us-east-1")


def provider(client):
    return bp.BedrockNarrativeProvider(client=client, sleep=lambda s: None)


def ask(p, n=1):
    for _ in range(n):
        p.complete("system", "prompt", max_tokens=10)


# --- the totals -----------------------------------------------------------------------------------------------------

def test_an_instance_adds_up_its_calls_and_tokens():
    p = provider(Client())
    ask(p, 3)
    assert (p.usage.calls, p.usage.input_tokens, p.usage.output_tokens, p.usage.unreported) == (3, 300, 60, 0)


def test_a_reply_with_no_token_counts_is_a_call_counted_as_unreported():
    p = provider(Client(usage=None))
    ask(p, 2)
    assert (p.usage.calls, p.usage.input_tokens, p.usage.output_tokens, p.usage.unreported) == (2, 0, 0, 2)
    assert bp.usage_record(p.usage, "m") == {"model": "m", "calls": 2, "input_tokens": 0, "output_tokens": 0,
                                             "calls_without_token_counts": 2}


def test_a_draft_tracker_sums_every_instance_created_in_it():
    one, two = provider(Client()), provider(Client(NS(input_tokens=5, output_tokens=1)))
    with bp.track_usage() as used:
        ask(one, 2)
        ask(two, 1)
    assert (used.calls, used.input_tokens, used.output_tokens) == (3, 205, 41)
    assert bp.current_usage.get() is None                      # a later call outside the draft is not added to it
    ask(one)
    assert used.calls == 3 and one.usage.calls == 3


def test_the_record_holds_tokens_and_calls_only():
    rec = bp.usage_record(bp.Usage(calls=4, input_tokens=10, output_tokens=2), "us.anthropic.claude-sonnet-4-6")
    assert rec == {"model": "us.anthropic.claude-sonnet-4-6", "calls": 4, "input_tokens": 10, "output_tokens": 2}


# --- the cap --------------------------------------------------------------------------------------------------------

def test_the_default_cap_is_sixty():
    assert bp.max_calls() == 60


@pytest.mark.parametrize("raw", ["0", "-3", "many", "2.5"])
def test_a_bad_cap_uses_the_default_and_warns_once_by_name(monkeypatch, caplog, raw):
    monkeypatch.setenv(VAR, raw)
    with caplog.at_level(logging.WARNING):
        assert bp.max_calls() == 60
    assert [r.getMessage() for r in caplog.records if VAR in r.getMessage()] == [
        f"{VAR} must be a whole number of 1 or more; the default 60 is used"]


def test_the_call_after_the_limit_is_refused_with_a_sentence_and_makes_no_request(monkeypatch):
    monkeypatch.setenv(VAR, "2")
    client = Client()
    p = provider(client)
    ask(p, 2)
    with pytest.raises(bp.BedrockError) as err:
        ask(p)
    assert str(err.value) == bp.CALL_LIMIT.format(n=2, var=VAR) and "limit of 2 Amazon Bedrock calls" in str(err.value)
    assert len(client.calls) == 2 and p.usage.calls == 2 and p.requests == 2    # the refused call is not counted


def test_the_cap_is_the_whole_drafts_across_its_instances(monkeypatch):
    monkeypatch.setenv(VAR, "3")
    first, second = Client(), Client()
    with bp.track_usage() as used:
        ask(provider(first), 2)
        ask(provider(second), 1)
        with pytest.raises(bp.BedrockError):
            ask(provider(second))                               # a fresh instance, but the draft is at its limit
    assert len(first.calls) + len(second.calls) == 3 and used.calls == 3


def test_a_retry_of_one_call_is_not_a_second_call(monkeypatch):
    monkeypatch.setenv(VAR, "1")
    monkeypatch.setenv("CYTONN_BEDROCK_RETRIES", "3")
    monkeypatch.setattr(bp, "_cool_until", 0.0)
    answers = [type("Throttle", (Exception,), {"status_code": 429})(), None]

    class Flaky(Client):
        def create(self, **kw):
            if answers[0] is not None:
                raise answers.pop(0)
            return super().create(**kw)

    client = Flaky()
    p = provider(client)
    ask(p)                                                      # throttled once, then answered: one call
    assert p.usage.calls == 1 and len(client.calls) == 1


def test_a_refused_call_surfaces_as_the_runs_failure_with_nothing_saved(monkeypatch, tmp_path):
    monkeypatch.setenv(VAR, "1")
    db = tmp_path / "app.db"

    def build(on_event=None):
        ask(provider(Client()), 2)

    monkeypatch.setattr(review_run, "build_digital_payments_review", build)
    api = TestClient(create_app(db_path=db, load_dotenv=False))
    run_id = api.post("/api/runs", json={"section": "digital_payments", "report_type": "weekly"}).json()["run_id"]
    run = wait(api, run_id)
    assert run["status"] == "failed" and bp.CALL_LIMIT.format(n=1, var=VAR) in run["events"][-1]["detail"]
    assert review_store.load_latest_review(db_path=db) is None


# --- what is saved --------------------------------------------------------------------------------------------------

def wait(api, run_id):
    for _ in range(300):
        run = api.get(f"/api/runs/{run_id}").json()
        if run["status"] in ("finished", "failed"):
            return run
        time.sleep(0.02)
    raise AssertionError("the run did not end")


def test_a_saved_draft_records_its_usage_and_one_with_no_bedrock_call_records_none(monkeypatch, tmp_path):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "us.anthropic.claude-test")
    db = tmp_path / "app.db"

    def drafted(on_event=None):
        ask(provider(Client()), 2)
        ask(provider(Client(NS(input_tokens=1, output_tokens=1))), 1)
        return make_review()

    monkeypatch.setattr(review_run, "build_digital_payments_review", drafted)
    api = TestClient(create_app(db_path=db, load_dotenv=False))
    assert wait(api, api.post("/api/runs", json={"section": "digital_payments"}).json()["run_id"])["status"] == "finished"
    saved = review_store.load_latest_review(db_path=db)
    assert saved.section["usage"] == {"model": "us.anthropic.claude-test", "calls": 3, "input_tokens": 201, "output_tokens": 41}

    monkeypatch.setattr(review_run, "build_digital_payments_review", lambda on_event=None: make_review())
    assert wait(api, api.post("/api/runs", json={"section": "digital_payments"}).json()["run_id"])["status"] == "finished"
    assert "usage" not in review_store.load_latest_review(db_path=db).section


def test_the_synchronous_digital_payments_route_records_usage_too(monkeypatch, tmp_path):
    db = tmp_path / "app.db"

    def drafted(on_event=None):
        ask(provider(Client()), 1)
        return make_review()

    monkeypatch.setattr(review_run, "build_digital_payments_review", drafted)
    api = TestClient(create_app(db_path=db, load_dotenv=False))
    assert api.post("/api/reviews/draft").status_code == 200
    assert review_store.load_latest_review(db_path=db).section["usage"]["calls"] == 1
