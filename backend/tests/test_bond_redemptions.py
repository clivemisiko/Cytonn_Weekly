"""Bond redemptions CBK prints on no result file: the typed rows, the maturity question, the stock check.

CBK prints a bond redemption only in the results of a bond auction settling that day.  First
case: IFB1/2014/12 matures on 12 October 2026 and no bond auction settles that day.

Public sources only: the captured value file of test_net_borrowing.py, an excerpt of the "Issues
of Treasury Bonds" table as CBK served it on 2026-10-12 (its header and the 15 rows maturing from
1 July 2026 to 31 January 2027), and the CBK Weekly Bulletin of 2 October 2026.  The results of
12 October 2026 are not captured, so the Treasury bill release of that day is a stand-in (the
5 October release moved a week, with the redemptions the 5 October results announced for it);
every typed amount is invented.
"""

import json
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly.checkers.digital_payments import MISSING, SOURCES_DISAGREE
from cytonn_weekly.common.checks import check_table_block
from cytonn_weekly.common.review import second_sources
from cytonn_weekly.fixed_income import bond_issues as bi
from cytonn_weekly.fixed_income import cbk_auctions as cbk
from cytonn_weekly.fixed_income import net_borrowing as nb
from cytonn_weekly.fixed_income import weekly as fiw
from cytonn_weekly.weekly import analyst, cbk_bulletin, inputs
from cytonn_weekly.weekly.inputs import InputError
from cytonn_weekly.weekly.week import Week
from tests import weekly_helpers as wh
from tests.test_net_borrowing import FY, RELEASES, TARGET, cbk_get
from tests.test_weekly_fixed_income import BULLETIN, blocks, fetchers, figures, items

WEEK = wh.WEEK                      # ending 2 October 2026: its auctions settle 3 to 9 October
NEXT = Week(date(2026, 10, 9))      # its auctions settle 10 to 16 October: the window that holds 12 October
PAGE = (wh.FIXTURES / "cbk_tbond_issues_2026-10-12_excerpt.html").read_text(encoding="utf-8")
MATURITIES = bi.maturities(bi.parse_issues(PAGE))
TABLE = "borrowing_redemptions"
WARNING = ("bond maturity on 12-10-2026 (IFB1/2014/12, up to 15,420.55 mn at face, outstanding may be lower): "
           "no redemption on any release and none typed; type the amount outstanding at maturity, as shown on the NSE "
           "Implied Yields sheet, under \"Other bond redemptions\"")
MATURITY_ROW = "2026-10-12 IFB1/2014/12 maturity"
TYPED_ROW = "2026-10-12 IFB1/2014/12 redemption (typed, not on a release)"


def bills_of_12_october():
    """A stand-in for the Treasury bill results of 12 October 2026, which are not captured."""
    last = next(r for r in reversed(RELEASES) if r["kind"] == "tbill")
    return {**last, "value_date": "2026-10-12", "redemptions_kes_m": last["next_week_redemptions_kes_m"],
            "redemptions_parts": [], "next_week_redemptions_kes_m": None, "next_value_date": None, "file": "stand-in",
            "sha256": None, "url": None}


NEXT_RELEASES = RELEASES + [bills_of_12_october()]


def typed(amount=9000.5, day=date(2026, 10, 12), bond="IFB1/2014/12"):
    return {"date": day, "bond": bond, "kes_m": amount, "source": "analyst input typed on the weekly form (a test)"}


def log_next(**kwargs):
    return nb.build_log(NEXT_RELEASES, FY, NEXT.value_date_window[1], maturities=MATURITIES, **kwargs)


def table_flags(log):
    block = nb.log_block(log)
    return block, check_table_block(block, second_sources(block)).flags


# ---------------------------------------------------------------------------
# 1. CBK's "Issues of Treasury Bonds" table
# ---------------------------------------------------------------------------

