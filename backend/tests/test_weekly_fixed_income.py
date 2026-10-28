"""The weekly Fixed Income section and the checking policy behind computed paragraphs.

The golden figures are the "during the week" figures the Q3'2026 review printed for the
week ending Friday 2 October 2026 (cytonnreport.com issue 892).  Those that come from
public sources (the CBK Weekly Bulletin of 2 October 2026, CBK's auction results and daily
rates) are asserted here from the committed fixtures.  Those that need the fixed income
workbook are asserted in the tests that read the real, confidential sample and skip
without it.
"""

import hashlib
import json
from collections import Counter
from datetime import date

import pytest

from cytonn_weekly.checkers.digital_payments import MISMATCH, MISSING, SOURCES_DISAGREE, UNSOURCED
from cytonn_weekly.common import computed
from cytonn_weekly.common.computed import ANALYST, BPS, OCR, PLAIN, PLAIN_PCT, POINTS, SOURCE, a_figure, an_input
from cytonn_weekly.common.checks import check_table_block
from cytonn_weekly.common.formatting import MULTIPLE, PCT
from cytonn_weekly.common.review import build_review, check_section, numbered, table_block
from cytonn_weekly.common.run_events import EventLog
from cytonn_weekly.equities import weekly as eqw
from cytonn_weekly.fixed_income import weekly as fiw
from cytonn_weekly.weekly import cbk_bulletin, inputs, previous_issue
from cytonn_weekly.weekly.week import Week
from tests import previous_issue_fixture as fx
from tests import weekly_helpers as wh
from tests.weekly_helpers import text_pdfs  # noqa: F401 - a fixture

WEEK = wh.WEEK
BULLETIN = (wh.FIXTURES / "cbk_weekly_bulletin_2026-10-02.pdf").read_bytes()
RATES = {date.fromisoformat(d): v for d, v in
         json.loads((wh.FIXTURES / "cbk_usd_rates_captured_2026-10-09.json").read_text())["rates"].items()}
TBONDS = json.loads((wh.FIXTURES / "cbk_tbond_results_value_2026-10-05_captured_2026-10-09.json").read_text())

PREVIOUS_FI = """
<p><strong>Kenya Shilling:</strong></p>
<p>During the week, the Kenya Shilling was stable.</p>
<p>The shilling is however expected to remain under pressure in 2026 as a result of:</p>
<ul><li>An ever-present current account deficit, and,</li><li>The need for government debt servicing.</li></ul>
<p>Kenya's forex reserves decreased by 0.3% during the week.</p>
<p><strong>Weekly Highlights</strong></p>
<p>Rates in the fixed income market have declined MTD. Inflation stood at 6.6%, within the target range of 2.5%-7.5%. The
government is 235.8% ahead of its prorated net domestic borrowing target of Kshs 224.8 bn, having a net borrowing position of
Kshs 530.0mn (inclusive of T-bills). We expect investors to prefer short to medium-term papers.</p>
"""
PREVIOUS_EQ = "<p>Market Performance:</p><p>We maintain a cautiously optimistic short-term outlook.</p>"
ISSUE = previous_issue.Issue(891, date(2026, 9, 27), {
    "fixed-income": {"name": "Fixed Income", "body": PREVIOUS_FI, "summary": ""},
    "equities": {"name": "Equities", "body": PREVIOUS_EQ, "summary": ""},
})


def no_releases(start, end, folder):
    """CBK's result files are not fetched: the borrowing log is then the typed one, else the workbook's (the fallback).
    The log built from CBK's results is tested in test_net_borrowing.py."""
    raise LookupError("CBK's results are not fetched in this test")


def fetchers(**over):
    base = dict(usd_rates=lambda: RATES, bulletin=lambda day: (_ for _ in ()).throw(LookupError("no bulletin")),
                tbonds=lambda start, end: TBONDS, previous_issue=lambda day, ref: ISSUE, releases=no_releases)
    return fiw.Fetchers(**{**base, **over})


def build(root, **over):
    return fiw.build_fixed_income_review(WEEK.ending, inputs=inputs.WeeklyInputs(WEEK, root), fetchers=over.pop("fetchers", fetchers()),
                                         draft=wh.no_draft, **over)


@pytest.fixture
def root(tmp_path):
    """The week's inputs: the real (public) bulletin and a synthetic fixed income workbook."""
    inputs.store(WEEK, "cbk_bulletin", BULLETIN, "bulletin.pdf", tmp_path)
    inputs.store(WEEK, "fi_workbook", wh.fi_workbook_bytes(), "FI.xlsx", tmp_path)
    return tmp_path


def blocks(review):
    return {b["id"]: b for b in review.section["blocks"]}


def figures(block):
    return {f["key"]: f["display"] for f in block["figures"]}


def items(review, prefix):
    return [i for i in review.review_items if i.ref.startswith(prefix)]


# ---------------------------------------------------------------------------
# Computed figures: the expressions, the display, the policy
# ---------------------------------------------------------------------------

def test_expressions_are_worked_out_exactly():
    inputs_ = {"a": {"value": 399.0}, "b": 400.0}
    assert computed.evaluate(computed.pct_change("a", "b"), inputs_) == computed.Decimal("-0.25")
    assert computed.evaluate(["mean", "a", "b", 401], inputs_) == 400
    assert computed.evaluate(["sum", ["div", "a", 3], ["mul", "b", 2], ["neg", ["abs", -1]]], inputs_) == 932
    assert computed.evaluate(computed.ratio_pct("a", "b"), inputs_) == computed.Decimal("99.75")
    for bad in (["div", "a", 0], ["pow", "a", 2], "missing", ["add", "a"], [], True):
        with pytest.raises(computed.ComputeError):
            computed.evaluate(bad, inputs_)


def test_a_sentence_prints_the_size_of_a_move_and_a_table_prints_its_sign():
    assert computed.show(-0.87, BPS, 1) == "0.9 bps" and computed.show(-0.04, BPS, 2) == "0.04 bps"
    assert computed.show(170.4167, PLAIN_PCT, 1) == "170.4%" and computed.show(-34.356, PLAIN_PCT, 1) == "34.4%"
    assert computed.show(3053.1346, PLAIN, 1) == "3,053.1" and computed.show(1.0239, POINTS, 1) == "1.0% points"
    assert computed.show(-0.25, PCT, 1) == "(0.3%)" and computed.show(0.9525, MULTIPLE, 1) == "1.0x"   # half up, never half to even


def _block(fig, body=None):
    return {"kind": "computed", "id": "b", "title": "Block", "body_md": body if body is not None else f"It was {fig['display']}.",
            "figures": [fig], "sources": [], "notes": []}


def test_a_figure_from_published_inputs_is_clean_and_is_worked_out_again():
    fig = a_figure("sub", "Subscription", PLAIN_PCT, 1, {"bids": an_input(47716.68, SOURCE, "CBK"), "offered": an_input(28000, SOURCE, "CBK")},
                   computed.ratio_pct("bids", "offered"))
    assert fig["display"] == "170.4%"
    assert computed.check_figure_record(_block(fig), fig) == ([], "")
    tampered = {**fig, "display": "170.5%"}
    flags, _ = computed.check_figure_record(_block(tampered), tampered)
    assert [f.kind for f in flags] == [MISMATCH] and "170.4 worked out from its inputs" in flags[0].message
    flags, _ = computed.check_figure_record(_block(fig, body="The sentence leaves the figure out."), fig)
    assert [f.kind for f in flags] == [MISSING] and "does not appear in the paragraph" in flags[0].message


