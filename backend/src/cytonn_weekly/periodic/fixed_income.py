"""Fixed Income in the quarterly, half-year and annual Markets Reviews.

Real structure (Q3'2026, H1'2026 and FY'2025 read 2026-10-05): the period's T-bill
auctions with charts, "Primary T-Bond Auctions in <period>" with the "Bond Issuances in
<period>" table, Secondary Bond Market Activity (Bond Turnover, Yield Curve), Money
Market Performance with the MMF yields table, Liquidity, Kenya Eurobonds (table),
the week's highlights, and "<period> Notable Highlights".  The review replaces that
week's Cytonn Weekly, so the week's T-bill, money-market and liquidity paragraphs ride
inside it too.

Built here: the Bond Issuances table, from CBK's own results PDFs (cbk_auctions), and
the period's notable highlights, drafted with citations.  Everything else is a stub.

The Bond Issuances table, as the three issues lay it out (and where they disagree):

* one row per bond, newest auction first; the auction's date, offer and subscription rate
  are printed once per auction (merged cells), every other figure per bond.  The screen
  cannot merge cells, so the date repeats on each of the auction's rows (it names the
  auction), while the offer and subscription stay on its first row only, "-" below them;
* columns, verbatim from Q3'2026: Issue Date, Bond Auctioned, Effective Tenor to Maturity
  (Years), Coupon, Amount offered (Kshs bn), Actual Amount Raised/Accepted (Kshs bn), Total
  bids received (Subscription), Average Accepted Yield, Subscription Rate, Acceptance Rate;
* switch auctions: Q3'2026 lists them ("FXD4/2019/010-Switch"), Q1'2026 and H1'2026 leave
  them out, and all three leave them out of the totals (Q3'2026's "Total" offer of 380.0
  and "Average" tenor of 15.6 only reconcile without its three switches);
* tap sales are listed ("-Tap Sale", CBK's own term) and counted; switches are listed and
  not counted; buybacks are neither (cbk_auctions.fetch_period_tbonds leaves them out).
  Checked 2026-10-06 against CBK's PDFs for five printed periods
  (tests/fixtures/sources/cbk_tbond_periods_captured_2026-10-06.json): counting tap sales
  reproduces the Totals of Q3'2025 (250.0 / 405.3 / 713.1, in the Q3'2025 issue, which lists
  the 25-08-2025 IFB tap as two "-Tapsale" rows, and again in the Q3'2026 issue), of Q3'2024
  (145.0 / 150.3 / 199.3, two taps) and the offer and accepted amount of H1'2025 (335.0 /
  464.1, one tap).  H1'2026 is the exception and is inconsistent with itself: its text says
  one bond was issued on tap sale, its table has no tap row, and its Totals (460.0 / 510.0 /
  781.1) are its nine primary auctions alone, where CBK lists two June 2026 tap sales
  (counted: 495.0 / 547.6 / 820.9).  The rule stays "counts tap sales"; the question is open
  for the analysts;
* "Total" sums offer, accepted and bids; "Average" is the plain mean of tenor, coupon and
  yield, while its subscription and acceptance rates are ratios of the totals (H1'2026:
  781.1 / 460.0 = 169.8%, 510.0 / 781.1 = 65.3%), each with the same rows for the same
  period a year earlier;
* Issue Date: the issues print CBK's results-signing date for most primary auctions
  (22/07/2026 for the bond CBK dates 27-07-2026) but the value date for others (21/09/2026,
  and most switches), and Q1/H1 use month-first dates (6/17/2026) where Q3 is day-first.
  This table prints CBK's value date, the bond's actual issue date, day-first as in Q3;
* precision 1 dp throughout (the issues print yields variously as "14%", "12.8%" and bids
  as "166.22"; 1 dp is the dominant form);
* "-Reopened" is not appended: CBK's PDF does not say whether an issue is new or reopened.

The issues' own figures do not always match CBK's PDFs (Q3'2026: the 26-08 switch's 22.5
accepted against CBK's 21,815.85m; the SDB1/2011/030 yield of 13.8% against CBK's
13.6942; the 13-07 auction's subscription of 178.3% against CBK's 144,466.60 / 70,000.00).
The checker compares this table with CBK, so those would not be copied.
"""

from __future__ import annotations

from datetime import date
from statistics import fmean
from typing import Any, Callable, Optional

