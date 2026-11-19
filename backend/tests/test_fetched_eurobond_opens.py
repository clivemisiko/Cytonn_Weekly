import re
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from urllib.parse import quote

import pdfplumber
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly.common.http import NotFound
from cytonn_weekly.history import store
from cytonn_weekly.weekly import cbk_bulletin as bulletin
from cytonn_weekly.weekly import cbk_eurobond_opens as opens
from cytonn_weekly.weekly import fetched_items

SOURCES = Path(__file__).parent / "fixtures" / "sources"
FILES = {date(2026, 1, 9): "cbk_weekly_bulletin_2026-01-09.pdf", date(2026, 10, 2): "cbk_weekly_bulletin_2026-10-02.pdf",
         date(2026, 10, 9): "cbk_weekly_bulletin_2026-10-09.pdf", date(2026, 11, 6): "cbk_weekly_bulletin_2026-11-06.pdf",
         date(2026, 11, 13): "cbk_weekly_bulletin_2026-11-13.pdf"}
TODAY = date(2026, 11, 18)
KEYS = {"2018_10y", "2018_30y", "2019_12y", "2021_13y", "2024_7y"}


def href(day):
    return f"/uploads/weekly_bulletin/Weekly CBK Bulletin, {day.day} {day:%B}, {day.year}.pdf"


def archive(missing=()):
    def get(url):
        if url == bulletin.LISTING:
            return "".join(f'<a href="{href(d)}">x</a>' for d in FILES if d not in missing).encode()
        for day, name in FILES.items():
            if url == bulletin.CBK + quote(href(day), safe="/") and day not in missing:
                return (SOURCES / name).read_bytes()
        raise NotFound(url)
    return get


def test_the_five_yield_layout_is_read_by_the_years_printed_over_it():
    days = opens.parse((SOURCES / FILES[date(2026, 1, 9)]).read_bytes())
    assert len(days) == 9 and min(days) == date(2025, 12, 29) and max(days) == date(2026, 1, 8)
    assert set(days[date(2026, 1, 2)]) == {2028, 2031, 2032, 2034, 2048}
    assert set(days[date(2026, 1, 1)]) == set(days[date(2026, 1, 2)])   # the "Public Holiday" row carries its yields too


def test_the_eight_yield_layout_is_read_too():
    days = opens.parse((SOURCES / FILES[date(2026, 10, 9)]).read_bytes())
    assert len(days) == 10 and set(days[date(2026, 10, 8)]) == {2028, 2031, 2032, 2034, 2036, 2038, 2039, 2048}


@contextmanager
def edited(monkeypatch, change):
    with pdfplumber.open(SOURCES / FILES[date(2026, 1, 9)]) as pdf:
        page = next(p for p in pdf.pages if "Performance of Key Market Indicators" in (p.extract_text() or ""))
        text, words = page.extract_text(), [dict(w) for w in page.extract_words()]
    change(words)

    class Page:
        def extract_text(self):
            return text

        def extract_words(self):
            return words

    class Pdf:
        pages = [Page()]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(opens.pdfplumber, "open", lambda f: Pdf())
    yield


def row_of(words, text):
    day = next(w for w in words if w["text"] == text)
    return [w for w in words if abs(w["top"] - day["top"]) <= 6 and w["x0"] > day["x1"]]


def drop_a_figure(words):
    words.remove(row_of(words, "2-Jan-26")[-1])


def a_text_cell(words):
    row_of(words, "5-Jan-26")[3]["text"] = "n/a"


def a_sixth_year(words):
    head = next(w for w in words if w["text"] == "2048")
    words.append({**head, "text": "2050", "x0": head["x0"] + 34, "x1": head["x1"] + 34})


def an_other_year_beside_the_index_base(words):
    head = next(w for w in words if w["text"] == "2028")
    words.append({**head, "text": "2009", "x0": 80, "x1": 100})


def a_yield_under_no_year(words):
    row_of(words, "6-Jan-26")[-1].update(x0=700, x1=720)


@pytest.mark.parametrize("change", [drop_a_figure, a_text_cell, a_sixth_year, an_other_year_beside_the_index_base, a_yield_under_no_year])
def test_a_layout_it_does_not_know_is_refused_whole(monkeypatch, change):
    with edited(monkeypatch, change), pytest.raises(ValueError, match="expected 13|not a number|under no single|maturity years"):
        opens.parse(b"%PDF")


def test_a_year_list_without_the_five_form_issues_is_refused(monkeypatch):
    monkeypatch.setitem(opens.KEY, 2050, "2050_x")
    with pytest.raises(ValueError, match="five Eurobond issues"):
        opens.parse((SOURCES / FILES[date(2026, 1, 9)]).read_bytes())