def test_the_issues_table_is_read_by_its_headings_and_summed_per_bond_and_maturity_date():
    rows = bi.parse_issues(PAGE)
    assert len(rows) == 15
    ifb = next(r for r in rows if r["issue"] == "IFB1/2014/12")
    assert ifb == {"issue_date": "2014-10-27", "issue": "IFB1/2014/12", "isin": "KE4000001109", "face_kes_m": 15420.55,
                   "maturity_date": "2026-10-12", "maturity_printed": "12/10/2026"}
    assert MATURITIES == [
        # one bond written two ways (FXD1/2016/10 and FXD1/2016/010): six rows, one ISIN
        {"date": "2026-08-17", "bond": "FXD1/2016/10", "face_kes_m": 103380.7, "issues": 6},
        {"date": "2026-10-12", "bond": "IFB1/2014/12", "face_kes_m": 15420.55, "issues": 1},
        {"date": "2026-11-09", "bond": "FXD1/2021/005", "face_kes_m": 57566.3, "issues": 2},
        {"date": "2027-01-11", "bond": "FXD1/2024/003", "face_kes_m": 91555.15, "issues": 5},
    ]


def test_the_tables_total_is_a_floor_not_the_amount_redeemed():
    # 17 August 2026: the table's six rows add to 103,380.70 and that day's results print redemptions of 118,137.00
    floor = next(m for m in MATURITIES if m["date"] == "2026-08-17")["face_kes_m"]
    printed = next(r for r in RELEASES if (r["value_date"], r["kind"]) == ("2026-08-17", "primary"))["redemptions_kes_m"]
    assert (floor, printed) == (103380.7, 118137.0) and floor < printed


def test_the_known_wrong_ifb1_2023_007_row_is_left_out_by_a_documented_list_and_nothing_else_is(monkeypatch):
    rows = bi.parse_issues(PAGE)
    wrong = [r for r in rows if (r["issue"], r["maturity_printed"]) == ("IFB1/2023/007", "15/07/2026")]
    assert len(wrong) == 1 and wrong[0]["face_kes_m"] == 42650.32                       # the row is on the page
    assert list(bi.KNOWN_WRONG_ROWS) == [("IFB1/2023/007", "15/07/2026")] and all(len(why) > 40 for why in bi.KNOWN_WRONG_ROWS.values())
    assert not any(m["date"] == "2026-07-15" for m in MATURITIES)
    log = nb.build_log(RELEASES, FY, WEEK.value_date_window[1], maturities=MATURITIES)
    assert log.unaccounted == [] and not any("maturity" in r["key"] for r in log.rows)  # 15 July is in the window: no warning
    # it is the list that does it, not a general silence: without the entry the same row would be asked about
    monkeypatch.setattr(bi, "KNOWN_WRONG_ROWS", {})
    asked = nb.build_log(RELEASES, FY, WEEK.value_date_window[1], maturities=bi.maturities(rows))
    assert asked.unaccounted == ["bond maturity on 15-07-2026 (IFB1/2023/007, up to 42,650.32 mn at face, outstanding may be "
                                 "lower): no redemption on any release and none typed; type the amount outstanding at "
                                 "maturity, as shown on the NSE Implied Yields sheet, under \"Other bond redemptions\""]


def test_a_page_without_the_table_says_so():
    with pytest.raises(bi.IssuesTableError, match="heading 'Issues of Treasury Bonds' is not on the page"):
        bi.parse_issues("<html><h2>Treasury Bond Results</h2><table></table></html>")
    with pytest.raises(bi.IssuesTableError, match="no 'Maturity Date' column"):
        bi.parse_issues("<h2>Issues of Treasury Bonds</h2><table><tr><th>Issue No</th></tr></table>")


def test_the_table_is_kept_with_its_hash_and_the_kept_reading_is_the_fallback(tmp_path):
    first = bi.read_maturities(PAGE.encode("utf-8"), tmp_path)
    assert first["maturities"] == MATURITIES and first["warnings"] == [] and len(first["sha256"]) == 64
    kept = json.loads((tmp_path / bi.CACHE_FILE).read_text(encoding="utf-8"))
    assert kept["sha256"] == first["sha256"] and len(kept["rows"]) == 15
    assert bi.read_maturities(PAGE.encode("utf-8"), tmp_path)["sha256"] == first["sha256"]      # the same table, the same hash
    later = bi.read_maturities(b"<html>maintenance</html>", tmp_path)
    assert later["maturities"] == MATURITIES and later["sha256"] == first["sha256"]
    assert "the table as read on" in later["warnings"][0] and "is used for the bond maturity check" in later["warnings"][0]
    nothing = bi.read_maturities(None, tmp_path / "empty")
    assert nothing["maturities"] is None and "were not looked for this run" in nothing["warnings"][0]


