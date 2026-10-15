"""The weekly Fixed Income section, in the real issue's order.

Read from #38.2026 (cytonnreport.com id 891) and the Q3'2026 review's weekly paragraphs
(id 892), 2026-10-09.  In order:

1. "Money Markets, T-Bills Primary Auction": subscription overall and by tenor against the
   previous week, acceptance, and each tenor's yield with its change in bps.
2. "T-Bonds Primary Market": the week's auction results from CBK, and the analysts'
   recommended bidding range (their own call; the tool never proposes one).
3. "Money Market Performance": 3-month bank placements, the 91-day and 364-day yields, the
   Cytonn Money Market Fund and the Top 5 funds' average, then the ranked fund table.
4. "Liquidity": the average interbank rate and volumes, Friday to Thursday.
5. "Kenya Eurobonds": the week's biggest mover and the performance table.
6. "Kenya Shilling": the week (Friday to Friday), the year to date, what supports the
   shilling (remittances, reserves) and what pressures it (carried forward), and the
   week's change in reserves.
7. "Weekly Highlights": cited narrative, drafted like every other section's.
8. The closing paragraph: the net domestic borrowing sentence, worked out from CBK's auction
   results of the fiscal year (fixed_income/net_borrowing.py), and the rest of the outlook
   carried forward from the previous issue.

Sources: the CBK Weekly Bulletin (Tables 2, 3, 4, 6) and CBK's own auction results and
daily rate table, which are published; the fixed income workbook, which is typed by the
analysts; the NSE yield curve.  KCB's reports are not used: they cover NSE equities only.

Every figure is worked out here from those inputs and recorded with them
(common/computed.py), so the checker works each one out again.  A figure that rests on a
typed workbook cell is "analyst input", never clean.  Where an input is missing the part is
an ``unavailable`` block that names what is missing; no number is ever filled in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Optional

from cytonn_weekly.common.computed import (
    ANALYST,
    BPS,
    PLAIN,
    PLAIN_PCT,
    carried_block,
    computed_block,
    evaluate,
    pct_change,
    ratio_pct,
)
from cytonn_weekly.common.formatting import NUMBER, PCT, TEXT
from cytonn_weekly.common.review import (
    build_review,
    check_section,
    narrative_block,
    numbered,
    supplied_block,
    table_block,
    unavailable_block,
)
from cytonn_weekly.common.run_events import Observer, report_blocks
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview
from cytonn_weekly.fixed_income import cbk_auctions, net_borrowing
from cytonn_weekly.narrative.base import NarrativeBrief, NarrativeProvider
from cytonn_weekly.narrative.drafter import draft_pieces
from cytonn_weekly.weekly import analyst, cbk_bulletin, cbk_rates, fi_workbook, previous_issue
from cytonn_weekly.weekly.inputs import CBK_BULLETIN, WeeklyInputs, store
from cytonn_weekly.weekly.prose import (
    Figures,
    direction,
    join_names,
    published,
    second_reading,
    try_fetch,
    typed,
    typed_second,
    typed_source,
)
from cytonn_weekly.weekly.week import Week, ordinal, table_date, week_for
from cytonn_weekly.weekly.workbook import WorkbookError

SECTION = "fixed_income"
TITLE = "Fixed Income"
N_HIGHLIGHTS = 2
WB = fi_workbook.SOURCE_NAME
TENORS = cbk_bulletin.TENORS

SUBSECTIONS = ("Money Markets, T-Bills Primary Auction:", "T-Bonds Primary Market:", "Money Market Performance:",
               "Liquidity:", "Kenya Eurobonds:", "Kenya Shilling:", "Weekly Highlights")
# The charts #38.2026 prints in this section (added by hand; the tool draws none).
CHARTS = (
    "The chart below shows the yield growth rate for the 91-day paper over the last year",
    "The chart below shows the performance of the 91-day, 182-day and 364-day papers over the last two years",
    "The chart below compares the overall average T-bill subscription rates obtained in 2023, 2024, 2025 and 2026 Year-to-date (YTD)",
    "Money market yields (uncaptioned chart under the Money Market Performance paragraph)",
    "The chart below shows the interbank rates in the market over the years",
    "The chart below summarizes the evolution of Kenya's months of import cover over the last two years",
)
CHART_REFERENCE = "Cytonn Weekly #38.2026"
# Where #38.2026 puts each chart: after which part of the section (the Word export marks the place).
CHART_AFTER = {"tbills": list(CHARTS[0:3]), "money_market": [CHARTS[3]], "liquidity": [CHARTS[4]], "shilling_support": [CHARTS[5]]}

UPLOAD = "Upload it under \"This week's inputs\" on the start screen and draft again."
NEED_BULLETIN = ("The CBK Weekly Bulletin for this week is not among this week's inputs and could not be fetched.",
                 f"The bulletin CBK publishes on the Friday. {UPLOAD}")

PLACEMENTS_FLAG = ("its source is unconfirmed: it was named as the CBK bulletin and then the NSE price list, and "
                   "neither carries it. Confirm the figure with the fixed income team")
TARGET_FLAG = ("the team has not confirmed whether the net domestic borrowing target is the workbook's figure or the "
               "Budget workbook's ('Borrowings', FY'2026/2027 domestic borrowing)")

# "Yields at Issue" is not in the workbook's issue list.  These are the figures #38.2026 printed,
# by column; that table's fixed rows are known to be stale or shifted, so every one needs the
# fixed income analysts' confirmation, and the row is flagged until they give it.  A yield typed
# under "Weekly analyst inputs" replaces the figure here, as an analyst input.
YIELDS_AT_ISSUE = {"2018_10y": 7.3, "2018_30y": 8.3, "2019_12y": 6.2, "2021_13y": 10.4, "2024_7y": 9.9}
YIELDS_AT_ISSUE_NOTE = ("Not confirmed: \"Yields at Issue\" is not in the workbook's issue list. These are the figures "
                        "printed in Cytonn Weekly #38.2026, whose fixed rows are known to be stale or shifted. "
                        "Confirm each with the fixed income analysts before accepting.")
# The curve is described as it is printed: the 2028 bond is "the 10-year Eurobond issued in 2018".
EUROBOND_NAMES = {"2018_10y": "10-year Eurobond issued in 2018", "2018_30y": "30-year Eurobond issued in 2018",
                  "2019_12y": "12-year Eurobond issued in 2019", "2021_13y": "13-year Eurobond issued in 2021",
                  "2024_7y": "7-year Eurobond issued in 2024"}

BRIEFS: list[NarrativeBrief] = [
    NarrativeBrief(
        id="monetary", section=TITLE, label="Monetary policy and inflation",
        focus=("a Central Bank of Kenya monetary policy decision or statement, an inflation release from the Kenya "
               "National Bureau of Statistics, or a fuel price review by EPRA published in the week"),
        preferred_domains=("centralbank.go.ke", "knbs.or.ke", "epra.go.ke"),
    ),
    NarrativeBrief(
        id="fiscal", section=TITLE, label="Government borrowing and fiscal policy",
        focus=("a National Treasury, Parliament or IMF development on Kenya's budget, public debt, revenue collection "
               "or a sovereign credit rating action published in the week"),
        preferred_domains=("treasury.go.ke", "parliament.go.ke", "imf.org"),
    ),
    NarrativeBrief(
        id="markets", section=TITLE, label="Fixed income markets",
        focus=("a development in Kenya's government securities, corporate bond or money markets published in the "
               "week, such as a new issue, a buyback or a regulatory change"),
        preferred_domains=("centralbank.go.ke", "nse.co.ke", "cma.or.ke"),
    ),
]


@dataclass
class Fetchers:
    """Every network call the section makes, so tests can replace each one."""

    usd_rates: Callable[[], dict[date, float]] = cbk_rates.fetch_usd_rates
    bulletin: Callable[[date], tuple[bytes, str]] = cbk_bulletin.fetch_bulletin
    tbonds: Callable[[date, date], dict[str, Any]] = cbk_auctions.fetch_period_tbonds
    # every T-bill and T-bond result of the fiscal year so far, kept under the data folder (the net borrowing log)
    releases: Callable[[date, date, Any], dict[str, Any]] = net_borrowing.fetch_releases
    previous_issue: Callable[[date, Optional[str]], previous_issue.Issue] = (
        lambda day, ref: previous_issue.find_previous_issue(day, reference=ref))


def _missing(block_id: str, title: str, reason_unblock: tuple[str, str]) -> dict[str, Any]:
    return unavailable_block(block_id, title, *reason_unblock)


def _bulletin_src(table: int) -> str:
    return f"{cbk_bulletin.SOURCE_NAME}, Table {table}"


def _table_reason(bulletin: Optional[cbk_bulletin.Bulletin], table: str, otherwise: str) -> str:
    """Why a part that needs one bulletin table is unavailable: the table's own refusal when it was left out."""
    return (bulletin.unavailable.get(table) if bulletin is not None else None) or otherwise


def _typed_sources(inputs: WeeklyInputs, *cells: Any) -> list[dict[str, Any]]:
    """The analysts' sources a part rests on: the workbook when one is uploaded, the form when a value was typed."""
    names = [WB] if inputs.fi_book is not None else []
    if any(analyst.is_typed(c) for c in cells):
        names.append(analyst.FORM)
    return [{"name": n} for n in names]


# ---------------------------------------------------------------------------
# 1. T-bills
# ---------------------------------------------------------------------------

def _auction_rows(bulletin: cbk_bulletin.Bulletin, week: Week) -> Optional[tuple[dict[str, dict], dict[str, dict]]]:
    """(this week's row, the previous week's row) per tenor from Table 4, or None if either is not printed."""
    this, prev = {}, {}
    for tenor in TENORS:
        rows = bulletin.tbills.get(tenor) or []
        t = next((r for r in rows if week.monday <= r["date"] <= week.ending), None)
        p = next((r for r in rows if week.previous.monday <= r["date"] <= week.previous.ending), None)
        if t is None or p is None:
            return None
        this[tenor], prev[tenor] = t, p
    return this, prev


