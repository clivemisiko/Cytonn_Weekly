import io
import sqlite3
from datetime import date, datetime

import pytest
from openpyxl import load_workbook

from cytonn_weekly.agent import readiness
from cytonn_weekly.history import store as history
from cytonn_weekly.review import store as review_store
from cytonn_weekly.weekly import analyst, equities_workbook, fi_workbook, inputs
from cytonn_weekly.weekly.week import Week
from tests import weekly_helpers as wh
from tests.agent_helpers import say
from tests.review_helpers import make_review
from tests.test_chat_api import Env
from tests.weekly_helpers import WEEK, text_pdfs  # noqa: F401 - a fixture

# Every figure and file name here is invented (tests/weekly_helpers.py builds the workbooks).
BOOKS = {"fixed_income": ("fi_workbook", "fi_workbook.xlsx", wh.fi_workbook_bytes, "fixed income workbook"),
         "equities": ("equities_workbook", "equities_workbook.xlsx", wh.equities_workbook_bytes, "equities workbook")}
SECTIONS = tuple(BOOKS)
BOOK_PROP = {"fixed_income": "fi_book", "equities": "equities_book"}
COVERED = ("from the workbook", "from the workbook; the form's value is its second reading")


def week_view(root, section):
    """(the workbook's slot entry, every form item by key, where readiness puts each item) for the week."""
    form = analyst.status(WEEK, root, section)
    got = readiness.classify(section, inputs.status(WEEK, root), form)
    where = {e["key"]: (group, e) for group, entries in got["groups"].items() for e in entries}
    items = {i["key"]: i for g in form["groups"] for i in g["items"]}
    return where[BOOKS[section][0]], items, {k: (g, e["why"]) for k, (g, e) in where.items()}


def held(item):
    return bool(item["workbook_rows"] if item["type"] == "table" else item["workbook"])


def read_one(root, section):
    """A reading a draft takes from the workbook (one no date check refuses), whether the draft opens the workbook at all,
    and the warnings the draft would add (Analyst.stale_lines)."""
    wi = inputs.WeeklyInputs(WEEK, root)
    a = wi.analyst
    got = a.field("large_caps") if section == "equities" else a.wb_rows("eurobond_issues")
    return got, getattr(wi, BOOK_PROP[section]) is not None, a.stale_lines()


def assert_form_has_nothing_from_it(root, items, where):
    """An ignored workbook gives the form nothing: no value, rows, ref or date note on any field or table, and readiness says it
    holds none of them.  The form reports no workbook for the section."""
    for key, i in items.items():
        assert not held(i) and i.get("workbook_ref") is None and i["workbook_stale"] is None, key
        assert "the workbook holds it" not in where[key][1], key


def without_date(section: str) -> bytes:
    """This week's synthetic workbook with the date inputs.identify reads taken out of it."""
    slot, _, book, _ = BOOKS[section]
    wb = load_workbook(io.BytesIO(book(WEEK)))
    if section == "equities":
        ws = wb[equities_workbook.VALUATION_SHEET]
        for row in ws.iter_rows(min_col=1, max_col=1):
            if isinstance(row[0].value, datetime):
                row[0].value = None
    else:
        ws = wb[fi_workbook.MMF_SHEET]
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.lower().startswith("money market fund yield for fund managers as published on"):
                    c.value = "Money Market Fund Yield for Fund Managers as published on"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


@pytest.mark.parametrize("section", SECTIONS)
def test_a_workbook_for_another_week_is_said_on_the_slot_and_in_readiness_and_covers_no_item(tmp_path, text_pdfs, section):  # noqa: F811
    slot, stored, book, name = BOOKS[section]
    inputs.store(WEEK, slot, book(updated=False), "Fake old book.xlsx", tmp_path)
    entry, items, where = week_view(tmp_path, section)
    # the slot: kept, not this week's, both weeks named, and counted as missing
    assert (tmp_path / WEEK.ending.isoformat() / stored).is_file()
    assert entry[0] == "needs_analyst" and entry[1]["files"] == [{"stored_name": stored}]
    assert entry[1]["why"] == ("uploaded, but it is for another week: the week ending 25 Sep 2026, and this report is for the week "
                               "ending 2 Oct 2026. The draft ignores it. Upload this week's workbook.")
    assert entry[1]["other_week"] is True
    # no item is covered by it, and each item it holds says so with both dates
    assert not [k for k, (g, why) in where.items() if g == "in_place" and why in COVERED]
    # an earlier week: the form follows the draft, so no item shows, folds or is badged with a figure from it, and the draft never
    # opens it, so no figure from it is used, not even as a second reading, and its warning names both weeks
    assert_form_has_nothing_from_it(tmp_path, items, where)
    value, opened, lines = read_one(tmp_path, section)
    assert not value and not opened
    assert lines[0].startswith(f"The uploaded {name} is for the week ending 25 Sep 2026, and this report is for the week ending 2 Oct 2026. "
                               "It is for an earlier week, so the draft ignores it: no figure from it is used, not even as a second "
                               "reading, and it counts for no item on the form.")


