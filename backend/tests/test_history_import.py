import importlib.util
import io
import sqlite3
from datetime import date, datetime
from decimal import Decimal

import pytest
from openpyxl import Workbook as XlWorkbook

from cytonn_weekly.history import importer, store
from cytonn_weekly.paths import BACKEND_ROOT
from cytonn_weekly.weekly import equities_workbook as eq
from cytonn_weekly.weekly.workbook import Workbook
from tests.weekly_helpers import WEEK, equities_workbook_bytes, fi_workbook_bytes

TODAY = date(2026, 10, 12)
SCRIPT = BACKEND_ROOT / "scripts" / "import_history.py"


def book(data: bytes, name="invented.xlsx") -> Workbook:
    return Workbook(data, name)


def mini(rows_by_sheet: dict) -> Workbook:
    """A workbook with only the named sheets, one row per tuple, from row 1."""
    wb = XlWorkbook()
    wb.remove(wb.active)
    for name, rows in rows_by_sheet.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(list(r))
    out = io.BytesIO()
    wb.save(out)
    return book(out.getvalue())


def points(plan, key):
    return [p for p in plan.points if p["key"] == key]


def rows_in(path, sql="SELECT * FROM series_points"):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql)]
    finally:
        conn.close()


def test_the_synthetic_workbooks_give_points_by_sheet_with_their_cells():
    plan = importer.read_workbook(book(equities_workbook_bytes()), TODAY)
    assert plan.errors == [] and set(plan.sheets) == {eq.TURNOVER_SHEET, eq.FOREIGN_SHEET, eq.VALUATION_SHEET, eq.UNIVERSE_SHEET}
    assert {p["key"] for p in plan.points} >= {"eq.turnover.day", "eq.turnover.week", "eq.turnover.ytd", "eq.foreign.week", "eq.pe", "eq.dividend_yield", "eq.price"}
    assert all(p["origin"] == "workbook_import" and p["source_kind"] == "workbook_cell" and "!" in p["source_ref"] for p in plan.points)
    assert points(plan, "eq.price") and all(p["subject"] for p in points(plan, "eq.price"))
    fi = importer.read_workbook(book(fi_workbook_bytes()), TODAY)
    assert fi.errors == [] and {p["key"] for p in fi.points} == {"fi.interbank.volume", "fi.interbank.rate", "fi.eurobond.yield"}


def test_percentages_are_stored_as_printed_and_prices_and_multiples_as_they_are():
    b = book(equities_workbook_bytes())
    valuation = eq.read_valuation(b, WEEK)
    plan = importer.read_workbook(b, TODAY)
    on = {p["key"]: Decimal(p["value"]) for p in plan.points if p["as_of"] == WEEK.as_at.isoformat() and p["key"] in ("eq.pe", "eq.dividend_yield")}
    assert on["eq.pe"] == Decimal(repr(valuation["pe"].number)) and on["eq.dividend_yield"] == Decimal(repr(valuation["dividend_yield"].number)) * 100


def test_rows_are_set_aside_with_a_reason_and_never_guessed():
    d = datetime
    plan = importer.read_workbook(mini({eq.VALUATION_SHEET: [
        ("Date", "P/E", None, "Dividend yield"),
        (d(2026, 10, 2), 9.5, None, 0.05),      # kept
        (d(2026, 10, 3), 9.6, None, 0.05),      # a Saturday: kept here, because the workbook's AVERAGE counts it
        (d(2026, 10, 9), None, None, 0.05),     # no P/E
        (d(2026, 10, 16), 9.7, None, 0.05),     # after today
        (d(2026, 10, 2), 9.5, None, 0.05),      # the same date, the same numbers
        ("AVERAGE", 9.0, None, 0.05)]}), TODAY)
    assert [(p["as_of"], p["week_ending"], p["value"]) for p in points(plan, "eq.pe")] == [("2026-10-02", "2026-10-02", "9.5"), ("2026-10-03", "2026-10-02", "9.6")]
    assert plan.skipped[("eq.pe", "no number in the cell")] == 1 and plan.skipped[("eq.pe", "dated after today")] == 1
    assert plan.skipped[("eq.pe", "the same date twice with the same number (one kept)")] == 1
    assert points(plan, "eq.dividend_yield")[0]["value"] == "5"


def test_a_weekend_day_in_a_daily_sheet_is_set_aside():
    plan = importer.read_workbook(mini({eq.TURNOVER_SHEET: [("Date", "USD mn"), (datetime(2026, 10, 2), 5), (datetime(2026, 10, 3), 6)]}), TODAY)
    assert [p["as_of"] for p in points(plan, "eq.turnover.day")] == ["2026-10-02"] and plan.skipped[("eq.turnover.day", "a weekend date")] == 1


def test_a_date_twice_with_different_numbers_keeps_neither():
    plan = importer.read_workbook(mini({eq.VALUATION_SHEET: [("Date", "P/E"), (datetime(2026, 10, 2), 9.5), (datetime(2026, 10, 2), 9.9)]}), TODAY)
    assert points(plan, "eq.pe") == [] and plan.skipped[("eq.pe", "the same date twice with different numbers (neither kept)")] == 1


