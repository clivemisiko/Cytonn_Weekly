from __future__ import annotations

import logging
from typing import Any

import pytest

from cytonn_weekly.weekly import analyst, inputs
from cytonn_weekly.weekly.workbook import Cell
from tests import weekly_helpers as wh
from tests.weekly_helpers import text_pdfs  # noqa: F401 - a fixture

WEEK = wh.WEEK


@pytest.fixture
def books(tmp_path, text_pdfs):
    inputs.store(WEEK, "kcb_weekly", wh.fake_pdf(wh.kcb_weekly_text()), "weekly.pdf", tmp_path)
    inputs.store(WEEK, "fi_workbook", wh.fi_workbook_bytes(), "FI.xlsx", tmp_path)
    inputs.store(WEEK, "equities_workbook", wh.equities_workbook_bytes(), "Equities.xlsx", tmp_path)
    return tmp_path


def test_status_logs_its_duration_and_the_kind_of_each_file_it_parsed(books, caplog):
    with caplog.at_level(logging.INFO, logger="cytonn_weekly.weekly.analyst"):
        analyst.status(WEEK, books)
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("analyst status:"))
    assert "section=all" in line and "seconds=" in line
    assert "fixed income workbook" in line and "equities workbook" in line
    assert ".xlsx" not in line and ".pdf" not in line


@pytest.fixture
def typed(books):
    """Both workbooks stored and every item typed from them, two typed so that they differ from the workbook."""
    changes = wh.typed_from_workbooks(WEEK, books)
    changes["fields"].update(placements="9.9", pe="9")
    analyst.save_form(WEEK, changes, books)
    return books


@pytest.mark.parametrize("section", sorted(analyst.WORKBOOKS))
def test_one_section_gets_what_the_whole_form_gives_it(typed, section):
    whole = analyst.status(WEEK, typed)
    mine = analyst.status(WEEK, typed, section)
    assert mine["groups"] == [g for g in whole["groups"] if g["section"] == section]
    assert any(i["differences"] for g in mine["groups"] for i in g["items"])   # the typed differences are there
    assert {k: v for k, v in mine.items() if k not in ("groups", "unconfirmed")} == \
        {k: v for k, v in whole.items() if k not in ("groups", "unconfirmed")}


@pytest.mark.parametrize("section", sorted(analyst.WORKBOOKS))
def test_the_other_sections_readers_and_workbook_are_not_touched(typed, section, monkeypatch):
    from cytonn_weekly.weekly import equities_workbook, fi_workbook

    def refuse(*a, **k):
        raise AssertionError("the other section was read")

    other = {analyst.FI: ("foreign_history", "universe"),
             analyst.EQ: ("mmf", "interbank", "eurobonds", "remittances", "borrowing")}[section]
    for name in other:
        monkeypatch.setattr(analyst.Analyst, name, refuse)
    opener = (equities_workbook, "open_equities_workbook") if section == analyst.FI else (fi_workbook, "open_fi_workbook")
    monkeypatch.setattr(*opener, refuse)
    got = analyst.status(WEEK, typed, section)
    assert got["workbooks"] == {analyst.FI: True, analyst.EQ: True}


def _count(monkeypatch, module, name):
    calls = []
    real = getattr(module, name)
    monkeypatch.setattr(module, name, lambda *a, **k: calls.append(1) or real(*a, **k))
    return calls


def test_an_unchanged_file_is_parsed_once_across_requests(books, monkeypatch, caplog):
    from cytonn_weekly.weekly import fi_workbook

    calls = _count(monkeypatch, fi_workbook, "open_fi_workbook")
    first, second = inputs.WeeklyInputs(WEEK, books).fi_book, inputs.WeeklyInputs(WEEK, books).fi_book
    assert len(calls) == 1 and first is not second
    with caplog.at_level(logging.INFO, logger="cytonn_weekly.weekly.analyst"):
        analyst.status(WEEK, books, analyst.FI)
    assert "fixed income workbook from cache" in caplog.text and len(calls) == 1


def test_a_replaced_file_is_parsed_again(books, monkeypatch):
    import os

    from cytonn_weekly.weekly import fi_workbook

    calls = _count(monkeypatch, fi_workbook, "open_fi_workbook")
    inputs.WeeklyInputs(WEEK, books).fi_book
    path = inputs.week_dir(WEEK, books) / "fi_workbook.xlsx"
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))   # same size, new time
    inputs.WeeklyInputs(WEEK, books).fi_book
    inputs.store(WEEK, "fi_workbook", wh.fi_workbook_bytes(funds=[("Alpha Fund", 9.0)]), "FI.xlsx", books)   # new bytes
    assert len(calls) == 3   # the store opens the new file once to check it
    inputs.WeeklyInputs(WEEK, books).fi_book
    assert len(calls) == 4


