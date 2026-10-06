"""Run events at the builder level (common/run_events.py): what a draft reports, and that reporting changes nothing.

Every builder runs its real pipeline on fake edges (tests/review_helpers.py,
section_helpers.py, periodic_helpers.py), once with no observer and once with an
EventLog.  The API side (the run registry, the routes, the stream) is in
tests/test_runs_api.py.
"""

import logging
from datetime import datetime, timezone

import pytest

from api import serialize, sso
from cytonn_weekly.checkers import digital_payments as dp_checks
from cytonn_weekly.common import run_events as ev
from cytonn_weekly.digital_payments.review_run import build_digital_payments_review
from cytonn_weekly.equities import stubs as eq_stubs
from cytonn_weekly.periodic import executive_summary, fixed_income as p_fi
from tests import periodic_helpers as ph
from tests import section_helpers as sh
from tests.review_helpers import ROWS, TODAY, FakeProvider


def weekly_dp(on_event=None, rows=ROWS):
    return build_digital_payments_review(provider=FakeProvider(), today=TODAY, fetch_table=lambda today: rows,
                                         on_event=on_event)


# Every draft builder, as a callable taking only the observer.
BUILDERS = {
    "weekly digital_payments": weekly_dp,
    "weekly equities": lambda on_event=None: sh.equities_review(on_event=on_event),
    "weekly real_estate": lambda on_event=None: sh.real_estate_review(on_event=on_event),
    "weekly focus": lambda on_event=None: sh.focus_review(on_event=on_event),
    "company_updates": lambda on_event=None: ph.company_updates_review(on_event=on_event),
    **{f"quarterly {slug}": (lambda on_event=None, _b=b: _b(on_event=on_event)) for slug, b in ph.BUILDERS.items()},
}
# Sections whose builder has no step of its own to report (see their docstrings).
NO_SUB_STEPS = {"company_updates"}


def snapshot(review):
    return {"section": review.section, "items": [i.to_dict() for i in review.review_items],
            "decision": review.decision, "report_type": review.report_type, "period": review.period}


def kinds(log):
    return [e.kind for e in log.events]


def of(log, kind):
    return [e for e in log.events if e.kind == kind]


# ---------------------------------------------------------------------------
# The event type and the observer contract
# ---------------------------------------------------------------------------

def test_an_event_log_numbers_from_one_and_stamps_utc_time():
    log = ev.EventLog()
    log(ev.RUN_STARTED, "Equities")
    log(ev.CHECK_FINISHED, "A table", counts={"clean": 3})
    log(ev.RUN_FAILED, "Equities", detail="it stopped")
    events = log.events
    assert [e.seq for e in events] == [1, 2, 3]
    assert events[0].to_dict().keys() == {"seq", "kind", "label", "detail", "counts", "at"}
    assert events[0].detail is None and events[0].counts is None
    assert events[1].counts == {"clean": 3, "flagged": 0, "not_auto_verified": 0}  # every status key, integers
    assert events[2].detail == "it stopped"
    for e in events:
        assert datetime.fromisoformat(e.at).tzinfo == timezone.utc


def test_only_the_eleven_kinds_exist():
    assert set(ev.KINDS) == {"run_started", "source_started", "source_finished", "source_failed", "piece_started",
                             "piece_finished", "part_skipped", "check_started", "check_finished", "run_finished",
                             "run_failed"}
    with pytest.raises(ValueError):
        ev.EventLog()("progress_estimated", "42%")


def test_emit_without_an_observer_does_nothing_and_a_failing_observer_is_logged_not_raised(caplog):
    ev.emit(None, ev.PIECE_STARTED, "anything")

    def broken(kind, label, detail=None, counts=None):
        raise RuntimeError("observer bug")

    with caplog.at_level(logging.ERROR):
        ev.emit(broken, ev.PIECE_STARTED, "Listed banks")
    assert "observer failed" in caplog.text and "Listed banks" in caplog.text
    # an unknown kind is the observer's error too, so it cannot break a draft either
    ev.emit(ev.EventLog(), "not_a_kind", "x")


def test_fetch_source_without_an_observer_is_just_the_call():
    assert ev.fetch_source(None, "a source", lambda a, b: a + b, 2, 3) == 5
    with pytest.raises(KeyError):
        ev.fetch_source(None, "a source", lambda: {}["missing"])