def test_a_figure_that_rests_on_a_typed_cell_is_never_clean():
    typed = an_input(9.0, ANALYST, "analyst input from Fixed income workbook 'Money Market Performance'!C6")
    fig = a_figure("placements", "Placements", PLAIN_PCT, 1, {"placements": typed})
    flags, note = computed.check_figure_record(_block(fig), fig)
    assert flags == [] and note.startswith("Not auto-verified: placements (9.0) is an analyst input from Fixed income workbook")
    review = build_review({"section": "x", "blocks": numbered([_block(fig)])}, check_section({"blocks": [_block(fig)]}))
    assert [(i.kind, i.status) for i in review.review_items] == [("computed_figure", "not_auto_verified")]
    # ...even when the arithmetic on it is exact: a figure worked out from a typed cell is not auto-verified either
    derived = a_figure("x", "Twice", PLAIN, 1, {"placements": typed}, ["mul", "placements", 2])
    assert computed.check_figure_record(_block(derived), derived)[1].startswith("Not auto-verified")
    # A published source agreeing with the typed cell does verify it.
    confirmed = a_figure("r", "Rate", PLAIN, 2, {"r": an_input(129.76, ANALYST, "analyst input", decimals=2,
                                                                 second={"value": 129.76, "source": "CBK", "origin": SOURCE})})
    assert computed.check_figure_record(_block(confirmed), confirmed) == ([], "")


def test_an_ocr_figure_needs_a_second_source():
    alone = a_figure("nse10", "NSE 10", PLAIN, 2, {"level": an_input(2750.05, OCR, "NSE daily price list")})
    flags, _ = computed.check_figure_record(_block(alone), alone)
    assert [f.kind for f in flags] == [UNSOURCED] and "read by OCR" in flags[0].message and "no second source" in flags[0].message
    differs = a_figure("nse10", "NSE 10", PLAIN, 2, {"level": an_input(2750.05, OCR, "NSE daily price list", decimals=2,
                                                                        second={"value": 2750.50, "source": "workbook", "origin": ANALYST})})
    flags, _ = computed.check_figure_record(_block(differs), differs)
    assert [f.kind for f in flags] == [SOURCES_DISAGREE]
    typed_agrees = a_figure("nse10", "NSE 10", PLAIN, 2, {"level": an_input(2750.05, OCR, "NSE daily price list", decimals=2,
                                                                             second={"value": 2750.05, "source": "the workbook", "origin": ANALYST})})
    flags, note = computed.check_figure_record(_block(typed_agrees), typed_agrees)
    assert flags == [] and "no published second source" in note    # agreed by a typed value only: not auto-verified
    published = a_figure("nasi", "NASI", PLAIN, 2, {"level": an_input(247.32, OCR, "NSE daily price list", decimals=2,
                                                                       second={"value": 247.32, "source": "KCB", "origin": SOURCE})})
    assert computed.check_figure_record(_block(published), published) == ([], "")
    # a second reading of the figure itself (afx's own week-on-week change) confirms an OCR'd input too
    with_afx = {**alone, "second": {"value": 2750.05, "source": "afx.kwayisi.org", "decimals": 2}}
    assert computed.check_figure_record(_block(with_afx), with_afx) == ([], "")
    with_other = {**alone, "second": {"value": 2760.0, "source": "afx.kwayisi.org", "decimals": 2}}
    assert SOURCES_DISAGREE in [f.kind for f in computed.check_figure_record(_block(with_other), with_other)[0]]


def test_a_builders_own_flag_and_carried_text_are_always_flagged():
    fig = a_figure("placements", "Placements", PLAIN_PCT, 1, {"p": an_input(9.0, ANALYST, "analyst input")})
    fig["flag"] = "its source is unconfirmed"
    flags, _ = computed.check_figure_record(_block(fig), fig)
    assert [f.kind for f in flags] == [UNSOURCED] and flags[0].message == "Placements: its source is unconfirmed"
    carried = computed.carried_block("outlook", "Outlook", "Old text.", {"issue_id": 891, "url": "u", "published": "2026-09-27"})
    content = {"section": "x", "blocks": numbered([carried])}
    review = build_review(content, check_section(content))
    item = review.review_items[0]
    assert (item.kind, item.status, item.ref) == ("carried_text", "flagged", "Outlook (carried forward)")
    assert item.detail[0].message.startswith("carried forward, edit before approving: this text is copied from issue 891")
    assert not review.is_approvable


def test_a_table_row_can_be_analyst_input_and_a_derived_column_is_worked_out_again():
    columns = [{"key": "name", "label": "Name", "fmt": "text"}, {"key": "price", "label": "Price", "fmt": "price", "decimals": 1},
               {"key": "last", "label": "Last", "fmt": "price", "decimals": 1},
               {"key": "wow", "label": "w/w", "fmt": PCT, "decimals": 1, "expr": computed.pct_change("price", "last")}]
    rows = [{"name": "A", "price": 399.0, "last": 400.0, "wow": -0.25}, {"name": "B", "price": 110.0, "last": 100.0, "wow": 10.0}]
    block = table_block("t", "T", columns, rows, "name", "name", {"name": "workbook", "url": None, "as_of": None})
    assert block["rows"][0]["wow"] == "(0.3%)" and check_table_block(block).flags == []
    block["row_origin"] = ANALYST
    content = {"section": "x", "blocks": numbered([block])}
    review = build_review(content, check_section(content))
    assert [i.status for i in review.review_items] == ["not_auto_verified", "not_auto_verified"]
    wrong = table_block("t", "T", columns, [{**rows[1], "wow": 12.0}], "name", "name", {"name": "w", "url": None, "as_of": None})
    flags = check_table_block(wrong).flags
    assert [f.kind for f in flags] == [MISMATCH] and "10.0 worked out from the row's inputs" in flags[0].message
    # a second source that disagrees is a "sources disagree" flag on that cell
    block["second_sources"] = [{"row": "B", "column": "price", "source": "CBK", "value": 111.0}]
    report = check_section({"blocks": [block]})
    assert [(f.kind, f.subject) for f in report.flags] == [(SOURCES_DISAGREE, "t/B")]


# ---------------------------------------------------------------------------
# The section: public golden figures (week ending 2 October 2026)
# ---------------------------------------------------------------------------

def test_the_section_is_in_the_real_issues_order(root):
    review = build(root)
    ids = [b["id"] for b in review.section["blocks"]]
    assert ids == ["tbills", "tbonds", "bidding_range", "money_market", "mmf_table", "liquidity", "eurobonds", "eurobonds_issues",
                   "eurobonds_table", "shilling", "shilling_support", "shilling_pressure", "outlook", "borrowing"]
    assert review.section["section"] == "fixed_income" and review.section["week_ending"] == "2026-10-02"
    assert len(review.section["chart_notes"]) == 6 and review.section["chart_reference"] == "Cytonn Weekly #38.2026"
    assert review.section["shortfall"] == fiw.N_HIGHLIGHTS   # no highlight was found (drafting is stubbed out here)


