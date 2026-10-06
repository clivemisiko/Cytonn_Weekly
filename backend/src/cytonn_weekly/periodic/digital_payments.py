"""Digital Payments in the quarterly and half-year Markets Reviews (the annual review has none).

Real structure: Q3'2026 and H1'2026 carry the week's highlights exactly as the weekly
does ("During the week, Visa ..."), the "Digital Payments NYSE and LSE stock
performance" table with period columns, then "Other notable digital payments sector
highlights during the month of September 2026" (H1: "... during H1'2026").  The FY'2025
annual review has no Digital Payments section: it predates the section, which first ran
in May 2026.

The week's highlights reuse the weekly drafter unchanged (IR-first, four companies).
The table is block-shaped here, so its period columns can be added without touching the
weekly table the Word summary reads.  Its columns, verified against the issues' own
figures with Yahoo Finance closes (2026-10-05, and again cell by cell on 2026-10-06; the
printed tables and the closes are in tests/fixtures/sources/cytonn_dp_period_tables_2026-10-06.json):

* Q3'2026: Year Open 2026 | Price 6/30/2026 | Price 8/03/2026 | Price 9/25/2026 | Price
  9/30/2026 | Price 10/03/2026 | w/w | m/m | Q/Q | YTD | Forward P/E.  The 6/30 and 9/30
  columns are the closes on the quarter's eve and last day (Visa 343.1 and 359.3, Mastercard
  513.6 and 551.5, as printed), and Q/Q is the one from the other (American Express 338.3 to
  304.1: (10.1%), as printed): the quarter-end close over the previous quarter-end close,
  minus 1.  All seven printed rows follow that, and w/w = 10/03 over 9/25, YTD = 10/03 over
  Year Open, m/m = 10/03 over 8/03.  "Price 10/03/2026" is a Saturday: the prices printed
  under it are the Friday 2 October closes (American Express 302.78, Visa 360.66), so this
  table, which labels a price column with the date of the close it holds, heads it
  "Price 10/02/2026".  "Price 8/03/2026" is the 3 August close (Visa 365.7, which the issue
  misprints as 3665.7, giving its "(90.2%)" m/m), two months before the issue, so that
  column's basis is a stub, not a guessed "a month ago".
* H1'2026: Year Open 2026 | Price 6/26/2026 | Price 6/30/2026 | Price 7/3/2026 | HY'2026
  change | w/w | YTD | P/E.  The issue printed two of its change columns with the ratio
  upside down: its "HY'2026 change" is Year Open over the 6/30 price, minus 1 (American
  Express 372.7 / 338.3 - 1 = 10.2%), and its w/w is the 6/26 price over the 7/3 price, minus
  1 ((3.3%)), for all six companies.  Its YTD is the right way up.  This table prints the
  half-year change the right way up, the 6/30 close over Year Open, minus 1 (American
  Express (9.2%) from the issue's printed 1 dp prices, (9.3%) from the unrounded closes, which
  is what this table prints), so it differs from the printed H1'2026 column by design
  (KNOWN_PRINTED_ERRORS, and the warning the review carries).  ("Price 7/3/2026" holds the
  2 July closes: 3 July 2026 was a market holiday.)

Year Open, the week-ago price, the current price, w/w, YTD and Forward P/E come from the
weekly fetcher, on its basis.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable, Optional

from cytonn_weekly.common.formatting import MULTIPLE, PCT, PRICE, TEXT, pct_change
from cytonn_weekly.common.review import build_review, check_section, narrative_block, table_block
from cytonn_weekly.common.run_events import Observer, fetch_source, report_blocks, report_failed_rows
from cytonn_weekly.digital_payments import fetcher as dp_fetcher
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview
from cytonn_weekly.digital_payments.highlights import N_HIGHLIGHTS, draft_highlights
from cytonn_weekly.digital_payments.providers.base import DraftingProvider
from cytonn_weekly.narrative.base import NarrativeProvider
from cytonn_weekly.narrative.drafter import draft_pieces
from cytonn_weekly.periodic.common import PeriodContext, Stub, compose, period_brief
from cytonn_weekly.report_types import HALF_YEAR, QUARTERLY

SECTION = "digital_payments"
TITLE = "Digital Payments"
TABLE_TITLE = "Digital Payments NYSE and LSE stock performance"
SOURCE_NAME = "Yahoo Finance"

History = Callable[[str, date, date], list[tuple[date, float]]]

CHARTS: dict[str, tuple[str, ...]] = {}  # neither issue has a Digital Payments chart

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

MONTH_CHANGE_BLOCKED_REASON = (
    "In the Q3'2026 issue the m/m column compares the 10/03/2026 price with a price it labels 8/03/2026 (all "
    "seven printed rows are the one over the other, minus 1). That is the 3 August close, two months before the "
    "issue, not one, so the base looks stale (and Visa's 8/03 price is misprinted as 3665.7, which gives its "
    "printed (90.2%)). The weekly issues print no m/m column (checked: #37.2026 and #38.2026), so nothing else "
    "settles what a \"month\" change is measured from."
)
MONTH_CHANGE_UNBLOCK = (
    "The Digital Payments analyst confirming the intended m/m base (the close a month before the issue's last "
    "price, the previous month end, or another date)."
)


def fetch_month_change(ctx: PeriodContext) -> Any:
    # TODO: needs the m/m base date confirmed (MONTH_CHANGE_UNBLOCK).
    raise NotImplementedError(MONTH_CHANGE_BLOCKED_REASON)


STUBS = (
    Stub("month_change", "Stock table: m/m change column", MONTH_CHANGE_BLOCKED_REASON, MONTH_CHANGE_UNBLOCK,
         fetch_month_change),
)
# The stubbed column of each report type's table, if it has one (the half-year table has none).
_STUB_FOR = {QUARTERLY: "month_change", HALF_YEAR: None}

# ---------------------------------------------------------------------------
# Where a published issue is known to be wrong
# ---------------------------------------------------------------------------

# The one documented exception to "this table reproduces the issue": a column the issue printed
# with its ratio upside down.  The tool's figure is still exact-matched against its own source
# (the Yahoo closes), like every other figure; what it must never be compared with is the printed
# column, and a test that finds them different is reading a published error, not a regression.
# {(report type, period): {column key: what the issue printed, with one worked example}}
KNOWN_PRINTED_ERRORS: dict[tuple[str, str], dict[str, str]] = {
    (HALF_YEAR, "H1'2026"): {
        "period_pct": "ratio inverted (Year Open over the 6/30/2026 price, minus 1): American Express printed "
                      "10.2%, correct (9.2%)",
        "wow_pct": "ratio inverted (the 6/26/2026 price over the 7/3/2026 price, minus 1): American Express "
                   "printed (3.3%), correct 3.4%",
    },
}

HALF_CHANGE_WARNING = (
    "HY change column: Cytonn's H1'2026 issue printed this column with the ratio inverted (American Express "
    "printed +10.2%, correct -9.2% from the issue's own printed prices), so this table's figures, the half-year "
    "end close over Year Open minus 1, differ from that issue by design."
)

# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------


def yahoo_history(ticker: str, start: date, end: date) -> list[tuple[date, float]]:
    """Unadjusted daily closes from Yahoo Finance, ``start``..``end`` inclusive (as the weekly fetcher reads them)."""
    import yfinance as yf

    hist = yf.Ticker(ticker).history(start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(),
                                     auto_adjust=False)
    if hist is None or hist.empty:
        return []
    hist = hist.dropna(subset=["Close"])
    return [(ts.date(), float(c)) for ts, c in zip(hist.index, hist["Close"])]


def close_on_or_before(series: list[tuple[date, float]], day: date) -> Optional[tuple[date, float]]:
    before = [(d, c) for d, c in series if d <= day]
    return before[-1] if before else None


def _label(d: Optional[date]) -> str:
    """A price column's date as the table prints it: month first, day padded ("9/25/2026", "8/03/2026")."""
    return f"{d.month}/{d.day:02d}/{d.year}" if d else "?"


