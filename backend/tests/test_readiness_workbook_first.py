import pytest

from cytonn_weekly.agent import readiness
from cytonn_weekly.weekly import analyst, inputs
from tests import weekly_helpers as wh
from tests.test_weekly_analyst import NEXT, WEEKLY, last_week  # noqa: F401 - a fixture
from tests.weekly_helpers import text_pdfs  # noqa: F401 - a fixture

SECTIONS = ("fixed_income", "equities")
BOOKS = {"fixed_income": ("fi_workbook", wh.fi_workbook_bytes), "equities": ("equities_workbook", wh.equities_workbook_bytes)}


def views(root, section):
    status = analyst.status(NEXT, root, section)
    by_key = {i["key"]: i for g in status["groups"] for i in g["items"]}
    groups = readiness.classify(section, {"week_ending": NEXT.ending.isoformat(), "slots": []}, status)["groups"]
    where = {e["key"]: (group, e["why"]) for group, entries in groups.items() for e in entries}
    return status, by_key, where


def supplied(item):
    return bool(item["workbook_rows"] if item["type"] == "table" else item["workbook"])


@pytest.mark.parametrize("section", SECTIONS)
def test_a_carried_item_the_uploaded_workbook_holds_is_from_the_workbook_not_waiting(last_week, section):
    analyst.carry_forward(NEXT, last_week)
    slot, book = BOOKS[section]
    inputs.store(NEXT, slot, book(NEXT), "book.xlsx", last_week)
    status, by_key, where = views(last_week, section)
    carried = {k for k in WEEKLY if k in by_key}
    held = {k for k in carried if supplied(by_key[k])}
    assert held, "the synthetic workbook should hold some of this section's weekly items"
    for key in held:
        assert by_key[key]["needs_confirmation"] is False
        assert where[key] == ("in_place", "from the workbook")
    # the draft gate waits only for what the workbook does not supply
    assert {u["key"] for u in status["unconfirmed"]} == carried - held
    for key in carried - held:
        assert by_key[key]["needs_confirmation"] is True and where[key][0] == "carried_or_suggested"
    # the builders read the workbook's cell, as the status now says
    form = inputs.WeeklyInputs(NEXT, last_week).analyst
    for key in held & set(analyst.FIELDS):
        assert form.field(key) is not None and not analyst.is_typed(form.field(key))


@pytest.mark.parametrize("section", SECTIONS)
def test_a_carried_item_with_no_workbook_still_waits_for_confirmation(last_week, section):
    analyst.carry_forward(NEXT, last_week)
    status, by_key, where = views(last_week, section)
    carried = {k for k in WEEKLY if k in by_key}
    assert carried and {u["key"] for u in status["unconfirmed"]} == carried
    for key in carried:
        assert by_key[key]["needs_confirmation"] is True and by_key[key]["carried"]["from"] == "2026-10-02"
        assert where[key] == ("carried_or_suggested", "carried from last week, not yet confirmed")


@pytest.mark.parametrize("section", SECTIONS)
def test_a_fresh_item_is_unchanged(tmp_path, text_pdfs, section):  # noqa: F811
    _, by_key, where = views(tmp_path, section)
    assert not any(i["needs_confirmation"] for i in by_key.values())
    required = [k for k, i in by_key.items() if i["required"]]
    assert all(where[k] == ("needs_analyst", "nothing typed and no workbook value") for k in required)
    slot, book = BOOKS[section]
    inputs.store(NEXT, slot, book(NEXT), "book.xlsx", tmp_path)
    _, by_key, where = views(tmp_path, section)
    for key, i in by_key.items():
        if supplied(i):
            assert where[key] == ("in_place", "from the workbook")
