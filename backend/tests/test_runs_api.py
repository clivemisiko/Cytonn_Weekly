"""Draft runs through the review API: POST /api/runs, GET /api/runs/{id}, GET /api/runs/{id}/events.

A run is the draft route's own draft, started in a worker thread and reported as it
happens.  Drafts run the real pipelines on fake edges (tests/review_helpers.py,
section_helpers.py, periodic_helpers.py); the database is a temp file; nothing waits on a
real clock except the short polls for a worker thread to end.
"""

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from api.main import create_app, failure_message
from api.runs import RunRegistry
from cytonn_weekly.common import run_events as ev
from cytonn_weekly.digital_payments import review_run, review_store
from cytonn_weekly.equities import review_run as eq_run
from cytonn_weekly.focus import review_run as focus_run
from cytonn_weekly.periodic import (
    digital_payments as p_dp,
    equities as p_eq,
    fixed_income as p_fi,
    global_markets as p_gm,
    kenya_macro as p_km,
    real_estate as p_re,
    ssa as p_ssa,
)
from cytonn_weekly.periodic import executive_summary
from cytonn_weekly.real_estate import review_run as re_run
from tests import periodic_helpers as ph
from tests import section_helpers as sh
from tests.review_helpers import ROWS, TODAY, FakeProvider, LocalFakeProvider

REAL_DP = review_run.build_digital_payments_review  # captured before any test patches it
REAL_EQ = eq_run.build_equities_review
Q3 = {"report_type": "quarterly", "period": "Q3'2026"}
WEEKLY_DP = {"report_type": "weekly", "section": "digital_payments"}
PERIODIC = [(p_gm, "build_global_markets_review", ph.global_markets_review), (p_ssa, "build_ssa_review", ph.ssa_review),
            (p_km, "build_kenya_macro_review", ph.kenya_macro_review),
            (p_fi, "build_fixed_income_review", ph.fixed_income_review), (p_eq, "build_equities_review", ph.equities_review),
            (p_re, "build_real_estate_review", ph.real_estate_review),
            (p_dp, "build_digital_payments_review", ph.digital_payments_review)]


