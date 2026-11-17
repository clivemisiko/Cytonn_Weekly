import json
from datetime import date

import pytest

from cytonn_weekly.common import run_events
from cytonn_weekly.common import sources as src
from cytonn_weekly.narrative import bedrock_provider as bp
from cytonn_weekly.narrative.base import NarrativeBrief
from tests.test_sourced_claims import Client, aws  # noqa: F401 - the fake client and the Bedrock settings fixture

START, END = date(2026, 9, 26), date(2026, 10, 2)
FRIDAY = date(2026, 10, 2)
SUBJECT = "Mortgage lending"
BRIEF = NarrativeBrief(id="lending", section="Real Estate", label=SUBJECT, focus="loans", words=(1, 400))
TEXT = "Private sector credit grew by 8.75% in the year to September 2026."
QUOTE = "Private sector credit grew by 8.75%"
INSIDE, OUTSIDE = "https://inside.example.com/a", "https://outside.example.com/old"


def paste(url, day, title, subject=SUBJECT):
    return src.from_paste(url, day, TEXT, subject, FRIDAY, title=title)


def shown_to_the_model(client):
    return json.dumps(client.calls[0], default=str)


@pytest.fixture
def events():
    log = run_events.EventLog()
    token = run_events.current_observer.set(log)
    yield log
    run_events.current_observer.reset(token)


def narrative(client):
    return bp.BedrockNarrativeProvider(client=client).draft_piece(BRIEF, start=START, end=END, today=FRIDAY)


def highlight(client, company="Visa"):
    return bp.BedrockProvider(client=client).find_highlight(company, "investor.visa.com", start=START, end=END, today=FRIDAY)


def left_out(log):
    return [e for e in log.events if e.kind == "source_left_out"]


# --- the narrative provider ------------------------------------------------------------------------------------------

def test_a_source_dated_inside_the_window_is_shown_and_unflagged(aws, events):
    inside = paste(INSIDE, "2026-09-30", "Inside page")
    client = Client([{"text": "Credit grew 8.75%.", "quote": QUOTE, "source_id": inside.id}])
    res = narrative(client)
    assert INSIDE in shown_to_the_model(client) and not res.no_story
    assert left_out(events) == [] and not any("outside this draft's dates" in w for w in res.draft_warnings)
    assert res.claims[0]["source_flags"] == [f for f in inside.flags]


@pytest.mark.parametrize("day", ["2026-09-25", "2026-10-03", "2025-01-15"])
def test_a_source_dated_outside_the_window_is_left_out_with_a_warning_and_an_event(aws, events, day):
    inside = paste(INSIDE, "2026-09-30", "Inside page")
    old = paste(OUTSIDE, day, "Old report")
    client = Client([{"text": "Credit grew 8.75%.", "quote": QUOTE, "source_id": inside.id}])
    res = narrative(client)
    seen = shown_to_the_model(client)
    assert INSIDE in seen and OUTSIDE not in seen and old.id not in seen        # the model was never shown it
    (note,) = [w for w in res.draft_warnings if "outside this draft's dates" in w]
    assert f'"Old report" from outside.example.com, dated {day}' in note and "2026-09-26 to 2026-10-02" in note
    assert note.startswith(f"{SUBJECT}: ")
    (event,) = left_out(events)
    assert event.label == "Old report" and event.detail == (
        f"From outside.example.com, dated {day}, outside 2026-09-26 to 2026-10-02, so it was not used for {SUBJECT}.")
    assert not res.no_story                                                       # the draft goes on with what is inside


def test_the_edges_of_the_window_are_inside(aws, events):
    first, last = paste("https://a.example.com/1", "2026-09-26", "First day"), paste("https://b.example.com/2", "2026-10-02", "Last day")
    client = Client([{"text": "Credit grew 8.75%.", "quote": QUOTE, "source_id": first.id}])
    narrative(client)
    assert "a.example.com" in shown_to_the_model(client) and "b.example.com" in shown_to_the_model(client)
    assert left_out(events) == []


def test_every_source_outside_the_window_leaves_no_sources_and_says_why(aws, events):
    paste(OUTSIDE, "2025-01-15", "Old report")
    client = Client([])
    res = narrative(client)
    assert res.no_story and res.reason == bp.NO_SOURCES and client.calls == []     # no model call
    assert any("Old report" in w and "outside this draft's dates" in w for w in res.draft_warnings)
    assert res.draft_warnings[-1] == f"{SUBJECT}: {bp.NO_SOURCES}"
    assert len(left_out(events)) == 1


def test_an_undated_source_is_kept_and_carries_the_flag(aws, events):
    undated = src.from_snip(b"image-bytes", ".png", TEXT, SUBJECT, FRIDAY, "", "Undated snip")
    assert undated.published_date == ""
    client = Client([{"text": "Credit grew 8.75%.", "quote": QUOTE, "source_id": undated.id}])
    res = narrative(client)
    assert undated.id in shown_to_the_model(client) and left_out(events) == []
    assert res.claims[0]["source_flags"] == ["No date on this source"]
    assert undated.flags == []                                                    # the saved source itself is not changed


def test_a_snip_dated_with_the_report_friday_counts_as_dated(aws, events):
    snip = src.from_snip(b"image-bytes", ".png", TEXT, SUBJECT, FRIDAY, FRIDAY.isoformat(), "Friday snip")   # what snips.confirm saves
    client = Client([{"text": "Credit grew 8.75%.", "quote": QUOTE, "source_id": snip.id}])
    res = narrative(client)
    assert res.claims[0]["source_flags"] == [] and left_out(events) == []