# ---------------------------------------------------------------------------
# Observing changes nothing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", BUILDERS)
def test_on_event_none_leaves_the_builders_output_unchanged(name):
    """The same review with no observer argument, with on_event=None, and with a real observer."""
    build = BUILDERS[name]
    plain = snapshot(build())
    assert snapshot(build(on_event=None)) == plain
    log = ev.EventLog()
    assert snapshot(build(on_event=log)) == plain
    assert bool(log.events) == (name not in NO_SUB_STEPS)


@pytest.mark.parametrize("name", BUILDERS)
def test_a_raising_observer_does_not_break_the_draft(name, caplog):
    calls = []

    def broken(kind, label, detail=None, counts=None):
        calls.append(kind)
        raise RuntimeError("observer bug")

    build = BUILDERS[name]
    with caplog.at_level(logging.CRITICAL):  # the swallowed errors are logged; keep the test output quiet
        assert snapshot(build(on_event=broken)) == snapshot(build())
    assert bool(calls) == (name not in NO_SUB_STEPS)


# ---------------------------------------------------------------------------
# What is reported
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", BUILDERS)
def test_a_builder_reports_only_steps_never_the_runs_own_start_or_end(name):
    """run_started, run_finished and run_failed belong to whoever runs the builder (the API): a run ends when saved."""
    log = ev.EventLog()
    BUILDERS[name](on_event=log)
    assert not set(kinds(log)) & {ev.RUN_STARTED, ev.RUN_FINISHED, ev.RUN_FAILED}


@pytest.mark.parametrize("name", BUILDERS)
def test_every_started_step_is_closed_once_under_the_same_label(name):
    log = ev.EventLog()
    BUILDERS[name](on_event=log)
    closes = {ev.SOURCE_STARTED: (ev.SOURCE_FINISHED, ev.SOURCE_FAILED), ev.PIECE_STARTED: (ev.PIECE_FINISHED, ev.PART_SKIPPED),
              ev.CHECK_STARTED: (ev.CHECK_FINISHED,)}
    events = log.events
    for i, e in enumerate(events):
        if e.kind in closes:
            # the very next event of a closing kind with this label closes it, before the label starts again
            later = [x for x in events[i + 1:] if x.label == e.label and x.kind in closes[e.kind] + (e.kind,)]
            assert later and later[0].kind in closes[e.kind], (e.kind, e.label)


@pytest.mark.parametrize("name", BUILDERS)
def test_the_checks_counts_add_up_to_the_reviews_own_items(name):
    """check_finished counts are the review model's statuses, not a second tally that could drift from it."""
    log = ev.EventLog()
    review = BUILDERS[name](on_event=log)
    total = dict.fromkeys(ev.COUNT_KEYS, 0)
    for e in of(log, ev.CHECK_FINISHED):
        assert set(e.counts) == set(ev.COUNT_KEYS)
        for k, v in e.counts.items():
            total[k] += v
    # What no check event covers: an unavailable part is one flagged item, supplied text one unverified item.
    blocks = review.section.get("blocks", [])
    total["flagged"] += sum(1 for b in blocks if b["kind"] == "unavailable")
    total["not_auto_verified"] += sum(1 for b in blocks if b["kind"] == "supplied")
    assert total == ev.review_counts(review)
    assert sum(total.values()) == len(review.review_items)


def test_weekly_digital_payments_reports_its_real_steps_in_order():
    log = ev.EventLog()
    review = weekly_dp(on_event=log)
    steps = [(e.kind, e.label) for e in log.events]
    companies = ["Visa", "Mastercard", "American Express", "PayPal"]  # four found, so Circle is never searched
    drafted = [(k, label) for k, label in steps if k in (ev.PIECE_STARTED, ev.PIECE_FINISHED) and label in companies]
    assert drafted == [(k, c) for c in companies for k in (ev.PIECE_STARTED, ev.PIECE_FINISHED)]
    assert "Circle" not in [label for _, label in steps]
    # the headline is only known once drafted, so it rides in the finished event's detail
    assert of(log, ev.PIECE_FINISHED)[0].detail == review.section["items"][0]["headline"]
    after = steps[len(drafted):]
    assert after[:5] == [(ev.SOURCE_STARTED, "Yahoo Finance"), (ev.SOURCE_FINISHED, "Yahoo Finance"),
                         (ev.PIECE_STARTED, "Outlook paragraph"), (ev.PIECE_FINISHED, "Outlook paragraph"),
                         (ev.PIECE_FINISHED, dp_checks.TABLE_TITLE)]
    checks = [label for k, label in after if k == ev.CHECK_STARTED]
    assert checks == [dp_checks.TABLE_TITLE, dp_checks.OUTLOOK_STATS_LABEL] + [
        i["headline"] for i in review.section["items"] if i["kind"] == "highlight"]
    table = next(e for e in of(log, ev.CHECK_FINISHED) if e.label == dp_checks.TABLE_TITLE)
    assert table.counts == {"clean": len(ROWS), "flagged": 0, "not_auto_verified": 0}


