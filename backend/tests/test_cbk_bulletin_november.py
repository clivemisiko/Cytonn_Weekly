from datetime import date
from pathlib import Path

from cytonn_weekly.weekly import cbk_bulletin as bulletin

SOURCES = Path(__file__).parent / "fixtures" / "sources"


def read(name):
    return bulletin.parse_bulletin((SOURCES / name).read_bytes())


def test_the_13_november_bulletin_is_read_whole_with_nine_yield_columns_and_wrapped_bond_codes():
    b = read("cbk_weekly_bulletin_2026-11-13.pdf")
    assert b.unavailable == {} and len(b.market) == 10 and len(b.market[-1]["eurobond_yields"]) == 9
    assert len(b.tbonds["codes"]) == 8 and len(b.tbonds["auction_dates"]) == 5 and len(b.tbonds["bids"]) == 8


def test_the_6_november_bulletin_keeps_table_6_and_refuses_table_5_where_a_bond_code_is_missing_a_digit():
    b = read("cbk_weekly_bulletin_2026-11-06.pdf")
    assert list(b.unavailable) == ["Table 5"] and "one code per bond" in b.unavailable["Table 5"]
    assert len(b.market) == 10 and len(b.market[0]["eurobond_yields"]) == 9   # the stray "2008" over the NASI column is no yield column


def test_a_public_holiday_row_is_not_a_trading_day_and_does_not_stop_the_table():
    b = read("cbk_weekly_bulletin_2026-01-09.pdf")
    assert len(b.market) == 8 and date(2026, 1, 1) not in {r["date"] for r in b.market}
    assert len(b.market[0]["eurobond_yields"]) == 5
