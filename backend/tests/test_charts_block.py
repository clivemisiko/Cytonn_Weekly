"""The chart block, its review items, its flags and its run events, on invented workbooks."""

import json
from datetime import timedelta
from decimal import Decimal

import pytest

from cytonn_weekly.charts.block import (AVERAGE, CHART_ITEM, CHART_SCOPE, DEFECTS, FRESHNESS, NOT_COMPARED, POINT,
                                        SERIES_DEFECT_FLAG, SOURCE, STALE_FLAG, TEAM_CHART_NOTE, chart_blocks, chart_counts,
                                        chart_parts, set_team_chart, team_chart_chosen)
from cytonn_weekly.charts.store import sha256
from cytonn_weekly.checkers.digital_payments import MISMATCH, MISSING, SOURCES_DISAGREE
from cytonn_weekly.common.review import build_review, check_section
from cytonn_weekly.common.run_events import (CHECK_FINISHED, PART_SKIPPED, PIECE_FINISHED, PIECE_STARTED, SOURCE_FINISHED,
                                             SOURCE_STARTED)
from cytonn_weekly.digital_payments.coordinator_review import CLEAN, FLAGGED, NOT_AUTO_VERIFIED
from tests.chart_helpers import FRIDAY, book, day, put

# What the invented draft prints, and an AVERAGE cell that agrees with the invented series' mean.
QUOTED = {"pe": "10.0x", "pe_average": "13.0x", "dividend_yield": "5.0%", "dividend_yield_average": "5.3%"}
STATED = (12.95, 0.05295)
MISSING_BOOK = ("The equities workbook for this week is not among this week's inputs.", "Upload it and draft again.")


def make(quoted=QUOTED, on_event=None, **kw):
    kw.setdefault("stated", STATED)
    return chart_blocks(book(**kw), "Equities workbook", FRIDAY, quoted, MISSING_BOOK, on_event)


def review_of(blocks, on_event=None):
    content = {"section": "equities", "title": "Equities", "blocks": blocks}
    return build_review(content, check_section(content, on_event))


def items(review, title="NASI P/E chart"):
    return [i for i in review.review_items if i.ref.startswith(title)]


def flag_kinds(item):
    return [f.kind for f in item.detail] if isinstance(item.detail, list) else []


# ---------------------------------------------------------------------------
# The block
# ---------------------------------------------------------------------------

def test_with_no_workbook_each_chart_is_information_and_makes_no_review_item():
    events = []
    blocks, files = chart_blocks(None, "Equities workbook", FRIDAY, QUOTED, MISSING_BOOK,
                                 lambda kind, label, detail=None, counts=None: events.append((kind, label, detail)))
    assert [(b["kind"], b["id"], b["status"], b["reason"], b["unblock"]) for b in blocks] == [
        ("chart", "chart_nasi_pe", "no_workbook", MISSING_BOOK[0], MISSING_BOOK[1]),
        ("chart", "chart_nasi_yield", "no_workbook", MISSING_BOOK[0], MISSING_BOOK[1])]
    assert files == {} and [b["png_sha256"] for b in blocks] == [None, None] and chart_parts(blocks[0]) == []
    assert events == [(PART_SKIPPED, "NASI P/E chart", MISSING_BOOK[0]), (PART_SKIPPED, "NASI dividend yield chart", MISSING_BOOK[0])]
    assert review_of(blocks).review_items == []                     # nothing for the coordinator to resolve, and nothing flagged
    assert [chart_counts(b) for b in blocks] == [{CLEAN: 0, FLAGGED: 0, NOT_AUTO_VERIFIED: 0}] * 2


def test_no_workbook_does_not_hold_up_approval_but_a_workbook_that_cannot_give_the_chart_does():
    other = {"kind": "supplied", "id": "company_updates", "title": "Company updates", "body_md": "Invented text.", "supplied_by": "coordinator"}
    none, _ = chart_blocks(None, "Equities workbook", FRIDAY, QUOTED, MISSING_BOOK)
    review = review_of([other, *none])
    assert len(review.review_items) == 1 and not review.is_approvable
    review.review_items[0].resolve("accept")
    assert review.is_approvable                                        # the charts asked nothing of the coordinator
    for name, kw in (("stale", {"newest": day(1)}), ("short", {"weeks": 10}), ("future", {"newest": FRIDAY + timedelta(days=7)}),
                     ("missing sheet", {"edit": lambda ws: setattr(ws, "title", "NASI PE & Dividend Yield")})):
        blocks, _ = make(**kw)
        review = review_of([other, *blocks])
        review.review_items[0].resolve("accept")
        assert [b["status"] for b in blocks] == ["not_drawn", "not_drawn"], name
        flagged = [i for i in review.review_items if i.kind == CHART_ITEM and i.status == FLAGGED]
        assert flagged and not review.is_approvable, name              # an uploaded workbook that fails still holds the section up
        for i in flagged:
            i.resolve("accept")
        assert review.is_approvable, name


