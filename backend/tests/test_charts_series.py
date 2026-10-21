"""The charts' series readers and checks, on invented workbooks (Stage A of the tool-drawn charts: no drawing).

The invented sheets (tests/chart_helpers.py) have the real sheet's name and layout with made-up
figures, and each test plants one defect the real workbook has or could have.  The replay on the
real workbook is test_charts_replay_real.py and skips when the workbook is absent.
"""

import ast
import sys
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from cytonn_weekly import charts
from cytonn_weekly.charts import series as cs
from cytonn_weekly.charts.series import (AverageCheck, ChartSeries, Point, Stated, average, check_quoted,
                                         compare_average, read_series, windowed)
from cytonn_weekly.charts.specs import AVERAGE_FROM, NASI_PE, NASI_YIELD, SPECS
from cytonn_weekly.checkers.digital_payments import MISMATCH, MISSING, SOURCES_DISAGREE
from cytonn_weekly.common.formatting import round_half_up
from cytonn_weekly.equities import weekly as eqw
from cytonn_weekly.weekly.workbook import Workbook
from tests import chart_helpers as ch
from tests.chart_helpers import FRIDAY, book, day, formats, nasi_bytes, pe, put, with_saved_values
from tests.test_weekly_equities import blocks, build, figures, root  # noqa: F401 - root is a fixture
from tests.weekly_helpers import dt, text_pdfs  # noqa: F401 - a fixture


def read(spec=NASI_PE, **kw):
    return read_series(book(**kw), spec, FRIDAY)


def kinds(s):
    return [d.kind for d in s.defects]


def cells(s, kind):
    return next(d for d in s.defects if d.kind == kind).cells


def clear_rows(first, last):
    def edit(ws):
        for r in range(first, last + 1):
            for c in range(1, 5):
                ws.cell(r, c).value = None
    return edit


# ---------------------------------------------------------------------------
# Finding and reading the series
# ---------------------------------------------------------------------------

def test_both_series_are_read_from_the_one_sheet_in_the_charts_unit():
    p, y = read(NASI_PE), read(NASI_YIELD)
    assert p.defects == () and y.defects == () and p.drawn and y.drawn
    assert len(p.points) == len(y.points) == 60
    assert [q.day for q in p.points] == sorted(q.day for q in p.points)   # oldest first
    assert (p.latest.day, p.latest.cell, p.latest.value) == (FRIDAY, "B8", Decimal("10.0"))
    assert (p.points[0].cell, p.points[0].value) == ("B67", Decimal("15.9"))
    # the yield is stored as a fraction shown as a percentage; the chart works in percentage points, exactly
    assert (y.latest.cell, y.latest.value, y.points[0].value) == ("D8", Decimal("5.0"), Decimal("5.59"))


def test_the_series_is_found_by_its_header_whatever_row_it_sits_on():
    base, moved = read(), read(shift=5, gap=2)
    assert [(q.day, q.value) for q in moved.points] == [(q.day, q.value) for q in base.points]
    assert (base.latest.cell, moved.latest.cell) == ("B8", "B15") and moved.defects == ()
    assert read(NASI_YIELD, shift=5, gap=2).latest.cell == "D15"
    far = read(shift=30)               # a header pushed past the search limit is reported, never guessed at
    assert kinds(far) == ["header_missing"] and not far.drawn and "first 30 rows" in far.defects[0].message


def test_a_table_may_run_oldest_first():
    base, flipped = read(), read(newest_first=False)
    assert [(q.day, q.value) for q in flipped.points] == [(q.day, q.value) for q in base.points]
    assert (flipped.latest.cell, flipped.points[0].cell) == ("B67", "B8") and flipped.defects == ()


def test_dates_that_go_on_below_the_last_value_are_ignored():
    base, tailed = read(), read(tail=5)
    assert tailed.defects == () and [(q.day, q.value) for q in tailed.points] == [(q.day, q.value) for q in base.points]


# ---------------------------------------------------------------------------
# Defects are listed by cell, left out and never repaired
# ---------------------------------------------------------------------------

def test_an_empty_value_cell_is_listed_and_left_out():
    s = read(edit=put(B20=None))
    assert kinds(s) == ["blank_value"] and cells(s, "blank_value") == ("B20",) and s.drawn
    assert len(s.points) == 59 and "B20" not in [q.cell for q in s.points]
    assert read(NASI_YIELD, edit=put(B20=None)).defects == ()      # the yield has its own columns


