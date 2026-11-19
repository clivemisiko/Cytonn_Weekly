from datetime import date
from pathlib import Path

import pytest

from cytonn_weekly.weekly import cbk_bulletin as bulletin

SOURCES = Path(__file__).parent / "fixtures" / "sources"
HOLIDAY = date(2026, 10, 20)


def read(name):
    return bulletin.parse_bulletin((SOURCES / name).read_bytes())


def test_the_23_october_bulletin_is_read_whole_though_a_gdp_table_came_first_and_moved_every_number():
    b = read("cbk_weekly_bulletin_2026-10-23.pdf")
    assert b.unavailable == {}
    assert (len(b.exchange_rates), len(b.reserves), len(b.interbank), len(b.interbank_weeks), len(b.market), len(b.bond_stock)) == (9, 5, 9, 2, 9, 8)
    assert sorted(b.tbills) == ["182-day", "364-day", "91-day"] and len(b.tbonds["codes"]) == 7


def test_the_30_october_bulletin_is_read_whole_and_the_public_holiday_has_no_row_in_any_table():
    b = read("cbk_weekly_bulletin_2026-10-30.pdf")
    assert b.unavailable == {}
    assert (len(b.exchange_rates), len(b.interbank), len(b.market)) == (9, 9, 9)
    assert HOLIDAY not in b.exchange_rates and HOLIDAY not in {r["date"] for r in b.interbank} | {r["date"] for r in b.market}
    assert len(b.interbank_weeks) == 2 and all(w["last_day"] in {r["date"] for r in b.interbank} | {HOLIDAY} for w in b.interbank_weeks)


def test_a_table_is_found_by_its_title_wherever_its_number_falls():
    out = bulletin.Bulletin(issue_date=None)
    bulletin._table_1(["Table 1: Real GDP Growth by Sector (Percent)", "20-Oct-26 9 9", "Table 2: Kenya Shilling Exchange Rates",
                       "21-Oct-26 1.5 2.5", "22-Oct-26 1.6 2.6"], out)
    assert list(out.exchange_rates) == [date(2026, 10, 21), date(2026, 10, 22)]
    with pytest.raises(bulletin.BulletinParseError, match="'Table 1' not found"):
        bulletin._table_1(["Table 1: Real GDP Growth by Sector (Percent)", "21-Oct-26 1.5"], bulletin.Bulletin(issue_date=None))


def test_only_the_words_public_holiday_stand_in_for_a_days_figures():
    title = "Table 1: Kenya Shilling Exchange Rates"
    out = bulletin.Bulletin(issue_date=None)
    bulletin._table_1([title, "20-Oct-26 Public Holiday", "21-Oct-26 1.5 2.5"], out)
    assert list(out.exchange_rates) == [date(2026, 10, 21)]
    for junk in ("n/a", "PUBLIC", "HOLIDAY 1.5", "1.5"):
        with pytest.raises(bulletin.BulletinParseError, match="does not hold 2 rates"):
            bulletin._table_1([title, "21-Oct-26 1.5 2.5", f"22-Oct-26 {junk}"], bulletin.Bulletin(issue_date=None))
    out = bulletin.Bulletin(issue_date=None)
    bulletin._table_3(["Table 3: Interbank Deals, Volumes and Interest Rates", "19-Oct-26 4 5 6", "20-Oct-26 PUBLIC HOLIDAY", "Oct 16-20 1 2 3"], out)
    assert [r["date"] for r in out.interbank] == [date(2026, 10, 19)] and out.interbank_weeks[0]["last_day"] == HOLIDAY
    with pytest.raises(bulletin.BulletinParseError, match="does not hold deals"):
        bulletin._table_3(["Table 3: Money Market", "19-Oct-26 4 5"], bulletin.Bulletin(issue_date=None))
