import pytest

from cytonn_weekly.agent import readiness
from cytonn_weekly.review.figures import SOURCES_DISAGREE
from cytonn_weekly.weekly import analyst, inputs
from tests import weekly_helpers as wh
from tests.test_weekly_analyst import FUNDS, blocks, fi, item, items, save, stores
from tests.weekly_helpers import text_pdfs  # noqa: F401 - a fixture

WEEK = wh.WEEK
TITLE = "Money Market Fund Yield for Fund Managers"
# The draft's line for this file's stale workbook (Analyst.book_stale): a workbook for an earlier week is not read by the draft.
IGNORED = ("The uploaded fixed income workbook is for the week ending 25 Sep 2026, and this report is for the week ending 2 Oct 2026. "
           "It is for an earlier week, so the draft ignores it: no figure from it is used, not even as a second reading")
# The paste box's six funds as a snip confirms them (invented rates; Alpha differs from the synthetic workbook's 10.8)
SNIP_ROWS = [{"rank": str(n), "fund": f, "rate": r} for n, (f, r) in enumerate(
    [("Cytonn Money Market Fund", "11.00"), ("Alpha Money Market Fund", "10.85"), ("Beta Money Market Fund", "10.70"),
     ("Gamma Money Market Fund", "10.60"), ("Delta Money Market Fund", "10.50"), ("Epsilon Money Market Fund", "9.00")], 1)]


def where(root, section="fixed_income"):
    status = analyst.status(WEEK, root, section)
    groups = readiness.classify(section, {"week_ending": WEEK.ending.isoformat(), "slots": []}, status)["groups"]
    return {e["key"]: (group, e["why"]) for group, entries in groups.items() for e in entries}


@pytest.fixture
def books(tmp_path, text_pdfs):  # noqa: F811
    stores(tmp_path)
    inputs.store(WEEK, "fi_workbook", wh.fi_workbook_bytes(), "FI.xlsx", tmp_path)
    return tmp_path


@pytest.fixture
def stale(tmp_path, text_pdfs):  # noqa: F811
    """A fixed income workbook still at the previous week: its fund table is dated the Friday before."""
    stores(tmp_path)
    inputs.store(WEEK, "fi_workbook", wh.fi_workbook_bytes(updated=False), "FI.xlsx", tmp_path)
    return tmp_path


def snip(root):
    analyst.fund_snip(WEEK, SNIP_ROWS, WEEK.ending.isoformat(), "sha256 of an invented image", [], root)


# ---------------------------------------------------------------------------
# Part 1: a fund table for another week is refused, and every place says so
# ---------------------------------------------------------------------------

def test_a_fund_table_dated_for_another_week_is_refused_on_the_form_in_readiness_and_in_the_draft(stale):
    # the form follows the draft (2026-11-25): a workbook for an earlier week is not opened, so the items carry nothing from it
    # and the slot alone says why (test_workbook_week.py)
    mmf = item("mmf", stale)
    assert mmf["workbook_rows"] is None and mmf["workbook_ref"] is None and mmf["workbook_stale"] is None
    assert item("mmf_published", stale)["workbook"] is None
    assert where(stale)["mmf"] == ("needs_analyst", "nothing typed and no workbook value")
    # the draft does not read a workbook for an earlier week at all, so it says that, naming both weeks, and never the sheet's refusal
    warnings = fi.build(stale).section["warnings"]
    assert len([w for w in warnings if w.startswith(IGNORED)]) == 1
    assert not any("holds a money market fund table" in w for w in warnings)


def test_placements_and_last_weeks_yield_on_that_sheet_get_the_same_refusal(stale):
    placements, last = item("placements", stale), item("cmmf_last_week", stale)
    # the production case (27 Nov against a 13 Nov workbook): neither folds as the workbook's, and neither is said to be held
    assert placements["workbook"] is None and last["workbook"] is None
    assert placements["workbook_stale"] is None and last["workbook_stale"] is None
    got = where(stale)
    assert got["placements"] == ("needs_analyst", "nothing typed and no workbook value")
    assert got["cmmf_last_week"][0] == "optional"
    warnings = " ".join(fi.build(stale).section["warnings"])
    assert IGNORED in warnings and "holds the 3-month bank placements" not in warnings


