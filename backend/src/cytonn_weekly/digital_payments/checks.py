"""Digital Payments checking layer, part 6a: exact-match checks.

Implements the project's non-negotiable checking rules for the figures that
trace to a source, with no LLM calls:

* Normalize the SOURCE value to the draft's display precision (round half up,
  formatting stripped), then require exact equality with the drafted figure.
  There is no tolerance band: 25.0 vs 24.99 passes at one decimal only because
  24.99 normalizes to 25.0; 25.1 vs 24.99 is a mismatch.
* A mismatch (draft != its own normalized source) is a different flag from
  "sources disagree" (two legitimate sources give genuinely different figures,
  so a human must choose; it does not imply the draft is wrong).
* Only figures are checked.  Prose in the outlook and highlights is never
  marked verified here.  The tool never approves anything: the report is just
  flags and counts for the analyst.

Extension points for later work:
* Task 6b: verify_highlight_claim() is a stub that returns a NOT_IMPLEMENTED
  flag; check_digital_payments() already calls it once per highlight.
* Second sources: pass ``extra_sources`` (a {(subject, field): [SourceValue]}
  mapping) to any check to bring in independent sources for the same figure.

Typical usage
-------------
    from cytonn_weekly.digital_payments.checks import check_digital_payments

    report = check_digital_payments(
        source_rows=fetch_digital_payments(),
        drafted_rows=drafted_table,            # display values, by ticker
        drafted_outlook_stats=outlook["stats"],
        highlights=draft["highlights"],
    )
    for flag in report.flags:
        ...
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any, Optional

from cytonn_weekly.common.run_events import CHECK_FINISHED, CHECK_STARTED, Observer, emit
from cytonn_weekly.review.figures import (
    NOT_IMPLEMENTED,
    UNSOURCED,
    MISSING,
    CheckReport,
    Flag,
    SourceValue,
    check_figure,
)

# What a run's events call the two figure checks (common/run_events.py).  TABLE_TITLE is the
# title the review screen shows above the table (api/serialize.py has the same string).
TABLE_TITLE = "Digital Payments NYSE and LSE Stock Performance"
OUTLOOK_STATS_LABEL = "Outlook figures against the table"

# Display precision (decimal places) per figure, confirmed against the real
# report table (Cytonn Weekly #37.2026, p.17): every price, % change and P/E is
# shown at one decimal (e.g. 372.7, (4.0%), 6.3%, 23.3x).  Override via the
# ``decimals`` arguments.
TABLE_DECIMALS: dict[str, int] = {
    "current_price": 1,
    "prior_close": 1,
    "ytd_open": 1,
    "wow_pct": 1,
    "ytd_pct": 1,
    "forward_pe": 1,
}


def outlook_decimals_from(table_decimals: dict[str, int]) -> dict[str, int]:
    """Outlook-stat precision, derived from the table's so the two cannot drift.

    The real outlook paragraph reuses the table's Average row verbatim, so each
    average is displayed at the same precision as its table column.  Counts are
    whole numbers.
    """
    return {
        "companies_included": 0,
        "companies_failed": 0,
        "avg_wow_pct": table_decimals["wow_pct"],
        "avg_ytd_pct": table_decimals["ytd_pct"],
        "advancers": 0,
        "decliners": 0,
        "avg_forward_pe": table_decimals["forward_pe"],
    }


OUTLOOK_DECIMALS: dict[str, int] = outlook_decimals_from(TABLE_DECIMALS)


# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------

def check_table(
    source_rows: list[dict[str, Any]],
    drafted_rows: list[dict[str, Any]],
    decimals: Optional[dict[str, int]] = None,
    extra_sources: Optional[dict[tuple[str, str], list[SourceValue]]] = None,
) -> CheckReport:
    """Check drafted table rows (display values, keyed by ticker) against source rows.

    Source rows are digital_payments/fetcher.py output; drafted rows use the same field
    names (current_price, prior_close, ytd_open, wow_pct, ytd_pct, forward_pe)
    holding the figures as drafted, either numbers or display strings in the
    real table's format (see format_table_rows() in the fetcher module).
    """
    decimals = decimals or TABLE_DECIMALS
    extra_sources = extra_sources or {}
    report = CheckReport()
    drafted_by_ticker = {r["ticker"]: r for r in drafted_rows}
    source_tickers = {r["ticker"] for r in source_rows}

    for src in source_rows:
        ticker = src["ticker"]
        drow = drafted_by_ticker.get(ticker)
        if src.get("error"):
            report.flags.append(Flag(
                kind=MISSING, scope="table", subject=ticker, field=None,
                message=f"source row failed to fetch, cannot check: {src['error']}",
            ))
            continue
        if drow is None:
            report.flags.append(Flag(
                kind=MISSING, scope="table", subject=ticker, field=None,
                message="row is absent from the draft",
            ))
            continue
        for fname, dec in decimals.items():
            flag = check_figure(
                "table", ticker, fname, drow.get(fname), src.get(fname), dec,
                extra_sources=extra_sources.get((ticker, fname)),
            )
            report.checked += 1
            if flag:
                report.flags.append(flag)

    for ticker in drafted_by_ticker.keys() - source_tickers:
        report.flags.append(Flag(
            kind=UNSOURCED, scope="table", subject=ticker, field=None,
            message="drafted row has no source row",
        ))
    return report


# ---------------------------------------------------------------------------
# Outlook stats
# ---------------------------------------------------------------------------

def expected_outlook_stats(source_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Recompute the outlook stats independently from the source rows (raw values).

    Rows that failed to fetch are excluded; forward P/E averages only rows that
    have one.  Averages are returned unrounded; normalization happens at check time.
    """
    ok = [r for r in source_rows if not r.get("error")]
    stats: dict[str, Any] = {
        "companies_included": len(ok),
        "companies_failed": len(source_rows) - len(ok),
    }
    if ok:
        wow = [Decimal(repr(r["wow_pct"])) for r in ok]
        ytd = [Decimal(repr(r["ytd_pct"])) for r in ok]
        stats["avg_wow_pct"] = sum(wow) / len(wow)
        stats["avg_ytd_pct"] = sum(ytd) / len(ytd)
        stats["advancers"] = sum(1 for v in wow if v > 0)
        stats["decliners"] = sum(1 for v in wow if v < 0)
    pes = [
        Decimal(repr(r["forward_pe"]))
        for r in ok
        if isinstance(r.get("forward_pe"), (int, float)) and not isinstance(r.get("forward_pe"), bool)
        and math.isfinite(r["forward_pe"])
    ]
    if pes:
        stats["avg_forward_pe"] = sum(pes) / len(pes)
    return stats