def test_the_table_comes_with_the_listing_the_bond_results_are_fetched_from(tmp_path):
    asked = []

    def get(url):
        asked.append(url)
        return cbk_get(url)

    out = nb.fetch_releases(date(2026, 9, 28), date(2026, 10, 5), tmp_path, get=get, probe=None, sleep=lambda s: None)
    assert out["maturities"] == MATURITIES and out["warnings"] == [] and len(out["issues_sha256"]) == 64
    assert asked.count(cbk.TBOND_LISTING) == 1 and (tmp_path / bi.CACHE_FILE).is_file()       # no request of its own


# ---------------------------------------------------------------------------
# 2. The log
# ---------------------------------------------------------------------------

def test_with_no_typed_rows_the_net_to_5_october_is_unchanged():
    log = nb.build_log(RELEASES, FY, WEEK.value_date_window[1], maturities=MATURITIES, typed_redemptions=[])
    assert (log.as_at, round(log.net_bn, 3), round(log.share_pct(TARGET), 1)) == (date(2026, 10, 5), Decimal("572.296"),
                                                                                  Decimal("236.0"))
    assert (log.counted, log.typed, len(log.rows), log.unaccounted, log.flags) == (20, 0, 24, [], [])
    # 17 August's maturity is carried by that day's bond results; 12 October is after this week's window
    assert not any(r["kind"] in (nb.TYPED_KIND, nb.MATURITY_KIND) for r in log.rows)


def test_the_maturity_of_12_october_with_nothing_typed_is_asked_about_and_adds_nothing():
    log = log_next()
    assert log.unaccounted == [WARNING]
    row = log.rows[-1]
    assert (row["key"], row["kind"], row["counted"]) == (MATURITY_ROW, "Bond maturity (no redemption found)", "No")
    assert (row["accepted_kes_m"], row["redemptions_kes_m"], row["net_kes_m"]) == (None, None, None)
    plain = nb.build_log(NEXT_RELEASES, FY, NEXT.value_date_window[1])
    assert log.net_kes_m == plain.net_kes_m and log.inputs == plain.inputs and log.as_at == date(2026, 10, 12)
    assert row["running_bn"] == float(log.net_kes_m / 1000)                    # the face value is never subtracted
    block, flags = table_flags(log)
    own = [f for f in flags if f.subject == f"borrowing_log/{MATURITY_ROW}"]
    assert [(f.kind, f.field, f.message) for f in own] == [(MISSING, "redemptions_kes_m", WARNING)]
    assert own[0].sources[0]["value"] == 15420.55 and "a floor" in own[0].sources[0]["source"]
    assert block["rows"][-1]["redemptions_kes_m"] == "-" and any("Other bond redemptions" in n for n in block["notes"])


def test_a_typed_row_counts_on_its_date_is_labelled_and_answers_the_question():
    before, log = log_next(), log_next(typed_redemptions=[typed(9000.5)])
    assert log.unaccounted == [] and log.typed == 1 and log.counted == before.counted
    assert before.net_kes_m - log.net_kes_m == Decimal("9000.5")
    row = log.rows[-1]
    assert (row["key"], row["value_date"], row["kind"], row["counted"]) == (
        TYPED_ROW, "2026-10-12", "Bond redemption (typed, not on a release)", "Yes")
    assert (row["accepted_kes_m"], row["redemptions_kes_m"], row["net_kes_m"]) == (None, 9000.5, -9000.5)
    assert row["_origin"] == "analyst_input" and row["_note"].startswith("typed, not on a release: analyst input typed")
    assert row["running_bn"] == float(log.net_kes_m / 1000) and log.rows[-2]["value_date"] == "2026-10-12"   # after the bills
    name = "redemptions 2026-10-12 IFB1/2014/12 (typed, not on a release)"
    assert log.inputs[name]["origin"] == "analyst_input" and log.inputs[name]["value"] == 9000.5 and log.redeemed[-1] == name
    block, flags = table_flags(log)
    assert not any(TYPED_ROW in f.subject for f in flags)                      # its net and running net work out again
    assert block["rows"][-1]["redemptions_kes_m"] == "9,000.50" and block["rows"][-1]["net_kes_m"] == "(9,000.50)"
    tampered = nb.log_block(log)
    tampered["source_rows"][-1]["net_kes_m"] = -9000.0
    assert any("worked out from its inputs" in f.message for f in check_table_block(tampered).flags)