class Clock:
    def __init__(self, t: float = 1_790_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


class GatedProvider(FakeProvider):
    """Drafts the highlights, then waits at the outlook until released: a run caught mid-flight."""

    def __init__(self):
        self.entered, self.release = threading.Event(), threading.Event()

    def draft_outlook(self, table_stats, highlights):
        self.entered.set()
        assert self.release.wait(timeout=10)
        return super().draft_outlook(table_stats, highlights)


def dp_pipeline(monkeypatch, provider=None):
    """Weekly Digital Payments: the real pipeline, a fake provider, fixed price rows (with or without an observer)."""
    monkeypatch.setattr(review_run, "build_digital_payments_review", lambda on_event=None: REAL_DP(
        provider=provider or FakeProvider(), today=TODAY, fetch_table=lambda today: ROWS, on_event=on_event))


@pytest.fixture
def db(tmp_path):
    return tmp_path / "app.db"


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def app(db, clock, monkeypatch):
    dp_pipeline(monkeypatch)
    monkeypatch.setattr(eq_run, "build_equities_review", lambda on_event=None: sh.equities_review(on_event=on_event))
    monkeypatch.setattr(re_run, "build_real_estate_review", lambda on_event=None: sh.real_estate_review(on_event=on_event))
    monkeypatch.setattr(focus_run, "build_focus_review",
                        lambda topic, on_event=None: sh.focus_review(topic=topic, on_event=on_event))
    for module, name, builder in PERIODIC:
        monkeypatch.setattr(module, name, lambda ctx, on_event=None, _b=builder: _b(ctx, on_event=on_event))
    return create_app(db_path=db, load_dotenv=False, clock=clock)


@pytest.fixture
def client(app):
    return TestClient(app)


def start(client, **body):
    r = client.post("/api/runs", json=body)
    assert r.status_code == 202, r.text
    assert set(r.json()) == {"run_id"}
    return r.json()["run_id"]


def finished(client, run_id, timeout=20.0):
    """The run once its worker thread has ended (a short poll: the fakes finish in milliseconds)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.01)
    raise AssertionError(f"run {run_id} did not end within {timeout}s")


def run_to_end(client, **body):
    return finished(client, start(client, **body))


def kinds(run):
    return [e["kind"] for e in run["events"]]


def parse_sse(text):
    """[(event name, data dict)] of each event in a stream body, and its comment lines."""
    events, comments = [], []
    for chunk in text.split("\n\n"):
        lines = [line for line in chunk.split("\n") if line]
        if not lines:
            continue
        if all(line.startswith(":") for line in lines):
            comments += lines
            continue
        name = next(line[len("event: "):] for line in lines if line.startswith("event: "))
        data = next(line[len("data: "):] for line in lines if line.startswith("data: "))
        events.append((name, json.loads(data)))
    return events, comments


def approve(client, run_id):
    review = client.post(f"/api/reviews/{run_id}/accept-clean").json()
    for item in review["review_items"]:
        if item["resolution"] is None:
            client.patch(f"/api/reviews/{run_id}/items/{item['index']}", json={"resolution": "accept"})
    assert client.post(f"/api/reviews/{run_id}/decide", json={"decision": "approved"}).status_code == 200


# ---------------------------------------------------------------------------
# A run's events
# ---------------------------------------------------------------------------

def test_a_weekly_digital_payments_run_emits_its_events_in_a_valid_order(client, db):
    run = run_to_end(client, **WEEKLY_DP)
    events = run["events"]
    assert kinds(run)[0] == "run_started" and kinds(run)[-1] == "run_finished"
    assert kinds(run).count("run_started") == 1 and kinds(run).count("run_finished") == 1 and "run_failed" not in kinds(run)
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert all(e["kind"] in ev.KINDS for e in events)
    assert [e["at"] for e in events] == sorted(e["at"] for e in events) and all(e["at"].endswith("+00:00") for e in events)
    # every source_started is followed by exactly one source_finished or source_failed with the same label
    started = [(i, e["label"]) for i, e in enumerate(events) if e["kind"] == "source_started"]
    assert started
    for i, label in started:
        closing = [e for e in events[i + 1:] if e["label"] == label and e["kind"] in ("source_finished", "source_failed")]
        assert len(closing) == 1, label
    # the run's own counts are the saved review's items per status
    assert run["status"] == "finished" and run["section"] == "digital_payments" and run["report_type"] == "weekly"
    assert run["period"] == "" and run["section_title"] == "Digital Payments"
    review = review_store.load_review(run["review_id"], db_path=db)
    final = events[-1]
    assert final["counts"] == ev.review_counts(review) and final["detail"] is None
    assert sum(final["counts"].values()) == len(review.review_items) > 0
    assert client.get("/api/sections").json()["drafting"] is None  # the draft slot is free again


def test_the_review_a_run_saves_equals_the_one_the_draft_route_saves(client, db):
    """Same builder, same stamp, same save: field for field, apart from ids and timestamps."""
    for body, path in [(WEEKLY_DP, "/api/reviews/draft"), ({"section": "equities"}, "/api/sections/equities/draft"),
                       ({"section": "fixed_income", **Q3}, "/api/sections/fixed_income/draft"),
                       ({"section": "focus", "topic": "SSA Eurobonds performance"}, "/api/sections/focus/draft")]:
        via_run = run_to_end(client, **body)
        assert via_run["status"] == "finished", via_run
        direct = client.post(path, json={k: v for k, v in body.items() if k != "section"} or None)
        assert direct.status_code == 200, direct.text
        a = review_store.load_review(via_run["review_id"], db_path=db)
        b = review_store.load_review(direct.json()["run_id"], db_path=db)
        assert a.run_id != b.run_id
        assert a.section == b.section
        assert [i.to_dict() for i in a.review_items] == [i.to_dict() for i in b.review_items]
        assert (a.report_type, a.period, a.decision, a.decided_at) == (b.report_type, b.period, b.decision, b.decided_at)
        # ... and so the API serves the two identically, apart from the review's id
        served = client.get(f"/api/reviews/{a.run_id}").json()
        assert {**served, "run_id": None} == {**direct.json(), "run_id": None}


def test_a_blocked_stub_part_is_skipped_with_its_blocked_reason(client):
    run = run_to_end(client, section="fixed_income", **Q3)
    skipped = {e["label"]: e["detail"] for e in run["events"] if e["kind"] == "part_skipped"}
    assert skipped["T-Bills primary auctions over the period"] == p_fi.TBILLS_BLOCKED_REASON
    assert skipped["Kenya Eurobonds Performance"] == p_fi.EUROBONDS_BLOCKED_REASON
    assert run["status"] == "finished" and run["period"] == "Q3'2026" and run["report_title"]


def test_a_source_that_fails_outright_fails_the_run_as_the_pipeline_does(client, db, monkeypatch):
    """Weekly Equities with the afx fetch broken (not an outage): the builder raises, so the run ends run_failed
    and nothing is saved."""

    def down():
        raise RuntimeError("afx listing page did not parse")

    monkeypatch.setattr(eq_run, "build_equities_review", lambda on_event=None: REAL_EQ(
        provider=sh.FakeNarrativeProvider(), today=sh.TODAY, fetch_market=down, on_event=on_event))
    run = run_to_end(client, section="equities")
    assert kinds(run) == ["run_started", "source_started", "source_failed", "run_failed"]
    assert run["events"][2]["detail"] == "RuntimeError: afx listing page did not parse"
    assert run["events"][3]["detail"] == "RuntimeError: afx listing page did not parse"
    assert "Traceback" not in json.dumps(run) and 'File "' not in json.dumps(run)
    assert run["status"] == "failed" and run["review_id"] is None and run["is_dev_draft"] is None
    assert review_store.load_latest_review("equities", db_path=db) is None
    assert client.get("/api/sections").json()["drafting"] is None  # a failed run frees the draft slot
    assert client.post("/api/sections/real_estate/draft").status_code == 200


def test_afx_down_still_finishes_the_run_and_saves_a_review_without_its_tables(client, db, monkeypatch):
    def down():
        raise ConnectionError("afx.kwayisi.org did not answer")

    monkeypatch.setattr(eq_run, "build_equities_review", lambda on_event=None: REAL_EQ(
        provider=sh.FakeNarrativeProvider(), today=sh.TODAY, fetch_market=down, on_event=on_event))
    run = run_to_end(client, section="equities")
    assert kinds(run)[:3] == ["run_started", "source_started", "source_failed"]
    assert kinds(run)[-1] == "run_finished" and run["status"] == "finished"
    saved = review_store.load_latest_review("equities", db_path=db)
    assert saved is not None and saved.run_id == run["review_id"]
    kinds_by_id = {b["id"]: b["kind"] for b in saved.section["blocks"]}
    assert [kinds_by_id[i] for i in ("indices", "gainers", "losers")] == ["unavailable"] * 3
    # the run's counts are still the saved review's own
    assert run["events"][-1]["counts"] == ev.review_counts(saved)


def test_a_source_failure_the_pipeline_absorbs_still_ends_in_run_finished(client, db):
    """Weekly Equities with one share page timed out, and Q3 Fixed Income with last year's PDFs missing."""
    run = run_to_end(client, section="equities")
    failed = [e for e in run["events"] if e["kind"] == "source_failed"]
    assert [(e["label"], e["detail"]) for e in failed] == [("afx.kwayisi.org: KCB share page", "timeout")]
    assert kinds(run)[-1] == "run_finished" and run["status"] == "finished"

    run = run_to_end(client, section="fixed_income", **Q3)
    assert any(e["kind"] == "source_failed" and e["label"].startswith("CBK results PDF dated") for e in run["events"])
    assert kinds(run)[-1] == "run_finished" and run["events"][-1]["counts"]["flagged"] > 0
    assert review_store.load_review(run["review_id"], db_path=db).by_status("flagged")


def test_an_executive_summary_run_is_only_its_start_and_its_end(client):
    """Before the approvals it fails with the pipeline's own message; once approved it is composed in one step."""
    run = run_to_end(client, section="executive_summary", **Q3)
    assert kinds(run) == ["run_started", "run_failed"] and run["status"] == "failed"
    assert "Still to approve" in run["events"][-1]["detail"] and "Fixed Income (not drafted)" in run["events"][-1]["detail"]
    for slug in ["global_markets", "ssa", "kenya_macro", "fixed_income", "equities", "real_estate", "digital_payments"]:
        approve(client, run_to_end(client, section=slug, **Q3)["review_id"])
    run = run_to_end(client, section="executive_summary", **Q3)
    assert kinds(run) == ["run_started", "run_finished"] and run["status"] == "finished"
    assert sum(run["events"][-1]["counts"].values()) > 0


def test_company_updates_runs_with_no_provider_and_no_draft_slot(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    run = run_to_end(client, section="company_updates", text="Investment Updates: demo.", **Q3)
    assert kinds(run) == ["run_started", "run_finished"]
    assert run["events"][-1]["counts"] == {"clean": 0, "flagged": 0, "not_auto_verified": 1}


def test_a_development_provider_run_is_reported_as_a_dev_draft(client, db, monkeypatch):
    run = run_to_end(client, **WEEKLY_DP)
    assert run["is_dev_draft"] is False and run["dev_mode_label"] is None

    dp_pipeline(monkeypatch, provider=LocalFakeProvider())
    run = run_to_end(client, **WEEKLY_DP)
    assert run["is_dev_draft"] is True and "NOT FOR PUBLICATION" in run["dev_mode_label"]
    # exactly what the serializer says of the saved review
    served = client.get(f"/api/reviews/{run['review_id']}").json()
    assert served["is_dev_draft"] is True and served["dev_mode_label"] == run["dev_mode_label"]


def test_a_failure_message_carries_no_traceback_and_no_secret(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-0123456789abcdef")
    message = failure_message(RuntimeError("401 for key sk-test-0123456789abcdef\n  at line 3"))
    assert message == "RuntimeError: 401 for key [redacted] at line 3"
    # a ValueError is the pipeline talking to the coordinator: its message stands alone, as the draft route shows it
    assert failure_message(ValueError("the topic is 900 characters")) == "the topic is 900 characters"
    assert failure_message(executive_summary.SectionsNotApproved(["Equities (not drafted)"])).startswith(
        "The Executive Summary is composed from approved sections only.")


# ---------------------------------------------------------------------------
# Starting a run: the same refusals as the draft route
# ---------------------------------------------------------------------------

def test_the_period_rules_apply_to_a_run_exactly_as_to_the_draft_route(client):
    for period in ["Q2'2026", "Q4'2026", "nonsense", None]:
        body = {"report_type": "quarterly", "period": period}
        direct = client.post("/api/sections/equities/draft", json=body)
        as_run = client.post("/api/runs", json={**body, "section": "equities"})
        assert direct.status_code == as_run.status_code == 422, period
        assert direct.json()["detail"] == as_run.json()["detail"]
    assert "H1" in client.post("/api/runs", json={"report_type": "quarterly", "period": "Q2'2026",
                                                  "section": "equities"}).json()["detail"]
    # a period typed loosely is normalized, and the review is saved under the normalized label
    run = run_to_end(client, section="equities", report_type="quarterly", period="q3 2026")
    assert run["period"] == "Q3'2026" and run["status"] == "finished"
    assert client.get(f"/api/reviews/{run['review_id']}").json()["period"] == "Q3'2026"
    direct = client.post("/api/sections/equities/draft", json={"report_type": "quarterly", "period": "q3 2026"})
    assert direct.json()["period"] == "Q3'2026"


def test_a_run_is_refused_for_the_reasons_a_draft_is(client, monkeypatch):
    cases = [
        ({"section": "no_such_section"}, "/api/sections/no_such_section/draft", None, 404),
        ({"section": "executive_summary"}, "/api/sections/executive_summary/draft", None, 404),  # not in the weekly
        ({"section": "fixed_income"}, "/api/sections/fixed_income/draft", None, 409),  # unavailable (KCB email)
        ({"section": "focus"}, "/api/sections/focus/draft", None, 422),  # no topic
        ({"section": "company_updates", **Q3}, "/api/sections/company_updates/draft", Q3, 422),  # no text
        ({"section": "equities", "report_type": "companion", "kind": "nope"}, "/api/sections/equities/draft",
         {"report_type": "companion", "kind": "nope"}, 422),
    ]
    for body, path, direct_body, status in cases:
        as_run, direct = client.post("/api/runs", json=body), client.post(path, json=direct_body)
        assert as_run.status_code == direct.status_code == status, body
        assert as_run.json()["detail"] == direct.json()["detail"]
    assert client.post("/api/runs", json={"report_type": "weekly"}).status_code == 422  # the section is required
    # no key in anthropic mode: refused before anything starts, in the draft route's words
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    as_run, direct = client.post("/api/runs", json={"section": "equities"}), client.post("/api/sections/equities/draft")
    assert as_run.status_code == direct.status_code == 409 and as_run.json()["detail"] == direct.json()["detail"]
    assert client.get("/api/sections").json()["drafting"] is None


def test_provider_is_only_a_check_of_what_the_screen_showed(client, monkeypatch):
    """It never selects the provider: a mismatch is refused, a match (or none given) runs on the configured one."""
    r = client.post("/api/runs", json={**WEEKLY_DP, "provider": "local"})
    assert r.status_code == 409 and "configured for anthropic" in r.json()["detail"]
    assert client.get("/api/sections").json()["drafting"] is None
    assert run_to_end(client, **WEEKLY_DP, provider="anthropic")["status"] == "finished"
    monkeypatch.setenv("CYTONN_LLM_PROVIDER", "local")
    assert client.post("/api/runs", json={**WEEKLY_DP, "provider": "anthropic"}).status_code == 409
    assert run_to_end(client, **WEEKLY_DP, provider="local")["status"] == "finished"


def test_a_second_run_of_the_same_section_is_refused_while_the_first_is_running(app, client, monkeypatch):
    provider = GatedProvider()
    dp_pipeline(monkeypatch, provider=provider)
    first = start(client, **WEEKLY_DP)
    try:
        assert provider.entered.wait(timeout=10)
        r = client.post("/api/runs", json=WEEKLY_DP)
        assert r.status_code == 409
        assert r.json()["detail"].startswith("A draft of Digital Payments is already running.")
        # another section is refused too, by the one draft slot, which names the draft that holds it
        other = client.post("/api/runs", json={"section": "equities"})
        assert other.status_code == 409 and "already running: Digital Payments" in other.json()["detail"]
        # ... and the refused run left nothing behind: only the first is on the overview
        assert client.get("/api/sections").json()["drafting"]["slug"] == "digital_payments"
        # the same section of another report is a different run, but it too waits for the slot
        assert client.post("/api/runs", json={"section": "digital_payments", **Q3}).status_code == 409
        # a section that calls no provider takes no slot, so it runs alongside
        assert run_to_end(client, section="company_updates", text="Demo.", **Q3)["status"] == "finished"
        assert client.get(f"/api/runs/{first}").json()["status"] == "running"
    finally:
        provider.release.set()
    assert finished(client, first)["status"] == "finished"
    # once it has ended, the same section can run again
    assert run_to_end(client, **WEEKLY_DP)["status"] == "finished"


def test_a_run_that_hung_and_was_replaced_fails_and_saves_nothing(app, client, db, clock, monkeypatch):
    provider = GatedProvider()
    dp_pipeline(monkeypatch, provider=provider)
    hung = start(client, **WEEKLY_DP)
    try:
        assert provider.entered.wait(timeout=10)
        clock.t += 3600  # past DRAFT_STALE_AFTER_SECONDS: the next draft takes the slot over
        assert client.post("/api/sections/equities/draft").status_code == 200
    finally:
        provider.release.set()
    run = finished(client, hung)
    assert run["status"] == "failed" and run["review_id"] is None
    assert "treated as stuck" in run["events"][-1]["detail"]
    assert review_store.load_latest_review("digital_payments", db_path=db) is None


# ---------------------------------------------------------------------------
# Reading a run
# ---------------------------------------------------------------------------

def test_an_unknown_run_is_not_found(client):
    assert client.get("/api/runs/0123456789abcdef0123456789abcdef").status_code == 404
    assert client.get("/api/runs/0123456789abcdef0123456789abcdef/events").status_code == 404
    assert "lost when the API restarts" in client.get("/api/runs/nope").json()["detail"]


def test_runs_are_in_memory_only_so_a_restart_forgets_them(app, client, db, clock):
    run = run_to_end(client, **WEEKLY_DP)
    restarted = TestClient(create_app(db_path=db, load_dotenv=False, clock=clock))
    assert restarted.get(f"/api/runs/{run['run_id']}").status_code == 404
    # the review it saved is in the database, so nothing that matters is lost
    assert restarted.get(f"/api/reviews/{run['review_id']}").status_code == 200
    assert restarted.get("/api/sections").json()["sections"][2]["latest"]["run_id"] == run["review_id"]


def test_the_registry_keeps_only_recent_ended_runs_and_never_drops_a_running_one():
    registry = RunRegistry(keep_ended=2)
    running = registry.start("weekly", "", "equities", "Equities", "Cytonn Weekly")
    ended = []
    for n in range(4):
        r = registry.start("quarterly", f"Q{n}", "equities", "Equities", "Quarterly")
        r.fail("stopped")
        ended.append(r.run_id)
    registry.start("weekly", "", "focus", "Focus of the Week", "Cytonn Weekly")
    assert registry.get(running.run_id) is running
    assert [registry.get(i) is not None for i in ended] == [False, False, True, True]


def test_the_stream_replays_then_follows_then_closes(app, client, monkeypatch):
    provider = GatedProvider()
    dp_pipeline(monkeypatch, provider=provider)
    run_id = start(client, **WEEKLY_DP)
    result = {}
    try:
        assert provider.entered.wait(timeout=10)
        before = client.get(f"/api/runs/{run_id}").json()["events"]
        assert before and before[-1]["kind"] == "piece_started" and before[-1]["label"] == "Outlook paragraph"
        # opened mid-run: the response only completes once the stream closes, so read it from another thread
        reader = threading.Thread(target=lambda: result.update(r=TestClient(app).get(f"/api/runs/{run_id}/events")))
        reader.start()
        time.sleep(0.2)
        assert reader.is_alive()  # still open: the run has not ended
    finally:
        provider.release.set()
    reader.join(timeout=10)
    assert not reader.is_alive()  # ... and it closed by itself after the run ended
    r = result["r"]
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"
    events, _ = parse_sse(r.text)
    assert all(name == "step" for name, _ in events)
    data = [d for _, d in events]
    assert data[: len(before)] == before  # first everything already recorded ...
    assert len(data) > len(before) and data[-1]["kind"] == "run_finished"  # ... then the new events, to the end
    assert [d["seq"] for d in data] == list(range(1, len(data) + 1))
    assert data == client.get(f"/api/runs/{run_id}").json()["events"]
    # the wire format: "event: step", then one "data:" line of JSON, then a blank line
    first = r.text.split("\n\n")[0].split("\n")
    assert first[0] == "event: step" and first[1].startswith("data: {") and len(first) == 2
    assert json.loads(first[1][len("data: "):])["kind"] == "run_started"
    # opened after the run ended: the whole run is replayed and the stream closes at once
    again = client.get(f"/api/runs/{run_id}/events")
    assert [d for _, d in parse_sse(again.text)[0]] == data


def test_an_idle_stream_sends_keepalive_comments(db, monkeypatch):
    provider = GatedProvider()
    dp_pipeline(monkeypatch, provider=provider)
    app = create_app(db_path=db, load_dotenv=False, run_keepalive=0.05)
    client = TestClient(app)
    run_id = start(client, **WEEKLY_DP)
    result = {}
    try:
        assert provider.entered.wait(timeout=10)
        reader = threading.Thread(target=lambda: result.update(r=TestClient(app).get(f"/api/runs/{run_id}/events")))
        reader.start()
        time.sleep(0.4)  # nothing happens meanwhile, so only keepalives go out
    finally:
        provider.release.set()
    reader.join(timeout=10)
    events, comments = parse_sse(result["r"].text)
    assert comments and set(comments) == {": keepalive"}
    assert events[-1][1]["kind"] == "run_finished"


def test_the_default_keepalive_is_fifteen_seconds():
    from api import runs

    assert runs.SSE_KEEPALIVE_SECONDS == 15.0
