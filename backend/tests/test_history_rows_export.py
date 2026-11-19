import hashlib
import io
from datetime import date

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from api.main import create_app
from cytonn_weekly.history import importer, rows_export, store
from cytonn_weekly.weekly import analyst, inputs
from cytonn_weekly.weekly.week import Week
from cytonn_weekly.weekly.workbook import Workbook
from tests import weekly_helpers as wh

WEEK = wh.WEEK
TODAY = date(2026, 10, 12)
SHEETS = ["Equities Turnover", "Foreign Positions", "NASI-PE & Dividend Yield", "Universe of Coverage", "Liquidity Indicators", "Eurobond",
          "Money Market Performance"]


def masters():
    return Workbook(wh.equities_workbook_bytes(), "eq.xlsx"), Workbook(wh.fi_workbook_bytes(), "fi.xlsx")


def fill(db, books, funds=(("Cytonn Money Market Fund ( Dial *809# or download Cytonn App)", "11.00"), ("Nabo Africa Money Market Fund", "10.00"))):
    for book in books:
        importer.apply(db, importer.read_workbook(book, TODAY))
    store.record_many(db, [{"key": "fi.mmf.rate", "subject": analyst.fund_key(name), "unit": "pct", "section": "fixed_income", "cadence": "week", "label": "Money market fund yield, by fund",
                            "as_of": WEEK.as_at.isoformat(), "week_ending": WEEK.ending.isoformat(), "value": rate, "origin": "typed", "source_kind": "form_field",
                            "source_ref": "x", "confirmed_by": store.FORM} for name, rate in funds])


@pytest.fixture
def full(tmp_path):
    eq, fi = masters()
    db = tmp_path / "h.db"
    fill(db, (eq, fi))
    return db, eq, fi, tmp_path


def sheet_rows(wb, name):
    return [[c.value for c in row] for row in wb[name].iter_rows()]


def notes(wb, name):
    return [r[0] for r in sheet_rows(wb, name) if isinstance(r[0], str) and r[0].startswith("Note: ")]


def test_the_export_has_one_sheet_per_workbook_sheet_with_the_masters_column_order_and_opens(full):
    db, eq, fi, tmp = full
    path = rows_export.write(WEEK, db, tmp / "out", eq, fi)
    assert path.parent == tmp / "out" and path.name == "Weekly rows, week ending 2026-10-02.xlsx"
    wb = load_workbook(path)
    assert wb.sheetnames == SHEETS
    assert sheet_rows(wb, "Equities Turnover")[0] == ["Date", "Turnover (USD mn)", "Year to date (USD mn)"]
    # the Universe's company order is the master's, and the new price column is headed as the readers look for it
    master_order = []
    for r in sheet_rows(load_workbook(io.BytesIO(wh.equities_workbook_bytes())), "Universe of Coverage")[2:]:
        if not r[1]:
            break
        master_order.append(analyst._key(r[1]))
    universe = sheet_rows(wb, "Universe of Coverage")
    assert universe[0] == ["Company", "Price as at 02/10/2026"]
    shown = [analyst._key(r[0]) for r in universe[1:] if r[0] and not str(r[0]).startswith("Note: ")]
    assert shown == master_order and all(r[1] is not None for r in universe[1:len(shown) + 1])
    assert any("column" in n and "Price as at 02/10/2026" in n for n in notes(wb, "Universe of Coverage"))
    # the fund table: the master's headings, best rate first, ranked
    funds = sheet_rows(wb, "Money Market Performance")
    assert funds[0] == ["Rank", "Fund Manager", "Effective Annual Rate"] and [r[0] for r in funds[1:3]] == [1, 2]
    assert funds[1][2] > funds[2][2]
    assert len(sheet_rows(wb, "Liquidity Indicators")[0]) == 3 and len(sheet_rows(wb, "Eurobond")[0]) == 6


def test_a_missing_point_is_an_empty_cell_with_a_note_naming_the_series_and_no_value(tmp_path):
    eq, fi = masters()
    db = tmp_path / "h.db"
    fill(db, (fi,), funds=())            # nothing for the equities sheets and no fund table
    wb = load_workbook(rows_export.write(WEEK, db, tmp_path / "out", None, fi))
    turnover = sheet_rows(wb, "Equities Turnover")
    assert all(r[1] is None and r[2] is None for r in turnover[1:len(WEEK.trading_days) + 2])
    text = "\n".join(notes(wb, "Equities Turnover"))
    assert "eq.turnover.day 2026-10-02: no confirmed point in the store, left empty" in text and "eq.turnover.ytd 2026-10-02" in text
    assert "No equities workbook is uploaded for this week: columns follow the reader's constants" in text   # said on the sheet
    assert "eq.pe 2026-10-02: no confirmed point" in "\n".join(notes(wb, "NASI-PE & Dividend Yield"))
    assert "fi.mmf.rate 2026-10-02: no confirmed point" in "\n".join(notes(wb, "Money Market Performance"))
    assert "uploaded fixed income workbook" in "\n".join(notes(wb, "Liquidity Indicators"))