def _tbill_inputs(bulletin: cbk_bulletin.Bulletin, week: Week, wb_tbills: Optional[dict[str, Any]]) -> Optional[dict[str, dict]]:
    rows = _auction_rows(bulletin, week)
    if rows is None:
        return None
    this, prev = rows
    src = _bulletin_src(4)
    inputs: dict[str, dict] = {}
    for tenor in TENORS:
        n = tenor.split("-")[0]
        wb = (wb_tbills or {}).get(tenor) or {}
        inputs[f"bids_{n}"] = published(this[tenor]["bids"], src, second=typed_second(wb.get("bids"), WB), decimals=2)
        inputs[f"offered_{n}"] = published(this[tenor]["offered"], src, second=typed_second(wb.get("offered"), WB), decimals=2)
        inputs[f"accepted_{n}"] = published(this[tenor]["accepted"], src, second=typed_second(wb.get("accepted"), WB), decimals=2)
        inputs[f"rate_{n}"] = published(this[tenor]["rate"], src, second=typed_second(wb.get("rate"), WB, 100), decimals=3)
        inputs[f"prev_bids_{n}"] = published(prev[tenor]["bids"], src)
        inputs[f"prev_offered_{n}"] = published(prev[tenor]["offered"], src)
        inputs[f"prev_rate_{n}"] = published(prev[tenor]["rate"], src, second=typed_second(wb.get("previous_rate"), WB, 100),
                                             decimals=3)
    return inputs


def _pick(inputs: dict[str, dict], *names: str) -> dict[str, dict]:
    return {n: inputs[n] for n in names}


def _yield_clause(figs: Figures, inputs: dict[str, dict], tenor: str) -> tuple[float, str]:
    n = tenor.split("-")[0]
    pair = _pick(inputs, f"rate_{n}", f"prev_rate_{n}")
    bps = figs.add(f"bps_{n}", f"{tenor} yield change", BPS, 1, pair, ["mul", ["sub", f"rate_{n}", f"prev_rate_{n}"], 100])
    now = figs.add(f"yield_{n}", f"{tenor} yield", PLAIN_PCT, 2, _pick(inputs, f"rate_{n}"))
    was = figs.add(f"prev_yield_{n}", f"{tenor} yield, previous week", PLAIN_PCT, 2, _pick(inputs, f"prev_rate_{n}"))
    change = figs.value(f"bps_{n}")
    verb = direction(change, "increased", "decreased", "was unchanged")
    if change == 0:
        figs.hide(f"bps_{n}")
        figs.hide(f"prev_yield_{n}")
        return 0.0, f"the yield on the {tenor} paper {verb} at {now}"
    if now == was:   # a move too small to show at two decimals, as the issues word it
        figs.hide(f"prev_yield_{n}")
        return abs(change), f"the yield on the {tenor} paper {verb} by {bps} to remain relatively unchanged at {now}"
    return abs(change), f"the yield on the {tenor} paper {verb} by {bps} to {now} from {was} recorded the previous week"


def tbills_block(inputs: Optional[dict[str, dict]], bulletin: Optional[cbk_bulletin.Bulletin]) -> dict[str, Any]:
    title = "Money Markets, T-Bills Primary Auction"
    if bulletin is None:
        return _missing("tbills", title, NEED_BULLETIN)
    if inputs is None:
        return unavailable_block("tbills", title, _table_reason(
            bulletin, "Table 4", "The bulletin's Table 4 does not print both this week's and the previous week's Treasury "
            "bill auctions."), "The bulletin issued on this week's Friday.")
    figs = Figures()
    ns = [t.split("-")[0] for t in TENORS]
    bids, offered = [f"bids_{n}" for n in ns], [f"offered_{n}" for n in ns]
    pbids, poffered = [f"prev_bids_{n}" for n in ns], [f"prev_offered_{n}" for n in ns]
    sub = figs.add("subscription", "Overall subscription rate", PLAIN_PCT, 1, _pick(inputs, *bids, *offered),
                   ["mul", ["div", ["sum", *bids], ["sum", *offered]], 100])
    psub = figs.add("prev_subscription", "Overall subscription rate, previous week", PLAIN_PCT, 1,
                    _pick(inputs, *pbids, *poffered), ["mul", ["div", ["sum", *pbids], ["sum", *poffered]], 100])
    sub_v, psub_v = figs.value("subscription"), figs.value("prev_subscription")
    text = [f"This week, T-bills were {'oversubscribed' if sub_v > 100 else 'undersubscribed'}, with the overall "
            f"subscription rate coming in at {sub}, {direction(sub_v - psub_v, 'higher than', 'lower than', 'unchanged from')} "
            f"the subscription rate of {psub} recorded the previous week."]
    tenor_text = {}
    for tenor, n in zip(TENORS, ns):
        s = figs.add(f"subscription_{n}", f"{tenor} subscription rate", PLAIN_PCT, 1, _pick(inputs, f"bids_{n}", f"offered_{n}"),
                     ratio_pct(f"bids_{n}", f"offered_{n}"))
        p = figs.add(f"prev_subscription_{n}", f"{tenor} subscription rate, previous week", PLAIN_PCT, 1,
                     _pick(inputs, f"prev_bids_{n}", f"prev_offered_{n}"), ratio_pct(f"prev_bids_{n}", f"prev_offered_{n}"))
        tenor_text[tenor] = (s, p, figs.value(f"subscription_{n}") - figs.value(f"prev_subscription_{n}"))
    b91 = figs.add("bids_91_bn", "91-day bids received (Kshs bn)", PLAIN, 1, _pick(inputs, "bids_91"), ["div", "bids_91", 1000])
    o91 = figs.add("offered_91_bn", "91-day amount offered (Kshs bn)", PLAIN, 1, _pick(inputs, "offered_91"), ["div", "offered_91", 1000])
    s, p, d = tenor_text["91-day"]
    text.append(f"The 91-day paper received bids worth Kshs {b91} bn against the offered Kshs {o91} bn, translating to a "
                f"subscription rate of {s}, {direction(d, 'higher than', 'lower than', 'unchanged from')} the subscription "
                f"rate of {p} recorded the previous week.")
    s2, p2, d2 = tenor_text["182-day"]
    s3, p3, d3 = tenor_text["364-day"]
    text.append(f"The subscription rate for the 182-day paper {direction(d2, 'increased', 'decreased', 'was unchanged')} to "
                f"{s2} from {p2} recorded the previous week, while that of the 364-day paper "
                f"{direction(d3, 'increased', 'decreased', 'was unchanged')} to {s3} from {p3} recorded the previous week.")
    accepted = [f"accepted_{n}" for n in ns]
    acc = figs.add("accepted_bn", "Total accepted (Kshs bn)", PLAIN, 1, _pick(inputs, *accepted), ["div", ["sum", *accepted], 1000])
    tot = figs.add("bids_bn", "Total bids received (Kshs bn)", PLAIN, 1, _pick(inputs, *bids), ["div", ["sum", *bids], 1000])
    rate = figs.add("acceptance", "Acceptance rate", PLAIN_PCT, 1, _pick(inputs, *accepted, *bids),
                    ["mul", ["div", ["sum", *accepted], ["sum", *bids]], 100])
    text.append(f"The government accepted a total of Kshs {acc} bn worth of bids out of Kshs {tot} bn bids received, "
                f"translating to an acceptance rate of {rate}.")
    clauses = sorted((_yield_clause(figs, inputs, t) for t in TENORS), key=lambda c: -c[0])
    parts = [c[1] for c in clauses]
    text.append(f"On yields, {parts[0]}, {parts[1]}, while {parts[2]}.")
    return computed_block("tbills", title, " ".join(text), figs.items,
                          sources=[{"name": _bulletin_src(4), "url": cbk_bulletin.LISTING}])


# ---------------------------------------------------------------------------
# 2. T-bonds
# ---------------------------------------------------------------------------

def _bulletin_bond(bulletin: Optional[cbk_bulletin.Bulletin], code: str, key: str) -> Optional[dict[str, Any]]:
    """The bulletin's Table 5 figure for a bond (its last printing), as a second reading in KSh bn."""
    if bulletin is None:
        return None
    codes = bulletin.tbonds.get("codes") or []
    values = bulletin.tbonds.get(key) or []
    if len(values) != len(codes) or code not in codes:
        return None
    index = len(codes) - 1 - codes[::-1].index(code)
    return second_reading(values[index] / 1000, _bulletin_src(5))