def test_two_requests_do_not_share_what_they_read(monkeypatch, tmp_path):
    import io

    from openpyxl import Workbook as Xlsx

    from cytonn_weekly.weekly.workbook import Workbook

    xlsx = Xlsx()
    xlsx.active.title = "Shown"
    xlsx.create_sheet("Kept").sheet_state = "hidden"
    xlsx["Kept"]["A1"] = 1
    buf = io.BytesIO()
    xlsx.save(buf)
    cached = Workbook(buf.getvalue(), "Book")
    one, two = cached.shared_copy(), cached.shared_copy()
    one.sheet("Kept")
    assert one.hidden_lines() and not two.hidden_lines() and not cached.hidden_lines()
    assert two.sheet("Kept") is one.sheet("Kept")          # the grid is shared ...
    assert two.hidden_lines() == one.hidden_lines()         # ... and the second still reports reading it


def test_a_cached_pdf_comes_back_as_a_copy(books):
    first = inputs.WeeklyInputs(WEEK, books).kcb_weekly
    first.problems.append("recorded by one request")
    assert "recorded by one request" not in inputs.WeeklyInputs(WEEK, books).kcb_weekly.problems


def _count_formula_opens(monkeypatch) -> list[bool]:
    from cytonn_weekly.weekly import workbook

    opened: list[bool] = []
    real = workbook.load_workbook

    def counting(*args, **kwargs):
        if kwargs.get("data_only") is False:
            opened.append(True)
        return real(*args, **kwargs)

    monkeypatch.setattr(workbook, "load_workbook", counting)
    return opened


def test_two_requests_open_the_formulas_workbook_once(books, monkeypatch):
    opened = _count_formula_opens(monkeypatch)
    analyst.status(WEEK, books, analyst.EQ)
    analyst.status(WEEK, books, analyst.EQ)
    assert len(opened) == 1


def test_a_replaced_workbook_is_not_served_its_old_formulas(books):
    first = inputs.WeeklyInputs(WEEK, books).equities_book
    first.formula(Cell(None, first.sheet_names[0], 1, 1))   # the old file's formulas are now in its holder
    path = inputs.week_dir(WEEK, books) / "equities_workbook.xlsx"
    path.write_bytes(_book_with_formulas({"A1": "=1+1"}))   # a new size, so a new cache key whatever the clock gives
    second = inputs.WeeklyInputs(WEEK, books).equities_book
    assert second._formula_cache is not first._formula_cache
    assert second.formula(Cell(None, "Sheet", 1, 1)) == "=1+1"


def _book_with_formulas(cells: dict[str, Any]) -> bytes:
    import io

    from openpyxl import Workbook as XlsxWorkbook

    wb = XlsxWorkbook()
    ws = wb.active
    ws.title = "Sheet"
    for ref, value in cells.items():
        ws[ref] = value
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_formula_reads_every_cell_as_the_per_cell_scan_did():
    import io
    import warnings

    from openpyxl import load_workbook

    from cytonn_weekly.weekly.workbook import Workbook

    cells = {"B2": "=A2*2", "C2": 5, "D4": "=SUM(B2:C2)", "A7": "text", "F7": "=AVERAGE(B8:B938)", "C9": None, "E12": "=1"}
    data = _book_with_formulas(cells)
    book = Workbook(data, "synthetic")
    raw = load_workbook(io.BytesIO(data), read_only=True, data_only=False)["Sheet"]
    for row in range(1, 15):          # past the last used row and column, where both give None
        for col in range(1, 9):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                old = next(iter(raw.iter_rows(min_row=row, max_row=row, min_col=col, max_col=col, values_only=True)))[0]
            expected = old if isinstance(old, str) and old.startswith("=") else None
            assert book.formula(Cell(None, "Sheet", row, col)) == expected, (row, col)


def test_hidden_sheet_reads_stay_with_each_copy():
    import io

    from openpyxl import Workbook as XlsxWorkbook

    from cytonn_weekly.weekly.workbook import Workbook

    wb = XlsxWorkbook()
    wb.active.title = "Shown"
    wb.active["A1"] = "=1"
    hidden = wb.create_sheet("Kept")
    hidden["A1"] = "=2"
    hidden.sheet_state = "hidden"
    out = io.BytesIO()
    wb.save(out)
    cached = Workbook(out.getvalue(), "synthetic")
    one, two = cached.shared_copy(), cached.shared_copy()
    one.sheet("Kept")
    assert one.formula(Cell(None, "Kept", 1, 1)) == "=2"
    assert two.formula(Cell(None, "Kept", 1, 1)) == "=2"   # the formulas come from the shared holder
    assert one._formula_cache is two._formula_cache is cached._formula_cache
    assert one.hidden_lines() and not two.hidden_lines() and not cached.hidden_lines()
