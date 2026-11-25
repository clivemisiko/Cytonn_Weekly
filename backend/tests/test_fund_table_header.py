import pytest
from openpyxl import load_workbook

from cytonn_weekly.history import rows_export
from cytonn_weekly.weekly import fi_workbook, inputs
from cytonn_weekly.weekly.workbook import Workbook, WorkbookError
from tests import weekly_helpers as wh
from tests.test_history_rows_export import fill, sheet_rows
from tests.test_weekly_analyst import item, stores
from tests.test_workbook_first_mmf import where
from tests.weekly_helpers import text_pdfs  # noqa: F401 - a fixture

WEEK = wh.WEEK
PLAIN = "The workbook's fund table could not be read: "


def book(header):
    return Workbook(wh.fi_workbook_bytes(rate_header=header), "fi.xlsx")


@pytest.mark.parametrize("header", ["Effective", "  effective  ", "EFFECTIVE ANNUAL RATE", "Effective Annual Rate"])
def test_the_rate_heading_is_matched_by_its_start(header):
    table = fi_workbook.read_mmf_table(book(header), WEEK)
    assert [f["fund"].value for f in table["funds"]] == [f for f, _ in wh.FUNDS]


@pytest.mark.parametrize("header", ["Annual Rate", "Rate", "Yield"])
def test_another_heading_is_still_refused(header):
    with pytest.raises(WorkbookError):
        fi_workbook.read_mmf_table(book(header), WEEK)


def test_the_rows_export_reads_the_short_heading(tmp_path):
    db = tmp_path / "h.db"
    master = book("Effective")
    fill(db, (master,))
    wb = load_workbook(rows_export.write(WEEK, db, tmp_path / "out", None, master))
    assert sheet_rows(wb, "Money Market Performance")[0] == ["Rank", "Fund Manager", "Effective"]


@pytest.fixture
def unreadable(tmp_path, text_pdfs):  # noqa: F811
    stores(tmp_path)
    inputs.store(WEEK, "fi_workbook", wh.fi_workbook_bytes(rate_header="Rate"), "FI.xlsx", tmp_path)
    return tmp_path


def test_an_unreadable_table_says_why_on_the_form_and_in_readiness_and_covers_nothing(unreadable):
    mmf = item("mmf", unreadable)
    assert mmf["workbook_rows"] is None and mmf["workbook_stale"] is None
    assert mmf["workbook_note"].startswith(PLAIN) and "Effective Annual Rate header" in mmf["workbook_note"]
    assert "'" not in mmf["workbook_note"].removeprefix("The workbook's")
    group, why = where(unreadable)["mmf"]
    assert group == "needs_analyst" and why == "nothing typed. " + mmf["workbook_note"]
    # the published date comes from the same read, so it says the same and is not covered either
    published = item("mmf_published", unreadable)
    assert published["workbook"] is None and published["workbook_note"] == mmf["workbook_note"]
    assert where(unreadable)["mmf_published"][0] == "needs_analyst"
    # the rest of the sheet still reads: the slot is not said to be unreadable
    assert item("placements", unreadable)["workbook"] is not None
    assert where(unreadable)["placements"] == ("in_place", "from the workbook")


def test_the_short_heading_folds_the_table_and_its_date(tmp_path, text_pdfs):  # noqa: F811
    stores(tmp_path)
    inputs.store(WEEK, "fi_workbook", wh.fi_workbook_bytes(rate_header="Effective"), "FI.xlsx", tmp_path)
    assert item("mmf", tmp_path)["workbook_rows"] and item("mmf_published", tmp_path)["workbook"]
    assert where(tmp_path)["mmf"][0] == where(tmp_path)["mmf_published"][0] == "in_place"