def test_tbills_reproduce_the_published_week(root):
    b = blocks(build(root))["tbills"]
    f = figures(b)
    assert (f["subscription"], f["prev_subscription"], f["acceptance"]) == ("170.4%", "149.0%", "86.3%")
    assert (f["bids_bn"], f["accepted_bn"], f["bids_91_bn"], f["offered_91_bn"]) == ("47.7", "41.2", "18.0", "8.0")
    assert (f["subscription_91"], f["subscription_182"], f["subscription_364"]) == ("224.8%", "191.5%", "105.9%")
    assert (f["prev_subscription_91"], f["prev_subscription_182"], f["prev_subscription_364"]) == ("221.7%", "127.6%", "112.3%")
    assert (f["yield_91"], f["bps_91"], f["prev_yield_91"]) == ("8.77%", "0.9 bps", "8.78%")
    assert (f["yield_182"], f["bps_182"], f["yield_364"], f["bps_364"]) == ("8.89%", "0.9 bps", "9.04%", "0.3 bps")
    assert b["body_md"].startswith("This week, T-bills were oversubscribed, with the overall subscription rate coming in at "
                                   "170.4%, higher than the subscription rate of 149.0% recorded the previous week.")
    assert "the yield on the 364-day paper decreased by 0.3 bps to remain relatively unchanged at 9.04%" in b["body_md"]
    assert "The government accepted a total of Kshs 41.2 bn worth of bids out of Kshs 47.7 bn bids received" in b["body_md"]


def test_tbonds_reproduce_cbks_results_for_the_week(root):
    b = blocks(build(root))["tbonds"]
    f = figures(b)
    assert (f["subscription"], f["bids_bn"], f["offered_bn"], f["accepted_bn"], f["acceptance"]) == (
        "161.1%", "80.6", "50.0", "57.5", "71.4%")
    assert (f["yield_0"], f["yield_1"], f["tenor_0"], f["tenor_1"], f["coupon_0"], f["coupon_1"]) == (
        "12.7%", "13.6%", "7.8", "12.5", "12.3%", "12.9%")
    assert "FXD3/2019/015" in b["body_md"] and "FXD1/2019/020" in b["body_md"] and "FXD1/2018/015" not in b["body_md"]  # the switch is not a primary auction


def test_liquidity_volumes_eurobonds_shilling_and_reserves_reproduce_the_published_week(root):
    by = blocks(build(root))
    liquidity = figures(by["liquidity"])
    assert (liquidity["volume_change"], liquidity["volume_bn"], liquidity["prev_volume_bn"]) == ("34.4%", "9.5", "14.5")
    assert "volumes traded decreased by 34.4% to Kshs 9.5 bn from Kshs 14.5 bn" in by["liquidity"]["body_md"]
    euro = figures(by["eurobonds"])
    assert (euro["biggest_bps"], euro["biggest_yield"], euro["biggest_previous"]) == ("75.6 bps", "7.6%", "6.9%")
    assert "the yield on the 10-year Eurobond issued in 2018 increasing the most by 75.6 bps to 7.6% from 6.9%" in by["eurobonds"]["body_md"]
    table = {r["label"]: [r[k] for k in ("2018_10y", "2018_30y", "2019_12y", "2021_13y", "2024_7y")] for r in by["eurobonds_table"]["rows"]}
    assert table["24-Sep-26"] == ["6.9%", "9.4%", "8.0%", "8.5%", "7.8%"]
    assert table["25-Sep-26"] == ["7.1%", "9.5%", "8.2%", "8.7%", "7.9%"]
    assert table["28-Sep-26"] == ["7.4%", "9.6%", "8.5%", "9.0%", "8.1%"]
    assert table["29-Sep-26"] == ["7.3%", "9.6%", "8.4%", "8.8%", "8.0%"]
    assert table["30-Sep-26"] == ["7.3%", "9.5%", "8.4%", "8.9%", "8.0%"]
    assert table["01-Oct-26"] == ["7.6%", "9.8%", "8.8%", "9.2%", "8.3%"]
    assert table["Weekly Change"] == ["0.8%", "0.4%", "0.7%", "0.7%", "0.5%"]   # percentage points
    assert by["eurobonds_table"]["source"]["name"] == "Central Bank of Kenya (CBK) Weekly Highlights"
    shilling = figures(by["shilling"])
    assert (shilling["week_bps"], shilling["rate"], shilling["previous_rate"]) == ("10.8 bps", "129.8", "129.6")
    assert (shilling["ytd_bps"], shilling["last_year_bps"]) == ("55.0 bps", "22.9 bps")
    assert by["shilling"]["body_md"] == (
        "During the week, the Kenya Shilling depreciated against the US Dollar by 10.8 bps, to close the week at Kshs 129.8, "
        "from Kshs 129.6 recorded the previous week. On a year-to-date basis, the shilling has depreciated by 55.0 bps against "
        "the dollar, compared to the 22.9 bps appreciation recorded in 2025.")
    support = figures(by["shilling_support"])
    assert (support["reserves"], support["previous_reserves"], support["import_cover"], support["reserves_change"]) == (
        "14,930.0", "15,042.0", "6.1", "0.7%")


def test_published_figures_are_clean_and_typed_ones_are_analyst_input(root):
    review = build(root)
    assert {i.status for i in items(review, "Money Markets, T-Bills Primary Auction:")} == {"clean"}
    assert {i.status for i in items(review, "T-Bonds Primary Market:")} == {"clean"}
    assert {i.status for i in items(review, "Kenya Shilling: Shilling")} == {"clean"}
    table = items(review, "Money Market Fund Yield for Fund Managers")
    assert len(table) == len(wh.FUNDS) and {i.status for i in table} == {"not_auto_verified"}
    assert "typed from Business Daily" in table[0].detail and "'Money Market Performance'!S12:U18" in table[0].detail
    top5 = items(review, "Money Market Performance: Average yield of the Top 5")[0]
    assert top5.status == "not_auto_verified" and "(10.72%)" in top5.ref   # the five highest rates of this week's table
    assert items(review, "Cytonn Report: Kenya Eurobonds Performance: 02-Jan-26")[0].status == "not_auto_verified"   # workbook only
    # The bulletin's days are printed from the bulletin; the synthetic workbook's invented yields differ from it, which is
    # exactly a "sources disagree" flag (the real workbook agrees: see the real-sample test below).
    day = items(review, "Cytonn Report: Kenya Eurobonds Performance: 01-Oct-26")[0]
    assert day.status == "flagged" and {f.kind for f in day.detail} == {SOURCES_DISAGREE}
    assert day.detail[0].sources[0]["source"] == "Central Bank of Kenya (CBK) Weekly Highlights"


