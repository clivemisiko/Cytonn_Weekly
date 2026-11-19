import json

import pytest

from cytonn_weekly.history import reads, store
from cytonn_weekly.history import weekly as history_weekly
from cytonn_weekly.history.importer import CATALOG
from cytonn_weekly.weekly import analyst as weekly_analyst
from tests.agent_helpers import call, say
from tests.test_agent_read_tools import Env
from tests.test_agent_scenarios import converse
from tests.weekly_helpers import WEEK

SECRET = "7777.5"   # a figure no tool result may carry for a confidential series
NOTE = "Suggested: 3,035.6000 saved for the week ending 2026-09-25 + 16.6000 worked out for this week, 4242 USD mn"


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    reads.counts.clear()
    monkeypatch.delenv(reads.MODE_ENV, raising=False)


def point(key, day, value, subject="", origin="typed", kind="form_field", ref="field", by=store.FORM):
    unit, cadence, section, label, _ = CATALOG[key]
    return {"key": key, "subject": subject, "unit": unit, "section": section, "cadence": cadence, "label": label, "as_of": day, "week_ending": "2026-10-02",
            "value": value, "origin": origin, "source_kind": kind, "source_ref": ref, "confirmed_by": by}


def fill(env, *points):
    store.record_many(env.db, list(points))


def shown_to_the_model(client):
    return json.dumps(client.calls)


def test_history_status_says_which_series_have_a_confirmed_point_an_unconfirmed_one_or_none_and_no_value(env, monkeypatch):
    fill(env, point("eq.turnover.day", "2026-10-01", "1234.5"), point("eq.turnover.day", "2026-10-02", "1235.5"),
         point("eq.turnover.ytd", "2026-10-02", "5678.25", origin="worked_out", kind="working", ref=NOTE, by=None),
         point("eq.pe", "2026-10-02", SECRET), point("eq.price", "2026-09-25", "40.5", subject="alpha bank"))   # last week's: not in this week
    monkeypatch.setattr(history_weekly, "_failed", 3)
    reads.counts["differences"] = 4
    said, client, shown = converse(env, "equities", "What does the store hold?", call(("history_status", {})), say("Some points are waiting."))
    got = shown["history_status"][0]
    by = {s["series"]: s for s in got["series"]}
    assert by["eq.turnover.day"]["state"] == "confirmed" and by["eq.turnover.day"]["confirmed"] == 2
    assert by["eq.turnover.day"]["confirmed_dates"] == ["2026-10-01", "2026-10-02"]
    assert by["eq.turnover.ytd"]["state"] == "unconfirmed" and by["eq.turnover.ytd"]["unconfirmed_dates"] == ["2026-10-02"]
    assert by["eq.price"]["state"] == "none" and by["eq.pe"]["state"] == "confirmed"
    assert {s["series"] for s in got["series"]} == {k for k, v in CATALOG.items() if v[2] == "equities"}   # this section's series only
    assert (got["failed_store_writes"], got["compare_differences"], got["failed_store_reads"], got["setting"]) == (3, 4, 0, "off")
    text = shown_to_the_model(client)
    assert not any(v in text for v in ("1234.5", "1235.5", "5678.25", SECRET, "4242"))   # counts and dates, never a value or a working


def test_history_status_has_nothing_to_say_for_a_section_without_series(env):
    _, _, shown = converse(env, "digital_payments", "Store?", call(("history_status", {})), say("No."))
    assert shown["history_status"][0] == {"error": "The history store holds no series for this section."}


def test_history_working_shows_the_provenance_and_the_working_of_a_series_that_is_not_confidential(env):
    fill(env, point("eq.turnover.ytd", "2026-10-02", "3052.2", origin="worked_out", kind="working", ref=NOTE, by=None),
         point("eq.price", "2026-10-02", "42.5", subject="alpha bank", origin="workbook_import", kind="workbook_cell", ref="Universe of Coverage!G3", by=store.IMPORT))
    _, _, shown = converse(env, "equities", "How was the total worked out?", call(("history_working", {"series": "eq.turnover.ytd", "day": "2026-10-02"}),
                                                                                  ("history_working", {"series": "eq.price", "day": "2026-10-02"})), say("As shown."))
    total, price = shown["history_working"]
    assert total["confidential"] is False and total["count"] == 1
    assert total["points"][0] == {"origin": "worked_out", "source_kind": "working", "confirmed": False, "subject": "", "value": "3052.2", "unit": "usd_mn", "working": NOTE}
    assert price["points"][0] == {"origin": "workbook_import", "source_kind": "workbook_cell", "confirmed": True, "source_ref": "Universe of Coverage!G3",
                                  "subject": "alpha bank", "value": "42.5", "unit": "kes"}