def test_a_date_that_does_not_read_as_a_date_is_treated_as_no_date(aws):
    results, notes = bp.within_window([{"id": "x", "publishedDate": "last week", "flags": ["host not on the approved list"]}],
                                      SUBJECT, START, END)
    assert notes == [] and results[0]["flags"] == ["host not on the approved list", "No date on this source"]
    again, _ = bp.within_window(results, SUBJECT, START, END)
    assert again[0]["flags"].count("No date on this source") == 1


def test_without_an_observer_a_left_out_source_is_still_warned_about(aws):
    paste(OUTSIDE, "2025-01-15", "Old report")
    res = narrative(Client([]))
    assert any("Old report" in w for w in res.draft_warnings)


# --- the Digital Payments provider -----------------------------------------------------------------------------------

def test_digital_payments_leaves_out_a_source_dated_outside_the_window(aws, events):
    inside = paste(INSIDE, "2026-09-30", "Inside page", subject="Visa")
    paste(OUTSIDE, "2025-01-15", "Old Visa release", subject="Visa")
    client = Client([{"text": "Visa said credit grew 8.75%.", "quote": QUOTE, "source_id": inside.id}])
    res = highlight(client)
    seen = shown_to_the_model(client)
    assert INSIDE in seen and OUTSIDE not in seen
    assert any('"Old Visa release" from outside.example.com, dated 2025-01-15' in w for w in res.draft_warnings)
    (event,) = left_out(events)
    assert event.label == "Old Visa release" and "so it was not used for Visa" in event.detail


def test_digital_payments_keeps_an_undated_source_with_the_flag_and_makes_no_call_when_nothing_is_left(aws, events):
    undated = src.from_snip(b"image-bytes", ".png", TEXT, "Visa", FRIDAY, "", "Undated Visa snip")
    client = Client([{"text": "Visa said credit grew 8.75%.", "quote": QUOTE, "source_id": undated.id}])
    highlight(client)
    assert undated.id in shown_to_the_model(client)
    old_only = Client([])
    paste(OUTSIDE, "2025-01-15", "Old Mastercard release", subject="Mastercard")
    res = highlight(old_only, company="Mastercard")
    assert res.no_story and old_only.calls == [] and any("Old Mastercard release" in w for w in res.draft_warnings)


# --- a brief that wants dated sources only, and the analyst's own snips -----------------------------------------------

DATED_BRIEF = NarrativeBrief(id="policy", section="Fixed Income", label="Monetary policy", focus="a decision", words=(1, 400),
                             context="The event itself must have happened in the report week.", dated_only=True)


def test_a_dated_only_brief_leaves_out_an_undated_source_and_says_so(aws, events):
    undated = src.from_snip(b"image-bytes", ".png", TEXT, "Monetary policy", FRIDAY, "", "Undated snip")
    dated = src.from_paste(INSIDE, "2026-09-30", TEXT, "Monetary policy", FRIDAY, title="Dated page")
    client = Client([{"text": "Credit grew 8.75%.", "quote": QUOTE, "source_id": dated.id}])
    res = bp.BedrockNarrativeProvider(client=client).draft_piece(DATED_BRIEF, start=START, end=END, today=FRIDAY)
    seen = shown_to_the_model(client)
    assert dated.id in seen and undated.id not in seen
    assert any('"Undated snip" from snip has no date, so the model was not shown it' in w for w in res.draft_warnings)
    (event,) = left_out(events)
    assert event.detail == "From snip, no date, so it was not used for Monetary policy."
    assert "The event itself must have happened in the report week." in seen                        # the prompt line


def test_the_dated_only_rule_is_the_three_fixed_income_briefs_alone():
    from cytonn_weekly.fixed_income import weekly as fiw
    from cytonn_weekly.equities import weekly as eqw
    assert all(b.dated_only and "recap of an earlier decision" in b.context for b in fiw.BRIEFS)
    assert not any(b.dated_only for b in eqw.BRIEFS) and not BRIEF.dated_only


@pytest.mark.parametrize("day", ["2026-09-01", "2026-10-20"])
def test_a_confirmed_snip_skips_the_date_window_and_shows_the_typed_date(aws, events, day):
    snip = src.from_snip(b"image-bytes", ".png", TEXT, SUBJECT, FRIDAY, day, "Typed-date snip", typed_date=True)
    assert snip.flags == [f"Date typed by the analyst: {day}"] and snip.published_date == day
    client = Client([{"text": "Credit grew 8.75%.", "quote": QUOTE, "source_id": snip.id}])
    res = narrative(client)
    assert snip.id in shown_to_the_model(client) and left_out(events) == [] and not res.no_story
    assert res.claims[0]["source_flags"] == [f"Date typed by the analyst: {day}"]


def test_a_fetched_page_keeps_the_window_and_an_untyped_snip_date_carries_no_flag(aws, events):
    paste(OUTSIDE, "2026-09-01", "Old page")
    friday = src.from_snip(b"image-bytes-2", ".png", TEXT, SUBJECT, FRIDAY, FRIDAY.isoformat(), "Friday snip")
    assert friday.flags == []                                                    # no date was typed, so none is claimed
    client = Client([{"text": "Credit grew 8.75%.", "quote": QUOTE, "source_id": friday.id}])
    res = narrative(client)
    assert OUTSIDE not in shown_to_the_model(client) and len(left_out(events)) == 1
    assert any("Old page" in w for w in res.draft_warnings)
