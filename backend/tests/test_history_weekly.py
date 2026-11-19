import logging
from datetime import date

import pytest

from cytonn_weekly import db
from cytonn_weekly.history import store
from cytonn_weekly.history import weekly as history
from cytonn_weekly.weekly import analyst, cbk_bulletin, inputs
from cytonn_weekly.weekly.week import Week
from tests import weekly_helpers as wh
from tests.test_weekly_analyst import FUNDS
from tests.test_weekly_fixed_income import BULLETIN

WEEK = wh.WEEK
NEXT = Week(date(2026, 10, 9))
DAY = WEEK.as_at.isoformat()


@pytest.fixture
def path(tmp_path):
    return tmp_path / "history.db"


def save(root, path, fields=None, tables=None, week=WEEK, confirm=None):
    return analyst.save_form(week, {"fields": fields or {}, "tables": tables or {}, "confirm": confirm or []}, root, path)


def held(path, key, subject="", confirmed_only=False):
    return [(p["as_of"], p["value"], p["origin"], p["confirmed_by"]) for p in store.current(path, key, subject, confirmed_only=confirmed_only)]


def test_a_save_writes_the_typed_figures_as_confirmed_points(tmp_path, path):
    save(tmp_path, path, {"pe": "9.73", "dividend_yield": "5.8"},
         {"mmf": {"text": FUNDS},"interbank": {"text": "2026-10-01 9.9"}})
    assert held(path, "eq.pe", confirmed_only=True) == [(DAY, "9.73", "typed", store.FORM)]
    assert held(path, "eq.dividend_yield") == [(DAY, "5.8", "typed", store.FORM)]
    assert held(path, "fi.mmf.rate", "cytonn money market fund") == [(DAY, "11.00", "typed", store.FORM)]
    assert held(path, "fi.interbank.rate") == [("2026-10-01", "9.9", "typed", store.FORM)]


def test_the_same_form_saved_again_adds_nothing_and_a_changed_figure_is_a_correction(tmp_path, path):
    save(tmp_path, path, {"pe": "9.73"})
    save(tmp_path, path, {"pe": "9.73"})
    save(tmp_path, path, {"pe": "9.8"})
    assert held(path, "eq.pe") == [(DAY, "9.8", "typed", store.FORM)]
    conn = db.open_db(path)
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM series_points").fetchone()["n"] == 2   # the old 9.73 is kept, pointing at the new one
    finally:
        conn.close()


def test_a_carried_or_suggested_figure_waits_and_no_reader_sees_it_until_it_is_confirmed(tmp_path, path):
    save(tmp_path, path, {"pe": "9.73", "placements": "9.1"})
    analyst.carry_forward(NEXT, tmp_path, path)
    next_day = NEXT.as_at.isoformat()
    assert held(path, "eq.pe", confirmed_only=True) == [(DAY, "9.73", "typed", store.FORM)]
    assert held(path, "eq.pe") == [(DAY, "9.73", "typed", store.FORM), (next_day, "9.73", "carried", None)]
    save(tmp_path, path, week=NEXT, confirm=["pe"])
    assert held(path, "eq.pe", confirmed_only=True)[-1] == (next_day, "9.73", "carried", store.FORM)


def test_a_suggested_total_is_a_waiting_working_point(tmp_path, path):
    analyst.suggest(WEEK, "turnover_ytd", "3052.2", "Suggested: 3,035.6 + 16.6", tmp_path, path)
    assert held(path, "eq.turnover.ytd", confirmed_only=True) == []
    [(_, value, origin, by)] = held(path, "eq.turnover.ytd")
    assert (value, origin, by) == ("3052.2", "worked_out", None)
    save(tmp_path, path, {"turnover_ytd": "3052.2"})   # confirmed as suggested: still a worked-out figure, now counted
    assert held(path, "eq.turnover.ytd", confirmed_only=True) == [(DAY, "3052.2", "worked_out", store.FORM)]
    save(tmp_path, path, {"turnover_ytd": "3060.0"})
    assert held(path, "eq.turnover.ytd", confirmed_only=True) == [(DAY, "3060.0", "typed", store.FORM)]