def test_text_in_a_value_cell_is_listed_and_left_out():
    s = read(edit=put(B20="n/a"))
    assert kinds(s) == ["non_numeric"] and cells(s, "non_numeric") == ("B20",) and len(s.points) == 59 and s.drawn


def test_a_value_with_no_date_is_listed_and_left_out():
    s = read(edit=put(A20=None))
    assert kinds(s) == ["missing_date"] and cells(s, "missing_date") == ("B20",) and len(s.points) == 59 and s.drawn


def test_this_weeks_value_typed_without_its_date_is_found_and_the_chart_is_stale():
    s = read(edit=put(A8=None))
    assert cells(s, "missing_date") == ("B8",) and s.latest.day == day(1)
    assert "stale" in kinds(s) and not s.drawn


def test_a_repeated_date_leaves_out_both_rows():
    s = read(edit=put(A12=dt(day(3))))     # row 12 now repeats row 11's date
    assert kinds(s) == ["duplicate_date"] and cells(s, "duplicate_date") == ("B11", "B12")
    assert len(s.points) == 58 and s.drawn


def test_a_date_out_of_order_leaves_out_both_rows_of_the_pair():
    s = read(edit=put(A20=dt(day(300))))     # row 20 is now older than row 21
    assert kinds(s) == ["out_of_order"] and cells(s, "out_of_order") == ("B20", "B21")
    assert len(s.points) == 58 and s.drawn


def test_one_empty_row_inside_the_table_does_not_end_it():
    p, y = read(edit=clear_rows(30, 30)), read(NASI_YIELD, edit=clear_rows(30, 30))
    assert (kinds(p), cells(p, "blank_value")) == (["blank_value"], ("B30",))
    assert (kinds(y), cells(y, "blank_value")) == (["blank_value"], ("D30",))
    assert len(p.points) == 59 and (p.latest.cell, p.points[0].cell) == ("B8", "B67")


def test_ten_empty_rows_in_a_row_end_the_table_and_nine_do_not():
    spec = replace(NASI_PE, min_points=1)
    nine = read_series(book(edit=clear_rows(40, 48)), spec, FRIDAY)
    ten = read_series(book(edit=clear_rows(40, 49)), spec, FRIDAY)
    assert len(nine.points) == 60 - 9 and len(cells(nine, "blank_value")) == 9
    assert "and 1 more" in nine.defects[0].message                 # eight references are named, the rest counted
    assert len(ten.points) == 32 and ten.defects == ()             # rows 8..39; nothing below the gap is read


# ---------------------------------------------------------------------------
# Blocking defects: the chart is not drawn
# ---------------------------------------------------------------------------

def test_a_number_format_that_contradicts_the_unit_stops_the_read():
    y = read(NASI_YIELD, edit=formats(D8="0.0"))     # a fraction shown as a plain number would be 100 times out
    p = read(NASI_PE, edit=formats(B8="0.0%"))
    for s in (y, p):
        assert kinds(s) == ["unit"] and s.defects[0].blocking and s.points == () and not s.drawn
    assert "D8" in y.defects[0].message and "a percentage" in y.defects[0].message


def test_a_renamed_sheet_names_similar_sheets_and_nothing_is_read_elsewhere():
    s = read(edit=lambda ws: setattr(ws, "title", "NASI PE & Dividend Yield"))
    assert kinds(s) == ["sheet_missing"] and not s.drawn and s.points == ()
    assert "'NASI PE & Dividend Yield'" in s.defects[0].message
    assert "Nothing was read from any other sheet" in s.defects[0].message
    other = read(edit=lambda ws: setattr(ws, "title", "Sheet1"))
    assert kinds(other) == ["sheet_missing"] and "similar" not in other.defects[0].message


def test_a_missing_or_repeated_header_stops_the_read():
    gone = read(edit=put(A6="Price / Earnings"))
    twice = read(edit=put(E2="Price to Earnings"))
    assert kinds(gone) == ["header_missing"] and not gone.drawn and gone.points == ()
    assert kinds(twice) == ["header_ambiguous"] and twice.defects[0].cells == ("E2", "A6")
    assert read(NASI_YIELD, edit=put(A6="Price / Earnings")).drawn      # the other chart's header is untouched