def test_a_drawn_block_holds_metadata_and_the_hashes_of_its_files_only():
    blocks, files = make()
    pe, dy = blocks
    assert set(pe) == {"kind", "id", "chart_id", "title", "caption", "status", "unit", "reason", "unblock",
                       "source", "points", "window", "newest_date", "last_value", "average", "stated", "png_sha256",
                       "series_sha256", "alt", "defects", "checks"}
    assert (pe["unit"], pe["reason"]) == ("multiple", None) and dy["unit"] == "pct"
    assert (pe["status"], pe["points"], pe["newest_date"]) == ("drawn", 60, FRIDAY.isoformat())
    assert pe["source"] == {"workbook": "Equities workbook", "sheet": "NASI-PE & Dividend Yield",
                            "provenance": "from the analyst workbook, not verified", "cells": "B8:B67"}
    assert (pe["last_value"]["display"], pe["last_value"]["cell"], dy["last_value"]["display"]) == ("10.0x", "B8", "5.0%")
    assert (pe["average"]["display"], pe["average"]["count"], pe["average"]["from"]) == ("13.0x", 60, "2009-01-01")
    assert pe["png_sha256"] == sha256(files["nasi_pe"]["png"]) and pe["series_sha256"] == sha256(files["nasi_pe"]["json"])
    assert set(files) == {"nasi_pe", "nasi_yield"} and pe["alt"].startswith(pe["caption"])
    assert json.loads(json.dumps(blocks)) == blocks                     # plain data: no bytes, no Decimals, no dates
    stored = json.loads(files["nasi_pe"]["json"])
    newest = stored["points"][-1]
    assert len(stored["points"]) == 60 and (newest[0], Decimal(newest[1]), newest[2], newest[3]) == (FRIDAY.isoformat(), Decimal("10"), "B8", "10.0x")
    assert json.loads(files["nasi_yield"]["json"])["points"][-1][3] == "5.0%"


def test_the_window_is_five_years_and_the_average_still_covers_everything_since_2009():
    pe = make(weeks=400)[0][0]
    assert pe["window"]["years"] == 5 and pe["window"]["last"] == FRIDAY.isoformat()
    assert pe["window"]["points"] < pe["average"]["count"] == 400


# ---------------------------------------------------------------------------
# Review items and flags
# ---------------------------------------------------------------------------

def test_a_clean_drawn_chart_is_five_items_and_none_is_clean_about_its_figures():
    its = items(review_of(make()[0]))
    assert [i.status for i in its] == [NOT_AUTO_VERIFIED, NOT_AUTO_VERIFIED, CLEAN, CLEAN, NOT_AUTO_VERIFIED]
    assert {i.kind for i in its} == {CHART_ITEM}
    assert "From the analyst workbook, not verified" in its[4].detail
    assert [p.key for p in chart_parts(make()[0][0])] == [POINT, AVERAGE, FRESHNESS, DEFECTS, SOURCE]


def test_a_last_point_that_differs_from_the_draft_is_a_mismatch():
    point = items(review_of(make(quoted={**QUOTED, "pe": "10.1x"})[0]))[0]
    assert point.status == FLAGGED and flag_kinds(point) == [MISMATCH]
    assert point.detail[0].scope == CHART_SCOPE and point.detail[0].subject == "chart_nasi_pe#point"


def test_an_average_cell_that_prints_a_different_figure_is_sources_disagree():
    avg = items(review_of(make(stated=(10.5, 0.052))[0]))[1]
    assert avg.status == FLAGGED and flag_kinds(avg) == [SOURCES_DISAGREE]


def test_a_draft_that_does_not_print_the_average_is_missing():
    avg = items(review_of(make(quoted={"pe": "10.0x"})[0]))[1]
    assert flag_kinds(avg) == [MISSING]


def test_a_missing_average_cell_is_a_series_defect_on_the_average_item():
    avg = items(review_of(make(edit=put(A7="Mean"))[0]))[1]
    assert flag_kinds(avg) == [SERIES_DEFECT_FLAG]


def test_rows_left_out_of_the_series_are_a_series_defect_and_the_chart_is_still_drawn():
    blocks, files = make(edit=put(B20=None))
    rows = items(review_of(blocks))[3]
    assert blocks[0]["status"] == "drawn" and "nasi_pe" in files
    assert rows.status == FLAGGED and flag_kinds(rows) == [SERIES_DEFECT_FLAG] and "B20" in rows.detail[0].message


def test_a_stale_chart_is_not_drawn_has_no_files_and_says_why():
    blocks, files = make(newest=day(1))
    pe = blocks[0]
    assert (pe["status"], pe["png_sha256"], pe["alt"]) == ("not_drawn", None, None) and files == {}
    fresh, rows = items(review_of(blocks))
    assert flag_kinds(fresh) == [STALE_FLAG] and fresh.ref == "NASI P/E chart: newest point"
    assert flag_kinds(rows) == [SERIES_DEFECT_FLAG] and rows.detail[0].message == NOT_COMPARED


def test_a_point_dated_after_the_ceiling_is_a_series_defect_on_the_freshness_item():
    fresh, rows = items(review_of(make(newest=FRIDAY + timedelta(days=7))[0]))
    assert flag_kinds(fresh) == [SERIES_DEFECT_FLAG] and "after" in fresh.detail[0].message
    assert rows.status == FLAGGED