from cytonn_weekly.common.formatting import NUMBER, PCT, TEXT
from cytonn_weekly.common.review import build_review, check_section, narrative_block, table_block
from cytonn_weekly.common.run_events import SOURCE_FAILED, Observer, emit, fetch_source, report_blocks
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview
from cytonn_weekly.fixed_income import cbk_auctions, kcb_email, mmf
from cytonn_weekly.narrative.base import NarrativeProvider
from cytonn_weekly.periodic.common import PeriodContext, Stub, compose, draft_period, period_brief
from cytonn_weekly.report_types import ANNUAL, HALF_YEAR, QUARTERLY, period_window

SECTION = "fixed_income"
TITLE = "Fixed Income"
N_HIGHLIGHTS = 2
CBK_RESULTS = "Central Bank of Kenya (CBK) T-bond auction results"  # the source, as a run's events name it

ISSUANCE_COLUMNS = [
    {"key": "issue_date", "label": "Issue Date", "fmt": TEXT},
    {"key": "bond", "label": "Bond Auctioned", "fmt": TEXT},
    {"key": "years_to_maturity", "label": "Effective Tenor to Maturity (Years)", "fmt": NUMBER, "decimals": 1},
    {"key": "coupon_pct", "label": "Coupon", "fmt": PCT, "decimals": 1},
    {"key": "offered_kes_bn", "label": "Amount offered (Kshs bn)", "fmt": NUMBER, "decimals": 1},
    {"key": "accepted_kes_bn", "label": "Actual Amount Raised/Accepted (Kshs bn)", "fmt": NUMBER, "decimals": 1},
    {"key": "bids_kes_bn", "label": "Total bids received (Subscription)", "fmt": NUMBER, "decimals": 1},
    {"key": "avg_rate_pct", "label": "Average Accepted Yield", "fmt": PCT, "decimals": 1},
    {"key": "subscription_pct", "label": "Subscription Rate", "fmt": PCT, "decimals": 1},
    {"key": "acceptance_pct", "label": "Acceptance Rate", "fmt": PCT, "decimals": 1},
]

CHARTS = {
    QUARTERLY: (
        "91-Day T-Bill Yield Growth (bps)",
        "Domestic Borrowing (Kshs bn)",
        "T-Bills Subscription Rates",
        "Secondary Market Bond Turnover (Kshs bn)",
        "Yield Curve (%)",
        "Money Market Performance (end of the quarter against a year earlier)",
        "Money Market Performance (the week)",
        "Interbank rates",
    ),
    HALF_YEAR: (
        "91-Day T-Bill Yield growth (bps)",
        "Government domestic borrowing against target (no caption in the text layer)",
        "T-Bills Subscription Rates",
        "Secondary Market Bond Turnover (Kshs bn)",
        "Yield Curve (%)",
        "Money Market Performance (end of the half against a year earlier)",
        "Money Market Performance (the week)",
        "Interbank rates",
    ),
    ANNUAL: (
        "T-Bill Yield Growth (bps)",
        "T-Bills Subscription Rates",
        "Secondary Market Bond Turnover (Kshs bn)",
        "Yield Curve",
        "Money Market Performance",
        "Interbank rates",
        "Kenya Eurobond Yields (2018, 2019, 2021 and 2024 issues, one chart each)",
    ),
}

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

# Tested 2026-10-06 against CBK's weekly results for two printed quarters (the figures are in
# tests/fixtures/sources/cbk_tbill_q3_2025_q3_2026_captured_2026-10-06.json, the comparison in
# tests/test_fixed_income.py).  Several yield methods tie, so by the project's rule the tool does
# not choose one and the part stays a stub.
TBILLS_BLOCKED_REASON = (
    "The period's T-bill paragraph aggregates every weekly auction and compares it with the same period a year "
    "earlier. Tested against CBK's weekly results for Q3'2026 and Q3'2025 (2026-10-06): the amounts and rates "
    "are settled, the average yields are not. The 13 auctions with a value date inside the quarter, with each "
    "rate taken as a ratio of sums (bids over the summed weekly offers, accepted over bids), reproduce every "
    "printed figure of both quarters exactly (Q3'2026: subscription 163.9% overall, 319.2%, 128.0% and 80.4% by "
    "tenor, acceptance 83.1%, bids Kshs 590.1 bn, accepted Kshs 490.2 bn; Q3'2025: 110.6%, 174.6%, 59.6%, "
    "136.1%, acceptance 89.5%). The average yields tie: a plain mean of the weekly average accepted rates, a "
    "mean weighted by the amount accepted and a mean weighted by the bids received all round to the printed "
    "8.8%, 8.9%, 9.0% (Q3'2026) and 8.0%, 8.2%, 9.6% (Q3'2025), differing only in the second decimal place, so "
    "two printed quarters cannot tell them apart and picking one would be a guess."
)
TBILLS_UNBLOCK = (
    "The Fixed Income analysts confirming how the period's average yield is taken (a plain mean of the weekly "
    "rates, accepted-weighted or bid-weighted); the amounts, subscription and acceptance rates then come from "
    "cbk_auctions.parse_tbill_results run over the period's weekly results, which already reproduces them."
)