def test_the_check_events_name_the_table_as_the_review_screen_does():
    assert dp_checks.TABLE_TITLE == serialize.TABLE_TITLE


def test_a_blocked_stub_part_is_skipped_with_its_real_blocked_reason():
    log = ev.EventLog()
    sh.equities_review(on_event=log)
    skipped = {e.label: e.detail for e in of(log, ev.PART_SKIPPED)}
    assert skipped[eq_stubs.MARKET_ACTIVITY_TITLE] == eq_stubs.MARKET_ACTIVITY_REASON
    assert skipped[eq_stubs.UNIVERSE_TITLE] == eq_stubs.UNIVERSE_REASON

    log = ev.EventLog()
    ph.fixed_income_review(on_event=log)
    skipped = {e.label: e.detail for e in of(log, ev.PART_SKIPPED)}
    for stub in p_fi.STUBS:
        assert skipped[stub.title] == stub.blocked_reason
    assert skipped["T-Bills primary auctions over the period"] == p_fi.TBILLS_BLOCKED_REASON
    # the stub itself still raises with that reason, as every stub in the repo does
    with pytest.raises(NotImplementedError, match="aggregates every weekly auction"):
        p_fi.fetch_period_tbill_summary(ph.ctx())


def test_a_theme_with_nothing_to_draft_closes_as_skipped_never_as_drafted():
    log = ev.EventLog()
    review = sh.real_estate_review(on_event=log)  # the helper's provider finds no hospitality story
    quiet = [e for e in log.events if e.label == "Hospitality and tourism"]
    assert [e.kind for e in quiet] == [ev.PIECE_STARTED, ev.PART_SKIPPED]
    assert quiet[1].detail == "Nothing qualifying found for the week."
    assert "Hospitality and tourism" not in [b.get("topic") for b in review.section["blocks"]]
    # a brief never searched (its target was already met) reports nothing at all
    assert not [e for e in log.events if e.label == "Land"]


def test_a_source_that_fails_outright_is_reported_and_the_error_still_propagates():
    """Weekly Equities: the afx fetch breaks (not an outage).  The builder raises; the observer was told why."""

    def broken():
        raise ValueError("afx listing page did not parse")

    from cytonn_weekly.equities.review_run import build_equities_review

    log = ev.EventLog()
    with pytest.raises(ValueError):
        build_equities_review(provider=sh.FakeNarrativeProvider(), today=sh.TODAY, fetch_market=broken, on_event=log)
    assert [(e.kind, e.label, e.detail) for e in log.events] == [
        (ev.SOURCE_STARTED, "afx.kwayisi.org", None),
        (ev.SOURCE_FAILED, "afx.kwayisi.org", "ValueError: afx listing page did not parse"),
    ]


def test_afx_down_is_reported_and_the_equities_draft_goes_on_without_its_tables():
    """Seen live 2026-10-05: afx unreachable.  The tables become unavailable parts; the highlights are drafted."""

    def down():
        raise ConnectionError("afx.kwayisi.org did not answer")

    from cytonn_weekly.equities import fetcher
    from cytonn_weekly.equities.review_run import TABLE_TITLES, build_equities_review

    log = ev.EventLog()
    review = build_equities_review(provider=sh.FakeNarrativeProvider(), today=sh.TODAY, fetch_market=down, on_event=log)
    assert [(e.kind, e.label, e.detail) for e in log.events[:2]] == [
        (ev.SOURCE_STARTED, "afx.kwayisi.org", None),
        (ev.SOURCE_FAILED, "afx.kwayisi.org", "ConnectionError: afx.kwayisi.org did not answer"),
    ]
    blocks = {b["id"]: b for b in review.section["blocks"]}
    for block_id, title in TABLE_TITLES:
        b = blocks[block_id]
        assert (b["kind"], b["title"], b["unblock"]) == ("unavailable", title, fetcher.DOWN_UNBLOCK)
        assert "ConnectionError: afx.kwayisi.org did not answer" in b["reason"]
        assert (ev.PART_SKIPPED, title, b["reason"]) in [(e.kind, e.label, e.detail) for e in log.events]
    assert not [b for b in review.section["blocks"] if b["kind"] == "table"]
    assert [b for b in review.section["blocks"] if b["kind"] == "narrative"]
    assert any("could not be reached" in w for w in review.section["warnings"])
    # each missing table is a flagged item the coordinator has to acknowledge
    assert sum(1 for i in review.review_items if i.status == "flagged") >= len(TABLE_TITLES)
    assert not review.is_approvable