def test_what_the_spec_says_to_flag_is_flagged(root):
    review = build(root)
    flagged = {i.ref: i for i in review.review_items if i.status == "flagged"}
    placements = flagged["Money Market Performance: 3-month bank placements (9.5%)"]
    assert "its source is unconfirmed" in placements.detail[0].message
    target = next(i for ref, i in flagged.items() if ref.startswith("Net domestic borrowing against the pro-rated target: Pro-rated"))
    message = target.detail[0].message
    assert "has not confirmed which figure is the net domestic borrowing target" in message
    assert "The app used" in message and "Budget workbook's 'Borrowings' sheet" in message
    assert sum(1 for ref in flagged if "amount issued, years to maturity and yield at issue" in ref) == 5   # Yields at Issue
    assert any(ref == "T-Bonds: recommended bidding range (the analysts' recommendation) (not available yet)" for ref in flagged)
    assert {"Kenya Shilling: what pressures the shilling (carried forward)", "Rates and outlook (closing paragraph) (carried forward)"} <= set(flagged)
    assert not review.is_approvable


def test_the_target_flag_names_the_cell_it_used_and_the_one_it_did_not_read():
    from cytonn_weekly.weekly.workbook import Cell
    msg = fiw.target_flag(Cell(919.36, "Government Borrowing", 40, 3))
    assert "919.36 bn" in msg and "Government Borrowing" in msg and "C40" in msg and "only target the app reads" in msg
    assert "does not read that workbook" in msg and "not known here" in msg


def test_the_borrowing_sentence_is_worked_out_and_never_says_ahead(root):
    b = blocks(build(root))["borrowing"]
    f = figures(b)
    # synthetic log: 14 Mondays to 5 October, each 30,000 accepted less 20,000 redeemed; target 910.0 over 96 of 364 days
    assert (f["net_borrowing"], f["prorated_target"], f["ratio"]) == ("140.0", "240.0", "58.3%")
    assert b["body_md"] == ("The government is at 58.3% of its pro-rated net domestic borrowing target of Kshs 240.0 bn, with a "
                            "net borrowing position of Kshs 140.0 bn (inclusive of T-bills).")
    assert "ahead" not in b["body_md"]


def test_text_is_carried_forward_from_the_previous_issue_without_its_borrowing_sentence(root):
    by = blocks(build(root))
    assert by["outlook"]["kind"] == "carried" and by["outlook"]["carried_from"] == {
        "issue_id": 891, "url": "https://cytonnreport.com/api/series/1/research-reports/891", "published": "2026-09-27"}
    assert by["outlook"]["body_md"] == ("Rates in the fixed income market have declined MTD. Inflation stood at 6.6%, within the "
                                        "target range of 2.5%-7.5%. We expect investors to prefer short to medium-term papers.")
    assert by["shilling_pressure"]["body_md"].splitlines() == [
        "The shilling is however expected to remain under pressure in 2026 as a result of:", "",
        "- An ever-present current account deficit, and,", "- The need for government debt servicing."]
    assert fiw.outlook_text(["nothing like it"]) is None and fiw.shilling_pressure_text(["nothing like it"]) is None


def test_the_bidding_range_is_the_analysts_text_or_an_empty_part_never_a_made_up_range(root, text_pdfs):
    empty = blocks(build(root))["bidding_range"]
    assert empty["kind"] == "unavailable" and "the analysts' own call, not a formula" in empty["reason"]
    inputs.store(WEEK, "nse_yield_curve", wh.fake_pdf(wh.yield_curve_text(WEEK.ending)), "curve.pdf", root)
    with_curve = blocks(build(root))["bidding_range"]
    # context only: the curve read at each auctioned bond's remaining tenor (9.0 + 0.1 per year in the synthetic curve)
    assert "Context only, from the NSE yield curve of 2nd October 2026" in with_curve["reason"]
    assert "FXD3/2019/015 (7.8 years): 9.78%" in with_curve["reason"] and "FXD1/2019/020 (12.5 years): 10.25%" in with_curve["reason"]
    inputs.write_notes(WEEK, {"bidding_range": "Our recommended bidding range for FXD1/2019/020 is 12.8% - 13.3%."}, root)
    supplied = blocks(build(root))["bidding_range"]
    assert supplied["kind"] == "supplied" and supplied["body_md"] == "Our recommended bidding range for FXD1/2019/020 is 12.8% - 13.3%."
    assert supplied["context"].startswith("Context only")
    assert items(build(root), "T-Bonds: recommended bidding range")[0].status == "not_auto_verified"   # carried, never verified


def test_a_typed_figure_that_disagrees_with_the_published_one_is_a_sources_disagree_flag(tmp_path):
    inputs.store(WEEK, "cbk_bulletin", BULLETIN, "b.pdf", tmp_path)
    book = wh.fi_workbook_bytes()
    # the same workbook with one typed T-bill figure changed: 91-day bids 17,983.23 -> 18,983.23
    import io

    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(book))
    wb["Treasury Bills "]["AA383"] = 18983.23
    out = io.BytesIO()
    wb.save(out)
    inputs.store(WEEK, "fi_workbook", out.getvalue(), "FI.xlsx", tmp_path)
    review = build(tmp_path)
    disagreeing = [i for i in items(review, "Money Markets, T-Bills Primary Auction:") if i.status == "flagged"]
    assert disagreeing and all(f.kind == SOURCES_DISAGREE for i in disagreeing for f in i.detail)
    assert "17983.23 in CBK Weekly Bulletin, Table 4 but 18983.23 in analyst input from Fixed income workbook 'Treasury Bills '!AA383" \
        in disagreeing[0].detail[0].message
    assert figures(blocks(review)["tbills"])["subscription"] == "170.4%"   # the published figure is still what is printed


def test_the_summary_is_the_sections_lead_paragraphs(root):
    review = build(root)
    by = blocks(review)
    assert review.section["summary"] == by["tbills"]["body_md"] + "\n\n" + by["tbonds"]["body_md"]
    assert 1000 < len(review.section["summary"]) <= 3000


def test_run_events_report_each_fetch_and_part_and_add_up_to_the_review(root):
    log = EventLog()
    review = fiw.build_fixed_income_review(WEEK.ending, inputs=inputs.WeeklyInputs(WEEK, root), fetchers=fetchers(),
                                           draft=wh.no_draft, on_event=log)
    kinds = Counter(e.kind for e in log.events)
    sources = [e.label for e in log.events if e.kind == "source_finished"]
    assert sources == ["Central Bank of Kenya, Daily KES Exchange Rates", "CBK T-bond results", "Previous issue on cytonnreport.com"]
    # CBK's result files are not fetched here (the workbook's log is the fallback); the bidding range is skipped
    assert [e.label for e in log.events if e.kind == "source_failed"] == ["CBK Treasury bill and bond auction results"]
    assert kinds["part_skipped"] == 1
    counted = Counter()
    for e in log.events:
        if e.kind == "check_finished":
            counted.update(e.counts or {})
    by_status = Counter(i.status for i in review.review_items)
    # the checks' counts, plus one flagged item per unavailable part and per carried paragraph
    assert counted["clean"] == by_status["clean"] and counted["not_auto_verified"] == by_status["not_auto_verified"]
    assert counted["flagged"] + 1 + 2 == by_status["flagged"]


# ---------------------------------------------------------------------------
# Missing inputs
# ---------------------------------------------------------------------------

