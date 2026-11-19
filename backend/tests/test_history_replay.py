import importlib.util
from datetime import date

import pytest

from cytonn_weekly.history import importer, replay, store
from cytonn_weekly.paths import BACKEND_ROOT
from cytonn_weekly.weekly.workbook import Workbook
from tests.weekly_helpers import equities_workbook_bytes

TODAY = date(2026, 10, 12)
SCRIPT = BACKEND_ROOT / "scripts" / "replay_history.py"


@pytest.fixture
def filled(tmp_path):
    book = Workbook(equities_workbook_bytes(), "synthetic.xlsx")
    importer.apply(tmp_path / "scratch.db", importer.read_workbook(book, TODAY))
    return book, tmp_path / "scratch.db"


def test_the_replay_passes_every_check_the_synthetic_workbook_can_make(filled):
    book, path = filled
    lines = replay.run(book, path)
    assert {l.series for l in lines} == {"eq.turnover.ytd", "eq.foreign.ytd", "eq.foreign.week", "eq.price", "eq.pe"}
    # the synthetic workbook's AVERAGE cell is a typed number, not a formula over a range, so only that line differs
    assert [(l.series, l.status) for l in lines if l.status == "FAIL"] == [("eq.pe", "FAIL")]
    assert any(l.status == "SKIP" and "restart" in l.note for l in lines)   # the new year's restart is named, not failed
    assert sum(l.status == "PASS" for l in lines) > 10


def test_a_stored_total_that_is_not_the_workbooks_is_a_failure_whatever_its_size(filled):
    book, path = filled
    mid = next(l for l in replay.run(book, path) if l.series == "eq.foreign.ytd" and l.check.startswith("before + week") and l.status == "PASS")
    point = store.current(path, "eq.foreign.ytd", since=mid.week, through=mid.week)[0]
    for size in ("0.05", "0.5"):
        store.record(path, key="eq.foreign.ytd", unit="usd_mn", section="equities", cadence="week", label="Foreign net position, year to date", as_of=point["as_of"],
                     week_ending=point["week_ending"], value=str(float(point["value"]) + float(size)), origin="typed", source_kind="form_field", source_ref="x",
                     confirmed_by=store.FORM)
        later = [l for l in replay.run(book, path) if l.series == "eq.foreign.ytd" and l.check == "before is last week's total"]
        assert any(l.status == "FAIL" and l.difference and abs(l.difference - float(size)) < 1e-6 for l in later)   # the stored total is no longer the workbook's


def test_the_script_fills_a_scratch_database_replays_it_and_prints_no_value(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("replay_history_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    xlsx = tmp_path / "equities.xlsx"
    xlsx.write_bytes(equities_workbook_bytes())
    mod.main([str(xlsx), "--db", str(tmp_path / "s.db"), "--fill"])
    out = capsys.readouterr().out
    assert "imported" in out and "eq.foreign.ytd | before is last week's total:" in out and "PASS" in out
    with pytest.raises(SystemExit):
        mod.main([str(xlsx)])   # a scratch database is required: the script never uses the configured one