@pytest.mark.parametrize("series, subject", [("eq.pe", ""), ("fi.mmf.rate", "cytonn money market fund"), ("fi.placements", "")])
def test_history_working_never_returns_a_value_a_subject_or_a_working_for_a_confidential_series(env, series, subject):
    fill(env, point(series, "2026-10-02", SECRET, subject=subject),
         point(series, "2026-10-01", "9999.5", subject=subject, origin="worked_out", kind="working", ref=NOTE, by=None))
    _, client, shown = converse(env, "equities", "What is it?", call(("history_working", {"series": series, "day": "2026-10-02"}),
                                                                      ("history_working", {"series": series, "day": "2026-10-01"})), say("Typed on the form."))
    typed, worked = shown["history_working"]
    assert typed["confidential"] is True and typed["points"] == [{"origin": "typed", "source_kind": "form_field", "confirmed": True, "source_ref": "field"}]
    assert worked["points"] == [{"origin": "worked_out", "source_kind": "working", "confirmed": False}]   # no source reference either: it is the working
    text = shown_to_the_model(client)
    assert not any(v in text for v in (SECRET, "9999.5", "4242", subject or SECRET)) and "values and workings are not shown" in text


def test_history_working_refuses_a_date_outside_the_week_and_a_series_that_is_not_one(env):
    _, _, shown = converse(env, "equities", "?", call(("history_working", {"series": "eq.pe", "day": "2026-09-25"}),
                                                       ("history_working", {"series": "form.pe", "day": "2026-10-02"}),
                                                       ("history_working", {"series": "eq.pe", "day": "2026-10-02", "run_id": 3})), say("Refused."))
    outside, unknown, extra = shown["history_working"]
    assert outside == {"error": "Only dates in this report's week are available: 2026-09-28 to 2026-10-02."}
    assert unknown["error"] == "The input was refused." and extra["error"] == "The input was refused."   # an unknown series, and an argument the tool does not take


def test_a_working_longer_than_a_title_is_kept_to_its_own_limit(env):
    long = "Suggested: " + "x" * 600
    fill(env, point("eq.foreign.ytd", "2026-10-02", "1.5", origin="worked_out", kind="working", ref=long, by=None))
    _, _, shown = converse(env, "equities", "?", call(("history_working", {"series": "eq.foreign.ytd", "day": "2026-10-02"})), say("ok"))
    assert len(shown["history_working"][0]["points"][0]["working"]) == 400


# --- week_status ---------------------------------------------------------------------------------------------------------------

def prepare(env):
    """A carried P/E and a suggested turnover total, written through the form so the store holds them as unconfirmed points."""
    weekly_analyst.save_form(WEEK.previous, {"fields": {"pe": "10.5"}}, env.root, env.db)
    weekly_analyst.carry_forward(WEEK, env.root, env.db)
    weekly_analyst.suggest(WEEK, "turnover_ytd", "3052.2", NOTE, env.root, env.db)


def status(env, question="What is waiting?"):
    return converse(env, "equities", question, call(("week_status", {})), say("ok"))[2]["week_status"][-1]   # the conversation keeps every earlier call


def test_week_status_is_exactly_as_it_was_with_the_setting_off_whatever_the_store_holds(env, tmp_path):
    prepare(env)
    assert any(p["confirmed_at"] is None for p in store.current(env.db, "eq.turnover.ytd", confirmed_only=False))
    off = status(env)
    assert "turnover_ytd" in {e["key"] for e in off["groups"]["carried_or_suggested"]}
    assert not any("source" in e for g in off["groups"].values() for e in g)
    bare = Env(tmp_path / "bare")   # the same week with no store at all
    weekly_analyst.save_form(WEEK.previous, {"fields": {"pe": "10.5"}}, bare.root)
    weekly_analyst.carry_forward(WEEK, bare.root)
    weekly_analyst.suggest(WEEK, "turnover_ytd", "3052.2", NOTE, bare.root)
    assert status(bare) == off


def test_week_status_adds_where_a_carried_or_suggested_figure_came_from_when_the_store_holds_it(env, tmp_path, monkeypatch):
    prepare(env)
    off = status(env)
    monkeypatch.setenv(reads.MODE_ENV, "on")
    got = status(env, "And now?")
    entries = {e["key"]: e for e in got["groups"]["carried_or_suggested"]}
    assert entries["pe"]["source"] == "carried: from the week ending 2026-09-25"
    assert entries["turnover_ytd"]["source"] == "suggested: last confirmed total for 25 Sep plus this week's figure"
    assert {k: [{f: v for f, v in e.items() if f != "source"} for e in es] for k, es in got["groups"].items()} == off["groups"]   # groups and counts unchanged
    assert got["counts"] == off["counts"]
    assert not any(v in json.dumps(got) for v in ("3052.2", "4242", "10.5"))
    # an empty store: exactly the off output
    empty = Env(tmp_path / "empty")
    weekly_analyst.save_form(WEEK.previous, {"fields": {"pe": "10.5"}}, empty.root)
    weekly_analyst.carry_forward(WEEK, empty.root)
    weekly_analyst.suggest(WEEK, "turnover_ytd", "3052.2", NOTE, empty.root)
    assert status(empty) == off
