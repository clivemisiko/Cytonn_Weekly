import json

import pytest

from cytonn_weekly.agent import tools
from cytonn_weekly.agent.tools import Params, Tool, ToolContext, execute, schemas, trim
from tests.agent_helpers import LookupParams, lookup_tool

CTX = ToolContext(job={"section": "equities"})


def test_trim_keeps_only_the_named_keys_at_every_depth():
    value = {"a": 1, "text": "x", "rows": [{"host": "h", "text": "t", "n": 2}], "deep": {"keep": 1, "drop": 2}}
    assert trim(value, {"a": None, "rows": ("host", "n"), "deep": ("keep",)}) == {"a": 1, "rows": [{"host": "h", "n": 2}], "deep": {"keep": 1}}


def test_a_dict_with_no_shape_passes_nothing():
    assert trim({"a": 1}, None) == {} and trim({"a": {"b": 1}}, {"a": None}) == {"a": {}}


def test_strings_and_lists_are_cut_and_plain_objects_become_text():
    from datetime import date

    assert trim({"s": "x" * 500}, ("s",))["s"] == "x" * tools.MAX_TEXT
    assert len(trim(list(range(500)), None)) == tools.MAX_ITEMS
    assert trim({"d": date(2026, 10, 2), "n": None, "ok": True, "f": 1.5}, ("d", "n", "ok", "f")) == {"d": "2026-10-02", "n": None, "ok": True, "f": 1.5}


def test_execute_runs_the_tool_and_trims_what_it_returns():
    seen = []
    result = execute({"lookup": lookup_tool(seen)}, "lookup", {"section": "equities"}, CTX)
    assert seen == [("equities", "equities")]
    assert set(result) == {"section", "title", "sources"} and "SECRET SOURCE TEXT" not in json.dumps(result)
    assert result["sources"] == [{"host": "centralbank.go.ke"}] and len(result["title"]) == tools.MAX_TEXT


@pytest.mark.parametrize("raw", [{}, {"section": 3}, {"section": "x", "extra": 1}, "section", None, ["x"]])
def test_a_bad_input_runs_nothing_and_says_why(raw):
    seen = []
    result = execute({"lookup": lookup_tool(seen)}, "lookup", raw, CTX)
    assert seen == [] and result["error"] == tools.BAD_INPUT and result["problems"]


def test_an_unknown_tool_name_runs_nothing():
    assert execute({"lookup": lookup_tool()}, "approve_review", {"run_id": 1}, CTX) == {"error": tools.UNKNOWN_TOOL}


def test_a_tool_that_fails_gives_a_fixed_sentence_not_the_exception():
    def boom(args, ctx):
        raise RuntimeError("RAW INTERNAL TEXT")

    assert execute({"t": Tool("t", "d", Params, boom, ())}, "t", {}, CTX) == {"error": tools.FAILED}


def test_a_result_that_is_too_large_is_dropped_whole():
    keys = tuple("abcdefghij")
    big = Tool("t", "d", Params, lambda a, c: {"rows": [{k: "y" * 200 for k in keys} for _ in range(100)]}, {"rows": keys})
    assert execute({"t": big}, "t", {}, CTX) == {"error": tools.TOO_LARGE}


def test_a_result_that_is_not_a_dict_is_wrapped():
    assert execute({"t": Tool("t", "d", Params, lambda a, c: [1, 2], ())}, "t", {}, CTX) == {"result": [1, 2]}


def test_schemas_list_each_tool_for_the_messages_api():
    listed = schemas([lookup_tool()])
    assert listed[0]["name"] == "lookup" and listed[0]["input_schema"]["required"] == ["section"]
    assert listed[0]["input_schema"]["additionalProperties"] is False
    assert LookupParams.model_json_schema()["properties"]["section"]["type"] == "string"
