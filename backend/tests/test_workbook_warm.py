import logging
import threading

from fastapi.testclient import TestClient

from cytonn_weekly.weekly import inputs
from tests.weekly_helpers import WEEK, equities_workbook_bytes, fi_workbook_bytes


def _store_books(root):
    inputs.store(WEEK, inputs.EQUITIES_WORKBOOK, equities_workbook_bytes(), "eq.xlsx", root, record=False)
    inputs.store(WEEK, inputs.FI_WORKBOOK, fi_workbook_bytes(), "fi.xlsx", root, record=False)


def test_warm_up_fills_the_cache_and_the_form_read_hits_it(tmp_path):
    _store_books(tmp_path)
    inputs.warm_in_background(root=tmp_path).result(timeout=60)
    assert {key[0] for key in inputs._PARSED} == {"eq", "fi"}
    reader = inputs.WeeklyInputs(WEEK, tmp_path)
    assert reader.equities_book is not None and reader.fi_book is not None
    assert reader.loads == {"eq": "from cache", "fi": "from cache"}


def test_warm_up_stays_within_the_cache_limit(tmp_path):
    _store_books(tmp_path)
    inputs.warm_in_background(root=tmp_path).result(timeout=60)
    assert len(inputs._PARSED) <= inputs._PARSED_MAX


def test_a_failed_warm_up_is_logged_and_does_not_raise(tmp_path, monkeypatch, caplog):
    _store_books(tmp_path)

    def boom(self, slugs=()):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(inputs.WeeklyInputs, "warm", boom)
    with caplog.at_level(logging.ERROR, logger=inputs.__name__):
        inputs.warm_in_background(root=tmp_path).result(timeout=60)   # returns normally
    assert "warming the parsed-workbook cache failed" in caplog.text


def test_a_failed_startup_warm_up_does_not_stop_the_app(tmp_path, monkeypatch):
    from api.main import create_app

    monkeypatch.setattr(inputs, "recent_weeks", lambda root=None, count=2: (_ for _ in ()).throw(OSError("synthetic")))
    with TestClient(create_app(db_path=tmp_path / "app.db", inputs_root=tmp_path / "in")) as client:
        assert client.get("/api/health").status_code == 200


def test_warm_up_does_not_run_on_the_calling_thread(tmp_path, monkeypatch):
    seen = []
    gate = threading.Event()

    def record(self, slugs=()):
        seen.append(threading.get_ident())
        gate.wait(5)

    monkeypatch.setattr(inputs.WeeklyInputs, "warm", record)
    inputs.store(WEEK, inputs.EQUITIES_WORKBOOK, equities_workbook_bytes(), "eq.xlsx", tmp_path, record=False)
    future = inputs.warm_in_background(root=tmp_path)
    assert not future.done()   # the caller returned while the warm-up is still held
    gate.set()
    future.result(timeout=10)
    assert seen and seen[0] != threading.get_ident()


def test_an_upload_warms_its_workbook_in_the_background(tmp_path, monkeypatch):
    from api.main import create_app

    calls = []
    monkeypatch.setattr(inputs, "warm_in_background", lambda weeks=None, root=None, slugs=(): calls.append((weeks, slugs)))
    client = TestClient(create_app(db_path=tmp_path / "app.db", inputs_root=tmp_path / "in"))
    response = client.put(f"/api/inputs/weekly/{WEEK.ending.isoformat()}/{inputs.EQUITIES_WORKBOOK}?filename=eq.xlsx",
                          content=equities_workbook_bytes())
    assert response.status_code == 200
    assert calls == [([WEEK], (inputs.EQUITIES_WORKBOOK,))]


def _gated_parser(monkeypatch, module, name, fail_first=False):
    """Wrap a workbook opener: it counts calls, holds each until the gate opens, and can fail its first call."""
    real = getattr(module, name)
    calls, gate, entered = [], threading.Event(), threading.Event()

    def opener(data, *args, **kwargs):
        calls.append(threading.get_ident())
        entered.set()
        gate.wait(10)
        if fail_first and len(calls) == 1:
            raise RuntimeError("synthetic parse failure")
        return real(data, *args, **kwargs)

    monkeypatch.setattr(module, name, opener)
    return calls, gate, entered


def _read_in_thread(root, prop, out):
    def run():
        try:
            out.append(getattr(inputs.WeeklyInputs(WEEK, root), prop))
        except Exception as exc:  # noqa: BLE001 - the test inspects what each caller got
            out.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    return thread


def test_two_concurrent_callers_for_one_workbook_parse_it_once(tmp_path, monkeypatch):
    from cytonn_weekly.weekly import equities_workbook

    _store_books(tmp_path)
    calls, gate, entered = _gated_parser(monkeypatch, equities_workbook, "open_equities_workbook")
    got = []
    first = _read_in_thread(tmp_path, "equities_book", got)
    assert entered.wait(10)
    second = _read_in_thread(tmp_path, "equities_book", got)
    second.join(0.3)
    assert second.is_alive()   # waiting on the first caller's parse, not parsing
    gate.set()
    first.join(10), second.join(10)
    assert len(calls) == 1
    assert len(got) == 2 and all(isinstance(book, inputs.Workbook) for book in got)


def test_a_failed_parse_releases_the_waiters(tmp_path, monkeypatch):
    from cytonn_weekly.weekly import equities_workbook

    _store_books(tmp_path)
    calls, gate, entered = _gated_parser(monkeypatch, equities_workbook, "open_equities_workbook", fail_first=True)
    got = []
    first = _read_in_thread(tmp_path, "equities_book", got)
    assert entered.wait(10)
    second = _read_in_thread(tmp_path, "equities_book", got)
    second.join(0.3)
    gate.set()
    first.join(10), second.join(10)
    assert not first.is_alive() and not second.is_alive()   # nobody hangs
    assert len(calls) == 2   # the waiter tried once itself after the failure
    assert sum(isinstance(r, RuntimeError) for r in got) == 1 and sum(isinstance(r, inputs.Workbook) for r in got) == 1
    assert not inputs._INFLIGHT