def test_with_no_inputs_and_no_sources_every_part_is_a_named_unavailable_block(tmp_path):
    def down(*args):
        raise ConnectionError("no route to host")

    review = build(tmp_path, fetchers=fiw.Fetchers(usd_rates=down, bulletin=down, tbonds=down, previous_issue=down, releases=down))
    by = blocks(review)
    assert {b["kind"] for b in by.values()} == {"unavailable"}
    assert list(by) == ["tbills", "tbonds", "bidding_range", "money_market", "liquidity", "eurobonds", "shilling",
                        "shilling_support", "shilling_pressure", "outlook", "borrowing"]
    assert by["tbills"]["reason"] == "The CBK Weekly Bulletin for this week is not among this week's inputs and could not be fetched."
    assert by["money_market"]["reason"] == (
        "The money market fund table and the 3-month bank placements rate have not been typed under \"Weekly analyst inputs\", "
        "and the fixed income workbook for this week is not among this week's inputs.")
    assert by["borrowing"]["reason"].startswith("The net domestic borrowing target for the fiscal year and the fiscal year's "
                                                "auction log have not been typed")
    assert by["borrowing"]["unblock"] == ("Type them under \"Weekly analyst inputs\" on the start screen, or upload the fixed "
                                          "income workbook updated for this week, and draft again.")
    assert by["tbonds"]["reason"] == "CBK T-bond results: ConnectionError: no route to host"
    assert "there is no text to carry forward" in by["outlook"]["reason"]
    assert len(review.review_items) == len(by) and {i.status for i in review.review_items} == {"flagged"}
    assert sum("ConnectionError" in w for w in review.section["warnings"]) == 5 and review.section["summary"] == ""


def test_the_bulletin_is_fetched_and_kept_when_it_was_not_uploaded(tmp_path):
    review = build(tmp_path, fetchers=fetchers(bulletin=lambda day: (BULLETIN, "https://www.centralbank.go.ke/x/Weekly CBK Bulletin.pdf")))
    assert blocks(review)["tbills"]["kind"] == "computed"
    kept = inputs.read_manifest(WEEK, tmp_path)["cbk_bulletin.pdf"]
    assert kept["fetched_from"].startswith("https://www.centralbank.go.ke/") and kept["matches"] is True
    by = blocks(review)
    # with the bulletin alone: the public parts are worked out, the workbook's parts are named as missing
    assert by["liquidity"]["kind"] == "computed" and "KESONIA" in by["liquidity"]["body_md"]
    assert by["money_market"]["kind"] == "unavailable" and by["borrowing"]["kind"] == "unavailable"
    assert "eurobonds_issues" not in by and [r["label"] for r in by["eurobonds_table"]["rows"]][-1] == "Weekly Change"
    assert {i.status for i in items(review, "Cytonn Report: Kenya Eurobonds Performance:")} == {"clean"}   # all from the bulletin
    assert any("MTD Change row is left out" in w for w in review.section["warnings"])


def test_a_fetched_file_refused_as_the_bulletin_is_named_by_issue_and_sha256(tmp_path):
    curve = (wh.FIXTURES / "nse_yield_curve_07-10-2026.pdf").read_bytes()    # a PDF, but not the bulletin
    review = build(tmp_path, fetchers=fetchers(bulletin=lambda day: (curve, "https://www.centralbank.go.ke/x/wrong.pdf")))
    sha = hashlib.sha256(curve).hexdigest()
    refusal = [w for w in review.section["warnings"] if "not a CBK Weekly Bulletin" in w]
    assert len(refusal) == 1 and f"sha256 {sha})" in refusal[0]
    assert blocks(review)["tbills"]["kind"] == "unavailable" and "cbk_bulletin.pdf" not in inputs.read_manifest(WEEK, tmp_path)
    # a file no reader can open carries no sha256 of its own in the error, so it is added, with the issue asked for
    assert cbk_bulletin.refused(ValueError("no pages"), b"%PDF-x", WEEK.ending) == (
        f"no pages (the issue asked for: 2026-10-02; sha256 {hashlib.sha256(b'%PDF-x').hexdigest()})")
    assert cbk_bulletin.refused(ValueError(refusal[0]), b"", WEEK.ending) == refusal[0]


def test_a_bulletin_table_left_out_makes_only_its_own_parts_unavailable_and_says_so(tmp_path, monkeypatch):
    wh.break_table_6(monkeypatch, "10336.9")   # Table 6's 1 October row is one figure short
    inputs.store(WEEK, "cbk_bulletin", BULLETIN, "b.pdf", tmp_path)
    review = build(tmp_path)
    by = blocks(review)
    why = (f"CBK Weekly Bulletin of 2026-10-02 (sha256 {hashlib.sha256(BULLETIN).hexdigest()}): Table 6 could not be read "
           "and is left out: Table 6 row for 2026-10-01 has 15 figures, expected 16")
    # the part that needs Table 6 is unavailable and gives the table's own refusal as the reason
    assert by["eurobonds"]["kind"] == "unavailable" and by["eurobonds"]["reason"] == why
    assert "eurobonds_table" not in by
    # the parts read from the other tables are worked out as before
    assert by["tbills"]["kind"] == "computed" and by["liquidity"]["kind"] == "computed"
    assert by["shilling_support"]["kind"] == "computed"
    # and the section's warnings say it once, so no part passes over it in silence
    assert review.section["warnings"].count(why) == 1
    assert [i.status for i in items(review, "Kenya Eurobonds")] == ["flagged"]


# The dozen paragraphs around the shilling in the Kenya Macro Economic Review of issue 892 (the Q3'2026 Markets
# Review), as cytonnreport.com serves them: the opening line, its three bullets, "Key to note, ..." and the next heading.
MACRO_EXCERPT = (wh.FIXTURES / "cytonn_issue_892_kenya_macro_shilling_excerpt.html").read_text(encoding="utf-8")
FI_OF_A_REVIEW = "<p><strong>Liquidity:</strong></p><p>In Q3, liquidity eased.</p><p>Rates in the fixed income market have declined MTD.</p>"
REVIEW_892 = previous_issue.Issue(892, date(2026, 10, 4), {
    "global-markets-review": {"name": "Global Markets Review", "body": "", "summary": ""},   # what makes an issue a review (Issue.kind)
    "kenya-macro-economic-review": {"name": "Kenya Macro Economic Review", "body": MACRO_EXCERPT, "summary": ""},
    "fixed-income": {"name": "Fixed Income", "body": FI_OF_A_REVIEW, "summary": ""},
    "equities": {"name": "Equities", "body": PREVIOUS_EQ, "summary": ""},
})
def review_sentence(issue_id):
    """What the flag says when a Markets Review supplied the text and no twin was skipped (a quarterly, half-year or annual review)."""
    return (f"; the text is from issue {issue_id}, a Markets Review (a quarterly, half-year or annual review), not a weekly; "
            "check that it speaks of this week's period and not only of the review's")


OPENING = "The shilling is however expected to remain under pressure in 2026 as a result of:"
PRESSURE_TITLE = "Kenya Shilling: what pressures the shilling"


def pressure(issue):
    return fiw._carried(issue, "shilling_pressure", PRESSURE_TITLE, fiw.shilling_pressure_text, also=(fiw.MACRO_SECTION,))


