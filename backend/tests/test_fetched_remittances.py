from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly.history import store
from cytonn_weekly.weekly import cbk_remittances, fetched_items
from cytonn_weekly.weekly.week import Week

PAGE = (Path(__file__).parent / "fixtures" / "sources" / "cbk_diaspora_remittances_captured_2026-11-18.html").read_bytes()
FRIDAY = "2026-10-02"
TODAY = date(2026, 11, 18)


def get(url):
    return PAGE


def fake(key, week):
    return fetched_items.FETCHERS[key](week, TODAY, get)


def test_the_table_is_read_by_its_headers_in_thousands():
    months, sha = cbk_remittances.fetch_months(get)
    assert len(months) == 28 and "2026-10" in months and "2004-01" in months and len(sha) == 64
    na, total = months["2026-08"]
    assert isinstance(na, Decimal) and total > na > 0


@pytest.mark.parametrize("edit", [
    lambda h: h.replace("Total Remittances (USD &#039;000)", "Total Remittances (USD Million)").replace("Total Remittances (USD '000)", "Total Remittances (USD Million)"),
    lambda h: h.replace("North America", "Americas"),
    lambda h: "<html>no table</html>",
    lambda h: h.replace("<tbody>", "<tbody><tr><td>2026</td><td>09</td><td>n/a</td><td>1</td><td>1</td><td>1</td></tr>"),
    lambda h: h[:h.index("<tbody>")] + "<tbody></tbody></table>",
])
def test_a_page_that_is_not_in_the_expected_shape_is_refused_whole(edit):
    with pytest.raises(ValueError, match="diaspora remittances"):
        cbk_remittances.parse_months(edit(PAGE.decode("utf-8")))


def test_the_latest_24_months_up_to_the_week_are_converted_exactly_to_millions():
    months, _ = cbk_remittances.fetch_months(get)
    rows, note = fetched_items.remittances(Week(date(2026, 10, 2)), TODAY, get)
    assert len(rows) == 24 and rows[0]["month"] == "2026-10" and rows[-1]["month"] == "2024-11"
    for r in rows:
        assert Decimal(r["total"]) * 1000 == months[r["month"]][1] and Decimal(r["north_america"]) * 1000 == months[r["month"]][0]
    assert note.startswith("Central Bank of Kenya, diaspora remittances, https://www.centralbank.go.ke/diaspora-remittances/, fetched 2026-11-18, sha256 ")
    assert [r["month"] for r in fetched_items.remittances(Week(date(2026, 9, 4)), TODAY, get)[0]][0] == "2026-09"   # nothing after the week's month


def test_fewer_than_24_months_in_a_row_is_not_passed_off_as_the_table():
    with pytest.raises(ValueError, match="24 months in a row"):
        fetched_items.remittances(Week(date(2025, 1, 3)), TODAY, get)


def test_the_route_keeps_the_table_and_writes_two_monthly_series_with_their_source(tmp_path):
    root, db = tmp_path / "weekly", tmp_path / "app.db"
    c = TestClient(create_app(db_path=db, load_dotenv=False, inputs_root=root, fetch_items=fake))
    r = c.post(f"/api/inputs/weekly/{FRIDAY}/analyst/fetch/remittances?section=fixed_income")
    assert r.status_code == 200
    got = next(i for g in r.json()["groups"] for i in g["items"] if i["key"] == "remittances")
    assert len(got["rows"]) == 24 and got["carried"]["from"] == "fetched" and got["source"] == "Central Bank of Kenya, diaspora remittances"
    total, na = store.current(db, "fi.remittances.total"), store.current(db, "fi.remittances.north_america")
    assert len(total) == len(na) == 24
    assert {p["origin"] for p in total + na} == {"fetched"} and all("sha256 " in p["source_ref"] for p in total)
    assert {p["as_of"] for p in total} >= {"2026-10-31", "2026-02-28", "2024-12-31"}
    assert c.post(f"/api/inputs/weekly/{FRIDAY}/analyst/fetch/remittances").status_code == 200   # again: replaced rows, no point changed
    assert len(store.current(db, "fi.remittances.total")) == 24
