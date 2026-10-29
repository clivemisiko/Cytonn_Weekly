"""The 91-day T-bill figures from CBK's auction results files when the bulletin's Table 4 does not print them."""

from datetime import date

from cytonn_weekly.common.computed import SOURCE
from cytonn_weekly.fixed_income import cbk_auctions
from cytonn_weekly.fixed_income import weekly as fiw
from cytonn_weekly.weekly import cbk_bulletin
from cytonn_weekly.weekly.week import Week

WEEK = Week(date(2026, 10, 2))
THIS_AUCTION, LAST_AUCTION = date(2026, 10, 1), date(2026, 9, 24)      # the Thursdays, as Table 4 dates them
THIS_VALUE, LAST_VALUE = date(2026, 10, 5), date(2026, 9, 28)          # the Mondays they settle, as the files are named
URL = "https://www.centralbank.go.ke/uploads/91_day_historical_treasury_bill_results/x_05-10-2026.pdf"


def table_4_row(day, bids, rate):
    return {"date": day, "offered": 10000.0, "bids": bids, "accepted": bids * 0.9, "rate": rate}


def bulletin_without_91_day():
    out = cbk_bulletin.Bulletin(issue_date=WEEK.ending)
    out.tbills = {"182-day": [table_4_row(THIS_AUCTION, 12000.0, 7.9), table_4_row(LAST_AUCTION, 11000.0, 7.95)],
                  "364-day": [table_4_row(THIS_AUCTION, 15000.0, 9.1), table_4_row(LAST_AUCTION, 14000.0, 9.2)]}
    return out


def results_file(value_date, bids_bn, accepted_m, rate, url=URL):
    """One auction as cbk_auctions.fetch_period_tbills returns it (amounts in bn per row, accepted in mn)."""
    rows = [{"tenor": t, "offered_kes_bn": 4.0, "bids_kes_bn": bids_bn, "accepted_kes_bn": accepted_m / 1000,
             "avg_rate_pct": rate, "error": None} for t in cbk_auctions.TENORS]
    return {"url": url, "kind": "tbill", "value_date": value_date.isoformat(), "error": None, "rows": rows,
            "accepted_kes_m": {t: accepted_m for t in cbk_auctions.TENORS}}


RESULTS = {"auctions": [results_file(THIS_VALUE, 8.12345, 7000.5, 7.8123), results_file(LAST_VALUE, 6.5, 5000.0, 7.85, "u")]}


def test_the_91_day_figures_come_from_the_results_files_when_table_4_lacks_them():
    b = bulletin_without_91_day()
    assert fiw._auction_rows(b, WEEK) is None and fiw._missing_tenors(b, WEEK) == ["91-day"]
    rows = fiw._auction_rows(b, WEEK, fiw._results_rows(RESULTS, WEEK))
    assert rows[2] == ["91-day"]
    inputs = fiw._tbill_inputs(b, WEEK, None, rows)
    assert inputs["bids_91"]["value"] == 8123.45 and inputs["offered_91"]["value"] == 4000.0   # back in Kshs mn, as Table 4
    assert inputs["accepted_91"]["value"] == 7000.5 and inputs["rate_91"]["value"] == 7.8123
    assert (inputs["prev_bids_91"]["value"], inputs["prev_rate_91"]["value"]) == (6500.0, 7.85)
    assert inputs["bids_91"]["source"] == "CBK T-bill auction results, value date 2026-10-05"
    assert inputs["bids_91"]["origin"] == SOURCE                       # a CBK publication, not marked as not verified
    assert inputs["bids_182"]["source"] == "CBK Weekly Bulletin, Table 4"   # the tenors Table 4 prints stay its own
    block = fiw.tbills_block(inputs, b)
    assert block["kind"] == "computed"
    assert block["sources"] == [{"name": "CBK Weekly Bulletin, Table 4", "url": cbk_bulletin.LISTING},
                                {"name": "CBK T-bill auction results", "url": cbk_auctions.TBILL_LISTING}]
    notice = fiw.tbill_notice(b, WEEK, rows, RESULTS)
    assert notice["text"] == ("The 91-day T-bill figures came from CBK's auction results files, because the weekly bulletin "
                              "table did not include them.")
    assert (notice["kind"], notice["level"], notice["link"]) == ("source", "info", URL)
    assert notice["days"] == ["2026-09-28", "2026-10-05"]


def test_with_no_results_file_the_block_stays_missing_and_a_warning_says_so():
    b = bulletin_without_91_day()
    rows = fiw._auction_rows(b, WEEK, fiw._results_rows(None, WEEK))
    assert rows is None
    assert fiw.tbills_block(None, b)["kind"] == "unavailable"            # today's behaviour
    notice = fiw.tbill_notice(b, WEEK, rows, None)
    assert notice["level"] == "warning"
    assert notice["text"] == ("The 91-day T-bill figures are missing. The weekly bulletin table did not include them, and CBK's "
                              "auction results files could not be fetched.")


def test_a_results_file_for_one_week_only_is_not_enough():
    b = bulletin_without_91_day()
    only_this_week = {"auctions": RESULTS["auctions"][:1]}
    assert fiw._auction_rows(b, WEEK, fiw._results_rows(only_this_week, WEEK)) is None
    assert fiw.tbill_notice(b, WEEK, None, only_this_week)["text"].endswith(
        "do not hold both this week's and the previous week's auction.")


def test_an_unreadable_results_file_is_not_used():
    broken = {"auctions": [{**RESULTS["auctions"][0], "error": "ValueError: bad pdf"}, RESULTS["auctions"][1]]}
    assert fiw._results_rows(broken, WEEK)[0] == {}


def test_a_full_table_4_needs_no_results_file_and_gives_no_notice():
    b = bulletin_without_91_day()
    b.tbills["91-day"] = [table_4_row(THIS_AUCTION, 9000.0, 7.7), table_4_row(LAST_AUCTION, 8000.0, 7.75)]
    rows = fiw._auction_rows(b, WEEK)
    assert rows[2] == [] and fiw.tbill_notice(b, WEEK, rows, None) is None
    assert fiw._tbill_inputs(b, WEEK, None, rows)["bids_91"]["source"] == "CBK Weekly Bulletin, Table 4"


def test_the_section_fetches_the_results_files_only_when_table_4_lacks_a_tenor(tmp_path, monkeypatch):
    calls = []

    def results(start, end, folder):
        calls.append((start, end))
        return RESULTS

    from cytonn_weekly.weekly import inputs as wi
    from tests import weekly_helpers as wh

    b = bulletin_without_91_day()
    monkeypatch.setattr(wi.WeeklyInputs, "bulletin", property(lambda self: b))
    monkeypatch.setattr(wi.WeeklyInputs, "matches", lambda self, name: True)
    down = lambda *a: (_ for _ in ()).throw(LookupError("not in this test"))   # noqa: E731
    fetchers = fiw.Fetchers(usd_rates=down, bulletin=down, tbonds=down, previous_issue=down, releases=down,
                            tbill_results=results)
    review = fiw.build_fixed_income_review(WEEK.ending, inputs=wi.WeeklyInputs(WEEK, tmp_path), fetchers=fetchers,
                                           draft=wh.no_draft)
    assert calls == [(WEEK.previous.value_date_window[0], WEEK.value_date_window[1])]
    assert next(blk for blk in review.section["blocks"] if blk["id"] == "tbills")["kind"] == "computed"
    assert [n["text"] for n in review.section["notices"] if n.get("kind") == "source"] == [
        "The 91-day T-bill figures came from CBK's auction results files, because the weekly bulletin table did not include them."]