def test_a_missing_sheet_is_one_flagged_item_and_never_clean():
    blocks, files = make(edit=lambda ws: setattr(ws, "title", "NASI PE & Dividend Yield"))
    assert files == {} and [b["status"] for b in blocks] == ["not_drawn", "not_drawn"]
    (rows,) = items(review_of(blocks))
    assert rows.status == FLAGGED and flag_kinds(rows) == [SERIES_DEFECT_FLAG, SERIES_DEFECT_FLAG]
    assert "no sheet" in rows.detail[0].message and "stops the chart" in rows.detail[0].message


def test_a_flagged_chart_blocks_approval_until_it_is_accepted():
    review = review_of(make(quoted={**QUOTED, "pe": "10.1x"})[0])
    flagged = next(i for i in review.review_items if i.status == FLAGGED)
    for i in review.review_items:
        if i is not flagged:
            i.resolve("accept")
    assert not review.is_approvable
    flagged.resolve("fix_needed")
    assert not review.is_approvable
    flagged.resolve("accept")
    assert review.is_approvable


# ---------------------------------------------------------------------------
# Run events
# ---------------------------------------------------------------------------

def test_the_run_events_are_the_real_steps_and_the_counts_match_the_items():
    events = []
    record = lambda kind, label, detail=None, counts=None: events.append((kind, label, detail, counts))   # noqa: E731
    blocks, _ = make(on_event=record, edit=put(D8=None))     # the yield's newest value is empty: that chart is stale
    review = review_of(blocks, record)
    kinds = [(k, label) for k, label, _, _ in events if k != CHECK_FINISHED and not k.startswith("check")]
    assert kinds == [
        (PIECE_STARTED, "NASI P/E chart"), (SOURCE_STARTED, "Equities workbook, 'NASI-PE & Dividend Yield' (Price to Earnings)"),
        (SOURCE_FINISHED, "Equities workbook, 'NASI-PE & Dividend Yield' (Price to Earnings)"), (PIECE_FINISHED, "NASI P/E chart"),
        (PIECE_STARTED, "NASI dividend yield chart"), (SOURCE_STARTED, "Equities workbook, 'NASI-PE & Dividend Yield' (Dividend Yield)"),
        (SOURCE_FINISHED, "Equities workbook, 'NASI-PE & Dividend Yield' (Dividend Yield)"), (PART_SKIPPED, "NASI dividend yield chart")]
    skipped = next(e for e in events if e[0] == PART_SKIPPED)
    assert skipped[2].startswith("Not drawn: The newest point is dated")
    for b in blocks:
        finished = next(c for k, label, _, c in events if k == CHECK_FINISHED and label == b["title"])
        statuses = [i.status for i in items(review, b["title"])]
        assert finished == chart_counts(b) == {s: statuses.count(s) for s in (CLEAN, FLAGGED, NOT_AUTO_VERIFIED)}


# ---------------------------------------------------------------------------
# The team's own chart
# ---------------------------------------------------------------------------

def test_setting_the_tool_chart_aside_accepts_all_its_items_and_can_be_taken_back():
    blocks, _ = make(quoted={**QUOTED, "pe": "10.1x"})               # one item is flagged (a mismatch)
    review = review_of(blocks)
    pe_items = items(review)
    assert pe_items[0].status == FLAGGED and not review.is_approvable
    set_team_chart(review, "nasi_pe", True)
    assert team_chart_chosen(review, "nasi_pe") and not team_chart_chosen(review, "nasi_yield")
    assert [(i.resolution, i.resolution_note) for i in pe_items] == [("accept", TEAM_CHART_NOTE)] * 5
    assert all(i.resolution is None for i in items(review, "NASI dividend yield chart"))      # the other chart is untouched
    set_team_chart(review, "nasi_pe", False)
    assert not team_chart_chosen(review, "nasi_pe") and all(i.resolution is None for i in pe_items)
    set_team_chart(review, "nasi_pe", True)
    pe_items[2].resolve("accept", "my own note")                  # changing any one item ends the choice
    assert not team_chart_chosen(review, "nasi_pe")


def test_the_team_chart_choice_covers_a_chart_that_was_not_drawn_too_and_refuses_what_it_cannot():
    blocks, _ = make(newest=day(1))
    review = review_of(blocks)
    set_team_chart(review, "nasi_pe", True)
    assert [i.resolution for i in items(review)] == ["accept", "accept"]
    with pytest.raises(KeyError):
        set_team_chart(review, "nope", True)
    none, _ = chart_blocks(None, "Equities workbook", FRIDAY, QUOTED, MISSING_BOOK)
    with pytest.raises(ValueError, match="nothing to set aside"):
        set_team_chart(review_of(none), "nasi_pe", True)
    # A chart with no items (no workbook) or no such chart is never "chosen": there is nothing it could rest on.
    assert not team_chart_chosen(review_of(none), "nasi_pe") and not team_chart_chosen(review, "nope")