def test_the_pressure_paragraph_is_taken_from_the_macro_section_when_the_previous_issue_is_a_markets_review(root):
    review = build(root, fetchers=fetchers(previous_issue=lambda day, ref: REVIEW_892))
    block = blocks(review)["shilling_pressure"]
    lines = block["body_md"].splitlines()
    # the opening line (it ends in a colon and is kept) and its three bullets; "Key to note, ..." and "Monetary Policy:" are not bullets
    assert block["kind"] == "carried" and lines[0] == OPENING and lines[1] == "" and len(lines) == 5
    for line, opens in zip(lines[2:], ("- An ever-present current account deficit which widened to 3.0% of GDP",
                                       "- The need for government debt servicing, continues to put pressure on forex reserves",
                                       "- Rising geopolitical tensions in the Middle East")):
        assert line.startswith(opens), line
    assert not any("Key to note" in line or "Monetary Policy" in line for line in lines)
    note = ("taken from the Kenya Macro Economic Review of issue 892, a Markets Review, not from its Fixed Income section; "
            "check the dates and the period it speaks of")
    assert block["carried_from"] == {"issue_id": 892, "url": REVIEW_892.url, "published": "2026-10-04", "kind": "review",
                                     "section": "kenya-macro-economic-review", "note": note}
    item = items(review, "Kenya Shilling: what pressures the shilling (carried forward)")[0]
    assert item.status == "flagged" and item.detail[0].message == (
        "carried forward, edit before approving: this text is copied from issue 892 on cytonnreport.com, published 2026-10-04 "
        f"and was not written for this week; {note}")
    assert item.detail[0].message.count("Markets Review") == 1 and "not a weekly" not in item.detail[0].message
    # the closing outlook still comes from Fixed Income alone, flagged in the same words as ever
    outlook = blocks(review)["outlook"]
    assert outlook["body_md"] == "Rates in the fixed income market have declined MTD." and set(outlook["carried_from"]) == {"issue_id", "url", "published", "kind"}
    assert outlook["carried_from"]["kind"] == "review"
    assert items(review, "Rates and outlook (closing paragraph) (carried forward)")[0].detail[0].message.endswith(review_sentence(892))


def test_the_fixed_income_section_wins_when_both_hold_the_paragraph():
    both = previous_issue.Issue(891, date(2026, 9, 27), {**ISSUE.sections, "kenya-macro-economic-review": REVIEW_892.sections["kenya-macro-economic-review"]})
    block = pressure(both)
    assert block["body_md"].splitlines() == [
        "The shilling is however expected to remain under pressure in 2026 as a result of:", "",
        "- An ever-present current account deficit, and,", "- The need for government debt servicing."]
    assert block["carried_from"] == {"issue_id": 891, "url": both.url, "published": "2026-09-27"}   # as a weekly issue always gave
    assert pressure(ISSUE) == block                                                                 # with no macro section: the same


def test_a_previous_issue_without_the_paragraph_says_which_sections_were_searched():
    bare = {"name": "Kenya Macro Economic Review", "body": "<p><strong>Monetary Policy:</strong></p><p>The MPC met once.</p>", "summary": ""}
    neither = previous_issue.Issue(892, date(2026, 10, 4), {"fixed-income": REVIEW_892.sections["fixed-income"], "kenya-macro-economic-review": bare})
    block = pressure(neither)
    assert block["kind"] == "unavailable" and block["reason"] == (
        "The previous issue (cytonnreport.com issue 892) has no paragraph that reads as this part: searched fixed-income and "
        "kenya-macro-economic-review of issue 892.")
    weekly = previous_issue.Issue(891, date(2026, 9, 27), {"fixed-income": REVIEW_892.sections["fixed-income"]})
    assert pressure(weekly)["reason"] == (
        "The previous issue (cytonnreport.com issue 891) has no paragraph that reads as this part: searched fixed-income of "
        "issue 891; the issue has no kenya-macro-economic-review section.")
    assert pressure(None)["reason"].startswith("The previous issue could not be read from cytonnreport.com")


def test_the_bullets_stop_at_each_thing_that_is_not_one_of_them():
    bullets = ["A current account deficit, and,", "The need for debt servicing.", "Rising tensions in the Middle East."]
    carried = OPENING + "\n\n" + "\n".join(f"- {b}" for b in bullets)
    for stop in ("Kenya's forex reserves decreased by 0.3% during the week.",                              # the old rule: in its first 40 characters
                 "Weekly Highlights",                                                                      # the old rule
                 "During the third quarter of 2026, the country's forex reserves increased by 7.1% to USD 15.0 bn.",   # anywhere in it
                 "Over the same period the months of import cover fell as forex reserves decreased.",
                 "Key to note, during the third quarter the months of import cover rose.",
                 "Monetary Policy:"):                                                                      # a heading
        assert fiw.shilling_pressure_text(["Before.", OPENING, *bullets, stop, "After."]) == carried, stop
    # a long line ending in a colon is a bullet, not a heading; and the opening line's own colon never ends anything
    long_bullet = "Rising tensions in the Middle East, which could weigh on the shilling through two channels that matter here:"
    assert fiw.shilling_pressure_text([OPENING, *bullets[:2], long_bullet, "Monetary Policy:"]) == OPENING + "\n\n" + "\n".join(
        f"- {b}" for b in (*bullets[:2], long_bullet))
    assert fiw.shilling_pressure_text([OPENING]) == OPENING and fiw.shilling_pressure_text([OPENING, "Monetary Policy:"]) == OPENING
    # five lines after the opening at most, whatever follows
    many = [f"Bullet {n}." for n in range(1, 9)]
    assert fiw.shilling_pressure_text([OPENING, *many]).splitlines()[2:] == [f"- Bullet {n}." for n in range(1, 6)]


def test_the_two_outlooks_look_only_in_their_own_section_as_before():
    macro_with_outlooks = {"name": "Kenya Macro Economic Review", "summary": "",
                           "body": "<p>Rates in the fixed income market have declined.</p><p>We maintain a cautious outlook.</p>"}
    issue = previous_issue.Issue(892, date(2026, 10, 4), {
        "kenya-macro-economic-review": macro_with_outlooks,
        "fixed-income": {"name": "Fixed Income", "body": "<p>Liquidity eased.</p>", "summary": ""},
        "equities": {"name": "Equities", "body": "<p>Turnover rose.</p>", "summary": ""}})
    old = "The previous issue (cytonnreport.com issue 892) has no paragraph that reads as this part."
    fi = fiw._carried(issue, "outlook", "Rates and outlook (closing paragraph)", fiw.outlook_text)
    eq = fiw._carried(issue, "outlook", "Equities outlook (closing paragraph)", eqw.equities_outlook_text, ("equities",))
    assert (fi["kind"], fi["reason"]) == ("unavailable", old) and (eq["kind"], eq["reason"]) == ("unavailable", old)


