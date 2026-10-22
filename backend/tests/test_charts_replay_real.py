"""Replay of the chart readers on the real equities workbook: relations only, never a value.

The workbook is confidential and not in the repository.  These tests read it from "sample data/"
(or CYTONN_SAMPLE_DIR) and skip when it is absent or locked.  Each one asserts a relation between
the new reader and something already trusted (the weekly section's own valuation reader, the
workbook's own AVERAGE cell) or a property of the table, and asserts on a plain True/False so that
a failure names the relation and never prints a workbook value.
"""

from datetime import date

import pytest

from cytonn_weekly.charts.series import average, compare_average, read_series, windowed
from cytonn_weekly.charts.specs import NASI_PE, NASI_YIELD
from cytonn_weekly.checkers.digital_payments import parse_number
from cytonn_weekly.weekly import equities_workbook
from cytonn_weekly.weekly.week import Week
from cytonn_weekly.weekly.workbook import Workbook
from tests import weekly_helpers as wh

NAME = "Equities Workbook 02.10.2026.v6 (1).xlsx"
WEEK = Week(date(2026, 10, 2))        # the week the file is for, as its name says
NON_BLOCKING = {"blank_value", "non_numeric", "missing_date", "duplicate_date", "out_of_order",
                "stated_missing", "stated_unreadable"}


def holds(ok: bool, relation: str) -> None:
    assert ok, f"relation does not hold: {relation}"


@pytest.fixture(scope="module")
def real():
    book = Workbook(wh.sample(NAME), "Equities workbook")
    return book, {s.id: read_series(book, s, WEEK.ending) for s in (NASI_PE, NASI_YIELD)}


def test_both_charts_read_and_are_current(real):
    _, got = real
    for sid, s in got.items():
        days = [p.day for p in s.points]
        holds(s.drawn, f"{sid} has no blocking defect")
        holds(all(d.kind in NON_BLOCKING for d in s.defects), f"{sid} has only known, non-blocking defects")
        holds(s.latest is not None and s.latest.day == WEEK.ending, f"{sid}'s newest point is the week's Friday")
        holds(all(a < b for a, b in zip(days, days[1:])), f"{sid}'s dates are strictly increasing")
        holds(average(s) is not None and average(s).count > len(windowed(s)), f"{sid}'s average covers more than its window")


def test_the_newest_points_equal_what_the_weekly_section_already_reads(real):
    book, got = real
    v = equities_workbook.read_valuation(book, WEEK)
    holds(got["nasi_pe"].latest.value == parse_number(v["pe"].number), "the newest P/E equals read_valuation's P/E")
    holds(got["nasi_pe"].latest.cell == v["pe"].a1, "the newest P/E is read from the same cell")
    holds(got["nasi_yield"].latest.value == parse_number(v["dividend_yield"].number) * 100,
          "the newest yield equals read_valuation's dividend yield, as percentage points")


def test_the_workbooks_average_cells_are_the_ones_the_weekly_section_reads(real):
    book, got = real
    v = equities_workbook.read_valuation(book, WEEK)
    for sid, cell in (("nasi_pe", v["pe_average"]), ("nasi_yield", v["dividend_yield_average"])):
        st = got[sid].stated
        holds(st is not None and st.cell == cell.a1, f"{sid}'s AVERAGE cell is the cell read_valuation reads")
        holds(st.value == parse_number(cell.number) * got[sid].spec.scale, f"{sid}'s AVERAGE value is read the same")


def test_each_average_prints_the_same_figure_as_the_workbooks_own(real):
    _, got = real
    for sid, s in got.items():
        check = compare_average(s)
        holds(s.stated is not None and s.stated.value is not None, f"{sid} has a saved AVERAGE value to compare with")
        holds(check.flag is None, f"{sid}'s average prints the same figure as the workbook's AVERAGE cell")
