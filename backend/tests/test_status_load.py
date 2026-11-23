from __future__ import annotations

import logging

import pytest

from cytonn_weekly.weekly import analyst, inputs
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