def test_a_typed_row_outside_the_window_does_not_count_and_one_on_another_day_does_not_answer():
    later = log_next(typed_redemptions=[typed(day=date(2026, 11, 9), bond="FXD1/2021/005")])
    assert later.typed == 0 and later.unaccounted == [WARNING] and later.net_kes_m == log_next().net_kes_m
    other_day = log_next(typed_redemptions=[typed(100.0, date(2026, 10, 13))])
    assert other_day.typed == 1 and other_day.unaccounted == [WARNING]         # counted, but 12 October is still unanswered


def test_a_bond_release_of_the_day_that_states_redemptions_carries_the_maturity():
    bonds = {"value_date": "2026-10-12", "kind": "primary", "url": None, "error": None, "file": "stand-in", "sha256": None,
             "accepted_parts": [{"label": "FXD1/2019/020", "kes_m": 20000.0}], "accepted_kes_m": 20000.0,
             "redemptions_kes_m": 15000.0}
    carried = nb.build_log(NEXT_RELEASES + [bonds], FY, NEXT.value_date_window[1], maturities=MATURITIES)
    assert carried.unaccounted == [] and not any(r["kind"] == nb.MATURITY_KIND for r in carried.rows)
    # a bond result that states no redemptions (zero, or a switch's none) does not, and nor do the day's Treasury bills
    for none in ({**bonds, "redemptions_kes_m": 0.0}, {**bonds, "kind": "switch", "redemptions_kes_m": None}):
        assert nb.build_log(NEXT_RELEASES + [none], FY, NEXT.value_date_window[1], maturities=MATURITIES).unaccounted == [WARNING]


def test_typed_rows_never_pair_with_a_workbooks_log():
    class Cell:
        def __init__(self, number):
            self.number, self.source, self.ref = number, "the workbook's log", "ref"

    theirs = [{"date": date(2026, 10, 12), "accepted": Cell(0.0), "redemptions": Cell(-9000.5)}]
    log = log_next(typed_redemptions=[typed()], workbook_log=theirs)
    assert not any(s["row"] == TYPED_ROW for s in log.second_sources)
    # the workbook's row for the day is set beside the day's Treasury bill results, never beside the typed row
    assert {s["row"] for s in log.second_sources if s["source"] == "the workbook's log"} == {"2026-10-12 T-bills"}


# ---------------------------------------------------------------------------
# 3. The form
# ---------------------------------------------------------------------------

@pytest.fixture
def root(tmp_path):
    return tmp_path / "data" / "weekly"


def save(root, text=None, rows=None, week=NEXT):
    given = {"text": text} if text is not None else {"rows": rows}
    return analyst.save_form(week, {"tables": {TABLE: given}}, root)


def refused(root, text, week=NEXT) -> str:
    with pytest.raises(InputError) as exc:
        save(root, text, week=week)
    return str(exc.value)


def item(root, week=NEXT):
    return next(i for g in analyst.status(week, root, "fixed_income")["groups"] for i in g["items"] if i["key"] == TABLE)


def test_the_form_holds_other_bond_redemptions_as_a_list_of_rows(root):
    group = next(g for g in analyst.status(NEXT, root, "fixed_income")["groups"] if g["key"] == "borrowing")
    assert [i["key"] for i in group["items"]] == ["borrowing_target", "fiscal_year_start", "borrowing_log", TABLE]
    shown = item(root)
    assert (shown["label"], shown["mode"], shown["rows"]) == ("Other bond redemptions", "paste", None)
    assert [(c["key"], c["label"], c["unit"]) for c in shown["columns"]] == [
        ("date", "Value date", ""), ("bond", "Bond", ""), ("amount", "Amount redeemed", "Kshs mn")]
    assert "typed, not on a release" in shown["help"] and shown["example"] == "2026-10-12  IFB1/2014/12  15420.55"
    save(root, "Value date  Bond  Amount\n12 October 2026  IFB1/2014/12  9,000.50\n2026-11-09\tFXD1/2021/005\t57566.3\n")
    assert json.loads((inputs.week_dir(NEXT, root) / "analyst.json").read_text(encoding="utf-8"))["tables"][TABLE] == [
        {"date": "2026-10-12", "bond": "IFB1/2014/12", "amount": "9000.50"},
        {"date": "2026-11-09", "bond": "FXD1/2021/005", "amount": "57566.3"}]
    assert item(root)["text"] == "2026-10-12\tIFB1/2014/12\t9000.50\n2026-11-09\tFXD1/2021/005\t57566.3"
    assert item(root)["workbook_rows"] is None                    # the workbook has no such rows: they are only ever typed
    save(root, "")
    assert item(root)["rows"] is None