def period_rows(ctx: PeriodContext, base: list[dict[str, Any]], history: History) -> tuple[list[dict[str, Any]], list[str]]:
    """The weekly fetcher's rows plus the closes on the period's eve and last day, and the period change.

    The period change is the period-end close over its base, minus 1.  Quarterly (Q/Q): the base
    is the previous quarter-end close (Q3'2026: 9/30 against 6/30, as the issue prints it; the
    same rule for Q1, whose base is the 31 December close).  Half-year (HY change): the base is
    Year Open, the weekly fetcher's own (the close of the year's first trading day), which is
    what the H1'2026 issue's column compares, the right way up (KNOWN_PRINTED_ERRORS).
    """
    eve = ctx.start - timedelta(days=1)
    rows, warnings = [], []
    for b in base:
        row = {k: b.get(k) for k in ("company", "ticker", "ytd_open", "prior_close", "prior_close_date",
                                      "current_price", "current_price_date", "wow_pct", "ytd_pct", "forward_pe")}
        row["error"] = b.get("error")
        row.update(period_start_close=None, period_start_date=None, period_end_close=None, period_end_date=None,
                   period_pct=None)
        if not row["error"]:
            try:
                series = history(b["ticker"], eve - timedelta(days=10), ctx.end)
                start, end = close_on_or_before(series, eve), close_on_or_before(series, ctx.end)
                if ctx.report_type == HALF_YEAR:
                    # The half-year table neither prints nor uses the close on the period's eve (31 December).
                    start = None
                    if end is None or end[0] < ctx.start:
                        raise ValueError(f"no close in the period on or before {ctx.end}")
                    base_close = row["ytd_open"]
                elif start is None or end is None:
                    raise ValueError(f"no close on or before {eve if start is None else ctx.end}")
                else:
                    base_close = start[1]
                if start is not None:
                    row.update(period_start_date=start[0].isoformat(), period_start_close=start[1])
                row.update(period_end_date=end[0].isoformat(), period_end_close=end[1],
                           period_pct=pct_change(end[1], base_close))
            except Exception as exc:  # noqa: BLE001 - one ticker's failure is that row's, not the table's
                row["error"] = f"period prices unavailable: {type(exc).__name__}: {exc}"
        rows.append(row)
    if any(r["error"] for r in rows):
        warnings.append("some companies' prices could not be fetched; their rows are flagged")
    return rows, warnings


