from datetime import date

import pytest

from cytonn_weekly.weekly import nse_prices as p
from cytonn_weekly.weekly.inputs import InputError
from cytonn_weekly.weekly.nse_price_list import PriceListError
from cytonn_weekly.weekly.week import Week

# Invented securities and figures; the layout (column order, a name merged with its 52-week low) is the list's.
COLS = {"isin": 1065, "status": 1190, "high": 1345, "low": 1500, "vwap": 1655, "previous": 1840, "volume": 2040}
HEAD = [(x - 20, 340, x + 20, 352, t) for t, x in
        (("ISIN", 1065), ("TRADING", 1190), ("HIGH", 1345), ("LOW", 1500), ("VWAP", 1655), ("PREVIOUS", 1840), ("VOLUME", 2040))]


def line(y, name, isin, **cells):
    words = [(300, y, 360, y + 12, "12.00"), (450, y, 700, y + 12, f"8.00 {name}"), (1010, y, 1120, y + 12, isin)]
    return words + [(COLS[c] - 25, y, COLS[c] + 25, y + 12, v) for c, v in cells.items()]


def page_words():
    return HEAD + line(400, "Alpha Plc Ord 1.00", "KE0000000001", high="10.50", low="10,00", vwap="10.25", previous="10.00", volume="1,200") \
        + [(600, 432, 800, 444, "BANKING")] \
        + line(464, "Beta Ltd Ord 5.00", "KE0000000002", vwap="4.00", previous="4.00") \
        + line(496, "Beta Ltd 7% Pref 5.00", "KE0000000003", vwap="2.00", previous="2.00") \
        + line(528, "Delta Ltd Ord 0.50", "UG0000000004", vwap="6.00", previous="6.00")


def test_number_reads_a_comma_for_a_decimal_point():
    assert [p.number(t) for t in ("1,355.00", "7,30", "1,147,471", "abc", "")] == ["1355.00", "7.30", "1147471", None, None]


def test_rows_by_header_position_and_sector_rows_skipped():
    rows = p.rows_of(page_words(), p.headers(page_words()))
    assert [r["name"] for r in rows] == ["Alpha Plc Ord 1.00", "Beta Ltd Ord 5.00", "Beta Ltd 7% Pref 5.00", "Delta Ltd Ord 0.50"]
    assert rows[0]["low"] == "10.00" and rows[0]["volume"] == "1200" and rows[1]["high"] is None


def test_states_and_a_disagreeing_cell():
    cols = p.headers(page_words())
    a = p.rows_of(page_words(), cols)
    other = [w if w[4] != "4.00" or w[0] < 1700 else (*w[:4], "4.50") for w in page_words()]
    rows = p.pair(a, p.rows_of(other, cols))
    assert [p.state(r) for r in rows] == ["traded", "unread", "untraded", "untraded"]
    assert rows[1]["unresolved"] == ["previous"]


def test_isin_letters_read_for_zero_compare_equal():
    assert p.isin_key("KEOC00000315") == p.isin_key("KE0000000315")


class _Page:
    shape = (3300, 2550)

    def __getitem__(self, _):
        return self


def test_refuses_a_list_not_dated_the_report_day():
    engine = lambda image: [(0, 0, 9, 9, "October 8, 2026")]
    with pytest.raises(PriceListError, match="dated 8 Oct"):
        p.read_prices(b"%PDF", Week(date(2026, 10, 16)), engine=engine, render=lambda pdf: [_Page()])


def test_refuses_a_list_without_headings():
    engine = lambda image: [(0, 0, 9, 9, "October 16, 2026")]
    with pytest.raises(PriceListError, match="headings"):
        p.read_prices(b"%PDF", Week(date(2026, 10, 16)), engine=engine, render=lambda pdf: [_Page()])


def test_mapping_first_word_ambiguity_and_exact_keys():
    rows = p.pair(*(p.rows_of(page_words(), p.headers(page_words())),) * 2)
    rows = [{"id": n, **r} for n, r in enumerate(rows)]
    data = p.parse_map("Alpha\nBeta\nBeta Pref | 7% Pref\nGamma\nBeta ord | KE0000000002\nDelta | UG0000000004")
    got = {c["stock"]: (c["state"], c["found"]) for c in p.classify(data, rows)}
    assert got == {"Alpha": ("traded", 1), "Beta": ("unmatched", 2), "Beta Pref": ("untraded", 1),
                   "Gamma": ("unmatched", 0), "Beta ord": ("untraded", 1), "Delta": ("untraded", 1)}


def test_map_refuses_duplicates_and_bad_keys(tmp_path):
    with pytest.raises(InputError, match="twice"):
        p.parse_map("Alpha\nalpha")
    with pytest.raises(InputError, match="key"):
        p.parse_map("Alpha | x")
    p.write_map("Alpha | KE0000000001\nBeta", root=tmp_path / "inputs")
    assert p.map_text(p.read_map(tmp_path / "inputs")) == "Alpha | KE0000000001\nBeta"


def test_a_dropped_decimal_point_agreed_by_both_readings_is_unread():
    words = HEAD + line(400, "Alpha Plc Ord 1.00", "KE0000000001", high="1.05", low="1.00", vwap="102", previous="1.00", volume="900")
    rows = p.rows_of(words, p.headers(words))
    assert rows[0]["vwap"] == p.BAD and p.state(p.pair(rows, rows)[0]) == "unread"