def test_a_row_must_be_in_the_fiscal_year_positive_and_listed_once(root):
    assert "2026-06-30 is not in the fiscal year (2026-07-01 to 2027-06-30)" in refused(root, "2026-06-30 IFB1/2014/12 100")
    assert "2027-07-01 is not in the fiscal year" in refused(root, "2027-07-01 IFB1/2014/12 100")
    for bad in ("0", "-15420.55", "(15420.55)"):
        assert "Other bond redemptions" in refused(root, f"2026-10-12 IFB1/2014/12 {bad}")
    assert "IFB1/2014/12 on 2026-10-12 appears twice" in refused(root, "2026-10-12 ifb1/2014/12 100\n2026-10-12 IFB1/2014/12 200")
    assert "expected value date, bond, amount redeemed" in refused(root, "2026-10-12 15420.55")
    assert item(root)["rows"] is None                                           # refused whole: nothing was stored
    save(root, "2026-07-01 A 0.01\n2027-06-30 B 1\n2026-10-12 IFB1/2014/12 100\n2026-10-12 FXD1/2016/010 200")   # the edges


def test_the_api_takes_the_rows_and_refuses_a_bad_one(tmp_path):
    client = TestClient(create_app(db_path=tmp_path / "app.db", load_dotenv=False, inputs_root=tmp_path / "data" / "weekly"))
    url = "/api/inputs/weekly/2026-10-09/analyst"
    bad = client.put(url, params={"section": "fixed_income"}, json={"tables": {TABLE: {"text": "2026-10-12 IFB1/2014/12 0"}}})
    assert bad.status_code == 422 and "Other bond redemptions" in json.dumps(bad.json())
    ok = client.put(url, params={"section": "fixed_income"}, json={"tables": {TABLE: {"text": "2026-10-12 IFB1/2014/12 9000.5"}}})
    assert ok.status_code == 200
    held = next(i for g in ok.json()["groups"] for i in g["items"] if i["key"] == TABLE)
    assert held["rows"] == [{"date": "2026-10-12", "bond": "IFB1/2014/12", "amount": "9000.5"}]


def test_the_rows_carry_to_the_next_week_and_are_used_at_once(root):
    save(root, "2026-10-12 IFB1/2014/12 9000.5")
    analyst.save_form(NEXT, {"fields": {"borrowing_target": "919.36"}}, root)
    after = Week(date(2026, 10, 16))
    done = analyst.carry_forward(after, root)
    assert TABLE in done["carried"] and TABLE not in done["unconfirmed"]        # a redemption stays a redemption all year
    assert "borrowing_target" in done["unconfirmed"]
    held = analyst.Analyst(inputs.WeeklyInputs(after, root)).borrowing()["redemptions"]
    assert [(r["date"], r["bond"], r["amount"].number) for r in held] == [(date(2026, 10, 12), "IFB1/2014/12", 9000.5)]
    assert held[0]["amount"].source == ("analyst input typed on the weekly form (other bond redemptions, IFB1/2014/12 on "
                                        "2026-10-12: amount redeemed; source: The fixed income team (a bond redemption CBK "
                                        "prints on no auction result))")
    assert item(root, after)["carried"]["from"] == "2026-10-09"


# ---------------------------------------------------------------------------
# 4. The section
# ---------------------------------------------------------------------------

def next_releases(start, end, folder):
    return {"start": start.isoformat(), "end": end.isoformat(), "warnings": [], "maturities": MATURITIES,
            "releases": [r for r in NEXT_RELEASES if start.isoformat() <= r["value_date"] <= end.isoformat()]}


def build(root, week=NEXT):
    analyst.save_form(week, {"fields": {"borrowing_target": "919.36"}}, root)
    return fiw.build_fixed_income_review(week.ending, inputs=inputs.WeeklyInputs(week, root), draft=wh.no_draft,
                                         fetchers=fetchers(releases=next_releases, tbonds=lambda start, end: {"auctions": []}))


