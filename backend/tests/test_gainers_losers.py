import io
from datetime import date

import pytest
from openpyxl import Workbook as XlsxWorkbook
from openpyxl import load_workbook

from cytonn_weekly.checkers.digital_payments import SOURCES_DISAGREE
from cytonn_weekly.equities import weekly as eqw
from cytonn_weekly.weekly import analyst, equities_workbook, inputs
from cytonn_weekly.weekly.week import Week
from cytonn_weekly.weekly.workbook import Workbook, WorkbookError
from tests import weekly_helpers as wh
from tests.test_weekly_equities import SYNTHETIC_BOXES, blocks, build, fetchers, items, root  # noqa: F401 - root is a fixture
from tests.weekly_helpers import text_pdfs  # noqa: F401 - a fixture

WEEK = wh.WEEK
SHEET = "Gainers & Losers"


def sheet_only(days=None, moves=None) -> Workbook:
    wb = XlsxWorkbook()
    wb.remove(wb.active)
    wh.gainers_losers_sheet(wb, WEEK, moves, days)
    out = io.BytesIO()
    wb.save(out)
    return Workbook(out.getvalue(), "Equities workbook")


def with_moves(root, moves, **over):
    inputs.store(WEEK, "equities_workbook", wh.equities_workbook_bytes(gainers_losers=moves), "Equities.xlsx", root)
    return blocks(build(root, **over))


def moves(**changed):
    return {**wh.GAINERS_LOSERS, **changed}


# ---------------------------------------------------------------------------
# The reader
# ---------------------------------------------------------------------------

def test_columns_are_found_by_their_date_never_the_2016_block_or_the_stray_older_date():
    rows = equities_workbook.read_gainers_losers(sheet_only(), [WEEK.ending, WEEK.previous_friday])
    assert [t for t, _ in rows] == list(wh.GAINERS_LOSERS)            # P3:P14, not B2:C17
    scom = rows[0][1]
    assert (scom[WEEK.ending].ref, scom[WEEK.ending].value) == ("'Gainers & Losers'!S3", 100.27)
    assert (scom[WEEK.previous_friday].ref, scom[WEEK.previous_friday].value) == ("'Gainers & Losers'!R3", 100.0)


def test_a_column_inserted_between_the_weeks_gives_the_same_result():
    days = [WEEK.previous.previous_friday, WEEK.previous_friday, date(2026, 9, 30), WEEK.ending]
    rows = equities_workbook.read_gainers_losers(sheet_only(days), [WEEK.ending, WEEK.previous_friday])
    plain = equities_workbook.read_gainers_losers(sheet_only(), [WEEK.ending, WEEK.previous_friday])
    assert [(t, {d: c.value for d, c in cells.items()}) for t, cells in rows] == \
           [(t, {d: c.value for d, c in cells.items()}) for t, cells in plain]
    assert rows[0][1][WEEK.ending].a1 == "T3"


def test_a_date_that_appears_twice_is_refused():
    days = [WEEK.previous_friday, WEEK.previous_friday, WEEK.ending]
    with pytest.raises(WorkbookError, match=r"'Gainers & Losers' has 2 columns dated 2026-09-25 in row 2 \(Q2, R2\)"):
        equities_workbook.read_gainers_losers(sheet_only(days), [WEEK.ending, WEEK.previous_friday])


def test_a_missing_date_column_makes_the_part_unavailable_naming_the_sheet_and_the_date(root):
    book = load_workbook(io.BytesIO(wh.equities_workbook_bytes()))
    del book[SHEET]
    wh.gainers_losers_sheet(book, WEEK, None, [WEEK.previous.previous_friday, WEEK.ending])
    out = io.BytesIO()
    book.save(out)
    inputs.store(WEEK, "equities_workbook", out.getvalue(), "Equities.xlsx", root)
    by = blocks(build(root))
    assert by["large_caps"]["kind"] == "unavailable"
    assert by["large_caps"]["reason"] == ("Equities workbook: 'Gainers & Losers' has no column dated 2026-09-25 in row 2: the "
                                          "workbook is not yet updated for this week.")
    # the banking paragraph keeps its index sentence and says why it names no stocks
    assert by["banking"]["body_md"].endswith("recorded the previous week.")
    assert by["banking"]["notes"] == ["No stocks are named: 'Gainers & Losers' has no column dated 2026-09-25 in row 2: the "
                                      "workbook is not yet updated for this week."]