def _first(rows: list[dict[str, Any]], key: str) -> Optional[date]:
    found = [r[key] for r in rows if r.get(key)]
    return date.fromisoformat(max(set(found), key=found.count)) if found else None


def columns(ctx: PeriodContext, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The table's columns for this report type, price columns labelled with the dates they hold."""
    price = {"fmt": PRICE, "decimals": 1}
    year = ctx.end.year
    cols = [{"key": "company", "label": "Company", "fmt": TEXT},
            {"key": "ytd_open", "label": f"Year Open {year}", **price}]
    if ctx.report_type == QUARTERLY:
        cols.append({"key": "period_start_close", "label": f"Price {_label(_first(rows, 'period_start_date'))}", **price})
    cols += [{"key": "prior_close", "label": f"Price {_label(_first(rows, 'prior_close_date'))}", **price},
             {"key": "period_end_close", "label": f"Price {_label(_first(rows, 'period_end_date'))}", **price},
             {"key": "current_price", "label": f"Price {_label(_first(rows, 'current_price_date'))}", **price}]
    if ctx.report_type == HALF_YEAR:  # H1'2026 prints it before w/w: "HY'2026 change | w/w change | YTD change"
        cols.append({"key": "period_pct", "label": f"HY\u2019{year} change", "fmt": PCT, "decimals": 1,
                     "note": HALF_CHANGE_WARNING})
    cols.append({"key": "wow_pct", "label": "w/w change", "fmt": PCT, "decimals": 1})
    if ctx.report_type == QUARTERLY:
        cols.append({"key": "period_pct", "label": "Q/Q change", "fmt": PCT, "decimals": 1})
    cols += [{"key": "ytd_pct", "label": "YTD change", "fmt": PCT, "decimals": 1},
             {"key": "forward_pe", "label": "Forward P/E" if ctx.report_type == QUARTERLY else "P/E",
              "fmt": MULTIPLE, "decimals": 1}]
    return cols


def _highlight_piece(h: dict[str, Any]) -> dict[str, Any]:
    """A weekly highlight as a narrative block's piece (same claims, links and drafted_by)."""
    return {"brief_id": h["company"].lower().replace(" ", "_"), "topic": h["company"], "headline": h["headline"],
            "body": h["body"], "body_md": h["body_md"], "links": h["links"], "claims": h["claims"],
            "warnings": h["warnings"], "search_scope": h["search_scope"], "preferred_domains": [h.get("ir_domain")],
            "drafted_by": h["drafted_by"]}


def other_highlights_brief(ctx: PeriodContext):
    month = date(ctx.end.year, ctx.end.month, 1)
    label = f"the month of {ctx.end:%B %Y}" if ctx.report_type == QUARTERLY else ctx.prose
    brief = period_brief(ctx, "other_highlights", TITLE, "Other notable digital payments sector highlights",
                         "notable developments in the global digital payments sector beyond the four tracked "
                         "companies' own news (stablecoin regulation, payment-network partnerships, fintech "
                         f"licensing), during {label}", words=(100, 220))
    window = (month, ctx.end) if ctx.report_type == QUARTERLY else ctx.window
    return brief, window


def build_digital_payments_review(
    ctx: PeriodContext,
    provider: Optional[DraftingProvider] = None,
    narrative_provider: Optional[NarrativeProvider] = None,
    fetch_table: Callable[[Optional[date]], list[dict[str, Any]]] = dp_fetcher.fetch_digital_payments,
    history: History = yahoo_history,
    on_event: Optional[Observer] = None,
) -> CoordinatorReview:
    """The week's four highlights, the period stock table, the month's other highlights; the quarterly m/m column a stub.

    ``on_event`` (common/run_events.py) is told each step as it happens: the weekly price
    fetch, then each company's price history over the period.
    """
    if ctx.report_type not in _STUB_FOR:
        raise ValueError(f"the {ctx.report_title} has no Digital Payments section")

    def observed_history(ticker: str, start: date, end: date) -> list[tuple[date, float]]:
        return fetch_source(on_event, f"{SOURCE_NAME}: {ticker} price history", history, ticker, start, end)

    week = draft_highlights(provider=provider, today=ctx.today, on_event=on_event)
    base = fetch_source(on_event, SOURCE_NAME, fetch_table, ctx.today)
    report_failed_rows(on_event, base, lambda r: f"{SOURCE_NAME}: {r.get('company') or r['ticker']} ({r['ticker']})")
    rows, warnings = period_rows(ctx, base, history if on_event is None else observed_history)
    average = dp_fetcher.average_forward_pe([r for r in rows if not r["error"]])
    rows.append({"company": "Average", "ticker": "AVERAGE", "forward_pe": average, "error": None})
    table = table_block("stock_table", TABLE_TITLE, columns(ctx, rows), rows, "ticker", "company",
                        {"name": SOURCE_NAME, "url": "https://finance.yahoo.com", "as_of": ctx.today.isoformat()})
    brief, window = other_highlights_brief(ctx)
    other = draft_pieces([brief], 1, provider=narrative_provider, today=ctx.today, window=window, on_event=on_event)
    blocks = [narrative_block(f"highlight_{n}", _highlight_piece(h)) for n, h in enumerate(week["highlights"])]
    blocks.append(table)
    if _STUB_FOR[ctx.report_type]:
        blocks.append({s.id: s for s in STUBS}[_STUB_FOR[ctx.report_type]].block())
    if ctx.report_type == HALF_YEAR:
        warnings.append(HALF_CHANGE_WARNING)
    blocks += [narrative_block("other_highlights", p) for p in other["pieces"]]
    draft = {"pieces": week["highlights"] + other["pieces"], "shortfall": week["shortfall"] + other["shortfall"],
             "warnings": week["warnings"] + other["warnings"]}
    content = compose(SECTION, TITLE, ctx, blocks, draft=draft, expected=N_HIGHLIGHTS + 1, warnings=warnings,
                      charts=CHARTS)
    content["week_highlights_window"] = [week["week_start"], week["week_end"]]
    report_blocks(on_event, content)
    return build_review(content, check_section(content, on_event))