def test_the_refusal_is_still_said_when_a_table_is_typed(stale):
    # the case that was silent: a typed table hid the workbook's note on the form, and the draft said nothing
    save(stale, {"mmf_published": "2026-10-02", "placements": "9.5"}, {"mmf": {"text": FUNDS}})
    assert item("mmf", stale)["workbook_rows"] is None
    review = fi.build(stale)
    assert blocks(review)["mmf_table"]["source"]["via"] == "rows typed on the weekly form"
    assert any(w.startswith(IGNORED) for w in review.section["warnings"])


def test_a_workbook_for_this_week_is_not_called_stale(books):
    assert all(item(k, books)["workbook_stale"] is None for k in ("mmf", "mmf_published", "placements", "cmmf_last_week"))
    assert not any("is for another week" in w or "this week needs" in w for w in fi.build(books).section["warnings"])


# ---------------------------------------------------------------------------
# Part 2: the workbook's fund table first (MMF_WORKBOOK_FIRST)
# ---------------------------------------------------------------------------

def test_the_workbooks_table_wins_over_a_pasted_one_which_becomes_its_second_reading(books):
    assert analyst.MMF_WORKBOOK_FIRST is True
    save(books, {"mmf_published": "2026-10-02"}, {"mmf": {"text": FUNDS.replace("10.80%", "10.85%")}})
    view = item("mmf", books)
    assert view["workbook_first"] is True and len(view["rows"]) == 6
    assert view["differences"][0] == (
        "money market fund table, Alpha Money Market Fund: effective annual rate: the uploaded fixed income workbook has 10.8% "
        "('Money Market Performance'!U13), but the table typed on the weekly form has 10.85%. The workbook's value is used.")
    assert view["differences"][-1] == (
        "Money market fund table: the table typed on the weekly form and the uploaded fixed income workbook do not list the "
        "same funds: 1 in the workbook only. The workbook's table is used.")
    review = fi.build(books)
    table = blocks(review)["mmf_table"]
    assert len(table["rows"]) == len(wh.FUNDS)                                   # the workbook's seven, not the six typed
    assert table["source"]["name"] == "Daily Nation"                             # the printed source line is unchanged
    assert table["source"]["via"] == "rows from the fixed income workbook ('Money Market Performance'!S12:U18)"
    second = table["second_sources"]
    assert [s["row"] for s in second] == ["Alpha Money Market Fund"] and second[0]["value"] == pytest.approx(10.85)
    assert "typed on the weekly form" in second[0]["source"]
    rows = items(review, TITLE)
    alpha = next(i for i in rows if "Alpha" in i.ref)
    assert alpha.status == "flagged" and SOURCES_DISAGREE in {f.kind for f in alpha.detail}
    cytonn = next(i for i in rows if "Cytonn" in i.ref)
    assert "analyst input from Fixed income workbook 'Money Market Performance'!S12:U18" in cytonn.detail
    assert "the table typed on the weekly form is its second reading" in cytonn.detail
    top5 = items(review, "Money Market Performance: Average yield of the Top 5")[0]
    assert "(10.72%)" in top5.ref and top5.status == "flagged"                  # the workbook's rates; Alpha disagrees
    assert any(w.startswith("Weekly analyst inputs: money market fund table, Alpha Money Market Fund: effective annual rate: "
                            "the uploaded fixed income workbook has 10.8%") for w in review.section["warnings"])


def test_the_workbooks_table_wins_over_a_confirmed_snip(books):
    snip(books)
    view = item("mmf", books)
    assert view["workbook_first"] is True and view["carried"]["from"] == analyst.SNIP
    assert view["differences"][0].startswith("money market fund table, Alpha Money Market Fund: effective annual rate: the uploaded "
                                             "fixed income workbook has 10.8% ('Money Market Performance'!U13), but the table "
                                             "confirmed from the Daily Nation snip has 10.85%.")
    review = fi.build(books)
    table = blocks(review)["mmf_table"]
    assert len(table["rows"]) == len(wh.FUNDS) and table["source"]["via"].startswith("rows from the fixed income workbook")
    assert "Daily Nation snip, confirmed on the weekly form" in table["second_sources"][0]["source"]
    cytonn = next(i for i in items(review, TITLE) if "Cytonn" in i.ref)
    assert "the table confirmed from the Daily Nation snip is its second reading" in cytonn.detail
    assert where(books)["mmf"] == ("in_place", "from the workbook; the form's value is its second reading")