# ---------------------------------------------------------------------------
# The selection and the two paragraphs
# ---------------------------------------------------------------------------

def test_three_falls_and_only_the_two_rises_there_are_from_the_sheet(root):
    review = build(root)
    b = blocks(review)["large_caps"]
    assert b["body_md"] == (
        "The equities market performance was mainly driven by losses recorded by large-cap stocks such as NCBA, Standard "
        "Chartered Bank and Equity of 2.2%, 1.5% and 1.4% respectively. However, the performance was supported by gains "
        "recorded by large-cap stocks such as EABL and Safaricom of 0.8% and 0.3% respectively.")
    # the sheet is the team's rule: no "check the names" flag; each change rests on typed prices, KCB agreeing
    assert {i.status for i in items(review, "Market Performance: large-cap movers:")} == {"not_auto_verified"}
    assert not any("check the names" in str(i.detail) for i in review.review_items)
    move = next(f for f in b["figures"] if f["key"] == "move_NCBA")
    assert move["expr"] == ["mul", ["sub", ["div", "now", "last_week"], 1], 100]
    assert move["inputs"]["now"]["source"] == "analyst input from Equities workbook 'Gainers & Losers'!S13"
    assert move["second"]["value"] == -2.23


def test_a_change_of_exactly_zero_is_neither_and_no_gains_drops_the_however_clause(root):
    flat = {t: (-abs(v) if v else 0.0) for t, v in wh.GAINERS_LOSERS.items()}     # every rise turned into a fall; BAMB 0
    text = with_moves(root, flat)["large_caps"]["body_md"]
    assert text == ("The equities market performance was mainly driven by losses recorded by large-cap stocks such as NCBA, "
                    "Standard Chartered Bank and Equity of 2.2%, 1.5% and 1.4% respectively.")
    assert "Bamburi" not in text and "However" not in text


def test_ties_go_by_the_unrounded_change_then_the_sheets_row_order(root):
    # SCOM and EABL tie exactly (row order: SCOM first); KCB's 0.94 prints 0.9 like theirs but is the larger rise
    text = with_moves(root, moves(SCOM=0.86, EABL=0.86, KCB=0.94))["large_caps"]["body_md"]
    assert text.endswith("However, the performance was supported by gains recorded by large-cap stocks such as KCB, "
                         "Safaricom and EABL of 0.9%, 0.9% and 0.9% respectively.")


def test_the_banking_paragraph_names_only_banks_when_the_index_falls(root):
    by = with_moves(root, moves(KCB=0.88))
    assert by["banking"]["body_md"] == (
        "During the week, the banking sector index decreased by 1.0% to 300.0 from 303.0 recorded the previous week. This is "
        "attributable to losses recorded by large cap stocks such as NCBA, Standard Chartered Bank and Equity of 2.2%, 1.5% "
        "and 1.4% respectively. The performance was however supported by gains recorded by large-cap stocks such as KCB of 0.9%.")
    assert "EABL" not in by["banking"]["body_md"] and "Safaricom" not in by["banking"]["body_md"]


