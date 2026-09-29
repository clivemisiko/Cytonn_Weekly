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
  flags and counts for the coordinator.

Extension points for later work:
* Task 6b: verify_highlight_claim() is a stub that returns a NOT_IMPLEMENTED
  flag; check_digital_payments() already calls it once per highlight.
* Second sources: pass ``extra_sources`` (a {(subject, field): [SourceValue]}
  mapping) to any check to bring in independent sources for the same figure.

Typical usage
-------------
    from cytonn_weekly.checkers.digital_payments import check_digital_payments

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
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Optional

# Flag kinds.
MISMATCH = "mismatch"                # drafted figure != normalized source figure
MISSING = "missing"                  # a sourced figure/row is absent from the draft
UNSOURCED = "unsourced"              # drafted figure exists with no source behind it
SOURCES_DISAGREE = "sources_disagree"  # independent sources differ; human call needed
NOT_IMPLEMENTED = "not_implemented"  # check not built yet (highlight citations, 6b)

# Display precision (decimal places) per figure.  ASSUMPTIONS to confirm against
# the published report layout: prices and % changes at 2dp, forward P/E at 1dp
# (real issues show e.g. 69.0x).  Override via the ``decimals`` arguments.
TABLE_DECIMALS: dict[str, int] = {
    "current_price": 2,
    "prior_close": 2,
    "ytd_open": 2,
    "wow_pct": 2,
    "ytd_pct": 2,
    "forward_pe": 1,
}

# Outlook stats are checked at the precision draft_outlook() emits them (2dp).
OUTLOOK_DECIMALS: dict[str, int] = {
    "companies_included": 0,
    "companies_failed": 0,
    "avg_wow_pct": 2,
    "avg_ytd_pct": 2,
    "advancers": 0,
    "decliners": 0,
    "avg_forward_pe": 2,
}

_BLANKS = {"", "-", "–", "—", "n/a", "n/m", "na", "none"}


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SourceValue:
    """One independent source's value for a figure (for sources-disagree checks)."""

    source: str
    value: Any


@dataclass
class Flag:
    """One finding for the coordinator.  Never an approval, only a flag."""

    kind: str                       # MISMATCH | MISSING | UNSOURCED | SOURCES_DISAGREE | NOT_IMPLEMENTED
    scope: str                      # "table" | "outlook" | "highlight"
    subject: str                    # ticker, "outlook", or highlight headline
    field: Optional[str]            # figure name, or None for a whole row/highlight
    message: str
    drafted: Any = None             # value as drafted (raw, as given)
    expected: Optional[str] = None  # normalized source value, as a string
    source_value: Any = None        # raw source value
    decimals: Optional[int] = None
    # Populated only for SOURCES_DISAGREE: [{"source", "value", "normalized"}, ...]
    sources: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CheckReport:
    flags: list[Flag] = field(default_factory=list)
    checked: int = 0  # figures compared (passes + flagged)

    @property
    def clean(self) -> bool:
        """True only if nothing was flagged.  Not an approval."""
        return not self.flags

    def by_kind(self, kind: str) -> list[Flag]:
        return [f for f in self.flags if f.kind == kind]


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    return isinstance(value, str) and value.strip().lower() in _BLANKS


def parse_number(value: Any) -> Decimal:
    """Parse a number or formatted display string ("$1,234.50", "+1.2%", "24.5x").

    Raises ValueError if it cannot be read as a finite number.
    """
    if isinstance(value, bool):
        raise ValueError(f"not a number: {value!r}")
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, (int, float)):
        d = Decimal(repr(value))  # shortest repr avoids binary-float artefacts
    elif isinstance(value, str):
        s = value.strip().replace("−", "-")
        for ch in "$£€,% ":
            s = s.replace(ch, "")
        if s[-1:] in ("x", "X"):
            s = s[:-1]
        if s.startswith("+"):
            s = s[1:]
        try:
            d = Decimal(s)
        except InvalidOperation:
            raise ValueError(f"not a number: {value!r}") from None
    else:
        raise ValueError(f"not a number: {value!r}")
    if not d.is_finite():
        raise ValueError(f"not a finite number: {value!r}")
    return d


