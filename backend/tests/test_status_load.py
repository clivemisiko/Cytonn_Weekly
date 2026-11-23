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