def check_outlook_stats(
    drafted_stats: dict[str, Any],
    source_rows: list[dict[str, Any]],
    decimals: Optional[dict[str, int]] = None,
    extra_sources: Optional[dict[tuple[str, str], list[SourceValue]]] = None,
) -> CheckReport:
    """Check draft_outlook()'s ``stats`` against the table's own figures.

    These are derived from the table, not external citations, so they get the
    same normalize-then-exact-match treatment and are never citation-verified.
    Only the stats dict is checked; numbers quoted in the outlook prose are not.
    """
    decimals = decimals or OUTLOOK_DECIMALS
    extra_sources = extra_sources or {}
    report = CheckReport()
    expected = expected_outlook_stats(source_rows)

    for key in drafted_stats.keys() - decimals.keys():
        report.flags.append(Flag(
            kind=UNSOURCED, scope="outlook", subject="outlook", field=key,
            drafted=drafted_stats[key], message=f"stat {key!r} is not a known, sourced stat",
        ))
    for key, dec in decimals.items():
        flag = check_figure(
            "outlook", "outlook", key, drafted_stats.get(key), expected.get(key), dec,
            extra_sources=extra_sources.get(("outlook", key)),
            primary_source="table",
        )
        report.checked += 1
        if flag:
            report.flags.append(flag)
    return report