def tbonds_blocks(results: Optional[dict[str, Any]], bulletin: Optional[cbk_bulletin.Bulletin], week: Week,
                  problems: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(the T-bond blocks, the week's auctioned bonds for the bidding-range context)."""
    title = "T-Bonds Primary Market"
    if results is None:
        why = next((p for p in problems if p.startswith("CBK T-bond results")), "CBK's Treasury bond results could not be fetched.")
        return [unavailable_block("tbonds", title, why, "Draft again once centralbank.go.ke answers.")], []
    auctions = [a for a in results.get("auctions", []) if a.get("kind") == "primary"]
    blocks, bonds = [], []
    for n, auction in enumerate(sorted(auctions, key=lambda a: a["value_date"])):
        block_id = "tbonds" if n == 0 else f"tbonds_{n + 1}"
        rows = [r for r in auction.get("rows", []) if not r.get("error")]
        if auction.get("error") or not rows or auction.get("total_offered_kes_bn") is None:
            blocks.append(unavailable_block(block_id, title, f"CBK's results for the auction with value date "
                                            f"{auction['value_date']} could not be read: {auction.get('error') or 'a figure is missing'}.",
                                            "A readable results PDF on centralbank.go.ke."))
            continue
        src = f"CBK Treasury bond auction results, value date {auction['value_date']}"
        figs = Figures()
        inputs: dict[str, dict] = {"offered": published(auction["total_offered_kes_bn"], src)}
        for i, r in enumerate(rows):
            inputs[f"bids_{i}"] = published(r["bids_kes_bn"], src, second=_bulletin_bond(bulletin, r["issue"], "bids"), decimals=2)
            inputs[f"accepted_{i}"] = published(r["accepted_kes_bn"], src,
                                                second=_bulletin_bond(bulletin, r["issue"], "accepted"), decimals=2)
        bid_names = [f"bids_{i}" for i in range(len(rows))]
        acc_names = [f"accepted_{i}" for i in range(len(rows))]
        sub = figs.add("subscription", "Overall subscription rate", PLAIN_PCT, 1, _pick(inputs, "offered", *bid_names),
                       ["mul", ["div", ["sum", *bid_names], "offered"], 100])
        bids = figs.add("bids_bn", "Bids received (Kshs bn)", PLAIN, 1, _pick(inputs, *bid_names), ["sum", *bid_names])
        offered = figs.add("offered_bn", "Amount offered (Kshs bn)", PLAIN, 1, _pick(inputs, "offered"))
        accepted = figs.add("accepted_bn", "Bids accepted (Kshs bn)", PLAIN, 1, _pick(inputs, *acc_names), ["sum", *acc_names])
        acceptance = figs.add("acceptance", "Acceptance rate", PLAIN_PCT, 1, _pick(inputs, *acc_names, *bid_names),
                              ["mul", ["div", ["sum", *acc_names], ["sum", *bid_names]], 100])
        names, yields, details = [], [], []
        for i, r in enumerate(rows):
            names.append(r["issue"])
            yields.append(figs.add(f"yield_{i}", f"{r['issue']} weighted average yield of accepted bids", PLAIN_PCT, 1,
                                   {"rate": published(r["avg_rate_pct"], src,
                                                      second=_bulletin_bond_rate(bulletin, r["issue"]), decimals=2)}))
            detail = []
            if r.get("years_to_maturity") is not None:
                detail.append("a tenor to maturity of " + figs.add(f"tenor_{i}", f"{r['issue']} years to maturity", PLAIN, 1,
                                                                   {"years": published(r["years_to_maturity"], src)}) + " years")
            if r.get("coupon_pct") is not None:
                detail.append("a fixed coupon rate of " + figs.add(f"coupon_{i}", f"{r['issue']} coupon", PLAIN_PCT, 1,
                                                                   {"coupon": published(r["coupon_pct"], src)}))
            details.append(f"{r['issue']}" + (f" ({' and '.join(detail)})" if detail else ""))
            bonds.append({"issue": r["issue"], "years_to_maturity": r.get("years_to_maturity")})
        plural = len(rows) > 1
        sub_v = figs.value("subscription")
        text = (f"During the week, the Central Bank of Kenya released the auction results for the treasury bond"
                f"{'s' if plural else ''} {join_names(details)}. The bond{'s were' if plural else ' was'} "
                f"{'oversubscribed' if sub_v > 100 else 'undersubscribed'}, with the overall subscription rate coming in at "
                f"{sub}, receiving bids worth Kshs {bids} bn against the offered Kshs {offered} bn. The government accepted "
                f"bids worth Kshs {accepted} bn, translating to an acceptance rate of {acceptance}. The weighted average "
                f"yield of accepted bids for {join_names(names)} came in at {join_names(yields)}"
                f"{' respectively' if plural else ''}.")
        blocks.append(computed_block(block_id, title, text, figs.items,
                                     sources=[{"name": src, "url": auction.get("url") or results.get("listing_url")}]))
    return blocks, bonds


def _bulletin_bond_rate(bulletin: Optional[cbk_bulletin.Bulletin], code: str) -> Optional[dict[str, Any]]:
    if bulletin is None:
        return None
    codes = bulletin.tbonds.get("codes") or []
    rates = bulletin.tbonds.get("rates") or []
    if len(rates) != len(codes) or code not in codes:
        return None
    return second_reading(rates[len(codes) - 1 - codes[::-1].index(code)], _bulletin_src(5))


def bidding_range_block(inputs: WeeklyInputs, bonds: list[dict[str, Any]]) -> dict[str, Any]:
    """The analysts' recommended bidding range: their text if they supplied it, else an empty part to fill.

    The NSE curve's yield at each auctioned bond's remaining tenor is shown as context only;
    it is never turned into a range.
    """
    title = "T-Bonds: recommended bidding range (the analysts' recommendation)"
    context = []
    curve = inputs.yield_curve
    if curve is not None:
        for b in bonds:
            years = b.get("years_to_maturity")
            at = curve.at(years) if years is not None else None
            if at is not None:
                context.append(f"{b['issue']} ({years:.1f} years): {at:.2f}%")
    note = ""
    if curve is not None:
        note = (f" Context only, from the NSE yield curve of {ordinal(curve.curve_date)}"
                + (f", interpolated at each bond's remaining tenor: {'; '.join(context)}." if context
                   else ": no bond with a known remaining tenor was auctioned this week."))
    text = inputs.notes.get("bidding_range")
    if text:
        block = supplied_block("bidding_range", title, text)
        block["context"] = note.strip()
        return block
    return unavailable_block(
        "bidding_range", title,
        "The recommended bidding range is the analysts' own call, not a formula, and none has been entered for this week."
        + note,
        "Type the analysts' range under \"This week's inputs\" on the start screen and draft again.")


# ---------------------------------------------------------------------------
# 3. Money market
# ---------------------------------------------------------------------------

def _top_five(table: dict[str, Any], figs: Figures, key: str, label: str) -> str:
    funds = sorted(table["funds"], key=lambda f: -f["rate"].number)[:5]
    inputs = {f"fund_{i + 1}": typed(f["rate"], WB, scale=100) for i, f in enumerate(funds)}
    return figs.add(key, label, PLAIN_PCT, 2, inputs, ["mean", *inputs])


def money_market_blocks(inputs: WeeklyInputs, tbill_inputs: Optional[dict[str, dict]], week: Week,
                        previous: Optional[WeeklyInputs], warnings: list[str]) -> list[dict[str, Any]]:
    title = "Money Market Performance"
    form = inputs.analyst
    table, placements = form.mmf(), form.field("placements")
    missing = [key for key, found in (("mmf", table), ("placements", placements)) if found is None]
    if missing:
        return [unavailable_block("money_market", title, *form.why(analyst.FI, missing))]
    figs = Figures()
    place = figs.add("placements", "3-month bank placements", PLAIN_PCT, 1, {"placements": typed(placements, WB, scale=100)},
                     flag=PLACEMENTS_FLAG)
    text = [f"In the money markets, 3-month bank placements ended the week at {place} (based on rates offered by various banks)."]
    if tbill_inputs is not None:
        c91, c364 = _yield_clause(figs, tbill_inputs, "91-day")[1], _yield_clause(figs, tbill_inputs, "364-day")[1]
        text.append(f"On government papers, {c91}, while {c364}.")
    else:
        warnings.append("Money Market Performance: the T-bill yields are left out (the bulletin's Table 4 was not available).")
    cytonn = next((f for f in table["funds"] if " ".join(str(f["fund"].value).split()).lower().startswith(fi_workbook.CYTONN_FUND)), None)
    if cytonn is None:
        warnings.append("Money Market Performance: the fund table has no Cytonn Money Market Fund row, so its yield is left out.")
    else:
        now = figs.add("cmmf", "Cytonn Money Market Fund yield", PLAIN_PCT, 1, {"cmmf": typed(cytonn["rate"], WB, scale=100)})
        last = form.field("cmmf_last_week")
        if last is None:
            text.append(f"The yield on the Cytonn Money Market Fund closed the week at {now}.")
        else:
            pair = {"cmmf": typed(cytonn["rate"], WB, scale=100), "cmmf_last": typed(last, WB, scale=100)}
            bps = figs.add("cmmf_bps", "Cytonn Money Market Fund yield change", BPS, 1, pair, ["mul", ["sub", "cmmf", "cmmf_last"], 100])
            was = figs.add("cmmf_last", "Cytonn Money Market Fund yield, previous week", PLAIN_PCT, 1, {"cmmf_last": pair["cmmf_last"]})
            change = figs.value("cmmf_bps")
            if round(change, 1) == 0:
                figs.hide("cmmf_bps")
            text.append(f"The yield on the Cytonn Money Market Fund remained unchanged at {now} from {was} recorded the previous week."
                        if round(change, 1) == 0 else
                        f"The yield on the Cytonn Money Market Fund {direction(change, 'increased', 'decreased')} by {bps} to "
                        f"{now} from {was} recorded the previous week.")
    top = _top_five(table, figs, "top5", "Average yield of the Top 5 Money Market Funds")
    prev_table = previous.analyst.mmf() if previous is not None else None
    if prev_table is None:
        text.append(f"The average yield on the Top 5 Money Market Funds stood at {top}.")
        warnings.append("Money Market Performance: the Top 5 average is not compared with the previous week, because the "
                        f"previous week's fund table is neither typed nor in a {WB.lower()} among the inputs for the week "
                        f"ending {week.previous_friday.isoformat()}.")
    else:
        was = _top_five(prev_table, figs, "top5_last", "Average yield of the Top 5 Money Market Funds, previous week")
        change = (figs.value("top5") - figs.value("top5_last")) * 100
        five = {f["key"]: f for f in figs.items}
        both = {**{f"now_{k}": v for k, v in five["top5"]["inputs"].items()},
                **{f"last_{k}": v for k, v in five["top5_last"]["inputs"].items()}}
        bps = figs.add("top5_bps", "Top 5 Money Market Funds average yield change", BPS, 1, both,
                       ["mul", ["sub", ["mean", *[k for k in both if k.startswith("now_")]],
                                ["mean", *[k for k in both if k.startswith("last_")]]], 100])
        text.append(f"The average yield on the Top 5 Money Market Funds {direction(change, 'increased', 'decreased', 'was unchanged')} "
                    f"by {bps} to {top} from {was} recorded the previous week.")
    rates = [f["rate"] for f in table["funds"]]
    blocks = [computed_block("money_market", title, " ".join(text), figs.items,
                             sources=_typed_sources(inputs, placements, *rates) + [{"name": _bulletin_src(4), "url": cbk_bulletin.LISTING}],
                             notes=["The Top 5 average is the average of this week's five highest rates in the fund table."])]
    rows = [{"rank": str(int(f["rank"].number)) if f["rank"].number is not None else str(f["rank"].value),
             "fund": " ".join(str(f["fund"].value).replace("( ", "(").split()), "rate": f["rate"].number * 100}
            for f in table["funds"]]
    block = table_block(
        "mmf_table", table["title"],
        [{"key": "rank", "label": "Rank", "fmt": TEXT}, {"key": "fund", "label": "Fund Manager", "fmt": TEXT},
         {"key": "rate", "label": "Effective Annual Rate", "fmt": PCT, "decimals": 1}],
        rows, "fund", "fund", {"name": "Business Daily", "url": None, "as_of": table["published"].isoformat()})
    block["row_origin"] = ANALYST
    block["origin_note"] = (f"Not auto-verified: {table['origin']}. The tool cannot read Business Daily (login pending), "
                            "so check the row against the paper.")
    # A typed rate that differs from the uploaded workbook's is shown to the reviewer on its row.
    block["second_sources"] = [{"row": row["fund"], "column": "rate", "source": typed_source(f["rate"].other, WB),
                                "value": f["rate"].other.number * 100}
                               for row, f in zip(rows, table["funds"]) if getattr(f["rate"], "other", None) is not None]
    if any(a["rate"] < b["rate"] for a, b in zip(rows, rows[1:])):
        warnings.append("The money market fund table is not in descending order of rate as typed; check its ranks.")
    return blocks + [block]


# ---------------------------------------------------------------------------
# 4. Liquidity
# ---------------------------------------------------------------------------

def liquidity_block(inputs: WeeklyInputs, bulletin: Optional[cbk_bulletin.Bulletin], week: Week,
                    warnings: list[str]) -> dict[str, Any]:
    title = "Liquidity"
    if bulletin is None:
        return _missing("liquidity", title, NEED_BULLETIN)
    this_week = next((w for w in bulletin.interbank_weeks if w["last_day"] == week.thursday), None)
    prev_week = next((w for w in bulletin.interbank_weeks if w["last_day"] == week.previous.thursday), None)
    if this_week is None or prev_week is None:
        return unavailable_block("liquidity", title, _table_reason(
            bulletin, "Table 3", "The bulletin's Table 3 does not print the weekly averages to "
            f"{week.thursday.isoformat()} and {week.previous.thursday.isoformat()}."),
            "The bulletin issued on this week's Friday.")
    src = _bulletin_src(3)
    figs = Figures()
    form = inputs.analyst
    daily = form.interbank()
    if "interbank" in form.errors:
        warnings.append(f"Liquidity: {form.errors['interbank']}")
    days = {"now": [r for r in daily if week.previous_friday <= r["date"] <= week.thursday],
            "last": [r for r in daily if week.previous.previous_friday <= r["date"] <= week.previous.thursday]}

    def mean_volume(key: str) -> Optional[dict[str, Any]]:
        rows = [r for r in days.get(key) or [] if r.get("volume") is not None]   # typed rows carry the rate only
        if not rows:
            return None
        return second_reading(sum(r["volume"].number for r in rows) / len(rows),
                              f"analyst input from {WB} {rows[0]['volume'].ref}:{rows[-1]['volume'].a1} (average)", ANALYST)

    vol = {"value": published(this_week["value_mn"], src, second=mean_volume("now"), decimals=0),
           "previous": published(prev_week["value_mn"], src, second=mean_volume("last"), decimals=0)}
    text = []
    if days.get("now") and days.get("last"):
        rate_in = {**{f"now_{i}": typed(r["rate"], WB, scale=100) for i, r in enumerate(days["now"])},
                   **{f"last_{i}": typed(r["rate"], WB, scale=100) for i, r in enumerate(days["last"])}}
        now_names = [k for k in rate_in if k.startswith("now_")]
        last_names = [k for k in rate_in if k.startswith("last_")]
        # Two decimals: the average interbank rate moves by hundredths of a basis point week to week.
        bps = figs.add("rate_bps", "Average interbank rate change", BPS, 2, rate_in,
                       ["mul", ["sub", ["mean", *now_names], ["mean", *last_names]], 100])
        rate = figs.add("rate", "Average interbank rate", PLAIN_PCT, 1, {k: rate_in[k] for k in now_names}, ["mean", *now_names])
        change = figs.value("rate_bps")
        text.append(f"During the week, liquidity in the money markets {direction(change, 'tightened', 'eased', 'was unchanged')}, "
                    f"with the average interbank rate {direction(change, 'increasing', 'decreasing', 'unchanged')}"
                    + (f" by {bps}" if change else "") + f" to {rate}.")
    else:
        kesonia = figs.add("kesonia", "KESONIA, weekly average", PLAIN_PCT, 2, {"kesonia": published(this_week["kesonia"], src)})
        text.append(f"During the week, the Kenya Shilling Overnight Interbank Average (KESONIA) averaged {kesonia}.")
        warnings.append("Liquidity: the change in the average interbank rate is left out; it needs the daily interbank rates, "
                        f"typed under \"{analyst.FORM}\" or in the {WB.lower()} (the bulletin prints KESONIA to two decimals "
                        "only).")
    change = figs.add("volume_change", "Average interbank volumes change", PLAIN_PCT, 1, vol, pct_change("value", "previous"))
    now = figs.add("volume_bn", "Average interbank volumes (Kshs bn)", PLAIN, 1, {"value": vol["value"]}, ["div", "value", 1000])
    was = figs.add("prev_volume_bn", "Average interbank volumes, previous week (Kshs bn)", PLAIN, 1,
                   {"previous": vol["previous"]}, ["div", "previous", 1000])
    moved = figs.value("volume_change")
    text.append(f"The average interbank volumes traded {direction(moved, 'increased', 'decreased', 'were unchanged')} by "
                f"{change} to Kshs {now} bn from Kshs {was} bn recorded the previous week.")
    return computed_block("liquidity", title, " ".join(text), figs.items,
                          sources=[{"name": src, "url": cbk_bulletin.LISTING}] + _typed_sources(inputs, *(r["rate"] for r in daily)),
                          notes=[f"Friday to Thursday: {week.previous_friday.isoformat()} to {week.thursday.isoformat()}."])


# ---------------------------------------------------------------------------
# 5. Eurobonds
# ---------------------------------------------------------------------------

def _yield_on(series: Optional[fi_workbook.EurobondSeries], bulletin: Optional[cbk_bulletin.Bulletin], day: date,
              maturity: int) -> tuple[Optional[float], Optional[str], Optional[float], Optional[str]]:
    """(yield %, where it was read, the analysts' own figure for the same day, where that was read) for one issue on one day."""
    row = next((r for r in (bulletin.market if bulletin else []) if r["date"] == day), None)
    typed_cell = series.yields.get(day) if series is not None else None
    typed_value = typed_cell.number * 100 if typed_cell is not None else None
    where = typed_source(typed_cell, WB) if typed_cell is not None else None
    if row is not None and maturity in row["eurobond_yields"]:
        return row["eurobond_yields"][maturity], _bulletin_src(6), typed_value, where
    if typed_cell is not None:
        return typed_value, where, None, None
    return None, None, None, None


def _typed_yields(wheres: list[Optional[str]]) -> str:
    """How a row's note names the analysts' yields it rests on."""
    if any(w and "typed on the weekly form" in w for w in wheres):
        return "analyst input typed on the weekly form"
    return f"analyst input from the {WB} 'Eurobond' sheet"


def eurobond_blocks(inputs: WeeklyInputs, bulletin: Optional[cbk_bulletin.Bulletin], week: Week,
                    warnings: list[str]) -> list[dict[str, Any]]:
    title = "Kenya Eurobonds"
    form = inputs.analyst
    series_list = form.eurobonds()
    if "eurobonds" in form.errors:
        warnings.append(f"Kenya Eurobonds: {form.errors['eurobonds']}")
    if bulletin is None and not any(series_list):
        return [unavailable_block("eurobonds", title, "Neither the CBK Weekly Bulletin nor the fixed income workbook for this "
                                  f"week is among this week's inputs, and no Eurobond yields are typed under \"{analyst.FORM}\".",
                                  f"The bulletin or the workbook. {UPLOAD}")]
    issues = [{"key": spec[0], "head": spec[1], "maturity": spec[5], "series": s}
              for spec, s in zip(fi_workbook.EUROBOND_ISSUES, series_list)]
    # The table's days: the last six trading days up to the week's Thursday that any source has.
    known = {r["date"] for r in (bulletin.market if bulletin else [])}
    for it in issues:
        if it["series"] is not None:
            known |= {d for d in it["series"].yields if week.previous.monday <= d <= week.thursday}
    days = sorted(d for d in known if d <= week.thursday)[-6:]
    if len(days) < 2:
        return [unavailable_block("eurobonds", title, _table_reason(
            bulletin, "Table 6", f"No Eurobond yields up to {week.thursday.isoformat()} were found in this week's inputs."),
            f"The bulletin issued on this week's Friday. {UPLOAD}")]
    last, first = days[-1], days[0]
    # The year's and the month's first trading day, as the analysts' series has them.  A series that starts later
    # (typed for a few days only) has neither, and that change row is left out rather than worked out from a later day.
    typed_days = sorted({d for it in issues if it["series"] for d in it["series"].yields})
    year_base = next((d for d in typed_days if d.year == last.year), None)
    if year_base is not None and not (year_base.month == 1 and year_base.day <= 8):
        year_base = None
    month_base = next((d for d in typed_days if (d.year, d.month) == (last.year, last.month)), None)
    if month_base is not None and month_base.day > 7:
        month_base = None

    columns = [{"key": "label", "label": "", "fmt": TEXT}] + [
        {"key": it["key"], "label": f"{it['head'][0]} {it['head'][1]}", "fmt": PCT, "decimals": 1} for it in issues]
    rows: list[dict[str, Any]] = []
    seconds: list[dict[str, Any]] = []

    def day_row(day: date) -> dict[str, Any]:
        row: dict[str, Any] = {"label": table_date(day)}
        wheres = []
        for it in issues:
            value, where, second, second_where = _yield_on(it["series"], bulletin, day, it["maturity"])
            row[it["key"]] = value
            if where and where.startswith("analyst input"):
                wheres.append(where)
            if second is not None:
                seconds.append({"row": row["label"], "column": it["key"],
                                "source": WB if second_where.startswith(f"analyst input from {WB}") else second_where,
                                "value": second})
        if wheres:
            row["_origin"] = ANALYST
            row["_note"] = (f"Not auto-verified: this day's yields are {_typed_yields(wheres)} "
                            "(the bulletin for this week does not print the day). Check them before accepting.")
        return row

    for base in (year_base, month_base):
        if base is not None and base not in days:
            rows.append(day_row(base))
    rows += [day_row(d) for d in days]

    def change_row(label: str, base: Optional[date]) -> Optional[dict[str, Any]]:
        if base is None:
            return None
        row: dict[str, Any] = {"label": label, "_derived": {}}
        wheres = []
        for it in issues:
            a, where_a, _, _ = _yield_on(it["series"], bulletin, last, it["maturity"])
            b, where_b, _, _ = _yield_on(it["series"], bulletin, base, it["maturity"])
            if a is None or b is None:
                row[it["key"]] = None
                continue
            how = {"expr": ["sub", "last", "base"], "inputs": {"last": a, "base": b}}
            row[it["key"]] = float(evaluate(how["expr"], how["inputs"]))   # exact, as the checker works it out
            row["_derived"][it["key"]] = how
            wheres += [w for w in (where_a, where_b) if w and w.startswith("analyst input")]
        if wheres:
            row["_origin"] = ANALYST
            row["_note"] = (f"Not auto-verified: worked out from yields that are {_typed_yields(wheres)}. "
                            "The subtraction is checked; the typed yields are not.")
        return row

    for label, base in (("Weekly Change", first), ("MTD Change", month_base), ("YTD Change", year_base)):
        row = change_row(label, base)
        if row is None:
            warnings.append(f"Kenya Eurobonds: the {label} row is left out; it needs the yields on the period's first trading "
                            f"day, typed under \"{analyst.FORM}\" or in the {WB.lower()}.")
        else:
            rows.append(row)
    performance = table_block("eurobonds_table", "Cytonn Report: Kenya Eurobonds Performance", columns, rows, "label", "label",
                              {"name": "Central Bank of Kenya (CBK) Weekly Highlights", "url": cbk_bulletin.LISTING,
                               "as_of": last.isoformat()})
    performance["second_sources"] = seconds
    performance["notes"] = ["Changes are in percentage points."]

    blocks: list[dict[str, Any]] = []
    # The week's biggest mover, from the first and last of the six days.
    moves = []
    for it in issues:
        a, where_a, *sa = _yield_on(it["series"], bulletin, last, it["maturity"])
        b, where_b, *sb = _yield_on(it["series"], bulletin, first, it["maturity"])
        if a is not None and b is not None:
            moves.append((abs(a - b), it, a, b, where_a, where_b, sa, sb))
    if moves:
        _, it, a, b, where_a, where_b, sa, sb = max(moves, key=lambda m: m[0])
        figs = Figures()

        def reading(value, where, second):
            if where.startswith("analyst input"):
                return {"value": value, "origin": ANALYST, "source": where}
            if second[0] is None:
                return published(value, where, decimals=3)
            label = WB if second[1].startswith(f"analyst input from {WB}") else second[1]
            return published(value, where, second=second_reading(second[0], label, ANALYST), decimals=3)

        pair = {"last": reading(a, where_a, sa), "first": reading(b, where_b, sb)}
        bps = figs.add("biggest_bps", f"{EUROBOND_NAMES[it['key']]} yield change", BPS, 1, pair, ["mul", ["sub", "last", "first"], 100])
        now = figs.add("biggest_yield", f"{EUROBOND_NAMES[it['key']]} yield", PLAIN_PCT, 1, {"last": pair["last"]})
        was = figs.add("biggest_previous", f"{EUROBOND_NAMES[it['key']]} yield, previous week", PLAIN_PCT, 1, {"first": pair["first"]})
        ups = sum(1 for m in moves if m[2] > m[3])
        trend = "an upward" if ups == len(moves) else "a downward" if ups == 0 else "a mixed"
        text = (f"During the week, the yields on Kenya's Eurobonds were on {trend} trajectory, with the yield on the "
                f"{EUROBOND_NAMES[it['key']]} {direction(a - b, 'increasing', 'decreasing')} the most by {bps} to {now} from {was} "
                f"recorded the previous week. The table below shows the summary performance of the Kenyan Eurobonds as of "
                f"{ordinal(last)}:")
        blocks.append(computed_block("eurobonds", title, text, figs.items,
                                     sources=[{"name": _bulletin_src(6), "url": cbk_bulletin.LISTING}]
                                     + _typed_sources(inputs, *(c for i in issues if i["series"] for c in i["series"].yields.values()))))

    # The table's fixed rows, per issue: amount issued and years to maturity from the analysts' issue list
    # (the workbook's, or the one typed on the form).
    detail_rows = []
    typed_cells = []
    for it in issues:
        s = it["series"]
        issue = s.issue if s is not None else None
        at_issue = s.yield_at_issue if s is not None else None
        row: dict[str, Any] = {"issue": f"{it['head'][0]} {it['head'][1]}", "amount_bn": None, "years": None, "_origin": ANALYST}
        if at_issue is not None:
            row["yield_at_issue"] = at_issue.number
            row["_note"] = (f"Not auto-verified: the yield at issue is an {at_issue.source}. The amount and years to maturity "
                            "are worked out again from the issue list; the typed values are not checked.")
        else:
            row.update({"yield_at_issue": YIELDS_AT_ISSUE.get(it["key"]), "_note": YIELDS_AT_ISSUE_NOTE,
                        "incomplete": {"yield_at_issue": "not confirmed by the analysts (printed in #38.2026, whose fixed rows "
                                                         "are stale)"}})
        typed_cells += [at_issue] + list((issue or {}).values())
        if issue is not None and issue["amount_before"].number is not None and issue["maturity"].day is not None:
            row["amount_mn"] = issue["amount_before"].number
            row["days_to_maturity"] = (issue["maturity"].day - last).days
            row["amount_bn"] = float(evaluate(["div", "amount_mn", 1000], row))
            row["years"] = float(evaluate(["div", "days_to_maturity", 365], row))
        detail_rows.append(row)
    on_form = any(analyst.is_typed(c) for c in typed_cells)
    if any(r["amount_bn"] is not None or "incomplete" not in r for r in detail_rows):
        details = table_block(
            "eurobonds_issues", "Kenya Eurobonds: amount issued, years to maturity and yield at issue",
            [{"key": "issue", "label": "Issue", "fmt": TEXT},
             {"key": "amount_bn", "label": "Amount Issued (USD bn)", "fmt": NUMBER, "decimals": 1, "expr": ["div", "amount_mn", 1000]},
             {"key": "years", "label": "Years to Maturity", "fmt": NUMBER, "decimals": 1, "expr": ["div", "days_to_maturity", 365]},
             {"key": "yield_at_issue", "label": "Yields at Issue", "fmt": PCT, "decimals": 1}],
            detail_rows, "issue", "issue",
            {"name": f"{analyst.FORM}, Eurobond issues" if on_form else f"{WB}, 'Eurobond' issue list", "url": None,
             "as_of": last.isoformat()})
        details["notes"] = [f"Years to maturity are to {ordinal(last)}, the table's last day.",
                            "The amount is the amount before buyback in the analysts' issue list."]
        # Reviewed here row by row; the Word export prints these rows inside the performance table, as the issue does.
        details["export"] = False
        blocks.append(details)
    else:
        warnings.append("Kenya Eurobonds: the Amount Issued, Years to Maturity and Yields at Issue rows are left out; they need "
                        f"the Eurobond issues, typed under \"{analyst.FORM}\" or in the {WB.lower()}'s issue list.")
        detail_rows = []
    performance["export_grid"] = _eurobond_grid(issues, detail_rows, performance)
    return blocks + [performance]


def _eurobond_grid(issues: list[dict[str, Any]], detail_rows: list[dict[str, Any]], performance: dict[str, Any]) -> list[list[str]]:
    """The table as the issue prints it (issues across, fixed rows on top), built from the checked display strings."""
    from cytonn_weekly.common.formatting import fmt_value

    grid = [[""] + [it["head"][0] for it in issues], ["Tenor"] + [it["head"][1] for it in issues]]
    if detail_rows:
        grid.append(["Amount Issued (USD)"] + [f"{fmt_value(r['amount_bn'], NUMBER, 1)} bn" if r["amount_bn"] is not None else "-"
                                                for r in detail_rows])
        grid.append(["Years to Maturity"] + [fmt_value(r["years"], NUMBER, 1) for r in detail_rows])
        grid.append(["Yields at Issue"] + [fmt_value(r["yield_at_issue"], PCT, 1) for r in detail_rows])
    for row in performance["rows"]:
        grid.append([row["label"]] + [row[it["key"]] for it in issues])
    return grid


# ---------------------------------------------------------------------------
# 6. Shilling
# ---------------------------------------------------------------------------

_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
           "December")


def shilling_blocks(inputs: WeeklyInputs, bulletin: Optional[cbk_bulletin.Bulletin], rates: Optional[dict[date, float]],
                    week: Week, issue: Optional[previous_issue.Issue], warnings: list[str]) -> list[dict[str, Any]]:
    title = "Kenya Shilling"
    book = inputs.fi_book
    typed_rates = {}
    if book is not None:
        try:
            typed_rates = fi_workbook.read_exchange_rates(book)
        except WorkbookError as exc:
            warnings.append(f"Kenya Shilling: {exc}")
    cbk = "Central Bank of Kenya, Daily KES Exchange Rates"

    def rate(day: date) -> Optional[dict[str, Any]]:
        cell = typed_rates.get(day)
        if rates and day in rates:
            return published(rates[day], cbk, second=typed_second(cell, WB), decimals=2)
        if bulletin is not None and day in bulletin.exchange_rates:
            return published(bulletin.exchange_rates[day], _bulletin_src(1), second=typed_second(cell, WB), decimals=2)
        return typed(cell, WB) if cell is not None else None

    blocks: list[dict[str, Any]] = []
    now, was = rate(week.ending), rate(week.previous_friday)
    if now is None or was is None:
        blocks.append(unavailable_block("shilling", title, f"The US dollar rate for {week.ending.isoformat()} or "
                                        f"{week.previous_friday.isoformat()} was not found: CBK's rate table did not answer and "
                                        "the fixed income workbook is not among this week's inputs.",
                                        f"centralbank.go.ke answering, or the {WB.lower()}. {UPLOAD}"))
    else:
        figs = Figures()
        pair = {"friday": now, "last_friday": was}
        bps = figs.add("week_bps", "Shilling's move against the US dollar over the week", BPS, 1, pair,
                       ["mul", pct_change("friday", "last_friday"), 100])
        close = figs.add("rate", "Shilling per US dollar, Friday", PLAIN, 1, {"friday": now})
        prev = figs.add("previous_rate", "Shilling per US dollar, previous Friday", PLAIN, 1, {"last_friday": was})
        moved = figs.value("week_bps")
        text = [f"During the week, the Kenya Shilling {direction(moved, 'depreciated', 'appreciated', 'was unchanged')} against the "
                f"US Dollar by {bps}, to close the week at Kshs {close}, from Kshs {prev} recorded the previous week."]
        # The year's first and last rates are taken from CBK's own table when it answered; the typed sheet
        # is only the fallback (it can hold days CBK published no rate for).
        known = sorted(rates) if rates else sorted(set(typed_rates) | set(bulletin.exchange_rates if bulletin else {}))
        year_days = [d for d in known if d.year == week.ending.year]
        base = rate(year_days[0]) if year_days else None
        if base is not None and year_days[0].month == 1 and year_days[0].day <= 7:
            ytd = figs.add("ytd_bps", "Shilling's year-to-date move against the US dollar", BPS, 1,
                           {"friday": now, "year_open": base}, ["mul", pct_change("friday", "year_open"), 100],
                           note=f"The year's first rate is {year_days[0].isoformat()}'s.")
            ytd_v = figs.value("ytd_bps")
            sentence = (f"On a year-to-date basis, the shilling has {direction(ytd_v, 'depreciated', 'appreciated', 'been unchanged')} "
                        f"by {ytd} against the dollar")
            last_year = [d for d in known if d.year == week.ending.year - 1]
            if last_year and last_year[0].month == 1 and last_year[0].day <= 7 and last_year[-1].month == 12:
                ly = figs.add("last_year_bps", f"Shilling's move against the US dollar in {week.ending.year - 1}", BPS, 1,
                              {"year_close": rate(last_year[-1]), "year_first": rate(last_year[0])},
                              ["mul", pct_change("year_close", "year_first"), 100],
                              note=f"{last_year[0].isoformat()} to {last_year[-1].isoformat()}.")
                ly_v = figs.value("last_year_bps")
                sentence += (f", compared to the {ly} {direction(ly_v, 'depreciation', 'appreciation', 'change')} recorded in "
                             f"{week.ending.year - 1}")
            text.append(sentence + ".")
        else:
            warnings.append("Kenya Shilling: the year-to-date move is left out; the year's first rate was not found.")
        blocks.append(computed_block("shilling", title, " ".join(text), figs.items, sources=[{"name": cbk, "url": cbk_rates.PAGE}, {"name": WB}],
                                     notes=[f"Friday to Friday: {week.previous_friday.isoformat()} to {week.ending.isoformat()}."]))

    # What supports the shilling: remittances (workbook) and reserves (bulletin).
    figs = Figures()
    support = []
    form = inputs.analyst
    months = form.remittances()
    if "remittances" in form.errors:
        warnings.append(f"Kenya Shilling: {form.errors['remittances']}")
    if months or book is not None:
        if len(months) >= 24:
            latest = months[0]
            this = {f"m{i}": typed(m["total"], WB) for i, m in enumerate(months[:12])}
            prior = {f"p{i}": typed(m["total"], WB) for i, m in enumerate(months[12:24])}
            total = figs.add("remittances_12m", "Diaspora remittances, latest twelve months (USD mn)", PLAIN, 1, this, ["sum", *this])
            before = figs.add("remittances_prior_12m", "Diaspora remittances, same twelve months a year earlier (USD mn)", PLAIN, 1,
                              prior, ["sum", *prior])
            share = figs.add("north_america_share", "North America's share of the latest month's remittances", PLAIN_PCT, 1,
                             {"north_america": typed(latest["north_america"], WB), "month_total": typed(latest["total"], WB)},
                             ratio_pct("north_america", "month_total"))
            diff = figs.value("remittances_12m") - figs.value("remittances_prior_12m")
            month = f"{_MONTHS[latest['month'] - 1]} {latest['year']}"
            support.append(f"Diaspora remittances standing at a cumulative USD {total} mn in the twelve months to {month}, "
                           f"{direction(diff, 'higher than', 'lower than', 'unchanged from')} the USD {before} mn recorded over the "
                           f"same period a year earlier. In the {month} figures, North America accounted for {share} of remittances.")
        else:
            warnings.append("Kenya Shilling: the remittances bullet is left out; fewer than 24 months are listed.")
    reserves_text = None
    if bulletin is not None and len(bulletin.reserves) >= 2:
        latest, earlier = bulletin.reserves[-1], bulletin.reserves[-2]
        src = _bulletin_src(2)
        typed_reserves = {}
        if book is not None:
            try:
                typed_reserves = {r["date"]: r for r in fi_workbook.read_reserves(book)}
            except WorkbookError:
                typed_reserves = {}
        cell = (typed_reserves.get(week.ending) or {}).get("usd_bn")
        usd = {"reserves": published(latest["usd_mn"], src, second=typed_second(cell, WB, 1000), decimals=0),
               "previous": published(earlier["usd_mn"], src)}
        level = figs.add("reserves", "Forex reserves (USD mn)", PLAIN, 1, {"reserves": usd["reserves"]})
        cover = figs.add("import_cover", "Months of import cover", PLAIN, 1, {"months": published(latest["months"], src)})
        support.append(f"Forex reserves currently at USD {level} mn (equivalent to {cover} months of import cover), above the "
                       "statutory requirement of maintaining at least 4.0 months of import cover.")
        change = figs.add("reserves_change", "Forex reserves, change over the week", PLAIN_PCT, 1, usd, pct_change("reserves", "previous"))
        before = figs.add("previous_reserves", "Forex reserves, previous week (USD mn)", PLAIN, 1, {"previous": usd["previous"]})
        moved = figs.value("reserves_change")
        reserves_text = (f"Kenya's forex reserves {direction(moved, 'increased', 'decreased', 'were unchanged')} by {change} during "
                         f"the week to USD {level} mn, from USD {before} mn recorded the previous week, equivalent to {cover} months "
                         "of import cover.")
    if support:
        body = "We expect the shilling to be supported by:\n\n" + "\n".join(f"- {s}" for s in support)
        if reserves_text:
            body += "\n\n" + reserves_text
        blocks.append(computed_block("shilling_support", "Kenya Shilling: support, and the week's reserves", body, figs.items,
                                     sources=_typed_sources(inputs, *(m["total"] for m in months[:1]))
                                     + [{"name": _bulletin_src(2), "url": cbk_bulletin.LISTING}]))
    else:
        left_out = _table_reason(bulletin, "Table 2", "")
        blocks.append(unavailable_block("shilling_support", "Kenya Shilling: support, and the week's reserves",
                                        "Neither the bulletin's reserves (Table 2) nor the remittances (typed, or in the "
                                        "workbook) are among this week's inputs." + (f" {left_out}" if left_out else ""),
                                        f"The bulletin or the {WB.lower()}. {UPLOAD}"))
    blocks.append(_carried(issue, "shilling_pressure", "Kenya Shilling: what pressures the shilling", shilling_pressure_text,
                           also=(MACRO_SECTION,)))
    return blocks


# ---------------------------------------------------------------------------
# Carried-forward text
# ---------------------------------------------------------------------------

# Where the shilling paragraphs sit when the previous issue is a Markets Review: under "The Kenyan Shilling:" in its
# Kenya Macro Economic Review, not in Fixed Income (checked on issue 892, the Q3'2026 review, 2026-10-13).
MACRO_SECTION = "kenya-macro-economic-review"


def _ends_pressure_bullets(paragraph: str) -> bool:
    """Whether a paragraph after the opening line is no longer one of its bullets."""
    low = paragraph.lower().strip()
    return ("forex reserves" in low[:40] or low.startswith("weekly highlights")
            # a Markets Review follows the bullets with "Key to note, ... Kenya's forex reserves increased by ..."
            or "forex reserves increased" in low or "forex reserves decreased" in low or low.startswith("key to note")
            # ... and then the next subsection's heading ("Monetary Policy:")
            or (low.endswith(":") and len(low.split()) <= 8))


def shilling_pressure_text(paragraphs: list[str]) -> Optional[str]:
    """The previous issue's "expected to remain under pressure" paragraph and its bullets (five lines at most).

    The opening line itself ends in a colon and is always kept; the heading rule applies to the lines after it.
    """
    start = next((n for n, p in enumerate(paragraphs) if p.lower().startswith("the shilling is however expected to remain under pressure")), None)
    if start is None:
        return None
    end = next((n for n in range(start + 1, len(paragraphs)) if _ends_pressure_bullets(paragraphs[n])),
               min(start + 6, len(paragraphs)))
    end = min(end, start + 6)
    lines = paragraphs[start:end]
    return lines[0] + "\n\n" + "\n".join(f"- {line}" for line in lines[1:]) if len(lines) > 1 else lines[0]


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")   # a full stop followed by a capital, so "235.8%" is not an end


def outlook_text(paragraphs: list[str]) -> Optional[str]:
    """The previous issue's closing rates paragraph, without its own borrowing sentence (worked out afresh here)."""
    para = next((p for p in reversed(paragraphs) if p.lower().startswith("rates in the fixed income market")), None)
    if para is None:
        return None
    kept = [s for s in _SENTENCE_END.split(para) if "net domestic borrowing target" not in s.lower()]
    return " ".join(" ".join(kept).split())


def _carried(issue: Optional[previous_issue.Issue], block_id: str, title: str,
             extract: Callable[[list[str]], Optional[str]], slugs: tuple[str, ...] = ("fixed-income",),
             also: tuple[str, ...] = ()) -> dict[str, Any]:
    """Text carried forward from the previous issue's section (the first of ``slugs`` the issue has).

    ``also`` names further sections to try, in order, when the first holds no such paragraph: the first section in
    which ``extract`` finds the text is used.  Text found in one of them says so on the block, and the flag repeats
    it, because it was written for another part of another kind of report.  Without ``also`` nothing changes.
    """
    if issue is None:
        return unavailable_block(block_id, title, "The previous issue could not be read from cytonnreport.com, so there is "
                                 "no text to carry forward. This part is the analysts' own text.",
                                 "Paste the previous issue's address under \"This week's inputs\" and draft again, or write "
                                 "the paragraph by hand.")
    section = issue.section(*slugs)
    text = extract(previous_issue.html_paragraphs(section["body"])) if section else None
    source = {"issue_id": issue.issue_id, "url": issue.url, "published": issue.published.isoformat() if issue.published else None}
    if issue.skipped_twins:   # a stripped copy was passed over: the flag names it, and says what kind of issue this one is
        source = {**source, "kind": issue.kind, "skipped": list(issue.skipped_twins)}
    if text:
        return carried_block(block_id, title, text, source)
    for slug in also:
        other = issue.sections.get(slug)
        text = extract(previous_issue.html_paragraphs(other["body"])) if other else None
        if text:
            name = other.get("name") or slug
            return carried_block(block_id, title, text, {
                **source, "section": slug,
                "note": f"taken from the {name} of issue {issue.issue_id}, a Markets Review, not from its Fixed Income "
                        "section; check the dates and the period it speaks of"})
    if not also:
        return unavailable_block(block_id, title, f"The previous issue (cytonnreport.com issue {issue.issue_id}) has no "
                                 "paragraph that reads as this part.", "Write the paragraph by hand.")
    wanted = [next((s for s in slugs if s in issue.sections), slugs[0]), *also]
    searched = [s for s in wanted if s in issue.sections]
    absent = [s for s in wanted if s not in issue.sections]
    reason = (f"The previous issue (cytonnreport.com issue {issue.issue_id}) has no paragraph that reads as this part: "
              f"searched {' and '.join(searched) if searched else 'no section'} of issue {issue.issue_id}")
    reason += f"; the issue has no {' or '.join(absent)} section." if absent else "."
    return unavailable_block(block_id, title, reason, "Write the paragraph by hand.")


# ---------------------------------------------------------------------------
# 8. Net domestic borrowing
# ---------------------------------------------------------------------------

BORROWING_TITLE = "Net domestic borrowing against the pro-rated target"


def _borrowing_sentence(figs: Figures, flows: dict[str, dict], net_expr: list, target_cell: Any, fy_start: date, as_at: date,
                        net_flag: str = "", net_note: str = "", net_second: Optional[dict[str, Any]] = None,
                        start_note: str = "") -> str:
    """The closing sentence's three figures, whatever the log came from; "is at X% of", never "ahead of"."""
    days = (as_at - fy_start).days
    target = {"target": typed(target_cell, WB)}
    prorated_expr = ["mul", ["div", "target", 364], days]
    net = figs.add("net_borrowing", "Net domestic borrowing (Kshs bn)", PLAIN, 1, flows, net_expr, flag=net_flag, note=net_note)
    if net_second is not None:
        figs.items[-1]["second"] = net_second
    prorated = figs.add("prorated_target", "Pro-rated net domestic borrowing target (Kshs bn)", PLAIN, 1, target, prorated_expr,
                        flag=TARGET_FLAG, note=f"{days} days from {fy_start.isoformat()} to the latest auction's "
                                                f"value date, {as_at.isoformat()}, over a 364-day year.{start_note}")
    ratio = figs.add("ratio", "Net borrowing as a share of the pro-rated target", PLAIN_PCT, 1, {**flows, **target},
                     ["mul", ["div", net_expr, prorated_expr], 100], flag=TARGET_FLAG)
    return (f"The government is at {ratio} of its pro-rated net domestic borrowing target of Kshs {prorated} bn, with a net "
            f"borrowing position of Kshs {net} bn (inclusive of T-bills).")


def _start_note(data: dict[str, Any]) -> str:
    """Said on the pro-rated target when the fiscal year's start is the analysts' own date, not 1 July."""
    if not data.get("fy_start_typed"):
        return ""
    return f" The fiscal year's start, {data['fy_start'].day.isoformat()}, is an {data['fy_start'].source}."


def _cbk_borrowing(inputs: WeeklyInputs, data: dict[str, Any], log: net_borrowing.Log,
                   bulletin: Optional[cbk_bulletin.Bulletin] = None) -> list[dict[str, Any]]:
    """The sentence from CBK's results, and the log it rests on (shown on the review screen, not exported).

    With a bulletin, the advisory check of the log against CBK's outstanding bond stock follows it.
    """
    figs = Figures()
    bills = sum(1 for r in log.rows if r["kind"] == net_borrowing.KINDS[net_borrowing.TBILL])
    note = (f"{log.counted} CBK results from {log.fy_start.isoformat()} to {log.as_at.isoformat()} ({bills} Treasury bill "
            f"auctions, {log.counted - bills} Treasury bond auctions): accepted amounts less redemptions. No switch auction "
            "is counted.")
    if log.typed:
        note += (f" Less {log.typed} bond redemption{'' if log.typed == 1 else 's'} typed under \"{analyst.FORM}\" "
                 f"({net_borrowing.TYPED_LABEL}).")
    # A maturity nobody accounted for is its own flagged row in the log, and flags the figure it may overstate.
    text = _borrowing_sentence(figs, log.inputs, log.net_expr, data["target_bn"], log.fy_start, log.as_at,
                               net_flag="; ".join(log.flags + log.unaccounted), net_note=note, start_note=_start_note(data))
    sources = [{"name": net_borrowing.SOURCE_NAME, "url": cbk_auctions.TBILL_LISTING}] + _typed_sources(inputs, data["target_bn"])
    notes = ["Net borrowing is worked out from CBK's Treasury bill and bond auction results: accepted amounts less "
             "redemptions, release by release (the log below). A switch auction is not new debt and is never counted."]
    if log.switches:
        notes.append(net_borrowing.switches_note(log.switches))
    out = [computed_block("borrowing", BORROWING_TITLE, text, figs.items, sources=sources, notes=notes),
           net_borrowing.log_block(log)]
    stock = net_borrowing.stock_check_block(log, bulletin.bond_stock, bulletin.issue_date) if bulletin is not None else None
    return out + ([stock] if stock is not None else [])


def _typed_borrowing(inputs: WeeklyInputs, week: Week, data: dict[str, Any],
                     cbk: Optional[net_borrowing.Log]) -> dict[str, Any]:
    """The sentence from the analysts' own log: typed on the form, else the uploaded workbook's (analyst input)."""
    title = BORROWING_TITLE
    limit = week.value_date_window[1]
    log = [r for r in data["log"] if data["fy_start"].day <= r["date"] <= limit]
    latest = max(r["date"] for r in log) if log else None
    if latest is None or latest < week.value_date_window[0]:
        shown = latest.isoformat() if latest else "none"
        if data["typed_log"]:
            return unavailable_block("borrowing", title, f"The auction log typed under \"{analyst.FORM}\" has no auction settling "
                                     f"in the week after {week.ending.isoformat()} (latest value date: {shown}).",
                                     "Add this week's auction to the typed log and draft again.")
        return unavailable_block("borrowing", title, f"'{fi_workbook.BORROWING_SHEET}' logs no auction settling in the week after "
                                 f"{week.ending.isoformat()} (latest value date: {shown}): workbook not yet updated for this week.",
                                 f"The {WB.lower()} updated for this week. {UPLOAD}")
    figs = Figures()
    flows = {}
    for i, r in enumerate(log):
        flows[f"accepted_{i}"] = typed(r["accepted"], WB)
        flows[f"redemptions_{i}"] = typed(r["redemptions"], WB)
    # CBK's own net, when its results could be read, is the second reading of a log the analysts typed.
    second = None
    if cbk is not None and cbk.usable:
        second = {"value": float(round(cbk.net_bn, 3)), "decimals": 3,
                  "source": f"{net_borrowing.SOURCE_NAME} ({cbk.counted} results to {cbk.as_at.isoformat()})"}
    text = _borrowing_sentence(figs, flows, ["div", ["sum", *flows], 1000], data["target_bn"], data["fy_start"].day, latest,
                               net_second=second, start_note=_start_note(data))
    cells = [data["target_bn"]] + [r["accepted"] for r in log]
    return computed_block("borrowing", title, text, figs.items, sources=_typed_sources(inputs, *cells))


def borrowing_blocks(inputs: WeeklyInputs, week: Week, fetched: Optional[dict[str, Any]],
                     warnings: list[str], bulletin: Optional[cbk_bulletin.Bulletin] = None) -> list[dict[str, Any]]:
    """The net domestic borrowing sentence, and the log it is worked out from.

    The log is CBK's auction results (``fetched``, net_borrowing.fetch_releases).  A log the
    analysts typed on the form overrides it, as analyst input, with CBK's net as its second
    reading.  When CBK's results cannot be fetched or read, the typed log, else the uploaded
    workbook's, is the fallback.  The full-year target is always the analysts' figure.

    A bond redemption CBK prints on no result file is typed on the form ("Other bond redemptions")
    and subtracted on its value date in the log built from CBK's results.  A maturity in CBK's
    "Issues of Treasury Bonds" table that neither a result nor a typed row accounts for is a
    flagged row of the log.  Neither touches a log the analysts typed themselves.
    """
    title = BORROWING_TITLE
    form = inputs.analyst
    data = form.borrowing()
    window = week.value_date_window
    log, cbk_problem = None, "CBK's auction results could not be fetched from centralbank.go.ke."
    if fetched is not None:
        wb = form.wb_borrowing()
        other = [{"date": r["date"], "bond": r["bond"], "kes_m": r["amount"].number, "source": typed_source(r["amount"], WB)}
                 for r in data["redemptions"]]
        log = net_borrowing.build_log(fetched["releases"], data["fy_start"].day, window[1],
                                      workbook_log=wb["log"] if wb else None, cell_source=lambda cell: typed_source(cell, WB),
                                      typed_redemptions=other, maturities=fetched.get("maturities"))
        warnings.extend(fetched.get("warnings") or [])
        if log.problems:
            cbk_problem = "; ".join(log.problems) + "."
        elif log.as_at is None or log.as_at < window[0]:
            shown = log.as_at.isoformat() if log.as_at else "none"
            cbk_problem = (f"CBK's results list no auction settling in the week after {week.ending.isoformat()} (latest value "
                           f"date: {shown}).")
            log.problems.append(cbk_problem)
    usable = log is not None and log.usable
    missing = [key for key, found in (("borrowing_target", data["target_bn"]), ("borrowing_log", data["log"] or usable or None))
               if found is None]
    if missing:
        reason, unblock = form.why(analyst.FI, missing)
        if "borrowing_log" in missing:
            reason = f"{reason} {cbk_problem}"
        return [unavailable_block("borrowing", title, reason, unblock)]
    if data["typed_log"]:
        warnings.append(f"Net domestic borrowing: the auction log typed under \"{analyst.FORM}\" is used instead of CBK's "
                        "auction results. It is analyst input; clear it to have the log built from CBK's results.")
        if data["redemptions"]:
            warnings.append(f"Net domestic borrowing: the \"{analyst.TABLES['borrowing_redemptions'].label}\" typed on the form "
                            "are not added to the typed auction log; a redemption belongs in that log as a row.")
        block = _typed_borrowing(inputs, week, data, log)
        return [block] + ([net_borrowing.log_block(log)] if usable and block["kind"] == "computed" else [])
    if usable:
        warnings.extend(log.warnings)
        difference = log.workbook_difference()
        if difference:
            warnings.append(difference)
        return _cbk_borrowing(inputs, data, log, bulletin)
    if data["redemptions"]:
        warnings.append(f"Net domestic borrowing: the \"{analyst.TABLES['borrowing_redemptions'].label}\" typed on the form "
                        f"are not added to the {WB.lower()}'s own log.")
    warnings.append(f"Net domestic borrowing: {cbk_problem} The {WB.lower()}'s own log is used instead, as analyst input.")
    return [_typed_borrowing(inputs, week, data, None)]


# ---------------------------------------------------------------------------
# The section
# ---------------------------------------------------------------------------

def compose_summary(blocks: list[dict[str, Any]], limit: int = 3000) -> str:
    """The section's summary for the CMS: its lead paragraphs, in order, never cut mid-paragraph."""
    lead = [b for b in blocks if b["kind"] in ("computed", "supplied") and b["id"].startswith(("tbills", "tbonds", "bidding_range"))]
    first_piece = next((b for b in blocks if b["kind"] == "narrative"), None)
    parts = [b["body_md"] for b in lead]
    if first_piece is not None:
        parts.append(first_piece.get("body_md", "").split("\n\n")[0])
    out: list[str] = []
    for p in parts:
        if p and sum(len(x) for x in out) + len(p) <= limit:
            out.append(p)
    return "\n\n".join(out)


def build_fixed_income_review(
    week_ending: Optional[date] = None,
    provider: Optional[NarrativeProvider] = None,
    today: Optional[date] = None,
    inputs: Optional[WeeklyInputs] = None,
    fetchers: Optional[Fetchers] = None,
    on_event: Optional[Observer] = None,
    draft: Optional[Callable[..., dict[str, Any]]] = None,
    inputs_root: Optional[Any] = None,
) -> CoordinatorReview:
    """Fetch what is published, read what was uploaded, work out the section, draft its highlights, check it.

    A missing input or a source that does not answer never fails the draft: the part that
    needed it is an ``unavailable`` block naming it.  Provider errors propagate, as in every
    section.
    """
    week = week_for(week_ending, today)
    inputs = inputs or WeeklyInputs(week, inputs_root)
    fetchers = fetchers or Fetchers()
    problems: list[str] = []
    warnings: list[str] = []

    bulletin = inputs.bulletin
    if bulletin is None:
        fetched = try_fetch(on_event, "CBK Weekly Bulletin", fetchers.bulletin, week.ending, problems=problems)
        if fetched is not None:
            try:
                store(week, CBK_BULLETIN, fetched[0], fetched[1].rsplit("/", 1)[-1], inputs.root, fetched_from=fetched[1])
                bulletin = cbk_bulletin.parse_bulletin(fetched[0])
            except Exception as exc:  # noqa: BLE001 - an unreadable bulletin is a missing input, not a failed draft
                problems.append(f"CBK Weekly Bulletin: {cbk_bulletin.refused(exc, fetched[0], week.ending)}")
    elif inputs.matches("cbk_bulletin.pdf") is False:
        warnings.append(f"The CBK Weekly Bulletin among this week's inputs is dated {bulletin.issue_date}, not "
                        f"{week.ending.isoformat()}; figures it does not print for this week are left out.")
    if bulletin is not None:   # a table left out is said once here, whatever each part that needed it goes on to say
        warnings.extend(bulletin.unavailable.values())
    rates = try_fetch(on_event, cbk_rates.SOURCE_NAME, fetchers.usd_rates, problems=problems)
    results = try_fetch(on_event, "CBK T-bond results", fetchers.tbonds, *week.value_date_window, problems=problems)
    issue = try_fetch(on_event, "Previous issue on cytonnreport.com", fetchers.previous_issue, week.ending,
                      inputs.notes.get("previous_issue"), problems=problems)

    wb_tbills = None
    if inputs.fi_book is not None:
        try:
            wb_tbills = fi_workbook.read_tbills(inputs.fi_book, week)
        except WorkbookError as exc:
            warnings.append(f"T-bills cross-check skipped: {exc}")
    tbill_inputs = _tbill_inputs(bulletin, week, wb_tbills) if bulletin is not None else None
    previous_inputs = WeeklyInputs(week.previous, inputs.root)

    blocks: list[dict[str, Any]] = [tbills_block(tbill_inputs, bulletin)]
    bond_blocks, bonds = tbonds_blocks(results, bulletin, week, problems)
    if results is not None and not bond_blocks:
        warnings.append(f"No Treasury bond auction settled between {week.value_date_window[0].isoformat()} and "
                        f"{week.value_date_window[1].isoformat()}, so there are no results to report.")
    blocks += bond_blocks
    blocks.append(bidding_range_block(inputs, bonds))
    blocks += money_market_blocks(inputs, tbill_inputs, week, previous_inputs, warnings)
    blocks.append(liquidity_block(inputs, bulletin, week, warnings))
    blocks += eurobond_blocks(inputs, bulletin, week, warnings)
    blocks += shilling_blocks(inputs, bulletin, rates, week, issue, warnings)

    drafted = (draft or draft_pieces)(BRIEFS, N_HIGHLIGHTS, provider=provider, today=today,
                                      window=(week.ending - timedelta(days=6), week.ending), on_event=on_event)
    blocks += [narrative_block(f"highlight_{p['brief_id']}", p) for p in drafted["pieces"]]
    blocks.append(_carried(issue, "outlook", "Rates and outlook (closing paragraph)", outlook_text))
    fy_start = inputs.analyst.borrowing()["fy_start"].day
    releases = try_fetch(on_event, net_borrowing.SOURCE_NAME, fetchers.releases, fy_start, week.value_date_window[1],
                         inputs.results_dir, problems=problems)
    blocks += borrowing_blocks(inputs, week, releases, warnings, bulletin)

    content = {
        "section": SECTION, "title": TITLE, "week_ending": week.ending.isoformat(),
        "week_start": drafted["week_start"], "week_end": drafted["week_end"],
        "blocks": numbered(blocks), "pieces_found": len(drafted["pieces"]), "pieces_expected": N_HIGHLIGHTS,
        "shortfall": drafted["shortfall"],
        "warnings": list(drafted["warnings"]) + warnings + inputs.analyst.difference_lines() + problems,
        "chart_notes": list(CHARTS), "chart_reference": CHART_REFERENCE, "chart_after": CHART_AFTER,
        "summary": compose_summary(blocks),
    }
    report_blocks(on_event, content)
    return build_review(content, check_section(content, on_event))