SECONDARY_BLOCKED_REASON = (
    "Bond turnover and the yield curve come from NSE secondary-market statistics; which NSE publication "
    "the analysts read has not been confirmed and no machine-readable source has been verified. The issues "
    "print no source line under the bond turnover chart or the yield curve chart (Q3'2026 and H1'2026, read "
    "2026-10-06)."
)
SECONDARY_UNBLOCK = (
    "The analysts naming where the turnover and yield curve figures come from (the NSE publication, or the KCB "
    "daily email, which carries secondary-market activity), then a parser written against a real sample."
)

LIQUIDITY_BLOCKED_REASON = (
    "Liquidity (the interbank rate and volumes) and the rest of the week's Fixed Income paragraphs are "
    "drafted from KCB's daily email in the weekly report. " + kcb_email.BLOCKED_REASON
)
LIQUIDITY_UNBLOCK = kcb_email.UNBLOCK

EUROBONDS_BLOCKED_REASON = (
    "The Kenya Eurobonds Performance table gives each issue's yield over time. Its source line reads \"Central "
    "Bank of Kenya (CBK)\" and names no page or file; CBK's daily Eurobond yield publication has not been "
    "located and inspected, so its layout is unknown."
)
EUROBONDS_UNBLOCK = (
    "The analysts naming which CBK page or file they take Kenya's Eurobond yields from, then a parser for a real "
    "sample."
)


def fetch_period_tbill_summary(ctx: PeriodContext) -> Any:
    # TODO: needs the yield-averaging basis confirmed (TBILLS_UNBLOCK) before the aggregation is written.
    raise NotImplementedError(TBILLS_BLOCKED_REASON)


def fetch_secondary_market(ctx: PeriodContext) -> Any:
    # TODO: needs the NSE (or KCB) secondary-market source identified and a real sample (SECONDARY_UNBLOCK).
    raise NotImplementedError(SECONDARY_BLOCKED_REASON)


def fetch_liquidity(ctx: PeriodContext) -> Any:
    # TODO: waits on the KCB email extraction (fixed_income/kcb_email.py).
    raise NotImplementedError(LIQUIDITY_BLOCKED_REASON)


def fetch_kenya_eurobonds(ctx: PeriodContext) -> Any:
    # TODO: needs CBK's Eurobond yield publication located and a real sample (EUROBONDS_UNBLOCK).
    raise NotImplementedError(EUROBONDS_BLOCKED_REASON)


STUBS = (
    Stub("tbills", "T-Bills primary auctions over the period", TBILLS_BLOCKED_REASON, TBILLS_UNBLOCK,
         fetch_period_tbill_summary),
    Stub("secondary_market", "Secondary Bond Market Activity: Bond Turnover and Yield Curve", SECONDARY_BLOCKED_REASON,
         SECONDARY_UNBLOCK, fetch_secondary_market),
    Stub("money_market_funds", "Money Market Performance: Money Market Fund Yields table", mmf.BLOCKED_REASON,
         mmf.UNBLOCK, mmf.fetch_mmf_yields),
    Stub("liquidity", "Liquidity, and the week's T-bill and money market paragraphs", LIQUIDITY_BLOCKED_REASON,
         LIQUIDITY_UNBLOCK, fetch_liquidity),
    Stub("kenya_eurobonds", "Kenya Eurobonds Performance", EUROBONDS_BLOCKED_REASON, EUROBONDS_UNBLOCK,
         fetch_kenya_eurobonds),
)

# ---------------------------------------------------------------------------
# Bond Issuances table
# ---------------------------------------------------------------------------