def test_a_typed_date_that_differs_gives_way_to_the_workbooks_with_the_table(books):
    save(books, {"mmf_published": "2026-10-01"}, {"mmf": {"text": FUNDS}})
    assert item("mmf_published", books)["differences"] == [
        "Fund table published on: the uploaded fixed income workbook has 2026-10-02 ('Money Market Performance'!S10), but the "
        "weekly form has 2026-10-01. The workbook's date is used, with the workbook's fund table."]
    assert blocks(fi.build(books))["mmf_table"]["title"].endswith("as published on 2nd October 2026")


@pytest.mark.parametrize("confirmed_from", ["paste", "snip"])
def test_with_the_constant_off_the_form_table_wins_as_before(books, monkeypatch, confirmed_from):
    monkeypatch.setattr(analyst, "MMF_WORKBOOK_FIRST", False)
    if confirmed_from == "snip":
        snip(books)
    else:
        save(books, {"mmf_published": "2026-10-02"}, {"mmf": {"text": FUNDS.replace("10.80%", "10.85%")}})
    view = item("mmf", books)
    assert view["workbook_first"] is False
    assert view["differences"][0].startswith("money market fund table, Alpha Money Market Fund: effective annual rate: typed as "
                                             "10.85%, but the uploaded fixed income workbook has 10.8%")
    table = blocks(fi.build(books))["mmf_table"]
    assert len(table["rows"]) == 6
    assert table["source"]["via"] == ("rows read from the Daily Nation snip and confirmed" if confirmed_from == "snip"
                                      else "rows typed on the weekly form")
    assert where(books)["mmf"] == ("in_place", "read from the Daily Nation page and confirmed" if confirmed_from == "snip" else "typed")


def test_without_an_accepted_workbook_table_the_form_table_is_used_as_now(stale):
    snip(stale)
    save(stale, {"placements": "9.5"})   # the sheet's placements are refused too, so the paragraph needs a typed one
    review = fi.build(stale)
    table = blocks(review)["mmf_table"]
    assert len(table["rows"]) == 6 and table["source"]["via"] == "rows read from the Daily Nation snip and confirmed"
    first = items(review, TITLE)[0]
    assert first.detail.startswith("Not auto-verified: analyst input read from a Daily Nation snip and confirmed on the weekly form "
                                   "(money market fund table; source: Daily Nation e-paper).")


def test_the_source_line_names_the_workbook_when_nothing_is_on_the_form(books):
    table = blocks(fi.build(books))["mmf_table"]
    assert table["source"]["via"] == "rows from the fixed income workbook ('Money Market Performance'!S12:U18)"
    assert item("mmf", books)["differences"] == []


# ---------------------------------------------------------------------------
# Part 3: what the workbook covers is shown as covered, and not asked for
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("section", ["fixed_income", "equities"])
def test_an_input_the_workbook_covers_is_in_place_and_one_it_does_not_reads_as_before(tmp_path, text_pdfs, section):  # noqa: F811
    stores(tmp_path)
    slot, book = {"fixed_income": ("fi_workbook", wh.fi_workbook_bytes),
                  "equities": ("equities_workbook", wh.equities_workbook_bytes)}[section]
    before = where(tmp_path, section)
    inputs.store(WEEK, slot, book(), "book.xlsx", tmp_path)
    status = analyst.status(WEEK, tmp_path, section)
    got = where(tmp_path, section)
    for view in (i for g in status["groups"] for i in g["items"]):
        covered = view["workbook_rows"] if view["type"] == "table" else view["workbook"]
        if covered:
            assert got[view["key"]] == ("in_place", "from the workbook"), view["key"]
            assert got[view["key"]][0] != "needs_analyst"
        elif not view.get("workbook_stale"):
            assert got[view["key"]] == before[view["key"]], view["key"]          # not covered: as it read before the upload
        assert view["workbook_first"] is (view["key"] in ("mmf", "mmf_published") and section == "fixed_income")
