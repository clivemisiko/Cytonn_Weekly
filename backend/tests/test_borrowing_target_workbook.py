import io

import pytest
from openpyxl import load_workbook

from cytonn_weekly.fixed_income import net_borrowing as nb
from cytonn_weekly.weekly import analyst, fi_workbook, inputs
from cytonn_weekly.weekly.workbook import Workbook, WorkbookError
from tests import weekly_helpers as wh
from tests.test_borrowing_history import draft
from tests.test_weekly_fixed_income import blocks, figures, items
from tests.test_workbook_week import without_date

# Every figure below is invented; the synthetic workbook's target (910) sits under its header in X47.
WEEK = wh.WEEK
LABEL = analyst.FIELDS["borrowing_target"].label


@pytest.fixture
def root(tmp_path):
    return tmp_path / "data" / "weekly"


def book(edit=None, **kw) -> bytes:
    wb = load_workbook(io.BytesIO(wh.fi_workbook_bytes(**kw)))
    if edit:
        edit(wb[fi_workbook.BORROWING_SHEET])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def item(root, week=WEEK):
    return next(i for g in analyst.status(week, root, "fixed_income")["groups"] for i in g["items"] if i["key"] == "borrowing_target")


def upload(root, data):
    inputs.store(WEEK, "fi_workbook", data, "FI.xlsx", root)


def test_the_switches_read_the_target_alone():
    assert nb.WORKBOOK_BORROWING is False and nb.WORKBOOK_TARGET is True


@pytest.mark.parametrize("down", [0, 3])
def test_the_target_is_read_by_its_header_wherever_the_table_sits(down):
    data = book(lambda ws: ws.move_range("X47:Y48", rows=down)) if down else book()
    cell = fi_workbook.read_borrowing_target(Workbook(data, "FI.xlsx"))
    assert cell.number == 910.0 and cell.row == 48 + down


@pytest.mark.parametrize("edit, words", [
    (lambda ws: ws.__setitem__("X48", "n/a"), "net domestic borrowing target"),
    (lambda ws: ws.__setitem__("X48", 9000), "outside the expected range of 1 to 5,000 Kshs bn"),
    (lambda ws: ws.__setitem__("X48", 0.5), "outside the expected range of 1 to 5,000 Kshs bn"),
    (lambda ws: ws.__setitem__("X47", "Target"), "Budget Borrowing target (Kshs bn)"),
])
def test_a_bad_target_is_refused_in_plain_words_and_covers_nothing(root, edit, words):
    with pytest.raises(WorkbookError, match=words.replace("(", r"\(").replace(")", r"\)")):
        fi_workbook.read_borrowing_target(Workbook(book(edit), "FI.xlsx"))
    upload(root, book(edit))
    got = item(root)
    assert got["workbook"] is None
    assert got["workbook_note"].startswith("The workbook's net domestic borrowing target could not be read:")


def test_this_weeks_workbook_covers_the_target(root):
    upload(root, book())
    got = item(root)
    assert got["workbook"]["ref"].endswith("X48")
    assert got["value"] is None and not got["differences"]


@pytest.mark.parametrize("data", [lambda: book(updated=False), lambda: without_date("fixed_income")], ids=["earlier", "undated"])
def test_an_earlier_or_undated_workbook_covers_nothing(root, data):
    upload(root, data())
    assert item(root)["workbook"] is None
    assert inputs.WeeklyInputs(WEEK, root).analyst.field("borrowing_target") is None


def test_typed_this_week_wins_and_the_difference_is_shown_and_flagged(root):
    upload(root, book())
    analyst.save_form(WEEK, {"fields": {"borrowing_target": "900"}}, root)
    got = item(root)
    assert got["value"] == "900" and any("The typed value is used." in d for d in got["differences"])
    review = draft(root, WEEK, target=False)
    assert any(w for w in review.section["warnings"] if LABEL in w and "The typed value is used." in w)
    assert [i.status for i in items(review, "Pro-rated net domestic borrowing target")] == ["flagged"]


def test_a_carried_target_wins_and_the_difference_is_shown_and_flagged(root):
    analyst.save_form(WEEK.previous, {"fields": {"borrowing_target": "900"}}, root)
    assert "borrowing_target" in analyst.carry_forward(WEEK, root)["carried"]
    upload(root, book())
    got = item(root)
    assert got["value"] == "900" and got["carried"] is not None
    assert any("The typed value is used." in d for d in got["differences"])
    review = draft(root, WEEK, target=False)
    assert inputs.WeeklyInputs(WEEK, root).analyst.field("borrowing_target").number == 900.0
    assert any(w for w in review.section["warnings"] if LABEL in w and "The typed value is used." in w)
    assert [i.status for i in items(review, "Pro-rated net domestic borrowing target")] == ["flagged"]


def test_the_workbook_target_gives_the_same_figures_as_the_same_value_typed(tmp_path):
    from_book, typed = tmp_path / "a", tmp_path / "b"
    upload(from_book, book())
    analyst.save_form(WEEK, {"fields": {"borrowing_target": "910"}}, typed)
    a, b = blocks(draft(from_book, WEEK, target=False))["borrowing"], blocks(draft(typed, WEEK, target=False))["borrowing"]
    assert a["kind"] == b["kind"] == "computed"
    assert figures(a) == figures(b) and a["body_md"] == b["body_md"]
    assert {"name": fi_workbook_name()} in a["sources"]


def fi_workbook_name():
    from cytonn_weekly.fixed_income import weekly as fiw

    return fiw.WB


def test_the_log_and_redemptions_still_ignore_the_workbook(root):
    upload(root, book())
    a = inputs.WeeklyInputs(WEEK, root).analyst
    assert a.wb_borrowing() is None and a.wb_rows("borrowing_log") is None and a.wb_rows("borrowing_redemptions") is None
    assert a.borrowing()["log"] is None
