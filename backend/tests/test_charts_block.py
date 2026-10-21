"""The chart block, its review items, its flags and its run events, on invented workbooks."""

import json
from datetime import timedelta
from decimal import Decimal

from cytonn_weekly.charts.block import (AVERAGE, CHART_ITEM, CHART_SCOPE, DEFECTS, FRESHNESS, NOT_COMPARED, POINT,
                                        SERIES_DEFECT_FLAG, SOURCE, STALE_FLAG, chart_blocks, chart_counts, chart_parts)
from cytonn_weekly.charts.store import sha256
from cytonn_weekly.checkers.digital_payments import MISMATCH, MISSING, SOURCES_DISAGREE
from cytonn_weekly.common.review import UNAVAILABLE_PART, build_review, check_section
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

def test_with_no_workbook_each_chart_is_an_unavailable_block():
    blocks, files = chart_blocks(None, "Equities workbook", FRIDAY, QUOTED, MISSING_BOOK)
    assert [(b["kind"], b["id"], b["reason"]) for b in blocks] == [
        ("unavailable", "chart_nasi_pe", MISSING_BOOK[0]), ("unavailable", "chart_nasi_yield", MISSING_BOOK[0])]
    assert files == {}
    assert [(i.kind, i.status) for i in review_of(blocks).review_items] == [(UNAVAILABLE_PART, FLAGGED)] * 2


def test_a_drawn_block_holds_metadata_and_the_hashes_of_its_files_only():
    blocks, files = make()
    pe, dy = blocks
    assert set(pe) == {"kind", "id", "chart_id", "title", "caption", "status", "source", "points", "window", "newest_date",
                       "last_value", "average", "stated", "png_sha256", "series_sha256", "alt", "defects", "checks"}
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
    assert len(stored["points"]) == 60 and (newest[0], Decimal(newest[1]), newest[2]) == (FRIDAY.isoformat(), Decimal("10"), "B8")


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