def test_the_nine_yield_layout_of_november_is_read_and_the_issues_the_form_does_not_use_are_ignored():
    for day in (date(2026, 11, 6), date(2026, 11, 13)):
        days = opens.parse((SOURCES / FILES[day]).read_bytes())
        assert len(days) == 10 and set(next(iter(days.values()))) == {2028, 2031, 2032, 2033, 2034, 2036, 2038, 2039, 2048}


def test_a_page_without_the_table_is_refused(monkeypatch):
    monkeypatch.setattr(bulletin, "_TABLE_6_TITLE", re.compile("^Not this title"))
    with pytest.raises(ValueError, match="Performance of Key Market Indicators"):
        opens.parse((SOURCES / FILES[date(2026, 10, 9)]).read_bytes())


def test_the_first_printed_day_comes_from_an_issue_that_reaches_back_before_the_1st():
    day, yields, url, sha = opens.opening(2026, 10, 7, date(2026, 10, 9), archive())
    assert day == date(2026, 10, 1) and set(yields) == KEYS and len(sha) == 64 and "2%20October" in url


def test_a_missing_issue_is_skipped_for_any_issue_that_prints_the_day_and_if_none_does_the_analyst_types_it():
    day, _, url, _ = opens.opening(2026, 10, 7, date(2026, 10, 9), archive(missing=[date(2026, 10, 2)]))
    assert day == date(2026, 10, 1) and "9%20October" in url
    day, *_ = opens.opening(2026, 1, 8, date(2026, 1, 9), archive())
    assert day == date(2026, 1, 1)   # a month's first printed day counts a holiday row
    day, *_ = opens.opening(2026, 1, 8, date(2026, 1, 9), archive(), frozenset({date(2026, 1, 1)}))
    assert day == date(2026, 1, 2)   # the year's opening skips 1 January
    day, *_ = opens.opening(2026, 11, 7, date(2026, 11, 13), archive())
    assert day == date(2026, 11, 2)
    with pytest.raises(LookupError, match="2026-02-06 is not in CBK's archive"):
        opens.opening(2026, 2, 7, date(2026, 2, 13), archive())
    with pytest.raises(LookupError, match="no bulletin is dated"):
        opens.opening(2026, 10, 7, date(2026, 10, 1), archive())
    with pytest.raises(LookupError, match="no complete row"):
        opens.opening(2026, 1, 0, date(2026, 1, 9), archive())


def client(tmp_path, **kw):
    return TestClient(create_app(db_path=tmp_path / "app.db", load_dotenv=False, inputs_root=tmp_path / "weekly",
                                 fetch_items=lambda key, week: fetched_items.FETCHERS[key](week, TODAY, archive(**kw))))


def test_the_route_keeps_two_rows_marked_fetched_and_writes_five_series_with_the_bulletins_as_source(tmp_path):
    r = client(tmp_path).post("/api/inputs/weekly/2026-10-09/analyst/fetch/eurobond_yields?section=fixed_income")
    assert r.status_code == 200
    got = next(i for g in r.json()["groups"] for i in g["items"] if i["key"] == "eurobond_yields")
    assert [(x["row"], x["date"]) for x in got["rows"]] == [("year_open", "2026-01-02"), ("month_open", "2026-10-01")]
    assert got["carried"]["from"] == "fetched" and "Weekly Bulletin" in got["carried"]["note"]
    pts = store.current(tmp_path / "app.db", "fi.eurobond.yield", None)
    assert {p["subject"] for p in pts} == KEYS and {p["as_of"] for p in pts} == {"2026-01-02", "2026-10-01"} and len(pts) == 10
    assert {p["origin"] for p in pts} == {"fetched"} and all("sha256 " in p["source_ref"] for p in pts)


def test_when_an_opening_cannot_be_found_nothing_is_kept_and_the_reason_says_type_it(tmp_path):
    r = client(tmp_path, missing=[date(2026, 1, 9)]).post("/api/inputs/weekly/2026-10-09/analyst/fetch/eurobond_yields?section=fixed_income")
    assert r.status_code == 404 and "year's first day" in r.json()["detail"] and "type them under" in r.json()["detail"].lower()
    assert store.current(tmp_path / "app.db", "fi.eurobond.yield", None) == []


def test_an_issue_that_skips_a_weekday_between_the_old_month_and_the_first_day_is_not_trusted(monkeypatch):
    full = dict.fromkeys(opens.KEY, "1")
    monkeypatch.setattr(opens, "parse", lambda pdf: {date(2026, 10, 30): full, date(2026, 11, 3): full})   # Monday 2 Nov is missing
    with pytest.raises(LookupError, match="cannot be trusted"):
        opens.opening(2026, 11, 7, date(2026, 11, 13), archive())
