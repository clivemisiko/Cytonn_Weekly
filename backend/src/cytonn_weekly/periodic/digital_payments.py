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
figures with Yahoo Finance closes (2026-10-05):

* Q3'2026: Year Open 2026 | Price 6/30/2026 | Price 8/03/2026 | Price 9/25/2026 | Price
  9/30/2026 | Price 10/03/2026 | w/w | m/m | Q/Q | YTD | Forward P/E.  The 6/30 and 9/30
  columns are the closes on the quarter's eve and last day (Visa 343.1 and 359.3, Mastercard
  513.6 and 551.5, as printed), and Q/Q is the one from the other (American Express 338.3 to
  304.1: (10.1%), as printed).  "Price 8/03/2026" is the 3 August close (Visa 365.7, which
  the issue misprints as 3665.7, giving its "(90.2%)" m/m), two months before the issue, so
  that column's basis is a stub, not a guessed "a month ago".
* H1'2026: Year Open 2026 | Price 6/26/2026 | Price 6/30/2026 | Price 7/3/2026 | HY'2026
  change | w/w | YTD | P/E.  Its HY change cannot be reproduced from any price it prints
  (American Express 10.2% beside a Year Open of 372.7 and a 6/30 price of 338.3), so it is
  a stub as well.

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
    "Q3'2026's m/m column is measured from a price it labels 8/03/2026, the 3 August close, two months "
    "before the issue (and misprinted for Visa as 3665.7), so the base date of a \"month\" change is not "
    "settled by the report."
)
MONTH_CHANGE_UNBLOCK = "The Digital Payments analyst confirming the m/m base date (a month before the issue, or another)."

HALF_CHANGE_BLOCKED_REASON = (
    "H1'2026's \"HY'2026 change\" cannot be reproduced from any price the table prints (American Express: "
    "10.2% beside a Year Open of 372.7 and a 6/30/2026 price of 338.3), so its base is unknown."
)
HALF_CHANGE_UNBLOCK = "The Digital Payments analyst confirming which two prices the half-year change compares."


def fetch_month_change(ctx: PeriodContext) -> Any:
    # TODO: needs the m/m base date confirmed (MONTH_CHANGE_UNBLOCK).
    raise NotImplementedError(MONTH_CHANGE_BLOCKED_REASON)


def fetch_half_change(ctx: PeriodContext) -> Any:
    # TODO: needs the half-year change's base confirmed (HALF_CHANGE_UNBLOCK).
    raise NotImplementedError(HALF_CHANGE_BLOCKED_REASON)


STUBS = (
    Stub("month_change", "Stock table: m/m change column", MONTH_CHANGE_BLOCKED_REASON, MONTH_CHANGE_UNBLOCK,
         fetch_month_change),
    Stub("half_change", "Stock table: HY change column", HALF_CHANGE_BLOCKED_REASON, HALF_CHANGE_UNBLOCK,
         fetch_half_change),
)
_STUB_FOR = {QUARTERLY: "month_change", HALF_YEAR: "half_change"}

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
    """The weekly fetcher's rows plus the closes on the period's eve and last day, and the period change."""
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
                if start is None or end is None:
                    raise ValueError(f"no close on or before {eve if start is None else ctx.end}")
                row.update(period_start_date=start[0].isoformat(), period_start_close=start[1],
                           period_end_date=end[0].isoformat(), period_end_close=end[1],
                           period_pct=pct_change(end[1], start[1]))
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
             {"key": "current_price", "label": f"Price {_label(_first(rows, 'current_price_date'))}", **price},
             {"key": "wow_pct", "label": "w/w change", "fmt": PCT, "decimals": 1}]
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
    """The week's four highlights, the period stock table, the month's other highlights; the unverified change column a stub.

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
    blocks += [table, {s.id: s for s in STUBS}[_STUB_FOR[ctx.report_type]].block()]
    blocks += [narrative_block("other_highlights", p) for p in other["pieces"]]
    draft = {"pieces": week["highlights"] + other["pieces"], "shortfall": week["shortfall"] + other["shortfall"],
             "warnings": week["warnings"] + other["warnings"]}
    content = compose(SECTION, TITLE, ctx, blocks, draft=draft, expected=N_HIGHLIGHTS + 1, warnings=warnings,
                      charts=CHARTS)
    content["week_highlights_window"] = [week["week_start"], week["week_end"]]
    report_blocks(on_event, content)
    return build_review(content, check_section(content, on_event))

