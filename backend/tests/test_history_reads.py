import logging
from datetime import date

import pytest

from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly.history import importer, reads, store
from cytonn_weekly.history.importer import CATALOG
from cytonn_weekly.weekly import analyst, inputs
from cytonn_weekly.weekly.week import Week
from cytonn_weekly.weekly.workbook import Workbook
from tests import weekly_helpers as wh
from tests import test_weekly_equities as eqt
from tests.test_weekly_analyst import save_week, stores
from tests.test_weekly_equities import blocks, build, figures, root  # noqa: F401 - root is a fixture
from tests.weekly_helpers import text_pdfs  # noqa: F401 - a fixture

WEEK = Week(date(2026, 10, 2))
LAST = "2026-09-25"
THIS = "2026-10-02"
LOG = "cytonn_weekly.history.reads"


def put(key, day, value, subject="", origin="typed", by=store.FORM):
    unit, cadence, section, label, _ = CATALOG[key]
    return {"key": key, "subject": subject, "unit": unit, "section": section, "cadence": cadence, "label": label, "as_of": day, "week_ending": day,
            "value": value, "origin": origin, "source_kind": "workbook_cell" if origin == "workbook_import" else "form_field", "source_ref": "S!A1",
            "confirmed_by": by}


def fill(*points):
    store.record_many(None, list(points))   # the per-test database conftest points the default at


class Form:
    """A figure as the form side holds it: a number and nothing else."""

    def __init__(self, number):
        self.number = number


@pytest.fixture(autouse=True)
def fresh_counts():
    reads.counts.clear()


@pytest.fixture
def mode(monkeypatch):
    return lambda value: monkeypatch.setenv(reads.MODE_ENV, value)