def normalize(value: Any, decimals: int) -> Decimal:
    """Source value -> display precision (round half up)."""
    return parse_number(value).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Core comparison
# ---------------------------------------------------------------------------

def check_figure(
    scope: str,
    subject: str,
    field_name: str,
    drafted: Any,
    source_value: Any,
    decimals: int,
    extra_sources: Optional[list[SourceValue]] = None,
    primary_source: str = "primary",
) -> Optional[Flag]:
    """Compare one drafted figure against its normalized source(s).

    Returns None if it passes, else a Flag.  If ``extra_sources`` carry a value
    that normalizes differently from the primary source, the result is a
    SOURCES_DISAGREE flag (a human picks the source) instead of a mismatch.
    """
    common = dict(scope=scope, subject=subject, field=field_name, drafted=drafted, decimals=decimals)

    sources = [SourceValue(primary_source, source_value), *(extra_sources or [])]
    present = [s for s in sources if not _is_blank(s.value)]

    if not present:  # nothing to check against
        if _is_blank(drafted):
            return None
        return Flag(
            kind=UNSOURCED,
            message=f"{field_name} is drafted as {drafted!r} but has no source value",
            **common,
        )

    try:
        normalized = [(s, normalize(s.value, decimals)) for s in present]
    except ValueError as exc:
        return Flag(kind=MISMATCH, message=f"source value unreadable: {exc}", source_value=source_value, **common)

    if len({n for _, n in normalized}) > 1:
        return Flag(
            kind=SOURCES_DISAGREE,
            message=(
                f"{field_name}: sources give different figures at {decimals}dp; "
                "a human call is needed on which to use (this does not imply the draft is wrong)"
            ),
            source_value=source_value,
            sources=[{"source": s.source, "value": s.value, "normalized": str(n)} for s, n in normalized],
            **common,
        )

    expected = normalized[0][1]
    if _is_blank(drafted):
        return Flag(
            kind=MISSING,
            message=f"{field_name} is absent from the draft; source gives {expected}",
            expected=str(expected),
            source_value=source_value,
            **common,
        )
    try:
        drafted_d = parse_number(drafted)
    except ValueError as exc:
        return Flag(
            kind=MISMATCH,
            message=f"drafted value unreadable: {exc}",
            expected=str(expected),
            source_value=source_value,
            **common,
        )
    if drafted_d == expected:
        return None

    extra = ""
    if drafted_d != drafted_d.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP):
        extra = f" (drafted value has more than the {decimals} display decimals)"
    return Flag(
        kind=MISMATCH,
        message=f"{field_name}: drafted {drafted!r} != normalized source {expected}{extra}",
        expected=str(expected),
        source_value=source_value,
        **common,
    )


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

    Source rows are digital_payments.py output; drafted rows use the same field
    names (current_price, prior_close, ytd_open, wow_pct, ytd_pct, forward_pe)
    holding the figures as drafted, either numbers or formatted strings.
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
) -> CheckReport:
    """Run every available check for the Digital Payments section.

    Each part is optional; only the parts passed are checked.  Highlights are
    routed to verify_highlight_claim() (currently a not-implemented stub).
    """
    report = CheckReport()
    parts = []
    if drafted_rows is not None:
        parts.append(check_table(source_rows, drafted_rows, table_decimals, extra_sources))
    if drafted_outlook_stats is not None:
        parts.append(check_outlook_stats(drafted_outlook_stats, source_rows, outlook_decimals, extra_sources))
    for part in parts:
        report.flags.extend(part.flags)
        report.checked += part.checked
    for h in highlights or []:
        report.flags.extend(verify_highlight_claim(h))
    return report