def test_the_banking_paragraph_leads_with_the_gains_when_the_index_rises(root):
    boxes = {**SYNTHETIC_BOXES, WEEK.ending: {**SYNTHETIC_BOXES[WEEK.ending], "banking": 309.0}}
    by = with_moves(root, moves(KCB=0.88, DTBK=-3.76), fetchers=fetchers(boxes))
    assert by["banking"]["body_md"].endswith(
        "This is attributable to gains recorded by large cap stocks such as KCB of 0.9%. The performance was however weighed "
        "down by losses recorded by large-cap stocks such as DTB-K, NCBA and Standard Chartered Bank of 3.8%, 2.2% and 1.5% "
        "respectively.")
    assert "such as DTBK" in by["large_caps"]["body_md"]          # the market paragraph keeps its own name for DTBK


def test_kcb_disagreeing_on_one_stock_is_a_sources_disagree_flag(root):
    with_moves(root, moves(SCOM=0.50))                              # KCB's synthetic report says 0.27
    review = build(root)
    scom = items(review, "Market Performance: large-cap movers: Safaricom week-on-week change")[0]
    assert scom.status == "flagged" and [f.kind for f in scom.detail] == [SOURCES_DISAGREE]
    assert "KCB Investment Bank weekly report, 2026-10-02 gives 0.27" in scom.detail[0].message
    assert {i.status for i in items(review, "Market Performance: large-cap movers:") if i is not scom} == {"not_auto_verified"}


def test_without_a_workbook_the_typed_list_and_kcb_are_used_as_before_and_flagged(tmp_path, text_pdfs):
    inputs.store(WEEK, "kcb_weekly", wh.fake_pdf(wh.kcb_weekly_text()), "weekly.pdf", tmp_path)
    analyst.save_form(WEEK, {"fields": {"large_caps": "\n".join(wh.LARGE_CAPS)}}, tmp_path)
    review = build(tmp_path)
    b = blocks(review)["large_caps"]
    assert b["body_md"] == (
        "The equities market performance was mainly driven by losses recorded by large-cap stocks such as I&M Holdings, NCBA "
        "and HFCB Group of 2.9%, 2.2% and 1.6% respectively. However, the performance was supported by gains recorded by "
        "large-cap stocks such as Safaricom of 0.3%.")
    assert "EABL" not in b["body_md"]   # EABL moved, but it is not on the typed large-cap list
    assert b["notes"][0].startswith("No equities workbook is among this week's inputs, so the movers are picked from the "
                                    "large-cap list by KCB IB's week-on-week changes")
    flagged = [i for i in items(review, "Market Performance: large-cap movers:") if i.status == "flagged"]
    assert len(flagged) == 1 and flagged[0].detail[0].message.startswith("I&M Holdings week-on-week change: check the names")


# ---------------------------------------------------------------------------
# The real workbook (confidential; skipped when absent): the October 2026 Monthly's week
# ---------------------------------------------------------------------------

def test_the_real_workbook_gives_the_monthlys_lists_for_the_week_ending_30_october(tmp_path):
    week = Week(date(2026, 10, 30))
    inputs.store(week, "equities_workbook", wh.sample("Equities Workbook 30.10.2026.vf (1).xlsx"), "Equities.xlsx", tmp_path)
    m = eqw.Market(week, inputs.WeeklyInputs(week, tmp_path), None, {}, {}, None, None, None)
    movers = eqw.sheet_movers(m)
    assert [x.ticker for x in movers] == ["SCOM", "EABL", "EQTY", "KCB", "COOP", "BAT", "BAMB", "ABSA", "SCBK",
                                                           "DTBK", "NCBA", "STANBIC"]

    def lists(group):
        gainers, losers = eqw.ranked(group)
        return [(x.ticker, f"{x.change:.2f}") for x in gainers], [(x.ticker, f"{x.change:.2f}") for x in losers]

    assert lists(movers) == ([("SCOM", "0.90"), ("KCB", "0.88")],
                             [("STANBIC", "-4.60"), ("ABSA", "-4.01"), ("DTBK", "-3.76")])
    assert lists([x for x in movers if x.ticker in eqw.BANKS]) == ([("KCB", "0.88")],
                                                                    [("STANBIC", "-4.60"), ("ABSA", "-4.01"), ("DTBK", "-3.76")])