@pytest.mark.parametrize("section", SECTIONS)
def test_a_workbook_for_the_reports_own_week_behaves_as_before(tmp_path, text_pdfs, section):  # noqa: F811
    slot, stored, book, _ = BOOKS[section]
    inputs.store(WEEK, slot, book(), "Fake book.xlsx", tmp_path)
    entry, items, where = week_view(tmp_path, section)
    assert (entry[0], entry[1]["why"]) == ("in_place", "uploaded")
    assert all(i["workbook_stale"] is None for i in items.values())
    covered = [k for k, i in items.items() if held(i)]
    assert covered and all(where[k] == ("in_place", "from the workbook") for k in covered if not items[k]["workbook_first"])
    value, opened, lines = read_one(tmp_path, section)
    assert value and opened and lines == []
    assert analyst.status(WEEK, tmp_path, section)["workbooks_ignored"][section] is None


@pytest.mark.parametrize("section", SECTIONS)
def test_a_workbook_with_no_readable_date_is_said_to_have_none_never_taken_as_current(tmp_path, text_pdfs, section):  # noqa: F811
    slot, stored, _, name = BOOKS[section]
    kept = inputs.store(WEEK, slot, without_date(section), "Fake undated book.xlsx", tmp_path)
    assert (kept["read_date"], kept["matches"]) == (None, False)
    entry, items, where = week_view(tmp_path, section)
    assert entry[0] == "needs_analyst"
    assert entry[1]["why"] == ("uploaded, but no date can be read from inside it, so it may be for another week, and this report is "
                               "for the week ending 2 Oct 2026. The draft ignores it. Upload this week's workbook.")
    assert entry[1]["other_week"] is True
    assert not [k for k, (g, why) in where.items() if g == "in_place" and why in COVERED]
    # treated as an earlier one by the draft and the form: it cannot be shown to hold this week
    assert_form_has_nothing_from_it(tmp_path, items, where)
    value, opened, lines = read_one(tmp_path, section)
    assert not value and not opened
    assert lines[0].startswith(f"The uploaded {name} has no date that can be read (")
    assert ("and this report is for the week ending 2 Oct 2026. It cannot be shown to hold this week, so the draft ignores it: no "
            "figure from it is used, not even as a second reading") in lines[0]


@pytest.mark.parametrize("section", SECTIONS)
def test_a_workbook_for_a_later_week_is_still_read_by_the_draft_but_never_counted_as_this_weeks(tmp_path, text_pdfs, section):  # noqa: F811
    slot, _, book, name = BOOKS[section]
    kept = inputs.store(WEEK, slot, book(Week(date(2026, 10, 9))), "Fake later book.xlsx", tmp_path)
    assert (kept["read_date"], kept["matches"]) == ("2026-10-09", False)
    # the page as before: the slot names both weeks, it counts as missing, and it covers no item (no check of its readers
    # finding this week's own rows makes it this week's)
    entry, items, where = week_view(tmp_path, section)
    assert entry[0] == "needs_analyst"
    # a later week is still read by the draft, so the slot says that, not that it is ignored
    assert entry[1]["why"] == ("uploaded, but it is for another week: the week ending 9 Oct 2026, and this report is for the week "
                               "ending 2 Oct 2026. The draft still reads it, so check every value taken from it. Upload this week's workbook.")
    assert entry[1]["other_week"] is True
    assert not [k for k, (g, why) in where.items() if g == "in_place" and why in COVERED]
    holding = [k for k, i in items.items() if held(i)]
    assert holding, "a later workbook is still read on the form, as today"
    assert all(items[k]["workbook_stale"]["found"] == "2026-10-09" for k in holding)
    # the draft still reads it, and says to check every value it takes
    value, opened, lines = read_one(tmp_path, section)
    assert value and opened
    assert lines[0].startswith(f"The uploaded {name} is for the week ending 9 Oct 2026, and this report is for the week ending 2 Oct 2026. "
                               "It is kept and still read, so check every value taken from it")


