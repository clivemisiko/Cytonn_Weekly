"""The one-draft-at-a-time slot (api/draft_slot.py): visible while held, never wedged forever.

The slot is global across every section.  These pin that a draft which crashes, or a server
restart, frees it; that a draft which hangs is shown on the overview and, once it has run
past the stale limit, is replaced rather than blocking drafting forever; and that the hung
run's late result is discarded rather than saved over its replacement.  Time is a fake
clock, so nothing here waits.
"""

import threading

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly.digital_payments import review_store
from cytonn_weekly.equities import review_run as eq_run
from cytonn_weekly.equities import weekly as eq_weekly
from cytonn_weekly.real_estate import review_run as re_run
from tests import section_helpers as sh

STALE_AFTER = 3600


class Clock:
    def __init__(self, t: float = 1_790_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def db(tmp_path):
    return tmp_path / "app.db"


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def app(db, clock, monkeypatch):
    monkeypatch.setattr(eq_weekly, "build_equities_weekly_review", lambda: sh.equities_review())
    monkeypatch.setattr(re_run, "build_real_estate_review", lambda: sh.real_estate_review())
    return create_app(db_path=db, load_dotenv=False, draft_stale_after=STALE_AFTER, clock=clock)


@pytest.fixture
def client(app):
    return TestClient(app)


def hang(monkeypatch, module, name):
    """Make ``module.name`` block until released, like a draft stuck on a stalled source."""
    entered, release = threading.Event(), threading.Event()
    real = getattr(module, name)

    def stuck():
        entered.set()
        assert release.wait(timeout=10)
        return real()

    monkeypatch.setattr(module, name, stuck)
    return entered, release


def start_in_background(app, path):
    result = {}
    t = threading.Thread(target=lambda: result.update(r=TestClient(app).post(path)))
    t.start()
    return t, result


def test_overview_shows_no_draft_when_none_is_running(client):
    assert client.get("/api/sections").json()["drafting"] is None


def test_a_draft_that_crashes_mid_run_frees_the_slot(client, db, monkeypatch):
    def crash():
        raise RuntimeError("afx went away mid-fetch")

    monkeypatch.setattr(eq_weekly, "build_equities_weekly_review", crash)
    assert client.post("/api/sections/equities/draft").status_code == 502
    assert client.get("/api/sections").json()["drafting"] is None
    monkeypatch.setattr(eq_weekly, "build_equities_weekly_review", lambda: sh.equities_review())
    assert client.post("/api/sections/equities/draft").status_code == 200


def test_a_draft_killed_by_a_non_exception_error_still_frees_the_slot(app, monkeypatch):
    """BaseException (e.g. KeyboardInterrupt) is not caught as a draft failure, but must not wedge the slot."""

    class Killed(BaseException):
        pass

    def killed():
        raise Killed()

    monkeypatch.setattr(re_run, "build_real_estate_review", killed)
    with pytest.raises(Killed):
        TestClient(app).post("/api/sections/real_estate/draft")
    client = TestClient(app)
    assert client.get("/api/sections").json()["drafting"] is None
    monkeypatch.setattr(re_run, "build_real_estate_review", lambda: sh.real_estate_review())
    assert client.post("/api/sections/real_estate/draft").status_code == 200


def test_a_server_restart_mid_draft_leaves_no_slot_behind(app, db, clock, monkeypatch):
    entered, release = hang(monkeypatch, eq_weekly, "build_equities_weekly_review")
    t, _ = start_in_background(app, "/api/sections/equities/draft")
    try:
        assert entered.wait(timeout=10)
        restarted = TestClient(create_app(db_path=db, load_dotenv=False, clock=clock))
        assert restarted.get("/api/sections").json()["drafting"] is None
        monkeypatch.setattr(re_run, "build_real_estate_review", lambda: sh.real_estate_review())
        assert restarted.post("/api/sections/real_estate/draft").status_code == 200
    finally:
        release.set()
        t.join(timeout=10)


def test_a_running_draft_is_shown_on_the_overview_and_named_in_the_refusal(app, client, clock, monkeypatch):
    entered, release = hang(monkeypatch, eq_weekly, "build_equities_weekly_review")
    t, first = start_in_background(app, "/api/sections/equities/draft")
    try:
        assert entered.wait(timeout=10)
        clock.t += 185
        drafting = client.get("/api/sections").json()["drafting"]
        assert drafting["slug"] == "equities" and drafting["title"] == "Equities"
        assert drafting["elapsed_seconds"] == 185 and drafting["stale"] is False
        assert drafting["stale_after_seconds"] == STALE_AFTER and drafting["started_at"].endswith("+00:00")
        # the slot is global: another section is refused too, and told which draft holds it
        r = client.post("/api/sections/real_estate/draft")
        assert r.status_code == 409
        assert "already running: Equities, for 3 min" in r.json()["detail"]
    finally:
        release.set()
        t.join(timeout=10)
    assert first["r"].status_code == 200
    assert client.get("/api/sections").json()["drafting"] is None


def test_a_hung_draft_goes_stale_is_replaced_and_its_late_result_is_discarded(app, client, db, clock, monkeypatch):
    entered, release = hang(monkeypatch, eq_weekly, "build_equities_weekly_review")
    t, hung = start_in_background(app, "/api/sections/equities/draft")
    try:
        assert entered.wait(timeout=10)
        clock.t += STALE_AFTER - 1
        assert client.post("/api/sections/real_estate/draft").status_code == 409  # not yet stale: still refused
        clock.t += 1
        assert client.get("/api/sections").json()["drafting"]["stale"] is True
        # past the limit, the next draft takes the slot over instead of being blocked forever
        r = client.post("/api/sections/real_estate/draft")
        assert r.status_code == 200
        assert client.get("/api/sections").json()["drafting"] is None
    finally:
        release.set()
        t.join(timeout=10)
    # the hung run finishes late: it no longer holds the slot, so it is not saved
    assert hung["r"].status_code == 409 and "treated as stuck" in hung["r"].json()["detail"]
    assert review_store.load_latest_review("equities", db_path=db) is None
    # ... and its release did not free the slot from under anyone: drafting still works normally
    assert client.post("/api/sections/equities/draft").status_code == 200


def test_a_late_stuck_run_cannot_release_its_replacements_claim(app, client, clock, monkeypatch):
    """Stuck run A is replaced by B; A finishing while B still runs must not let C start beside B."""
    a_in, a_go = hang(monkeypatch, eq_weekly, "build_equities_weekly_review")
    ta, ra = start_in_background(app, "/api/sections/equities/draft")
    assert a_in.wait(timeout=10)
    clock.t += STALE_AFTER
    b_in, b_go = hang(monkeypatch, re_run, "build_real_estate_review")
    tb, rb = start_in_background(app, "/api/sections/real_estate/draft")
    try:
        assert b_in.wait(timeout=10)
        a_go.set()
        ta.join(timeout=10)
        assert ra["r"].status_code == 409
        drafting = client.get("/api/sections").json()["drafting"]
        assert drafting["slug"] == "real_estate" and drafting["stale"] is False
        assert client.post("/api/sections/equities/draft").status_code == 409
    finally:
        a_go.set()
        b_go.set()
        tb.join(timeout=10)
    assert rb["r"].status_code == 200


def test_a_draft_without_an_anthropic_key_is_refused_before_it_starts(client, monkeypatch):
    """Seen live: with no key, a draft fetched its sources first and then failed inside the SDK."""
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.delenv("CYTONN_LLM_PROVIDER", raising=False)
    called = []
    monkeypatch.setattr(eq_weekly, "build_equities_weekly_review", lambda: called.append(1))
    r = client.post("/api/sections/equities/draft")
    assert r.status_code == 409 and "ANTHROPIC_API_KEY" in r.json()["detail"]
    assert called == [] and client.get("/api/sections").json()["drafting"] is None  # nothing fetched, slot never taken
    assert "ANTHROPIC_API_KEY" in client.get("/api/config").json()["provider_problem"]
    assert client.post("/api/reviews/draft").status_code == 409  # the original Digital Payments route too


def test_local_mode_needs_no_anthropic_key(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("CYTONN_LLM_PROVIDER", "local")
    assert client.get("/api/config").json()["provider_problem"] is None
    assert client.post("/api/sections/equities/draft").status_code == 200
