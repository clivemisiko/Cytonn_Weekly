import json
from dataclasses import replace

import pytest

from api.runs import RunRegistry
from cytonn_weekly.agent import readiness
from cytonn_weekly.agent.tools import execute
from cytonn_weekly.common import sources as source_store
from cytonn_weekly.real_estate import snips as snip_store
from cytonn_weekly.run_store import RunStore
from cytonn_weekly.weekly import analyst as weekly_analyst
from cytonn_weekly.weekly import inputs as weekly_inputs
from tests.test_agent_read_tools import BY_NAME, PERIOD, PNG, Env
from tests.weekly_helpers import WEEK, equities_workbook_bytes


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def keys(got, group):
    return {e["key"] for e in got["groups"][group]}


def test_a_fresh_equities_week_lists_what_it_needs_and_only_its_own_inputs(env):
    got = env.use("week_status")
    assert {"equities_workbook", "kcb_daily", "kcb_weekly", "cbk_bulletin", "pe", "turnover_ytd"} <= keys(got, "needs_analyst")
    assert keys(got, "optional") == {"foreign_prior_year"}
    everything = set().union(*(keys(got, g) for g in readiness.GROUPS))
    assert not everything & {"fi_workbook", "nse_yield_curve", "dp_workbook", "placements"}   # other sections' inputs
    assert sum(got["counts"].values()) == sum(len(v) for v in got["groups"].values()) and "snips" not in got and "sources" not in got


def test_a_fresh_fixed_income_week_asks_for_its_own_workbook_and_marks_the_curve_optional(env):
    got = env.use("week_status", section="fixed_income")
    assert {"fi_workbook", "cbk_bulletin", "placements", "borrowing_target"} <= keys(got, "needs_analyst")
    assert {"nse_yield_curve", "cmmf_last_week", "liquidity_driver", "fiscal_year_start", "borrowing_log"} <= keys(got, "optional")
    assert "kcb_daily" not in keys(got, "needs_analyst") and "equities_workbook" not in keys(got, "needs_analyst")
    assert next(e for e in got["groups"]["needs_analyst"] if e["key"] == "cbk_bulletin")["why"] == "not received; fetch it or upload it"


def test_uploaded_typed_carried_and_fetched_inputs_land_in_their_own_groups(env):
    weekly_inputs.store(WEEK, "equities_workbook", equities_workbook_bytes(), "w.xlsx", env.root)
    weekly_analyst.save_form(WEEK.previous, {"fields": {"pe": "10.5", "large_caps": "KCB\nEQUITY"}}, env.root)
    weekly_analyst.carry_forward(WEEK, env.root)
    weekly_analyst.save_form(WEEK, {"fields": {"turnover_ytd": "300"}}, env.root)
    got = env.use("week_status")
    why = {e["key"]: e["why"] for g in got["groups"].values() for e in g}
    assert why["equities_workbook"] == "uploaded" and why["turnover_ytd"] == "typed" and why["large_caps"] == "typed"
    # the uploaded workbook holds this week's P/E, so the carried one does not wait (test_readiness_workbook_first.py)
    assert why["pe"] == "from the workbook" and "pe" in keys(got, "in_place")
    assert "pe" not in keys(got, "needs_analyst") and "equities_workbook" not in keys(got, "needs_analyst")


def test_each_kept_file_comes_through_the_tool_by_its_stored_name_and_never_the_analysts_name(env):
    # through execute(), as the model and the prepare page's readiness route both get it: its trim keeps the files
    weekly_inputs.store(WEEK, "equities_workbook", equities_workbook_bytes(), "Fake Analyst Name.xlsx", env.root)
    got = env.use("week_status")
    kept = next(e for e in got["groups"]["in_place"] if e["key"] == "equities_workbook")
    assert kept["files"] == [{"stored_name": "equities_workbook.xlsx"}]
    others = [e for g in got["groups"].values() for e in g if e["kind"] == "upload" and e["key"] != "equities_workbook"]
    assert others and all(e["files"] == [] for e in others)
    assert "Fake Analyst Name" not in json.dumps(got)


def test_a_fetched_upload_is_in_the_fetched_group(env):
    env.upload_equities_workbook()
    from tests.test_weekly_fixed_income import BULLETIN

    weekly_inputs.store(WEEK, "cbk_bulletin", BULLETIN, "b.pdf", env.root, fetched_from="centralbank.go.ke")
    got = env.use("week_status")
    assert keys(got, "fetched") == {"cbk_bulletin"} and "cbk_bulletin" not in keys(got, "needs_analyst")