def test_the_review_for_the_week_ending_9_october_asks_about_the_12_october_maturity(root):
    review = build(root)
    rows = items(review, "Net domestic borrowing log:")
    asked = next(i for i in rows if i.ref == f"Net domestic borrowing log: {MATURITY_ROW}")
    assert asked.status == "flagged" and [f.message for f in asked.detail] == [WARNING]
    net = next(i for i in review.review_items if "Net domestic borrowing (Kshs bn)" in i.ref)
    assert net.status == "flagged" and WARNING in str(net.detail)            # the figure it may overstate says so too
    assert "typed" not in net.context["note"]


def test_a_typed_redemption_is_subtracted_in_the_review_as_analyst_input(root):
    before = figures(blocks(build(root))["borrowing"])["net_borrowing"]
    save(root, "2026-10-12 IFB1/2014/12 9000.5")
    review = build(root)
    b = blocks(review)["borrowing"]
    assert Decimal(before.replace(",", "")) - Decimal(figures(b)["net_borrowing"].replace(",", "")) == Decimal("9.0")
    rows = items(review, "Net domestic borrowing log:")
    assert not any("maturity" in i.ref for i in rows)
    row = next(i for i in rows if i.ref == f"Net domestic borrowing log: {TYPED_ROW}")
    assert row.status == "not_auto_verified" and row.detail.startswith("typed, not on a release: analyst input typed on the weekly form")
    net = next(i for i in review.review_items if "Net domestic borrowing (Kshs bn)" in i.ref)
    assert net.status == "not_auto_verified"                                    # an analyst input is in it: never clean
    assert net.context["note"].endswith('Less 1 bond redemption typed under "Weekly analyst inputs" (typed, not on a release).')
    assert WARNING not in json.dumps(review.section)


def test_the_week_ending_2_october_is_unchanged_with_the_maturities_known_and_nothing_typed(root):
    review = build(root, WEEK)
    b = blocks(review)["borrowing"]
    assert (figures(b)["net_borrowing"], figures(b)["ratio"]) == ("572.3", "236.0%")
    net = next(i for i in review.review_items if "Net domestic borrowing (Kshs bn)" in i.ref)
    assert net.status == "clean" and len(items(review, "Net domestic borrowing log:")) == 24


def test_typed_redemptions_are_not_added_to_a_log_the_analysts_typed_themselves(root):
    save(root, "2026-10-12 IFB1/2014/12 9000.5")
    analyst.save_form(NEXT, {"tables": {"borrowing_log": {"text": "2026-10-05 41196.84 (30511.20)\n2026-10-12 41196.84 (48062.00)"}}},
                      root)
    review = build(root)
    assert any('"Other bond redemptions" typed on the form are not added to the typed auction log' in w
               for w in review.section["warnings"])
    assert figures(blocks(review)["borrowing"])["net_borrowing"] == "3.8"       # the typed log alone: 10,685.64 - 6,865.16


# ---------------------------------------------------------------------------
# 5. Advisory: the bond stock in the bulletin against the log
# ---------------------------------------------------------------------------

STOCK = cbk_bulletin.parse_bulletin(BULLETIN).bond_stock


def test_the_bond_stock_is_read_from_the_table_found_by_its_title():
    assert STOCK == {date(2025, 12, 31): 5578.98, date(2026, 3, 31): 5798.22, date(2026, 5, 29): 5944.45,
                     date(2026, 6, 30): 6021.15, date(2026, 7, 31): 6157.18, date(2026, 8, 28): 6365.63,
                     date(2026, 9, 18): 6414.66, date(2026, 9, 25): 6468.61}
    out = cbk_bulletin.Bulletin(issue_date=None)
    lines = ["Table 8: Government Domestic Debt (KSh Billion)", "18-Sep-26 25-Sep-26", "1. Treasury Bills (Excluding Repos) 1.0 2.0",
             "2. Treasury Bonds 6,414.66 6,468.61"]
    cbk_bulletin._domestic_debt(lines, out)                                     # the number shifts by one in some issues
    assert out.bond_stock == {date(2026, 9, 18): 6414.66, date(2026, 9, 25): 6468.61} and out.problems == []
    # a bulletin without the table: the table is refused by name, like any other, and gives no stock
    with pytest.raises(cbk_bulletin.BulletinParseError, match="'Government Domestic Debt' table not found"):
        cbk_bulletin._domestic_debt(["Table 7: Composition of Government Domestic Debt by Instrument (Percent)"], out2 := cbk_bulletin.Bulletin(None))
    assert out2.bond_stock == {}