def test_different_workbooks_parse_independently(tmp_path, monkeypatch):
    from cytonn_weekly.weekly import equities_workbook

    _store_books(tmp_path)
    _, gate, entered = _gated_parser(monkeypatch, equities_workbook, "open_equities_workbook")
    got = []
    held = _read_in_thread(tmp_path, "equities_book", got)
    assert entered.wait(10)
    fi = inputs.WeeklyInputs(WEEK, tmp_path).fi_book   # not held up by the equities parse in flight
    assert isinstance(fi, inputs.Workbook)
    gate.set()
    held.join(10)
    assert isinstance(got[0], inputs.Workbook)


def _store_week(root, week, book_week=None):
    book_week = book_week or week
    inputs.store(week, inputs.EQUITIES_WORKBOOK, equities_workbook_bytes(book_week), "eq.xlsx", root, record=False)
    inputs.store(week, inputs.FI_WORKBOOK, fi_workbook_bytes(book_week), "fi.xlsx", root, record=False)


def test_recent_weeks_picks_weeks_by_their_workbook_not_the_newest_folders(tmp_path):
    from datetime import timedelta

    from cytonn_weekly.weekly.week import Week

    weeks = [Week(WEEK.ending + timedelta(days=7 * n)) for n in range(5)]   # oldest first
    for week in weeks[:3]:
        _store_week(tmp_path, week)
    _store_week(tmp_path, weeks[3], book_week=weeks[2])   # an earlier week's workbook: the form skips it
    (inputs.inputs_root(tmp_path) / weeks[4].ending.isoformat()).mkdir(parents=True)   # a folder with no workbook
    assert inputs.recent_weeks(tmp_path) == [weeks[2], weeks[1]]   # WARM_WEEKS is 2: the newest two that qualify


def test_the_warmed_weeks_stay_within_the_cache_and_keep_the_newest(tmp_path):
    from datetime import timedelta

    from cytonn_weekly.weekly.week import Week

    weeks = [Week(WEEK.ending + timedelta(days=7 * n)) for n in range(4)]
    for week in weeks:
        _store_week(tmp_path, week)
    inputs.warm_in_background(root=tmp_path).result(timeout=120)
    assert len(inputs._PARSED) <= inputs._PARSED_MAX
    newest = inputs.WeeklyInputs(weeks[-1], tmp_path)
    assert newest.equities_book is not None and newest.fi_book is not None
    assert newest.loads == {"eq": "from cache", "fi": "from cache"}


def test_each_form_read_of_the_warm_up_is_logged_with_week_section_and_seconds(tmp_path, caplog):
    _store_books(tmp_path)
    with caplog.at_level(logging.WARNING, logger=inputs.__name__):
        inputs.warm_in_background(root=tmp_path).result(timeout=60)
    assert f"week ending {WEEK.ending.isoformat()}, equities form read in" in caplog.text
    assert f"week ending {WEEK.ending.isoformat()}, fixed_income form read in" in caplog.text


def test_section_readiness_warms_the_opened_week(tmp_path, monkeypatch):
    from api.main import create_app

    calls = []
    monkeypatch.setattr(inputs, "warm_in_background", lambda weeks=None, root=None, slugs=(): calls.append(weeks))
    client = TestClient(create_app(db_path=tmp_path / "app.db", inputs_root=tmp_path / "in"))
    period = f"Week ending {WEEK.ending.isoformat()}"
    response = client.get("/api/sections/equities/readiness", params={"period": period})
    assert response.status_code == 200
    assert [WEEK] in calls


def _count_opens(monkeypatch):
    """Count every openpyxl open of a stored workbook, values (the parse) and formulas alike."""
    opened = []
    real = inputs.Workbook._open

    def counting(self, data_only):
        opened.append(data_only)
        return real(self, data_only)

    monkeypatch.setattr(inputs.Workbook, "_open", counting)
    return opened


def test_after_the_warm_up_the_form_read_opens_nothing(tmp_path, monkeypatch):
    from cytonn_weekly.weekly import analyst

    _store_books(tmp_path)
    inputs.warm_in_background(root=tmp_path).result(timeout=120)
    opened = _count_opens(monkeypatch)
    for section in (analyst.EQ, analyst.FI):
        analyst.status(WEEK, tmp_path, section)
    assert opened == []   # no values parse and no formulas open


def test_both_sections_of_one_week_are_warmed(tmp_path, monkeypatch):
    from cytonn_weekly.weekly import analyst

    _store_books(tmp_path)
    seen = []
    real = analyst.status
    monkeypatch.setattr(analyst, "status", lambda week, root=None, section=None: seen.append((week, section)) or real(week, root, section))
    inputs.warm_in_background(root=tmp_path).result(timeout=120)
    assert sorted(s for _, s in seen) == sorted([analyst.EQ, analyst.FI]) and {w for w, _ in seen} == {WEEK}


def test_a_failed_form_read_in_the_warm_up_is_swallowed(tmp_path, monkeypatch, caplog):
    from cytonn_weekly.weekly import analyst

    _store_books(tmp_path)
    monkeypatch.setattr(analyst, "status", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("synthetic")))
    with caplog.at_level(logging.ERROR, logger=inputs.__name__):
        inputs.warm_in_background(root=tmp_path).result(timeout=60)
    assert "warming the parsed-workbook cache failed" in caplog.text