def test_a_holiday_weeks_fixed_income_workbook_dated_the_as_at_day_is_this_weeks():
    holiday = Week(WEEK.ending, WEEK.thursday)   # the as-at day set to the Thursday, as a closed Friday would
    found = inputs.identify(inputs.BY_SLUG["fi_workbook"], wh.fi_workbook_bytes(holiday), holiday)
    assert (found["read_date"], found["matches"]) == (WEEK.thursday.isoformat(), True)


# ---------------------------------------------------------------------------
# Removing an upload: this week's inputs only
# ---------------------------------------------------------------------------

def dump(path):
    conn = sqlite3.connect(path)
    try:
        return list(conn.iterdump())
    finally:
        conn.close()


def test_removing_an_uploaded_workbook_returns_the_slot_to_not_uploaded_and_touches_no_run_or_history(tmp_path):
    env = Env(tmp_path, say("Hello back."))
    run_id = review_store.save_review(make_review(), db_path=env.db)
    history.record(env.db, key="test.series", subject="alpha", unit="multiple", section="equities", cadence="week", label="Invented series",
                   as_of="2026-10-02", week_ending="2026-10-02", value="9.5", origin="typed", source_kind="form_field", source_ref="invented")
    period = {"period": "Week ending 2026-10-02"}
    put = env.client.put("/api/inputs/weekly/2026-10-02/equities_workbook?filename=Fake%20Equities.xlsx", content=wh.equities_workbook_bytes())
    assert put.status_code == 200, put.text
    before = env.client.get("/api/sections/equities/readiness", params=period).json()["readiness"]
    kept = next(e for e in before["groups"]["in_place"] if e["key"] == "equities_workbook")
    assert kept["files"] == [{"stored_name": "equities_workbook.xlsx", "name": "Fake Equities.xlsx"}]   # named for the dialog

    saved = dump(env.db)
    gone = env.client.delete("/api/inputs/weekly/2026-10-02/equities_workbook.xlsx")
    assert gone.status_code == 200, gone.text
    assert dump(env.db) == saved   # no saved run, review or history point changed

    after = env.client.get("/api/sections/equities/readiness", params=period).json()["readiness"]
    slot = next(e for e in after["groups"]["needs_analyst"] if e["key"] == "equities_workbook")
    assert (slot["why"], slot["files"]) == ("not uploaded", [])
    assert after["counts"]["needs_analyst"] > before["counts"]["needs_analyst"]   # what it covered is missing again
    assert not (tmp_path / "inputs" / "2026-10-02" / "equities_workbook.xlsx").exists()
    assert review_store.load_review(run_id, db_path=env.db) is not None


@pytest.mark.parametrize("section", SECTIONS)
def test_an_earlier_workbook_reaches_no_field_or_table_on_the_form_or_its_workbooks_flag(tmp_path, text_pdfs, section):  # noqa: F811
    # the production case: placements, last week's Cytonn yield and the Eurobond issues had no date of their own and folded
    slot, _, book, _ = BOOKS[section]
    inputs.store(WEEK, slot, book(updated=False), "Fake old book.xlsx", tmp_path)
    form = analyst.status(WEEK, tmp_path, section)
    assert form["workbooks"][section] is False
    assert form["workbooks_ignored"][section] == (f"the uploaded {BOOKS[section][3]} is for the week ending 25 Sep 2026, "
                                                  "an earlier week, so the draft does not read it")
    items = {i["key"]: i for g in form["groups"] for i in g["items"]}
    assert all(not held(i) and i.get("workbook_ref") is None for i in items.values())
    if section == "fixed_income":
        assert items["placements"]["workbook"] is None and items["cmmf_last_week"]["workbook"] is None
        assert items["eurobond_issues"]["workbook_rows"] is None