# ---------------------------------------------------------------------------
# Highlights (task 6b plugs in here)
# ---------------------------------------------------------------------------

def verify_highlight_claim(highlight: dict[str, Any]) -> list[Flag]:
    """Citation verification for one highlight.  NOT IMPLEMENTED (task 6b).

    Contract for 6b: take one highlight dict from draft_highlights() (with its
    "claims", each carrying the exact source url and cited_text) and return a
    list of Flags; an empty list means every checkable claim was verified.
    Until then it returns a single NOT_IMPLEMENTED flag so the highlight is
    visibly unchecked rather than silently passing.
    """
    return [Flag(
        kind=NOT_IMPLEMENTED,
        scope="highlight",
        subject=highlight.get("headline", ""),
        field=None,
        message="citation verification is not implemented yet (task 6b); claims are unchecked",
    )]


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def check_digital_payments(
    source_rows: list[dict[str, Any]],
    drafted_rows: Optional[list[dict[str, Any]]] = None,
    drafted_outlook_stats: Optional[dict[str, Any]] = None,
    highlights: Optional[list[dict[str, Any]]] = None,
    table_decimals: Optional[dict[str, int]] = None,
    outlook_decimals: Optional[dict[str, int]] = None,
    extra_sources: Optional[dict[tuple[str, str], list[SourceValue]]] = None,
    on_event: Optional[Observer] = None,
) -> CheckReport:
    """Run every available check for the Digital Payments section.

    Each part is optional; only the parts passed are checked.  Highlights are
    routed to verify_highlight_claim() (currently a not-implemented stub).

    ``on_event`` (common/run_events.py) is told as each check starts and ends, with
    the number of review items it leaves per status; it changes nothing in the report.
    """
    report = CheckReport()
    parts = []
    if drafted_rows is not None:
        emit(on_event, CHECK_STARTED, TABLE_TITLE)
        part = check_table(source_rows, drafted_rows, table_decimals, extra_sources)
        parts.append(part)
        emit(on_event, CHECK_FINISHED, TABLE_TITLE,
             counts=_unit_counts({r["ticker"] for r in source_rows}, {f.subject for f in part.flags}))
    if drafted_outlook_stats is not None:
        if outlook_decimals is None and table_decimals is not None:
            outlook_decimals = outlook_decimals_from({**TABLE_DECIMALS, **table_decimals})
        emit(on_event, CHECK_STARTED, OUTLOOK_STATS_LABEL)
        part = check_outlook_stats(drafted_outlook_stats, source_rows, outlook_decimals, extra_sources)
        parts.append(part)
        emit(on_event, CHECK_FINISHED, OUTLOOK_STATS_LABEL,
             counts=_unit_counts(set(drafted_outlook_stats), {f.field or "outlook" for f in part.flags}))
    for part in parts:
        report.flags.extend(part.flags)
        report.checked += part.checked
    for h in highlights or []:
        emit(on_event, CHECK_STARTED, h.get("headline", ""))
        flags = verify_highlight_claim(h)
        report.flags.extend(flags)
        # As the review model reads it (review/model.py): one item per claim (one for a highlight with
        # none), flagged if the highlight carries a real flag, otherwise not auto-verified.
        claims = len(h.get("claims") or [None])
        flagged = any(f.kind != NOT_IMPLEMENTED for f in flags)
        emit(on_event, CHECK_FINISHED, h.get("headline", ""),
             counts={"flagged": claims if flagged else 0, "not_auto_verified": 0 if flagged else claims})
    return report


def _unit_counts(units: set, flagged: set) -> dict[str, int]:
    """Review items a figure check leaves: one per unit (a row, a stat), flagged if any flag points at it."""
    return {"clean": len(units - flagged), "flagged": len(units | flagged) - len(units - flagged)}