def test_a_point_that_is_not_confirmed_is_not_exported(tmp_path):
    eq, fi = masters()
    db = tmp_path / "h.db"
    fill(db, (eq, fi))
    store.record_many(db, [{"key": "eq.pe", "subject": "", "unit": "multiple", "section": "equities", "cadence": "week", "label": "Market P/E", "as_of": "2026-10-02",
                            "week_ending": "2026-10-02", "value": "55.5", "origin": "carried", "source_kind": "form_field", "source_ref": "x", "confirmed_by": None}])
    wb = load_workbook(rows_export.write(WEEK, db, tmp_path / "out", eq, fi))
    assert sheet_rows(wb, "NASI-PE & Dividend Yield")[1][1] != 55.5


def test_the_formula_columns_are_values_with_a_note_and_the_average_row_is_not_exported(full):
    db, eq, fi, tmp = full
    wb = load_workbook(rows_export.write(WEEK, db, tmp / "out", eq, fi))
    assert not [c for ws in wb for row in ws.iter_rows() for c in row if c.data_type == "f"]
    for name in ("Equities Turnover", "Foreign Positions"):
        week_row = next(r for r in sheet_rows(wb, name)[1:] if r[0] is None and r[1] is not None)   # the weekly row: no date, its sum, its running total
        assert isinstance(week_row[1], (int, float)) and isinstance(week_row[2], (int, float))
        assert any("formulas in the master and are values here" in n for n in notes(wb, name))
    valuation = sheet_rows(wb, "NASI-PE & Dividend Yield")
    assert not any(str(r[0]).upper().startswith("AVERAGE") for r in valuation) and any("AVERAGE row is not exported" in n for n in notes(wb, "NASI-PE & Dividend Yield"))


def test_the_weeks_figures_are_the_stores_points_as_the_master_holds_them(full):
    db, eq, fi, tmp = full
    wb = load_workbook(rows_export.write(WEEK, db, tmp / "out", eq, fi))
    pe, dy = (store.current(db, k)[-1] for k in ("eq.pe", "eq.dividend_yield"))
    row = sheet_rows(wb, "NASI-PE & Dividend Yield")[1]
    assert row[0].date() == WEEK.as_at and row[1] == float(pe["value"]) and abs(row[2] - float(dy["value"]) / 100) < 1e-9   # a fraction, as the master holds it
    assert "eq.pe" not in "\n".join(notes(wb, "NASI-PE & Dividend Yield"))


def test_the_masters_are_never_modified(tmp_path):
    root = tmp_path / "weekly"
    eq_bytes, fi_bytes = wh.equities_workbook_bytes(), wh.fi_workbook_bytes()
    inputs.store(WEEK, "equities_workbook", eq_bytes, "e.xlsx", root)
    inputs.store(WEEK, "fi_workbook", fi_bytes, "f.xlsx", root)
    db = tmp_path / "app.db"
    fill(db, masters())
    stored = sorted(p for p in root.rglob("*.xlsx"))
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in stored}
    client = TestClient(create_app(db_path=db, load_dotenv=False, inputs_root=root, export_root=tmp_path / "exports"))
    r = client.post("/api/export/weekly-rows/2026-10-02")
    assert r.status_code == 200 and r.headers["content-type"].endswith("spreadsheetml.sheet")
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in stored} and len(stored) == 2
    assert [p.name for p in (tmp_path / "exports").iterdir()] == ["Weekly rows, week ending 2026-10-02.xlsx"]      # and nowhere else
    assert sorted(p for p in root.rglob("*.xlsx")) == stored                                                         # nothing new in the inputs
    out = tmp_path / "got.xlsx"
    out.write_bytes(r.content)
    wb = load_workbook(out)
    assert wb.sheetnames == SHEETS and any("Columns read from the uploaded equities workbook" in n for n in notes(wb, "Universe of Coverage"))


def test_the_route_refuses_a_day_that_is_not_a_friday_and_works_with_no_workbook_uploaded(tmp_path):
    client = TestClient(create_app(db_path=tmp_path / "app.db", load_dotenv=False, inputs_root=tmp_path / "weekly", export_root=tmp_path / "exports"))
    assert client.post("/api/export/weekly-rows/2026-10-01").status_code == 422
    r = client.post("/api/export/weekly-rows/2026-10-02")
    assert r.status_code == 200 and (tmp_path / "exports").exists()
