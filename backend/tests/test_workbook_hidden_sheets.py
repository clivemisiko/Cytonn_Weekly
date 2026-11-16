import io

import pytest
from openpyxl import Workbook as XlsxWorkbook
from openpyxl import load_workbook

from cytonn_weekly.fixed_income import weekly as fiw
from cytonn_weekly.weekly import inputs
from cytonn_weekly.weekly.workbook import Workbook
from tests import weekly_helpers as wh
from tests.test_weekly_fixed_income import BULLETIN, WEEK, fetchers


def three_sheets() -> bytes:
    wb = XlsxWorkbook()
    wb.active.title = "Shown"
    wb.active["A1"] = 1
    wb.create_sheet("Quiet")["A1"] = 2
    wb.create_sheet("Secret")["A1"] = 3
    wb["Quiet"].sheet_state = "hidden"
    wb["Secret"].sheet_state = "veryHidden"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_a_visible_sheet_gives_no_line_and_a_hidden_one_only_when_it_is_read():
    book = Workbook(three_sheets(), "The test workbook")
    assert book.hidden_lines() == []
    book.sheet("Shown")
    assert book.hidden_lines() == []                        # reading a visible sheet says nothing
    assert book.sheet("Quiet").value(1, 1) == 2
    assert book.hidden_lines() == ["The test workbook: values were read from the hidden sheet 'Quiet'. "
                                   "Check that the team means that sheet to be used."]
    book.sheet("Secret")
    assert book.hidden_lines()[1] == ("The test workbook: values were read from the very hidden sheet 'Secret' "
                                      "(Excel's Unhide menu does not list it). Check that the team means that sheet to be used.")
    book.sheet("Quiet")
    assert len(book.hidden_lines()) == 2                    # one line a sheet, however often it is read


def test_a_number_format_read_counts_as_reading_the_sheet():
    book = Workbook(three_sheets(), "The test workbook")
    from cytonn_weekly.weekly.workbook import Cell

    book.number_format(Cell(2, "Quiet", 1, 1))
    assert len(book.hidden_lines()) == 1


def hide(workbook_bytes: bytes, sheet: str, state: str) -> bytes:
    wb = load_workbook(io.BytesIO(workbook_bytes))
    wb[sheet].sheet_state = state
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


@pytest.mark.parametrize("state, said", [("visible", None), ("hidden", "hidden sheet 'Treasury Bills '"),
                                         ("veryHidden", "very hidden sheet 'Treasury Bills '")])
def test_a_fixed_income_draft_says_which_hidden_sheet_it_read(tmp_path, state, said):
    inputs.store(WEEK, "cbk_bulletin", BULLETIN, "bulletin.pdf", tmp_path)
    inputs.store(WEEK, "fi_workbook", hide(wh.fi_workbook_bytes(), "Treasury Bills ", state), "FI.xlsx", tmp_path)
    review = fiw.build_fixed_income_review(WEEK.ending, inputs=inputs.WeeklyInputs(WEEK, tmp_path), fetchers=fetchers(),
                                           draft=wh.no_draft)
    lines = [w for w in review.section["warnings"] if "values were read from the" in w]
    if said is None:
        assert lines == []
    else:
        assert any(said in w and w.endswith("Check that the team means that sheet to be used.") for w in lines)


def test_a_draft_with_no_workbook_has_no_hidden_sheet_line(tmp_path):
    inputs.store(WEEK, "cbk_bulletin", BULLETIN, "bulletin.pdf", tmp_path)
    review = fiw.build_fixed_income_review(WEEK.ending, inputs=inputs.WeeklyInputs(WEEK, tmp_path), fetchers=fetchers(),
                                           draft=wh.no_draft)
    assert not any("values were read from the" in w for w in review.section["warnings"])