@pytest.mark.parametrize("break_it", ["raises", "unreachable"])
def test_a_failed_store_write_never_fails_a_save_a_suggest_or_a_carry(tmp_path, path, monkeypatch, caplog, break_it):
    if break_it == "raises":
        def boom(*a, **k):
            raise RuntimeError("the row 7777.77 broke")   # a driver's message can quote a value

        monkeypatch.setattr(store, "record_many", boom)
        target = path
    else:
        target = tmp_path / "missing folder" / "h.db"
    before = history.failed_writes()
    with caplog.at_level(logging.WARNING, logger="cytonn_weekly.history.weekly"):
        done = save(tmp_path, target, {"pe": "9.73"})
        analyst.suggest(WEEK, "turnover_ytd", "3052.2", "Suggested", tmp_path, target)
        analyst.carry_forward(NEXT, tmp_path, target)
    assert done["fields"]["pe"] == "9.73" and analyst.read_form(WEEK, tmp_path)["fields"]["pe"] == "9.73"   # the file has everything
    assert analyst.read_form(NEXT, tmp_path)["carried"]
    assert history.failed_writes() - before == 3
    text = caplog.text
    assert "eq.pe " + DAY in text and "eq.turnover.ytd " + DAY in text
    assert not any(v in text for v in ("9.73", "7777", "3052"))


def test_fetched_figures_are_written_once_with_the_file_name_and_hash_and_never_replace_a_figure_that_is_there(tmp_path, path):
    wk = Week(cbk_bulletin.parse_bulletin(BULLETIN).issue_date)
    entry = inputs.store(wk, "cbk_bulletin", BULLETIN, "bulletin.pdf", tmp_path, db_path=path)
    first = store.current(path, "fi.kesonia", confirmed_only=True)
    assert first and {p["origin"] for p in first} == {"fetched"}
    assert all(entry["sha256"] in p["source_ref"] and "cbk_bulletin.pdf" in p["source_ref"] for p in first)
    inputs.store(wk, "cbk_bulletin", BULLETIN, "bulletin.pdf", tmp_path, db_path=path)   # again: the same points, not a second set
    assert [p["point_id"] for p in store.current(path, "fi.kesonia", confirmed_only=True)] == [p["point_id"] for p in first]
    # a figure an analyst has already typed for that date stays
    day = first[0]["as_of"]
    store.record(path, key="fi.kesonia", unit="pct", section="fixed_income", cadence="day", label="KESONIA", as_of=day, week_ending=wk.ending.isoformat(),
                 value="1.23", origin="typed", source_kind="form_field", source_ref="x", confirmed_by=store.FORM)
    inputs.store(wk, "cbk_bulletin", BULLETIN, "bulletin.pdf", tmp_path, db_path=path)
    assert [p["value"] for p in store.current(path, "fi.kesonia") if p["as_of"] == day] == ["1.23"]


def test_a_report_for_another_week_writes_nothing_and_a_bad_database_does_not_fail_the_upload(tmp_path, path):
    wk = Week(cbk_bulletin.parse_bulletin(BULLETIN).issue_date)
    other = Week(date(2026, 1, 9))
    inputs.store(other, "cbk_bulletin", BULLETIN, "bulletin.pdf", tmp_path, db_path=path)
    assert store.current(path, "fi.kesonia", confirmed_only=False) == []
    before = history.failed_writes()
    entry = inputs.store(wk, "cbk_bulletin", BULLETIN, "bulletin.pdf", tmp_path, db_path=tmp_path / "missing folder" / "h.db")
    assert entry["stored_name"] == "cbk_bulletin.pdf" and history.failed_writes() - before == 1


def test_a_batch_takes_a_handful_of_statements_not_one_per_point(path, monkeypatch):
    calls = []
    real = db.Db.execute
    monkeypatch.setattr(db.Db, "execute", lambda self, sql, params=(): (calls.append(sql), real(self, sql, params))[1])
    items = [{"key": "test.many", "subject": "s", "unit": "count", "section": "equities", "cadence": "day", "label": "Invented", "as_of": date.fromordinal(739000 + i).isoformat(),
              "week_ending": "2026-10-02", "value": str(i), "origin": "typed", "source_kind": "form_field", "source_ref": "x", "confirmed_by": store.FORM} for i in range(300)]
    store.record_many(path, items)
    assert len(calls) < 15
    calls.clear()
    store.record_many(path, items)   # again: nothing new
    assert len(calls) < 15 and len(store.current(path, "test.many", "s")) == 300