def _dmy(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def issuance_rows(auctions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One source row per bond (the per-auction offer and subscription on the auction's first row only)."""
    rows: list[dict[str, Any]] = []
    for a in auctions:
        if a.get("error"):
            rows.append({"key": f"{a['value_date']} auction", "label": f"Auction dated {_dmy(a['value_date'])}",
                         "issue_date": _dmy(a["value_date"]), "bond": None, "error": f"{a['error']} ({a['url']})"})
            continue
        bonds = a["rows"]
        sub = a.get("total_subscription_pct")
        if sub is None and len(bonds) == 1:
            sub = bonds[0]["subscription_pct"]  # a one-bond auction prints no total column
        for i, r in enumerate(bonds):
            name = r["issue"] + {"switch": "-Switch", "tap": "-Tap Sale"}.get(a["kind"], "")
            rows.append({
                "key": f"{a['value_date']} {r['issue']}", "label": f"{name} ({_dmy(a['value_date'])})",
                "issue_date": _dmy(a["value_date"]), "bond": name,
                "years_to_maturity": r.get("years_to_maturity"), "coupon_pct": r["coupon_pct"],
                "offered_kes_bn": a["total_offered_kes_bn"] if i == 0 else None,
                "accepted_kes_bn": r["accepted_kes_bn"], "bids_kes_bn": r["bids_kes_bn"], "avg_rate_pct": r["avg_rate_pct"],
                "subscription_pct": sub if i == 0 else None, "acceptance_pct": r.get("acceptance_pct"),
                "kind": a["kind"], "source_url": a["url"], "error": r.get("error"),
            })
    return rows


def _ratio(num: float, den: float) -> Optional[float]:
    return num / den * 100 if den else None


def summary_rows(period: str, auctions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """The "<period> Total" and "<period> Average" rows: primary auctions and tap sales, never switches.

    If any counted auction's PDF could not be read, both rows carry an error instead of
    figures (the checker flags them): a sum over the readable auctions alone would be
    wrong, yet would match its own source exactly and check clean.
    """
    counted = [a for a in auctions if a["kind"] in ("primary", "tap")]
    unread = [a for a in counted if a.get("error")]
    if unread:
        dated = ", ".join(_dmy(a["value_date"]) for a in unread)
        error = (f"{len(unread)} of {len(counted)} {period} auction results PDF(s) could not be read (dated {dated}), "
                 f"so the {period} totals would be incomplete")
        return [{"key": f"{period} {kind}", "label": f"{period} {kind.title()}", "issue_date": f"{period} {kind.title()}",
                 "bond": "", "error": error} for kind in ("total", "average")], []
    primary = counted
    bonds = [r for a in primary for r in a["rows"]]
    warnings: list[str] = []
    if not bonds:
        return [], [f"no primary T-bond auction results found for {period}; its Total and Average rows are left out"]
    offered = sum(a["total_offered_kes_bn"] or 0 for a in primary)
    accepted = sum(r["accepted_kes_bn"] or 0 for r in bonds)
    bids = sum(r["bids_kes_bn"] or 0 for r in bonds)
    tenors = [r["years_to_maturity"] for r in bonds if r.get("years_to_maturity") is not None]
    if len(tenors) < len(bonds):
        missing = ", ".join(r["issue"] for r in bonds if r.get("years_to_maturity") is None)
        warnings.append(f"{period} Average tenor is over {len(tenors)} of {len(bonds)} bonds: CBK printed no remaining "
                        f"life for {missing}")
    total = {"key": f"{period} total", "label": f"{period} Total", "issue_date": f"{period} Total", "bond": "",
             "offered_kes_bn": offered, "accepted_kes_bn": accepted, "bids_kes_bn": bids, "error": None}
    average = {"key": f"{period} average", "label": f"{period} Average", "issue_date": f"{period} Average", "bond": "",
               "years_to_maturity": fmean(tenors) if tenors else None,
               "coupon_pct": fmean(r["coupon_pct"] for r in bonds if r["coupon_pct"] is not None),
               "avg_rate_pct": fmean(r["avg_rate_pct"] for r in bonds if r["avg_rate_pct"] is not None),
               "subscription_pct": _ratio(bids, offered), "acceptance_pct": _ratio(accepted, bids), "error": None}
    # A figure built from every bond or auction must say so when an input was missing and left out:
    # it matches its own derivation exactly, so only this keeps the checker from reading it clean.
    total["incomplete"] = _incomplete("total", {"accepted_kes_bn": ("accepted_kes_bn", bonds, "bonds"),
                                                "bids_kes_bn": ("bids_kes_bn", bonds, "bonds"),
                                                "offered_kes_bn": ("total_offered_kes_bn", primary, "auctions")})
    average["incomplete"] = _incomplete("average", {
        "years_to_maturity": ("years_to_maturity", bonds, "bonds"), "coupon_pct": ("coupon_pct", bonds, "bonds"),
        "avg_rate_pct": ("avg_rate_pct", bonds, "bonds"),
        "subscription_pct": ("bids_kes_bn", bonds, "bonds"), "acceptance_pct": ("accepted_kes_bn", bonds, "bonds")})
    return [total, average], warnings


def _incomplete(what: str, parts: dict[str, tuple[str, list[dict[str, Any]], str]]) -> dict[str, str]:
    """{figure: reason} for every figure with an input left out.

    ``parts`` maps a figure to (the input's key, every input, what an input is called).  The
    reason reads like "average of 9 of 12 bonds: no years_to_maturity for FXD1/2022/010, ...".
    """
    out: dict[str, str] = {}
    for figure, (key, inputs, noun) in parts.items():
        left_out = [x for x in inputs if x.get(key) is None]
        if left_out:
            names = ", ".join(x.get("issue") or x.get("value_date") or "?" for x in left_out)
            out[figure] = f"{what} of {len(inputs) - len(left_out)} of {len(inputs)} {noun}: no {key} for {names}"
    return out


def issuance_table(ctx: PeriodContext, fetch: Callable[[date, date], dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """The "Bond Issuances in <period>" table block, with this period's and last year's summary rows."""
    current = fetch(ctx.start, ctx.end)
    ago_start, ago_end = period_window(ctx.report_type, ctx.year_ago)
    ago = fetch(ago_start, ago_end)
    rows = issuance_rows(current["auctions"])
    now_rows, warnings = summary_rows(ctx.period, current["auctions"])
    ago_rows, ago_warnings = summary_rows(ctx.year_ago, ago["auctions"])
    # The issues print the summary rows in this order: both Totals, then both Averages.
    rows += [r for r in now_rows + ago_rows if r["key"].endswith("total")]
    rows += [r for r in now_rows + ago_rows if r["key"].endswith("average")]
    if any(a.get("error") for a in current["auctions"]):
        warnings.append(f"some {ctx.period} CBK results PDFs could not be read; see the flagged rows")
    if any(a.get("error") for a in ago["auctions"]):
        warnings.append(f"some {ctx.year_ago} CBK results PDFs could not be read, so the {ctx.year_ago} Total and "
                        "Average rows are flagged rather than summed from the rest")
    block = table_block("bond_issuances", f"Bond Issuances in {ctx.prose}", ISSUANCE_COLUMNS, rows, "key", "label",
                        {"name": "Central Bank of Kenya (CBK)", "url": current["listing_url"],
                         "as_of": ctx.end.isoformat()})
    return block, warnings + ago_warnings


def briefs(ctx: PeriodContext):
    return [
        period_brief(ctx, "monetary_policy", TITLE, "Monetary Policy Committee",
                     "a Central Bank of Kenya Monetary Policy Committee decision on the Central Bank Rate, with the "
                     "reasons the CBK gave", preferred_domains=("centralbank.go.ke",)),
        period_brief(ctx, "public_debt", TITLE, "Government borrowing and public debt",
                     "a National Treasury or Central Bank of Kenya development in government domestic or external "
                     "borrowing (bond programme, Eurobond issue or buyback, borrowing target)",
                     preferred_domains=("treasury.go.ke", "centralbank.go.ke")),
    ]


def build_fixed_income_review(
    ctx: PeriodContext,
    provider: Optional[NarrativeProvider] = None,
    fetch_tbonds: Callable[[date, date], dict[str, Any]] = cbk_auctions.fetch_period_tbonds,
    on_event: Optional[Observer] = None,
) -> CoordinatorReview:
    """The period's bond table from CBK, the notable highlights drafted with citations, every other part a stub.

    ``on_event`` (common/run_events.py) is told each step as it happens: each period's CBK
    fetch, and each results PDF in it that could not be read.
    """

    def observed_fetch(start: date, end: date) -> dict[str, Any]:
        result = fetch_source(on_event, f"{CBK_RESULTS} dated {_dmy(start.isoformat())} to {_dmy(end.isoformat())}",
                              fetch_tbonds, start, end)
        for a in result["auctions"]:
            if a.get("error"):
                emit(on_event, SOURCE_FAILED, f"CBK results PDF dated {_dmy(a['value_date'])}",
                     detail=" ".join(str(a["error"]).split()))
        return result

    table, warnings = issuance_table(ctx, fetch_tbonds if on_event is None else observed_fetch)
    draft = draft_period(briefs(ctx), N_HIGHLIGHTS, ctx, provider, on_event)
    stubs = {s.id: s.block() for s in STUBS}
    blocks = [stubs["tbills"], table, stubs["secondary_market"], stubs["money_market_funds"], stubs["liquidity"],
              stubs["kenya_eurobonds"]]
    blocks += [narrative_block(f"highlight_{p['brief_id']}", p) for p in draft["pieces"]]
    content = compose(SECTION, TITLE, ctx, blocks, draft=draft, expected=N_HIGHLIGHTS, warnings=warnings,
                      charts=CHARTS)
    report_blocks(on_event, content)
    return build_review(content, check_section(content, on_event))