def test_a_sheet_that_cannot_be_read_is_an_error_line_and_the_others_still_go():
    plan = importer.read_workbook(mini({eq.VALUATION_SHEET: [("Date", "P/E"), (datetime(2026, 10, 2), 9.5)], eq.UNIVERSE_SHEET: [("nothing here",)]}), TODAY)
    assert len(points(plan, "eq.pe")) == 1 and len(plan.errors) == 1 and "Universe of Coverage" in plan.errors[0]
    assert importer.read_workbook(mini({"Something else": [("a",)]}), TODAY).errors == ["none of the history sheets is in this workbook"]


def test_the_dry_run_report_holds_counts_and_dates_and_no_value(tmp_path):
    plan = importer.read_workbook(mini({eq.VALUATION_SHEET: [("Date", "P/E", None, "Dividend yield"), (datetime(2026, 10, 2), 7777.1234, None, 0.4321),
                                                             (datetime(2026, 10, 9), 8888.5678, None, 0.4321)]}), TODAY)
    counts, _ = importer.classify(tmp_path / "h.db", plan)
    text = "\n".join(importer.report(plan, counts))
    assert "eq.pe: 2 rows seen, 2 points over 1 subject(s), 2026-10-02 to 2026-10-09, 2 new" in text
    assert not any(v in text for v in ("7777", "8888", "43.21", "0.4321"))
    assert not any(v in str(plan.errors) for v in ("7777", "8888"))


def test_apply_adds_confirmed_imports_once_and_never_touches_what_is_stored(tmp_path):
    path = tmp_path / "h.db"
    plan = importer.read_workbook(book(equities_workbook_bytes()), TODAY)
    n = importer.apply(path, plan)
    assert n == len(plan.points) and n > 0
    stored = rows_in(path)
    assert {r["confirmed_by"] for r in stored} == {"workbook import"} and all(r["confirmed_at"] for r in stored) and all(r["superseded_by"] is None for r in stored)
    assert importer.apply(path, plan) == 0 and len(rows_in(path)) == n   # idempotent
    counts, new = importer.classify(path, plan)
    assert new == [] and {w for c in counts.values() for w in c} == {"same"}

    # An analyst corrects one point in the tool; a re-run reports it as different and leaves it alone.
    p = points(plan, "eq.pe")[0]
    store.record(path, key="eq.pe", unit="multiple", section="equities", cadence="week", label="x", as_of=p["as_of"], week_ending=p["week_ending"],
                 value="1.5", origin="typed", source_kind="form_field", source_ref="pe", confirmed_by=store.FORM)
    counts, new = importer.classify(path, plan)
    assert counts["eq.pe"]["different"] == 1 and new == [] and importer.apply(path, plan) == 0
    assert [c["value"] for c in store.current(path, "eq.pe") if c["as_of"] == p["as_of"]] == ["1.5"]


def test_an_import_whose_date_is_already_current_is_refused_whole(tmp_path):
    path = tmp_path / "h.db"
    plan = importer.read_workbook(mini({eq.VALUATION_SHEET: [("Date", "P/E"), (datetime(2026, 10, 2), 9.5), (datetime(2026, 10, 9), 9.6)]}), TODAY)
    store.add_new(path, [{**plan.points[0], "confirmed_by": store.IMPORT}])
    with pytest.raises(sqlite3.IntegrityError):
        store.add_new(path, [{**p, "confirmed_by": store.IMPORT} for p in plan.points])   # the second would be new, the first is not
    assert len(rows_in(path)) == 1


def test_a_large_import_is_written_in_chunks(tmp_path):
    many = [{"key": "test.big", "unit": "count", "section": "equities", "cadence": "day", "label": "Invented", "as_of": date.fromordinal(739000 + i).isoformat(),
             "week_ending": "2026-10-02", "value": str(i), "origin": "workbook_import", "source_kind": "workbook_cell", "source_ref": f"S!A{i}",
             "confirmed_by": store.IMPORT} for i in range(1200)]   # more than store._CHUNK
    assert store.add_new(tmp_path / "h.db", many) == 1200 and len(rows_in(tmp_path / "h.db")) == 1200


def load_script(monkeypatch):
    spec = importlib.util.spec_from_file_location("import_history_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "load_env", lambda: None)   # the real .env must never be read by a test
    return mod


def test_the_script_dry_runs_by_default_and_writes_only_with_apply(tmp_path, monkeypatch, capsys):
    xlsx = tmp_path / "equities.xlsx"
    xlsx.write_bytes(equities_workbook_bytes())
    db_file = tmp_path / "scratch.db"
    script = load_script(monkeypatch)
    assert script.main([str(xlsx), "--db", str(db_file)]) == 0
    out = capsys.readouterr().out
    assert "dry run, nothing is written" in out and "equities.xlsx" in out and "eq.pe:" in out
    assert rows_in(db_file) == []
    assert script.main([str(xlsx), "--db", str(db_file), "--apply"]) == 0
    assert "wrote" in capsys.readouterr().out and len(rows_in(db_file)) > 0
    assert script.main([str(xlsx), "--db", str(db_file), "--apply"]) == 0
    assert "wrote" not in capsys.readouterr().out


def test_the_script_names_a_file_it_cannot_open_and_exits_non_zero(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "notes.xlsx"
    bad.write_bytes(b"not a workbook")
    assert load_script(monkeypatch).main([str(bad), "--db", str(tmp_path / "s.db")]) == 1
    assert "cannot open" in capsys.readouterr().out