def test_afx_down_leaves_the_markets_review_index_table_out_and_the_draft_goes_on():
    import httpx

    from cytonn_weekly.equities import fetcher

    def down():
        raise httpx.ConnectTimeout("no answer")

    log = ev.EventLog()
    review = ph.build_equities_review(ph.ctx(), provider=ph.narrative(), fetch=down, on_event=log)
    indices = next(b for b in review.section["blocks"] if b["id"] == "indices")
    assert indices["kind"] == "unavailable" and indices["unblock"] == fetcher.DOWN_UNBLOCK
    assert "ConnectTimeout: no answer" in indices["reason"]
    assert (ev.SOURCE_FAILED, "afx.kwayisi.org") in [(e.kind, e.label) for e in log.events]
    assert [b for b in review.section["blocks"] if b["kind"] == "narrative"]


def test_a_row_level_failure_is_reported_and_the_draft_goes_on():
    """Weekly Equities: one share page timed out (the fetcher isolates it to its row), the rest drafted."""
    log = ev.EventLog()
    review = sh.equities_review(on_event=log)
    failed = of(log, ev.SOURCE_FAILED)
    assert [(e.label, e.detail) for e in failed] == [("afx.kwayisi.org: KCB share page", "timeout")]
    assert (ev.SOURCE_FINISHED, "afx.kwayisi.org") in [(e.kind, e.label) for e in log.events]
    assert review.review_items


def test_a_caught_source_failure_is_reported_and_leaves_a_flagged_table():
    """Kenya Macro: the CPI release is missing.  The pipeline catches it and flags the table, so the draft finishes."""

    def missing(month):
        raise LookupError("KNBS CPI release for September 2026 not found")

    log = ev.EventLog()
    review = ph.kenya_macro_review(on_event=log, fetch_inflation=missing)
    label = "KNBS consumer price index release, September 2026"
    assert [(e.kind, e.detail) for e in log.events if e.label == label] == [
        (ev.SOURCE_STARTED, None), (ev.SOURCE_FAILED, "LookupError: KNBS CPI release for September 2026 not found")]
    table = next(e for e in of(log, ev.CHECK_FINISHED) if e.label.startswith("Major Inflation Changes"))
    assert table.counts == {"clean": 0, "flagged": 1, "not_auto_verified": 0}
    assert review.by_status("flagged")


def test_each_unreadable_cbk_pdf_is_a_failed_source():
    """Fixed Income: the year-earlier period's PDFs are not among the captured sources, so each one fails."""
    log = ev.EventLog()
    ph.fixed_income_review(on_event=log)
    started = [e.label for e in of(log, ev.SOURCE_STARTED)]
    assert started == ["Central Bank of Kenya (CBK) T-bond auction results dated 01/07/2026 to 30/09/2026",
                       "Central Bank of Kenya (CBK) T-bond auction results dated 01/07/2025 to 30/09/2025"]
    failed = of(log, ev.SOURCE_FAILED)
    assert failed and all(e.label.startswith("CBK results PDF dated ") and e.label.endswith("/2025") for e in failed)
    assert all("not captured" in e.detail for e in failed)


def test_the_executive_summary_and_company_updates_have_no_step_to_report(tmp_path):
    """Composed or carried in one step: their builders never call the observer, so a run is only its start and end."""
    log = ev.EventLog()
    ph.company_updates_review(on_event=log)
    assert log.events == []
    with pytest.raises(executive_summary.SectionsNotApproved):
        executive_summary.build_executive_summary_review(ph.ctx(db_path=tmp_path / "app.db"), on_event=log)
    assert log.events == []


# ---------------------------------------------------------------------------
# The SSO stub
# ---------------------------------------------------------------------------

def test_begin_sso_login_is_a_stub_that_says_what_blocks_it():
    assert sso.BLOCKED_REASON == ("Cytonn has not yet provided the identity provider type, client ID, an approved "
                                  "redirect address, or the list of allowed users.")
    assert sso.UNBLOCK.startswith("Get those four items from Cytonn IT")
    with pytest.raises(NotImplementedError) as exc:
        sso.begin_sso_login()
    assert str(exc.value) == sso.BLOCKED_REASON