def test_a_workbook_for_last_week_leaves_its_parts_unavailable_with_the_reason(tmp_path):
    inputs.store(WEEK, "cbk_bulletin", BULLETIN, "b.pdf", tmp_path)
    inputs.store(WEEK, "fi_workbook", wh.fi_workbook_bytes(updated=False), "FI.xlsx", tmp_path)
    by = blocks(build(tmp_path))
    assert by["money_market"]["kind"] == "unavailable" and "The workbook is not yet updated for this week" in by["money_market"]["reason"]
    assert by["borrowing"]["kind"] == "unavailable" and "workbook not yet updated for this week" in by["borrowing"]["reason"]
    assert by["tbills"]["kind"] == "computed"   # the bulletin still gives the auction


def test_the_top_five_average_is_compared_with_last_week_when_last_weeks_workbook_is_stored(root):
    last = [(n, r - 0.0010) for n, r in wh.FUNDS]
    inputs.store(WEEK.previous, "fi_workbook", wh.fi_workbook_bytes(Week(WEEK.previous_friday), funds=last), "FI last.xlsx", root)
    b = blocks(build(root))["money_market"]
    f = figures(b)
    assert (f["top5"], f["top5_last"], f["top5_bps"]) == ("10.72%", "10.62%", "10.0 bps")
    assert "increased by 10.0 bps to 10.72% from 10.62% recorded the previous week" in b["body_md"]


# ---------------------------------------------------------------------------
# The real workbook (confidential; skipped when absent)
# ---------------------------------------------------------------------------

def test_the_real_workbook_reproduces_the_published_week(tmp_path):
    inputs.store(WEEK, "fi_workbook", wh.sample("FI_MASTERSHEET_05.10.2026.v1.xlsx"), "FI.xlsx", tmp_path)
    inputs.store(WEEK, "cbk_bulletin", BULLETIN, "b.pdf", tmp_path)
    review = build(tmp_path)
    by = blocks(review)
    money = figures(by["money_market"])
    assert money["placements"] == "9.0%" and money["cmmf"] == "11.0%"
    assert "The yield on the Cytonn Money Market Fund remained unchanged at 11.0%" in by["money_market"]["body_md"]
    # The equities team's rule (this week's five highest rates) gives 10.77%; the issue printed 10.75%, from a stale list
    # of five named funds.  The difference is expected and is not tuned away.
    assert money["top5"] == "10.77%"
    assert len(by["mmf_table"]["rows"]) == 34 and by["mmf_table"]["title"].endswith("as published on 2nd October 2026")
    assert by["mmf_table"]["source"]["name"] == "Business Daily"
    liquidity = figures(by["liquidity"])
    assert (liquidity["rate_bps"], liquidity["volume_change"]) == ("0.04 bps", "34.4%")
    assert "liquidity in the money markets eased, with the average interbank rate decreasing by 0.04 bps to 8.8%" in by["liquidity"]["body_md"]
    assert by["borrowing"]["body_md"] == ("The government is at 245.3% of its pro-rated net domestic borrowing target of Kshs 242.5 bn, "
                                          "with a net borrowing position of Kshs 594.8 bn (inclusive of T-bills).")
    table = {r["label"]: r for r in by["eurobonds_table"]["rows"]}
    assert [table["02-Jan-26"][k] for k in ("2018_10y", "2018_30y", "2019_12y", "2021_13y", "2024_7y")] == ["6.1%", "8.8%", "7.2%", "7.8%", "7.1%"]
    assert table["YTD Change"]["2018_10y"] == "1.6%"
    issues = {r["issue"]: r for r in by["eurobonds_issues"]["rows"]}
    # Worked out, so they differ from the printed (stale) fixed rows by design: 2028-02-28 less 2026-10-01 is 1.4 years.
    assert (issues["2018 10-year issue"]["years"], issues["2018 10-year issue"]["amount_bn"]) == ("1.4", "1.0")
    assert issues["2019 12-year issue"]["amount_bn"] == "1.2"
    # every typed figure agrees with the published one where both exist: no "sources disagree" anywhere
    assert not [f for i in review.review_items if isinstance(i.detail, list) for f in i.detail if f.kind == SOURCES_DISAGREE]
    assert figures(by["shilling_support"])["north_america_share"] == "50.3%"


# ---------------------------------------------------------------------------
# A twin skipped by the previous-issue lookup is said on the carried text it affects
# ---------------------------------------------------------------------------

def previous_by_lookup(friday):
    """The real previous_issue lookup over the fixture's metadata, as it would run for the week ending ``friday``."""
    site = fx.site(fx.ISSUES, fx.newest_as_of(fx.ISSUES, friday))
    return lambda day, ref: previous_issue.find_previous_issue(friday, site)


TWIN_SENTENCE = ("the lookup skipped issue 850 on cytonnreport.com, a copy of this issue with its charts stripped; "
                 "the text is from issue 849, a weekly")


def test_the_week_ending_27_february_finds_the_outlook_in_849_and_says_it_skipped_850(root):
    review = build(root, fetchers=fetchers(previous_issue=previous_by_lookup(date(2026, 2, 27))))
    outlook = blocks(review)["outlook"]
    assert outlook["kind"] == "carried" and "(issue 849)" in outlook["body_md"]  # 850's Fixed Income has no such paragraph
    assert outlook["carried_from"] == {"issue_id": 849, "url": "https://cytonnreport.com/api/series/1/research-reports/849",
                                       "published": "2026-02-22", "kind": "weekly", "skipped": [850]}
    flagged = items(review, "Rates and outlook (closing paragraph) (carried forward)")[0]
    assert flagged.status == "flagged" and flagged.detail[0].message == (
        "carried forward, edit before approving: this text is copied from issue 849 on cytonnreport.com, published 2026-02-22 "
        f"and was not written for this week; {TWIN_SENTENCE}")
    # the shilling paragraph and the Equities outlook come from the same issue and say the same
    assert blocks(review)["shilling_pressure"]["carried_from"]["skipped"] == [850]


def test_a_review_used_after_a_twin_is_skipped_is_named_as_one_and_the_shilling_lookup_is_still_not_found(root):
    review = build(root, fetchers=fetchers(previous_issue=previous_by_lookup(date(2026, 1, 9))))
    outlook = blocks(review)["outlook"]
    assert outlook["carried_from"]["issue_id"] == 840 and outlook["carried_from"]["kind"] == "review"
    assert outlook["carried_from"]["skipped"] == [841]
    message = items(review, "Rates and outlook (closing paragraph) (carried forward)")[0].detail[0].message
    assert message.endswith("the lookup skipped issue 841 on cytonnreport.com, a copy of this issue with its charts stripped; "
                            "the text is from issue 840, a Markets Review")
    # 840 is also a review and has no such paragraph in Fixed Income or Kenya Macro: not found, as for 841 (not chased here)
    assert blocks(review)["shilling_pressure"]["kind"] == "unavailable"


def test_nothing_is_added_to_the_carried_text_when_no_twin_was_skipped(root):
    review = build(root, fetchers=fetchers(previous_issue=previous_by_lookup(date(2026, 4, 17))))  # 861: its twin has the lower id
    outlook = blocks(review)["outlook"]
    assert set(outlook["carried_from"]) == {"issue_id", "url", "published"}
    assert items(review, "Rates and outlook (closing paragraph) (carried forward)")[0].detail[0].message.endswith(
        "published 2026-04-12 and was not written for this week")