def test_an_empty_series_is_not_drawn():
    s = read(weeks=0)
    assert kinds(s) == ["empty"] and s.defects[0].blocking and s.points == () and not s.drawn


def test_too_few_points_is_not_drawn():
    s = read(weeks=10)
    assert kinds(s) == ["too_few"] and len(s.points) == 10 and not s.drawn


def test_a_newest_point_older_than_the_report_week_is_stale():
    s = read(newest=day(1))
    assert kinds(s) == ["stale"] and cells(s, "stale") == ("B8",) and s.latest.day == day(1) and not s.drawn


def test_a_point_dated_after_the_ceiling_is_not_drawn_and_not_removed():
    ahead = read(newest=FRIDAY + timedelta(days=7))
    saturday = read(newest=FRIDAY + timedelta(days=1))
    for s in (ahead, saturday):
        assert kinds(s) == ["future"] and cells(s, "future") == ("B8",) and not s.drawn
        assert len(s.points) == 60            # the row is flagged, not taken out for the coordinator


# ---------------------------------------------------------------------------
# The window and the average
# ---------------------------------------------------------------------------

def test_an_average_that_lands_exactly_on_a_half_rounds_up():
    spec = replace(NASI_PE, min_points=2)
    a = average(read_series(book(weeks=2, edit=put(B8=11.3, B9=11.2)), spec, FRIDAY))
    assert a.value == Decimal("11.25") and a.display == Decimal("11.3")
    assert round(11.25, 1) == 11.2           # Python's round() goes the other way: why round_half_up is used
    y = average(read_series(book(weeks=2, edit=put(D8=0.049, D9=0.048)), replace(NASI_YIELD, min_points=2), FRIDAY))
    assert (y.value, y.display) == (Decimal("4.85"), Decimal("4.9"))
    # 0.0485 is not exactly representable as a float; read through float arithmetic it would land below the half
    one = average(read_series(book(weeks=1, edit=put(D8=0.0485)), replace(NASI_YIELD, min_points=1), FRIDAY))
    assert (one.value, one.display) == (Decimal("4.85"), Decimal("4.9"))


def test_the_average_covers_every_point_since_2009_and_not_only_the_window():
    s = read(weeks=931)
    used = [n for n in range(931) if day(n) >= AVERAGE_FROM]
    assert 0 < len(used) < 931                      # the series reaches back before 2009; those points are not averaged
    exact = sum(Decimal(repr(pe(n))) for n in used) / len(used)
    a = average(s)
    assert s.drawn and a.count == len(used) and a.first >= AVERAGE_FROM and a.last == FRIDAY
    assert abs(a.value - exact) < Decimal("1e-20") and a.display == round_half_up(exact, 1)
    assert a.cells == f"B8:B{8 + used[-1]}"
    assert len(windowed(s)) < a.count               # the picture shows 7 years; the average does not stop there


def test_the_window_counts_years_back_from_the_newest_point_and_survives_29_february():
    days = [date(2017, 2, 27), date(2017, 2, 28), date(2020, 2, 29), date(2024, 2, 29)]
    pts = tuple(Point(d, Decimal(i), i + 8, f"B{i + 8}") for i, d in enumerate(days))
    s = ChartSeries(NASI_PE, date(2024, 3, 1), "B", pts, (), None)
    assert [p.day for p in windowed(s)] == days[1:]       # 7 years before 2024-02-29 is 2017-02-28 (2017 has no 29 February)
    assert windowed(ChartSeries(NASI_PE, FRIDAY, "", (), (), None)) == ()


# ---------------------------------------------------------------------------
# The workbook's own AVERAGE cell
# ---------------------------------------------------------------------------

def test_the_workbooks_own_average_is_compared_at_the_display_precision():
    spec = replace(NASI_PE, min_points=2)

    def two(**c):
        return read_series(book(weeks=2, edit=put(B8=11.3, B9=11.2, **c)), spec, FRIDAY)

    assert compare_average(two(B7=11.3)) == AverageCheck(None, None)         # B7 is the workbook's AVERAGE cell
    flag = compare_average(two(B7=11.2)).flag                                 # ours prints 11.3: a human call
    assert flag.kind == SOURCES_DISAGREE and sorted(s["normalized"] for s in flag.sources) == ["11.2", "11.3"]
    assert two(B7=11.3).stated == Stated("B7", Decimal("11.3"), None)