def test_the_one_week_the_saved_bulletin_gives_has_the_residual_seen():
    log = nb.build_log(RELEASES, FY, WEEK.value_date_window[1])
    block = nb.stock_check_block(log, STOCK, date(2026, 10, 2))
    # the bulletin's only consecutive Fridays: 18 and 25 September; the bond results of 21 September settle between them
    assert block["rows"] == [{"key": "2026-09-18 to 2026-09-25", "from": "2026-09-18", "to": "2026-09-25",
                              "stock_from_bn": "6,414.66", "stock_to_bn": "6,468.61", "change_bn": "53.95",
                              "net_bonds_bn": "50.18", "residual_bn": "3.77"}]
    assert block["export"] is False and block["id"] == "bond_stock_check" and "Advisory, not an exact match" in block["notes"][0]
    assert check_table_block(block).flags == [] and nb.STOCK_RESIDUAL_FLOOR_BN == Decimal("-1.0")
    tampered = nb.stock_check_block(log, STOCK)
    tampered["source_rows"][0]["residual_bn"] = 3.0
    assert any("worked out from its inputs" in f.message for f in check_table_block(tampered).flags)


def test_a_fall_no_result_explains_is_flagged_and_a_typed_redemption_explains_it():
    stock = {date(2026, 10, 9): 6500.00, date(2026, 10, 16): 6490.50}
    log = log_next()
    block = nb.stock_check_block(log, stock)
    flags = check_table_block(block).flags
    assert block["rows"][0]["residual_bn"] == "(9.50)" and [(f.kind, f.field) for f in flags] == [(SOURCES_DISAGREE, "residual_bn")]
    assert flags[0].message == ("possible unprinted bond redemption: the Treasury bond stock changed by -9.50 bn from 09-10-2026 "
                                "to 16-10-2026, 9.50 bn less than the net of the bond results settling between them "
                                "(advisory, not an exact match)")
    explained = nb.stock_check_block(log_next(typed_redemptions=[typed(9000.5)]), stock)
    assert explained["rows"][0]["net_bonds_bn"] == "(9.00)" and explained["rows"][0]["residual_bn"] == "(0.50)"
    assert check_table_block(explained).flags == []                             # above the floor of -1.0 bn


def test_a_week_with_a_switch_is_left_out_and_no_consecutive_fridays_means_no_table():
    log = nb.build_log(RELEASES, FY, WEEK.value_date_window[1])
    assert nb.stock_check_block(log, {date(2026, 7, 31): 6157.18, date(2026, 8, 28): 6365.63}) is None    # four weeks apart
    assert nb.stock_check_block(log, {date(2026, 9, 4): 6400.0, date(2026, 9, 11): 6300.0}) is None       # the 9 September switch
    both = nb.stock_check_block(log, {date(2026, 9, 4): 6400.0, date(2026, 9, 11): 6300.0,
                                      date(2026, 9, 18): STOCK[date(2026, 9, 18)], date(2026, 9, 25): STOCK[date(2026, 9, 25)]})
    assert [r["key"] for r in both["rows"]] == ["2026-09-11 to 2026-09-18", "2026-09-18 to 2026-09-25"]
    assert both["notes"][-1] == ("Left out, because a switch auction settled in the week or a result could not be read: "
                                 "2026-09-04 to 2026-09-11.")


def test_the_stock_check_follows_the_log_in_the_review_when_the_bulletin_is_among_the_inputs(root):
    inputs.store(WEEK, "cbk_bulletin", BULLETIN, "bulletin.pdf", root)
    review = build(root, WEEK)
    assert list(blocks(review))[-3:] == ["borrowing", "borrowing_log", "bond_stock_check"]
    row = items(review, "Treasury bond stock against the log (advisory):")
    assert [(i.ref, i.status) for i in row] == [
        ("Treasury bond stock against the log (advisory): 2026-09-18 to 2026-09-25", "clean")]