def test_the_flag_names_the_issue_used_its_kind_and_every_issue_skipped():
    block = computed.carried_block("outlook", "Outlook", "Old text.", {
        "issue_id": 888, "url": "u", "published": "2026-09-20", "kind": "weekly", "skipped": [889]})
    assert computed.carried_flag(block).message == (
        "carried forward, edit before approving: this text is copied from issue 888 on cytonnreport.com, published 2026-09-20 "
        "and was not written for this week; the lookup skipped issue 889 on cytonnreport.com, a copy of this issue with its "
        "charts stripped; the text is from issue 888, a weekly")
    several = computed.carried_block("outlook", "Outlook", "Old text.", {
        "issue_id": 840, "url": "u", "published": "2026-01-04", "kind": "review", "skipped": [841, 842],
        "section": "kenya-macro-economic-review", "note": "taken from another section"})
    assert computed.carried_flag(several).message.endswith(
        "was not written for this week; the lookup skipped issues 841 and 842 on cytonnreport.com, copies of this issue with "
        "their charts stripped; the text is from issue 840, a Markets Review; taken from another section")


# ---------------------------------------------------------------------------
# A Markets Review that supplies the carried text is named in the flag, whether or not a twin was skipped
# ---------------------------------------------------------------------------

def previous_issue_for(friday):
    return previous_by_lookup(friday)(friday, None)


def outlook_flag(review):
    return items(review, "Rates and outlook (closing paragraph) (carried forward)")[0].detail[0].message


def copied_from(issue_id, published):
    return (f"carried forward, edit before approving: this text is copied from issue {issue_id} on cytonnreport.com, "
            f"published {published} and was not written for this week")


@pytest.mark.parametrize("friday, used, published", [
    (date(2026, 1, 23), 843, "2026-01-18"),   # the markets outlook issue, which has the same Global Markets sections
    (date(2026, 4, 10), 859, "2026-04-05"),   # Q1
    (date(2026, 7, 10), 877, "2026-07-05"),   # H1
    (date(2026, 10, 9), 892, "2026-10-04"),   # Q3
])
def test_a_review_that_supplies_the_fixed_income_outlook_is_named_in_the_flag(root, friday, used, published):
    review = build(root, fetchers=fetchers(previous_issue=previous_by_lookup(friday)))
    carried = blocks(review)["outlook"]["carried_from"]
    assert carried == {"issue_id": used, "url": f"https://cytonnreport.com/api/series/1/research-reports/{used}",
                       "published": published, "kind": "review"}   # no twin was skipped, so no "skipped"
    assert outlook_flag(review) == copied_from(used, published) + review_sentence(used)


@pytest.mark.parametrize("friday, used, published", [
    (date(2026, 4, 10), 859, "2026-04-05"),
    (date(2026, 7, 10), 877, "2026-07-05"),
    (date(2026, 10, 9), 892, "2026-10-04"),
])
def test_a_review_that_supplies_the_equities_outlook_is_named_in_the_flag(friday, used, published):
    block = fiw._carried(previous_issue_for(friday), "outlook", "Equities outlook (closing paragraph)", eqw.equities_outlook_text, ("equities",))
    assert block["kind"] == "carried" and block["carried_from"]["kind"] == "review"
    assert computed.carried_flag(block).message == copied_from(used, published) + review_sentence(used)


def test_the_week_ending_23_january_finds_no_equities_outlook_in_the_markets_outlook_issue():
    block = fiw._carried(previous_issue_for(date(2026, 1, 23)), "outlook", "Equities outlook (closing paragraph)", eqw.equities_outlook_text, ("equities",))
    assert block["kind"] == "unavailable"   # nothing is carried, so there is no flag to add a sentence to


def test_a_review_that_supplies_the_shilling_text_from_its_own_fixed_income_is_named_once(root):
    review = build(root, fetchers=fetchers(previous_issue=previous_by_lookup(date(2026, 4, 10))))   # 859: the text is in Fixed Income
    block = blocks(review)["shilling_pressure"]
    assert block["kind"] == "carried" and "section" not in block["carried_from"] and block["carried_from"]["kind"] == "review"
    message = items(review, "Kenya Shilling: what pressures the shilling (carried forward)")[0].detail[0].message
    assert message == copied_from(859, "2026-04-05") + review_sentence(859)


def test_the_shilling_text_taken_from_the_kenya_macro_section_does_not_say_the_kind_twice(root):
    review = build(root, fetchers=fetchers(previous_issue=lambda day, ref: REVIEW_892))
    message = items(review, "Kenya Shilling: what pressures the shilling (carried forward)")[0].detail[0].message
    assert message.count("Markets Review") == 1 and "not a weekly" not in message
    assert blocks(review)["shilling_pressure"]["carried_from"]["kind"] == "review"   # the data says it, the message already did


def test_a_plain_weekly_week_is_unchanged(root):
    review = build(root, fetchers=fetchers(previous_issue=previous_by_lookup(date(2026, 4, 3))))   # 856, the weekly of 29 March
    carried = blocks(review)["outlook"]["carried_from"]
    assert carried == {"issue_id": 856, "url": "https://cytonnreport.com/api/series/1/research-reports/856", "published": "2026-03-29"}
    assert outlook_flag(review) == copied_from(856, "2026-03-29")


def test_a_weekly_used_after_a_twin_was_skipped_keeps_the_message_of_the_twin_change(root):
    review = build(root, fetchers=fetchers(previous_issue=previous_by_lookup(date(2026, 2, 27))))
    assert outlook_flag(review) == copied_from(849, "2026-02-22") + "; " + TWIN_SENTENCE
    assert "Markets Review" not in outlook_flag(review) and "not a weekly" not in outlook_flag(review)


def test_a_review_used_after_a_twin_was_skipped_says_its_kind_once(root):
    review = build(root, fetchers=fetchers(previous_issue=previous_by_lookup(date(2026, 1, 9))))   # 841 skipped, 840 used
    message = outlook_flag(review)
    assert message.count("Markets Review") == 1 and "not a weekly" not in message
    assert message.endswith("the text is from issue 840, a Markets Review")


def test_the_flag_adds_the_review_sentence_only_where_the_kind_is_not_already_said():
    base = {"issue_id": 892, "url": "u", "published": "2026-10-04"}
    review = computed.carried_flag(computed.carried_block("o", "Outlook", "Text.", {**base, "kind": "review"})).message
    assert review == copied_from(892, "2026-10-04") + review_sentence(892)
    weekly = computed.carried_flag(computed.carried_block("o", "Outlook", "Text.", base)).message
    assert weekly == copied_from(892, "2026-10-04")   # no kind: nothing is added
    macro = computed.carried_flag(computed.carried_block("o", "Outlook", "Text.", {
        **base, "kind": "review", "section": "kenya-macro-economic-review", "note": "taken from the Kenya Macro Economic Review of issue 892, a Markets Review"})).message
    assert macro == copied_from(892, "2026-10-04") + "; taken from the Kenya Macro Economic Review of issue 892, a Markets Review"
    twin = computed.carried_flag(computed.carried_block("o", "Outlook", "Text.", {**base, "kind": "review", "skipped": [893]})).message
    assert twin.count("Markets Review") == 1 and "not a weekly" not in twin