def test_a_workbook_value_counts_as_in_place_and_a_missing_day_is_named():
    slots = [{"slug": "kcb_daily", "title": "KCB", "optional": False, "per_day": True, "fetchable": False, "received": True,
              "complete": False, "sections": ["equities"], "file": None,
              "days": [{"weekday": "Monday", "received": True, "file": {"fetched_from": None, "stored_name": "kcb_daily_2026-09-28.pdf"}},
                       {"weekday": "Tuesday", "received": False, "file": None}]}]
    item = {"type": "field", "key": "pe", "label": "P/E", "required": True, "value": None, "workbook": {"value": "9"},
            "rows": None, "workbook_rows": None, "needs_confirmation": False, "carried": None}
    got = readiness.classify("equities", {"week_ending": "2026-10-02", "slots": slots}, {"groups": [{"items": [item]}]})
    assert got["groups"]["needs_analyst"] == [{"kind": "upload", "key": "kcb_daily", "label": "KCB", "why": "missing days: Tuesday",
                                                "files": [{"stored_name": "kcb_daily_2026-09-28.pdf"}], "other_week": False}]
    assert got["groups"]["in_place"] == [{"kind": "field", "key": "pe", "label": "P/E", "why": "from the workbook", "other_week": False}]


def test_an_item_held_for_another_week_is_marked_and_dated_as_the_screen_writes_dates():
    item = {"type": "field", "key": "pe", "label": "P/E", "required": True, "value": None, "workbook": {"value": "9"},
            "rows": None, "workbook_rows": None, "needs_confirmation": False, "carried": None,
            "workbook_stale": {"found": "2026-11-13", "expected": ["2026-11-27"], "whole": True}}
    got = readiness.classify("equities", {"week_ending": "2026-11-27", "slots": []}, {"groups": [{"items": [item]}]})
    assert got["groups"]["needs_analyst"] == [{"kind": "field", "key": "pe", "label": "P/E", "other_week": True,
                                                "why": "the workbook holds it, but dated 13 Nov 2026; this week needs 27 Nov 2026"}]


def test_digital_payments_has_only_its_optional_workbook(env):
    got = env.use("week_status", section="digital_payments")
    assert keys(got, "optional") == {"dp_workbook"} and sum(got["counts"].values()) == 1


def test_real_estate_gives_snip_and_source_counts_and_no_verdict(env):
    snip_store.add(WEEK.ending, "land", "a.png", PNG, env.snips)
    for day in ("2026-09-30", "2026-09-19"):
        source_store.from_paste("https://www.nse.co.ke/" + day, day, "SECRET " + day, "Land", WEEK.ending, title=day, root=env.sources)
    got = env.use("week_status", section="real_estate")
    assert {s["sector"]: s["uploaded"] for s in got["snips"]}["Land"] == 1
    assert got["sources"] == {"total": 2, "in_week": 1, "outside_week": 1} and "not say whether they are enough" in got["note"]
    assert got["counts"] == dict.fromkeys(readiness.GROUPS, 0)
    assert not {"ready", "verdict"} & got.keys() and "SECRET" not in json.dumps(got)


def test_focus_gives_source_counts_only(env):
    got = env.use("week_status", section="focus")
    assert got["sources"] == {"total": 0, "in_week": 0, "outside_week": 0} and "snips" not in got


def test_only_a_weekly_conversation_has_a_week_status(env):
    assert "no weekly readiness check" in env.use("week_status", section="no_such_section")["error"]


# --- draft_status falls back to the saved run -------------------------------------------------------

def test_draft_status_falls_back_to_the_saved_run_and_says_so(env):
    registry = RunRegistry(store=RunStore(env.db))
    run = registry.start("weekly", PERIOD, "equities", "Equities", "Weekly report")
    run.record("source_started", "CBK bulletin")
    run.fail("The source could not be reached.")
    env.runs = RunRegistry()   # as after a restart: nothing in memory
    got = env.use("draft_status")
    assert (got["state"], got["source"]) == ("failed", "saved_record") and "saved in the database" in got["note"]
    assert got["events"][-1]["kind"] == "run_failed" and got["events"][0]["label"] == "CBK bulletin"
    assert env.use("draft_status", section="fixed_income") == {"state": "none"}


def test_a_saved_run_that_was_still_running_is_read_as_interrupted(env):
    RunRegistry(store=RunStore(env.db)).start("weekly", PERIOD, "equities", "Equities", "Weekly report")
    env.runs = RunRegistry()
    assert env.use("draft_status")["state"] == "interrupted"


def test_draft_status_needs_no_registry_at_all(env):
    assert execute(BY_NAME, "draft_status", {}, replace(env.ctx(), runs=None)) == {"state": "none"}