@pytest.fixture
def no_store(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the store was read")

    monkeypatch.setattr(store, "current", boom)


def test_off_is_the_default_and_never_reads_the_store(no_store, monkeypatch):
    assert reads.mode() == reads.OFF
    form = Form(1.5)
    assert reads.running_before(WEEK, "eq.foreign.ytd", form) is form
    assert reads.foreign_history(WEEK, []) == [] and reads.pe_average(WEEK, form) is form
    monkeypatch.setenv(reads.MODE_ENV, "OFF")
    assert reads.mode() == reads.OFF and not reads.counts


def test_a_setting_that_is_not_one_of_the_three_means_off_and_says_so_once(mode, caplog):
    mode("sometimes")
    with caplog.at_level(logging.WARNING, logger=LOG):
        assert reads.mode() == reads.OFF and reads.mode() == reads.OFF
    assert caplog.text.count("is not off, compare or on") <= 1


def test_the_running_total_before_is_last_weeks_confirmed_point_in_on_and_only_a_count_in_compare(mode, caplog):
    fill(put("eq.foreign.ytd", LAST, "100.5", origin="workbook_import", by=store.IMPORT), put("eq.foreign.ytd", "2026-09-18", "90"))
    form = Form(100.4)
    mode("compare")
    with caplog.at_level(logging.WARNING, logger=LOG):
        assert reads.running_before(WEEK, "eq.foreign.ytd", form) is form
    assert reads.counts["differences"] == 1 and "eq.foreign.ytd 2026-09-25" in caplog.text and not any(v in caplog.text for v in ("100.5", "100.4"))
    mode("on")
    got = reads.running_before(WEEK, "eq.foreign.ytd", form)
    assert got.number == 100.5 and "history store" in got.source and "imported" in got.source
    assert reads.running_before(WEEK, "eq.turnover.ytd", form) is form   # no point for that series: the form's


def test_a_point_that_waits_for_confirmation_is_not_a_total_to_add_to(mode):
    fill(put("eq.foreign.ytd", LAST, "100.5", by=None))
    mode("on")
    form = Form(1.0)
    assert reads.running_before(WEEK, "eq.foreign.ytd", form) is form


def test_foreign_weeks_come_oldest_first_and_compare_names_each_date_that_differs(mode, caplog):
    fill(*[put("eq.foreign.week", d, v) for d, v in (("2026-09-11", "-3"), ("2026-09-18", "2"), (LAST, "4"), (THIS, "9"))])
    form = [(date(2026, 9, 18), 2.0, None), (date(2026, 9, 25), 4.5, None), (date(2026, 9, 4), 1.0, None)]
    mode("on")
    got = reads.foreign_history(WEEK, form)
    assert [(d.isoformat(), n) for d, n, _ in got] == [("2026-09-11", -3.0), ("2026-09-18", 2.0), (LAST, 4.0)]   # this week's own is not "before"
    mode("compare")
    with caplog.at_level(logging.WARNING, logger=LOG):
        assert reads.foreign_history(WEEK, form) is form
    assert reads.counts["differences"] == 2 and "eq.foreign.week 2026-09-25" in caplog.text and "eq.foreign.week 2026-09-04" in caplog.text
    assert "4.5" not in caplog.text


def test_the_year_before_closes_on_the_row_before_the_restart(mode):
    weeks = (("2025-12-19", "1", "10"), ("2025-12-26", "2", "12"), ("2026-01-02", "3", "15"), ("2026-01-09", "4", "4"), ("2026-01-16", "5", "9"))
    fill(*[p for d, w, y in weeks for p in (put("eq.foreign.week", d, w), put("eq.foreign.ytd", d, y))])
    mode("on")
    got = reads.foreign_prior_year(Week(date(2026, 1, 16)), None)
    assert got.number == 15.0
    assert reads.foreign_prior_year(Week(date(2026, 1, 9)), None).number == 15.0
    assert reads.foreign_prior_year(Week(date(2025, 12, 26)), "form") == "form"   # no restart in that year: the form's


def test_last_fridays_price_by_company_and_a_hand_typed_price_stays(mode):
    fill(put("eq.price", LAST, "40.5", subject="alpha bank"), put("eq.price", "2026-09-18", "38", subject="alpha bank"), put("eq.price", LAST, "10", subject="beta"))
    mode("on")
    loaded = lambda: reads.last_prices(WEEK)   # noqa: E731
    assert reads.last_price(WEEK, "Alpha  Bank", Form(1), loaded).number == 40.5
    assert reads.last_price(WEEK, "Gamma", None, loaded) is None
    typed = analyst.Typed(41.0, "price", "label")
    assert reads.last_price(WEEK, "Alpha Bank", typed, loaded) is typed
    mode("compare")
    assert reads.last_price(WEEK, "Alpha Bank", Form(40.5), loaded).number == 40.5 and reads.counts["differences"] == 0
    assert reads.last_price(WEEK, "Beta", Form(11), loaded) and reads.counts["differences"] == 1


def test_the_average_pe_is_over_the_workbooks_own_window_and_needs_this_weeks_point(mode):
    fill(put("eq.pe", "2008-12-05", "100"), put("eq.pe", "2008-12-12", "10"), put("eq.pe", LAST, "20"), put("eq.pe", "2026-09-18", "30", by=None))
    mode("on")
    form = Form(7.0)
    assert reads.pe_average(WEEK, form) is form    # this week's own point is not there yet: the window would not match the workbook's
    fill(put("eq.pe", THIS, "12"))
    got = reads.pe_average(WEEK, form)
    assert got.number == pytest.approx(14.0) and "3 weekly market P/E points from 2008-12-12 to 2026-10-02" in got.source   # (10 + 20 + 12) / 3


def test_the_previous_fund_table_is_the_latest_day_published_best_rate_first(mode, caplog):
    fill(put("fi.mmf.rate", "2026-09-24", "10.0", subject="beta"), put("fi.mmf.rate", LAST, "10.8", subject="beta"), put("fi.mmf.rate", LAST, "11.2", subject="cytonn money market fund"))
    mode("on")
    table = reads.previous_fund_table(WEEK, None)
    assert [(f["fund"].value, f["rate"].number) for f in table["funds"]] == [("cytonn money market fund", 0.112), ("beta", 0.108)]
    assert [f["rank"].number for f in table["funds"]] == [1.0, 2.0]
    form = {"funds": [{"fund": analyst.Typed("Beta", "x", "y"), "rate": analyst.Typed(0.109, "x", "y")}]}
    mode("compare")
    with caplog.at_level(logging.WARNING, logger=LOG):
        assert reads.previous_fund_table(WEEK, form) is form
    assert reads.counts["differences"] == 1 and "fi.mmf.rate beta" in caplog.text


@pytest.mark.parametrize("which", ["compare", "on"])
def test_a_store_that_cannot_be_read_never_fails_a_draft(mode, monkeypatch, caplog, which):
    mode(which)

    def boom(*a, **k):
        raise RuntimeError("the row 7777.5 broke")

    monkeypatch.setattr(store, "current", boom)
    form = Form(1.0)
    with caplog.at_level(logging.WARNING, logger=LOG):
        assert reads.running_before(WEEK, "eq.foreign.ytd", form) is form
    assert reads.counts["failed_reads"] == 1 and "eq.foreign.ytd" in caplog.text and "7777" not in caplog.text


def test_the_analyst_reads_the_store_only_when_told_to(mode, tmp_path):
    analyst.save_form(WEEK, {"fields": {"pe": "9.5", "pe_average": "7.5"}, "tables": {"universe": {"rows": [{"company": "Alpha Bank", "price": "42"}]}}, "confirm": []}, tmp_path)
    fill(put("eq.pe", "2010-01-01", "10"), put("eq.pe", THIS, "12"), put("eq.price", LAST, "40.5", subject="alpha bank"),
         put("fi.mmf.rate", LAST, "11.2", subject="beta"))

    def read():
        form = inputs.WeeklyInputs(WEEK, tmp_path).analyst
        return form.field("pe_average").number, form.universe()["companies"][0]["last_price"], form.previous_mmf(None)

    average, last, table = read()   # off: the typed average, no last Friday's price anywhere, no previous table
    assert (average, table) == (7.5, None) and last.number is None
    mode("compare")
    average, last, table = read()
    assert (average, table) == (7.5, None) and last.number is None and reads.counts["compared"] == 3
    mode("on")
    average, last, table = read()
    assert average == pytest.approx(11.0) and last.number == 40.5 and table["funds"][0]["rate"].number == 0.112


def test_a_section_drafted_from_the_imported_store_gives_the_same_figures_as_one_drafted_from_the_workbook(root, mode, caplog):
    off = build(root)
    importer.apply(None, importer.read_workbook(Workbook(wh.equities_workbook_bytes(), "synthetic.xlsx"), date(2026, 10, 9)))
    mode("compare")
    with caplog.at_level(logging.WARNING, logger=LOG):
        compared = build(root)
    # the synthetic workbook's AVERAGE cell is a typed number, not the formula over a range, so it is the one difference
    assert reads.counts["differences"] == 1 and "history compare: eq.pe average 2026-10-02" in caplog.text
    assert blocks(compared) == blocks(off)
    mode("on")
    on = build(root)
    for part in ("foreign", "turnover"):
        assert figures(blocks(on)[part]) == figures(blocks(off)[part])
    rows = lambda review: [{k: v for k, v in r.items() if k != "_note"} for r in blocks(review)["universe_of_coverage"]["source_rows"]]   # noqa: E731
    assert rows(on) == rows(off)
    assert "history store" in str(blocks(on)["universe_of_coverage"]["source_rows"]) and "history store" not in str(blocks(off)["universe_of_coverage"])


def suggest_client(tmp_path):
    root = tmp_path / "weekly"
    stores(root)
    db = tmp_path / "app.db"
    client = TestClient(create_app(db_path=db, load_dotenv=False, inputs_root=root, fetch_usd_rates=lambda: eqt.RATES))
    return root, db, lambda field: client.post(f"/api/inputs/weekly/{THIS}/analyst/suggest/{field}?section=equities")


def note_of(response, key):
    return next(i for g in response.json()["groups"] for i in g["items"] if i["key"] == key)["carried"]["note"]


def test_the_suggest_route_starts_from_the_stores_total_in_on(tmp_path, text_pdfs, mode):
    root, db, suggest = suggest_client(tmp_path)
    assert suggest("turnover_ytd").status_code == 409   # off: last week's form holds nothing to add to
    store.record_many(db, [put("eq.turnover.ytd", LAST, "3035.6", origin="workbook_import", by=store.IMPORT), put("eq.foreign.ytd", LAST, "-167.2")])
    assert suggest("turnover_ytd").status_code == 409   # still off
    mode("on")
    for field, before in (("turnover_ytd", "3,035.6000"), ("foreign_ytd", "-167.2000")):
        r = suggest(field)
        assert r.status_code == 200 and note_of(r, field).startswith(f"Suggested: {before} saved for the week ending {LAST} + ")
    assert analyst.read_form(Week(date(2026, 10, 2)), root)["unconfirmed"] == ["foreign_ytd", "turnover_ytd"]   # a suggestion is still only a prefill


def test_the_suggest_route_in_compare_returns_the_forms_total_and_logs_the_difference_without_a_value(tmp_path, text_pdfs, mode, caplog):
    root, db, suggest = suggest_client(tmp_path)
    save_week(root, Week(date(2026, 9, 25)), fields={"turnover_ytd": "3035.6"})
    store.record_many(db, [put("eq.turnover.ytd", LAST, "3099.9")])
    mode("compare")
    with caplog.at_level(logging.WARNING, logger=LOG):
        r = suggest("turnover_ytd")
    assert r.status_code == 200 and note_of(r, "turnover_ytd").startswith(f"Suggested: 3,035.6000 saved for the week ending {LAST} + ")   # the form's
    assert "history compare: eq.turnover.ytd 2026-09-25: the form and the store differ" in caplog.text
    assert not any(v in caplog.text for v in ("3035", "3099"))