def test_a_formula_with_no_saved_value_is_reported_and_its_range_is_kept():
    s = read(edit=put(B7="=AVERAGE(B8:B67)"))
    assert s.stated == Stated("B7", None, "B8:B67") and kinds(s) == ["stated_unreadable"] and s.drawn
    assert compare_average(s) == AverageCheck(None, None)


def test_the_two_ranges_are_named_when_they_differ_even_if_the_figures_agree():
    ours = average(read()).display
    raw = nasi_bytes(edit=put(B7="=AVERAGE(B8:B20)"))
    s = read_series(Workbook(with_saved_values(raw, {"B7": ours}), "Equities workbook"), NASI_PE, FRIDAY)
    c = compare_average(s)
    assert s.defects == () and c.flag is None and "B8:B20" in c.note and "B8:B67" in c.note


def test_a_missing_average_label_is_reported_and_nothing_stands_in_for_it():
    s = read(edit=put(A7="Mean"))      # relabelled: no AVERAGE label to find
    assert s.stated is None and kinds(s) == ["stated_missing"] and s.drawn
    assert compare_average(s) == AverageCheck(None, None)
    bare = read(edit=put(A7=None))     # label deleted: the number is left with nothing beside it
    assert kinds(bare) == ["missing_date", "stated_missing"] and cells(bare, "missing_date") == ("B7",)


def test_data_straight_under_the_header_does_not_search_the_whole_sheet_for_the_label():
    # Sheet.find_all treats an empty row range as every row; a stray AVERAGE far below must not be picked up.
    spec = replace(NASI_PE, min_points=1)
    s = read_series(book(weeks=30, label=False, edit=put(A60="AVERAGE", B60=9.9)), spec, FRIDAY)
    assert s.stated is None and kinds(s) == ["stated_missing"]


# ---------------------------------------------------------------------------
# The figures the draft quotes
# ---------------------------------------------------------------------------

def test_the_last_point_and_the_average_must_equal_the_figures_the_draft_prints():
    p, y = read(NASI_PE), read(NASI_YIELD)
    pe_ok = {"pe": "10.0x", "pe_average": f"{average(p).display}x"}
    yield_ok = {"dividend_yield": "5.0%", "dividend_yield_average": f"{average(y).display}%"}
    assert check_quoted(p, pe_ok) == [] and check_quoted(y, yield_ok) == []
    assert check_quoted(p, {"pe": 10.0, "pe_average": average(p).display}) == []      # numbers as well as text

    wrong = check_quoted(p, {**pe_ok, "pe": "10.1x"})
    assert [(f.kind, f.field, f.expected) for f in wrong] == [(MISMATCH, "last point (pe)", "10.0")]
    off = check_quoted(y, {**yield_ok, "dividend_yield_average": "9.9%"})
    assert [(f.kind, f.field) for f in off] == [(MISMATCH, "average (dividend_yield_average)")]
    silent = check_quoted(p, {"pe": "10.0x"})                                          # the draft does not print the average
    assert [(f.kind, f.field) for f in silent] == [(MISSING, "average (pe_average)")]


def test_a_chart_that_is_not_drawn_has_no_plotted_point_to_compare():
    assert check_quoted(read(newest=day(1)), {"pe": "1.0x"}) == []
    assert check_quoted(read(edit=put(A6="x")), {"pe": "1.0x"}) == []


# ---------------------------------------------------------------------------
# The specs and the package
# ---------------------------------------------------------------------------

def test_the_specs_name_a_caption_and_figure_keys_the_equities_section_really_has(root):
    keys = set(figures(blocks(build(root))["valuation"]))
    assert len({s.id for s in SPECS.values()}) == len(SPECS)
    for spec in SPECS.values():
        assert spec.caption in eqw.CHARTS and spec.sheet == ch.SHEET
        assert {key for _, key in spec.quoted} <= keys


def test_the_chart_package_reads_no_chart_xml_and_adds_no_dependency():
    roots: set[str] = set()
    for f in Path(charts.__file__).parent.glob("*.py"):
        src = f.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                roots |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                roots.add(node.module.split(".")[0])
        assert "xl/charts" not in src and "drawingml" not in src, f.name
    assert roots <= set(sys.stdlib_module_names) | {"cytonn_weekly", "openpyxl"}
    assert not roots & {"zipfile", "xml", "lxml", "matplotlib"}
