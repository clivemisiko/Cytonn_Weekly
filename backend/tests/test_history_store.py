import sqlite3

import pytest

from cytonn_weekly.history import store

S = dict(key="test.series", subject="alpha", unit="multiple", section="equities", cadence="week", label="Invented series")


def point(day="2026-10-02", value="9.5", **over):
    return {**S, "as_of": day, "week_ending": day, "value": value, "origin": "typed", "source_kind": "form_field",
            "source_ref": "invented", **over}


@pytest.fixture
def path(tmp_path):
    return tmp_path / "history.db"


def rows(path, sql="SELECT * FROM series_points ORDER BY point_id"):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql)]
    finally:
        conn.close()


def test_a_confirmed_point_is_read_back_exactly_and_an_unconfirmed_one_is_not(path):
    first, status = store.record(path, **point("2026-10-02", "9.50", confirmed_by=store.FORM))
    assert status == store.ADDED
    store.record(path, **point("2026-10-09", "9.7"))   # waiting: no confirmed_by
    assert [(p["as_of"], p["value"], p["confirmed_by"]) for p in store.current(path, "test.series", "alpha")] == [("2026-10-02", "9.50", "analyst (form)")]
    both = store.current(path, "test.series", "alpha", confirmed_only=False)
    assert [p["as_of"] for p in both] == ["2026-10-02", "2026-10-09"]
    assert [p["as_of"] for p in store.current(path, "test.series", "alpha", confirmed_only=False, through="2026-10-05")] == ["2026-10-02"]
    assert store.current(path, "test.series", "other") == [] and first


def test_the_same_number_again_changes_nothing_even_written_differently(path):
    one, _ = store.record(path, **point(value="9.5", confirmed_by=store.FORM))
    two, status = store.record(path, **point(value=" 9.50 ", confirmed_by=store.FORM))
    assert (one, status) == (two, store.UNCHANGED) and len(rows(path)) == 1


def test_a_correction_adds_a_point_and_points_the_old_one_at_it(path):
    old, _ = store.record(path, **point(value="9.5", confirmed_by=store.FORM))
    new, status = store.record(path, **point(value="9.6", confirmed_by=store.FORM))
    assert status == store.SUPERSEDED and new != old
    kept = {r["point_id"]: r for r in rows(path)}
    assert kept[old]["value"] == "9.5" and kept[old]["superseded_by"] == new   # the old value is never edited
    assert kept[new]["superseded_by"] is None
    assert [p["value"] for p in store.current(path, "test.series", "alpha")] == ["9.6"]


def test_typing_the_suggested_number_makes_a_confirmed_point_that_supersedes_the_suggestion(path):
    suggested, _ = store.record(path, **point(value="100", origin="worked_out", source_kind="working"))
    typed, status = store.record(path, **point(value="100", confirmed_by=store.FORM))
    assert status == store.SUPERSEDED
    assert [(p["point_id"], p["origin"]) for p in store.current(path, "test.series", "alpha")] == [(typed, "typed")]
    assert {r["point_id"]: r["superseded_by"] for r in rows(path)}[suggested] == typed


def test_confirm_as_it_stands_once_and_not_a_replaced_point(path):
    waiting, _ = store.record(path, **point(value="1", origin="carried", source_kind="source"))
    assert store.confirm(path, waiting, store.FORM) is True and store.confirm(path, waiting, store.FORM) is False
    changed, _ = store.record(path, **point(value="2", confirmed_by=store.FORM))
    assert store.confirm(path, waiting, "someone") is False   # superseded: not a current point
    assert rows(path, f"SELECT confirmed_by FROM series_points WHERE point_id = {waiting}")[0]["confirmed_by"] == "analyst (form)"
    assert changed


def test_the_database_allows_one_current_point_per_series_and_date(path):
    first, _ = store.record(path, **point())
    conn = sqlite3.connect(path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO series_points (series_id, as_of, week_ending, value, origin, source_kind, source_ref, created_at) "
                     "SELECT series_id, as_of, week_ending, '1', 'typed', 'form_field', 'x', 'now' FROM series_points WHERE point_id = ?", (first,))
    conn.close()


def test_a_series_unit_is_fixed_for_good(path):
    store.record(path, **point())
    with pytest.raises(store.HistoryError, match="unit is fixed"):
        store.record(path, **point("2026-10-09", unit="pct"))


@pytest.mark.parametrize("bad", [9.5, True, None, "abc", "NaN", "inf", "", b"1"])
def test_a_value_that_is_not_a_decimal_given_as_text_is_refused_without_echoing_it(path, bad):
    with pytest.raises(store.HistoryError) as err:
        store.record(path, **point(value=bad))
    assert "9.5" not in str(err.value) and "abc" not in str(err.value)
    assert rows(path) == []


@pytest.mark.parametrize("over", [{"as_of": "2026-13-01"}, {"as_of": "10/02/2026"}, {"week_ending": ""}, {"origin": "guess"},
                                  {"source_kind": "memory"}, {"source_ref": " "}, {"unit": "dollars"}, {"cadence": "hour"}])
def test_every_other_bad_input_is_refused(path, over):
    with pytest.raises(store.HistoryError):
        store.record(path, **point(**over))


def test_a_batch_is_all_or_nothing(path):
    with pytest.raises(store.HistoryError):
        store.record_many(path, [point("2026-10-02"), point("2026-10-09", value="x")])
    assert rows(path) == [] and rows(path, "SELECT * FROM series") == []


def test_a_refusal_names_the_series_and_the_date_not_the_value(path):
    with pytest.raises(store.HistoryError) as err:
        store.record(path, **point("2026-10-02", value="12345.678", origin="guess"))
    assert "test.series" in str(err.value) and "2026-10-02" in str(err.value) and "12345" not in str(err.value)
