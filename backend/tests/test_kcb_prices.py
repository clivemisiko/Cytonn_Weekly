from datetime import date

import pytest
from openpyxl import load_workbook

from cytonn_weekly.history import rows_export, store
from cytonn_weekly.history import weekly as history
from cytonn_weekly.weekly import kcb, kcb_prices
from cytonn_weekly.weekly.workbook import Workbook
from tests import weekly_helpers as wh

MAP = {"AAA": "Alpha Ltd", "BBB": "Beta Plc", "CCC": "Gamma"}
ROWS = ["Alpha Ltd", "Beta Plc", "Gamma"]


@pytest.mark.parametrize("case, rows, prices, mapping, want, flagged", [
    ("normal week", ROWS, {"AAA": 1.5, "BBB": 2.0, "CCC": 3.25}, MAP, [1.5, 2.0, 3.25], []),
    ("a KCB name with no map entry", ROWS, {"AAA": 1.5, "BBB": 2.0, "CCC": 3.25, "ZZZ": 9.0}, MAP, [1.5, 2.0, 3.25], ["ZZZ"]),
    ("two KCB names for one row", ROWS, {"AAA": 1.5, "BBB": 2.0, "CCC": 3.25, "DDD": 4.0}, {**MAP, "DDD": "Gamma"},
     [1.5, 2.0, None], ["Gamma: 2 KCB tickers (CCC, DDD)"]),
    ("a missing price", ROWS, {"AAA": 1.5, "CCC": 3.25}, MAP, [1.5, None, 3.25], ["Beta Plc: KCB's report has no price for BBB"]),
    ("a workbook row with no entry", ROWS + ["Delta"], {"AAA": 1.5, "BBB": 2.0, "CCC": 3.25}, MAP, [1.5, 2.0, 3.25, None],
     ["Delta: no KCB ticker is mapped"]),
    ("a changed order of securities in the report", ROWS, {"CCC": 3.25, "AAA": 1.5, "BBB": 2.0}, MAP, [1.5, 2.0, 3.25], []),
    ("no workbook: the map's order", None, {"CCC": 3.25, "AAA": 1.5, "BBB": 2.0}, MAP, [1.5, 2.0, 3.25], []),
])
def test_fill_keeps_the_sheets_order_and_flags_every_blank_by_name(case, rows, prices, mapping, want, flagged):
    filled, flags = kcb_prices.fill(rows, prices, mapping, name_unused=True)
    assert [r[0] for r in filled] == (rows or ROWS)
    assert [r[1] for r in filled] == want
    assert len(flags) == len(flagged) and all(any(f in g for g in flags) for f in flagged)


def test_a_row_name_is_matched_exactly_after_spaces_are_collapsed_never_fuzzily():
    filled, flags = kcb_prices.fill(["Alpha  Ltd ", "alpha ltd", "Alpha"], {"AAA": 1.5}, {"AAA": "Alpha Ltd"})
    assert [r[1] for r in filled] == [1.5, None, None] and len(flags) == 2


@pytest.mark.parametrize("mapping", [kcb_prices.MARKET_PE, kcb_prices.LARGE_CAPS])
def test_the_maps_have_one_ticker_per_row(mapping):
    assert len(set(mapping.values())) == len(mapping)


def test_a_kcb_weekly_upload_stores_every_kes_price_by_ticker_and_the_export_fills_both_blocks(tmp_path):
    db = tmp_path / "h.db"
    report = kcb.parse_kcb_text(wh.kcb_weekly_text())
    history.record_upload(wh.WEEK, "kcb_weekly", report, {"matches": True, "stored_name": "kcb.pdf", "sha256": "0"}, db)
    day = report.report_date.isoformat()
    held = {p["subject"]: p for p in store.current(db, "eq.price", None, since=day, through=day)}
    kes = {t for t, s in report.securities.items() if s["currency"] == "KES"}
    assert kes and kes <= set(held) and all(held[t]["origin"] == "fetched" for t in kes)
    assert not {t for t, s in report.securities.items() if s["currency"] == "USD"} & set(held)

    master = Workbook(wh.equities_workbook_bytes(), "eq.xlsx")
    wb = load_workbook(rows_export.write(wh.WEEK, db, tmp_path / "out", master, None))
    for title, rows in (("Market PE & Dividend Yield", wh.LARGE_CAPS), ("Gainers & Losers", list(wh.GAINERS_LOSERS))):
        got = [[c.value for c in r] for r in wb[title].iter_rows()]
        assert got[0][1].date() == report.report_date   # the sheet's own header: the date
        assert [r[0] for r in got[1:len(rows) + 1]] == rows   # the master's order
        for name, price in got[1:len(rows) + 1]:
            ticker = next((t for t, n in (kcb_prices.MARKET_PE if title.startswith("Market") else kcb_prices.LARGE_CAPS).items() if n == name), None)
            want = report.securities.get(ticker, {}).get("price") if ticker in kes else None
            assert price == want
            if want is None:
                assert any(n.startswith(f"Note: {name}:") for n in (r[0] for r in got if isinstance(r[0], str)))
    # the Universe of Coverage still lists companies, not the tickers stored beside them
    assert not any(isinstance(r[0].value, str) and r[0].value.isupper() and r[0].value in kes for r in wb["Universe of Coverage"].iter_rows(min_row=2))


def test_with_no_kcb_report_the_blocks_are_blank_and_say_so(tmp_path):
    wb = load_workbook(rows_export.write(wh.WEEK, tmp_path / "h.db", tmp_path / "out", None, None))
    got = [[c.value for c in r] for r in wb["Gainers & Losers"].iter_rows()]
    assert [r[0] for r in got[1:13]] == list(kcb_prices.LARGE_CAPS.values()) and all(r[1] is None for r in got[1:13])
    assert any("eq.price" in str(r[0]) and "no confirmed point" in str(r[0]) for r in got)
    assert date.fromisoformat(wh.WEEK.as_at.isoformat()) == got[0][1].date()
