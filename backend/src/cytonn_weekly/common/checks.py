"""The checking layer for every section after Digital Payments.

Two kinds of check, matching the project's non-negotiable rules:

* **Tables: exact match after normalization.**  Every figure in a fetched table is
  compared with its own source value, normalized to the column's display
  precision with round-half-up, with no tolerance band.  This reuses the
  Digital Payments checker's ``check_figure`` unchanged, so the mismatch /
  missing / unsourced / sources-disagree semantics are literally the same code.
* **Drafted claims: figures against the cited span.**  Full citation
  verification (task 6b) is still blocked on API budget.  What can be checked
  mechanically, with no LLM, is the figure-vs-analysis rule's checkable half:
  every number in a claim must appear, exactly, among the numbers in the text
  the search tool cited for it.  A figure that does not appear is flagged.  The
  wording around the figures is interpretive and is never marked verified, so
  a claim that passes is still ``not_auto_verified``, with a note saying which
  figures were found.

Flags use the Digital Payments ``Flag`` dataclass so ``ReviewItem.from_dict``
restores them unchanged.  Scopes: ``table`` (subject ``"<table id>/<row key>"``),
``claim`` (subject ``"<block id>#<claim index>"``) and ``unavailable``
(subject ``<block id>``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from cytonn_weekly.checkers.digital_payments import (
    MISMATCH,
    MISSING,
    UNSOURCED,
    CheckReport,
    Flag,
    SourceValue,
    check_figure,
)
from cytonn_weekly.common.computed import ComputeError, evaluate
from cytonn_weekly.common.formatting import TEXT, round_half_up

TABLE_SCOPE = "table"
CLAIM_SCOPE = "claim"
UNAVAILABLE_SCOPE = "unavailable"


def row_subject(table_id: str, key: str) -> str:
    return f"{table_id}/{key}"


def check_table_block(
    block: dict[str, Any],
    extra_sources: Optional[dict[tuple[str, str], list[SourceValue]]] = None,
) -> CheckReport:
    """Exact-match every numeric column of a table block: drafted ``rows`` against ``source_rows``.

    Rows are matched on the block's ``key_field``.  A source row with an ``error``
    is a MISSING flag (nothing to check against), a source row absent from the
    draft is MISSING, a drafted row with no source row is UNSOURCED.

    ``extra_sources`` brings in independent second sources, as for the Digital Payments
    table: a ``{(subject, column key): [SourceValue]}`` mapping, where the subject is the
    row's flag subject (``row_subject(block id, row key)``).  Each list is handed to
    ``check_figure`` as it is, so what a second source means is that function's rule and
    nothing is decided here.  Left out, every figure is checked against its own source
    row alone.  No caller passes it yet: no second source exists.
    """
    report = CheckReport()
    extra_sources = extra_sources or {}
    key = block["key_field"]
    numeric = [c for c in block["columns"] if c.get("fmt", TEXT) != TEXT]
    drafted = {r[key]: r for r in block.get("rows", [])}
    source_keys = set()
    for src in block.get("source_rows", []):
        k = src[key]
        source_keys.add(k)
        subject = row_subject(block["id"], k)
        if src.get("error"):
            report.flags.append(Flag(kind=MISSING, scope=TABLE_SCOPE, subject=subject, field=None,
                                     message=f"source row failed to fetch, cannot check: {src['error']}"))
            continue
        drow = drafted.get(k)
        if drow is None:
            report.flags.append(Flag(kind=MISSING, scope=TABLE_SCOPE, subject=subject, field=None,
                                     message="row is absent from the draft"))
            continue
        for c in numeric:
            flag = check_figure(TABLE_SCOPE, subject, c["key"], drow.get(c["key"]), src.get(c["key"]),
                                c.get("decimals", 1), extra_sources=extra_sources.get((subject, c["key"])),
                                primary_source=block.get("source", {}).get("name", "primary"))
            report.checked += 1
            if flag:
                report.flags.append(flag)
            # A column that says how it is worked out (``expr`` over the row's own raw fields) is worked
            # out again here, so a derived figure is checked against its inputs, not only against itself.
            if c.get("expr") is not None and src.get(c["key"]) is not None:
                decimals = c.get("decimals", 1)
                try:
                    worked = round_half_up(evaluate(c["expr"], src), decimals)
                    same = worked == round_half_up(src[c["key"]], decimals)
                    reason = f"is {src[c['key']]!r} in the row but {worked} worked out from the row's inputs"
                except (ComputeError, ValueError, ArithmeticError) as exc:
                    worked, same = None, False
                    reason = f"cannot be worked out from the row's inputs: {exc}"
                if not same:
                    report.flags.append(Flag(kind=MISMATCH, scope=TABLE_SCOPE, subject=subject, field=c["key"],
                                             drafted=drow.get(c["key"]), expected=None if worked is None else str(worked),
                                             source_value=src.get(c["key"]), decimals=decimals,
                                             message=f"{c['key']} {reason}"))
        # A row can also say how single cells were worked out (``_derived``: {column: {expr, inputs}}),
        # for a row made from other rows (a "Weekly Change" row); each is worked out again here.
        for fld, how in (src.get("_derived") or {}).items():
            column = next((c for c in numeric if c["key"] == fld), None)
            if column is None or src.get(fld) is None:
                continue
            decimals = column.get("decimals", 1)
            try:
                worked = round_half_up(evaluate(how["expr"], how.get("inputs") or {}), decimals)
                same = worked == round_half_up(src[fld], decimals)
                reason = f"is {src[fld]!r} in the row but {worked} worked out from its inputs"
            except (ComputeError, ValueError, ArithmeticError) as exc:
                worked, same = None, False
                reason = f"cannot be worked out from its inputs: {exc}"
            report.checked += 1
            if not same:
                report.flags.append(Flag(kind=MISMATCH, scope=TABLE_SCOPE, subject=subject, field=fld, drafted=drow.get(fld),
                                         expected=None if worked is None else str(worked), source_value=src.get(fld),
                                         decimals=decimals, message=f"{fld} {reason}"))
        # A figure derived from several inputs (a Total, an Average) matches its own source exactly
        # even when some inputs were missing and left out, so it would read clean.  The source row
        # says which figures are incomplete and why; each one is flagged, whatever the match.
        for fld, reason in (src.get("incomplete") or {}).items():
            report.flags.append(Flag(kind=MISSING, scope=TABLE_SCOPE, subject=subject, field=fld, drafted=drow.get(fld),
                                     source_value=src.get(fld), message=f"incomplete: {reason}"))
    for k in drafted.keys() - source_keys:
        report.flags.append(Flag(kind=UNSOURCED, scope=TABLE_SCOPE, subject=row_subject(block["id"], k), field=None,
                                 message="drafted row has no source row"))
    return report


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

# A figure: optional sign or accounting parentheses, digits with optional thousands
# commas and decimals.  "Sh30.1bn", "KES 4.19Tr", "8.75%", "(4.0%)", "1,234" all
# contribute their numeric part; units are not compared (a claim and its source
# commonly spell units differently), the number itself must match exactly.
_FIGURE_RE = re.compile(r"(?<![\d.])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\d.,])\d+(?:\.\d+)?")


def figures_in(text: str) -> list[Decimal]:
    """Every number in ``text``, thousands commas removed, in order of appearance."""
    out = []
    for m in _FIGURE_RE.finditer(text or ""):
        try:
            out.append(Decimal(m.group(0).replace(",", "")))
        except InvalidOperation:  # pragma: no cover - the regex only matches digits
            continue
    return out


@dataclass
class ClaimCheck:
    """The mechanical result for one claim."""

    flags: list[Flag] = field(default_factory=list)
    note: str = ""   # for a claim that is not flagged: what was and was not checked


def _fmt(d: Decimal) -> str:
    return format(d.normalize(), "f") if d == d.to_integral() else str(d)


def check_claim(block_id: str, index: int, claim: dict[str, Any]) -> ClaimCheck:
    """Check one drafted claim's figures against its cited text.  Never marks the wording verified."""
    subject = f"{block_id}#{index}"
    text = claim.get("text") or ""
    url = (claim.get("url") or "").strip()
    cited = claim.get("cited_text") or ""
    if not url:
        return ClaimCheck(flags=[Flag(kind=UNSOURCED, scope=CLAIM_SCOPE, subject=subject, field=None,
                                      drafted=text, message="claim has no source URL")])
    figures = figures_in(text)
    if not figures:
        return ClaimCheck(note=(
            "No figures in this claim, so there is nothing to exact-match; the wording is not "
            "automatically checked (citation verification, task 6b, is not built). Check it against its source."
        ))
    shown = ", ".join(_fmt(f) for f in figures)
    if not cited.strip():
        return ClaimCheck(note=(
            f"Figures {shown} could not be checked: the provider returned no cited span for this claim "
            "(the local dev provider never does). Check them against the source by hand."
        ))
    available = set(figures_in(cited))
    missing = [f for f in figures if f not in available]
    if missing:
        return ClaimCheck(flags=[Flag(
            kind=UNSOURCED, scope=CLAIM_SCOPE, subject=subject, field="figures", drafted=text,
            expected=None, source_value=cited,
            message=(f"figure(s) {', '.join(_fmt(f) for f in missing)} do not appear in the text the search "
                     "tool cited for this claim"),
        )])
    return ClaimCheck(note=(
        f"Figures {shown} appear exactly in the cited text. The wording around them is not automatically "
        "checked (task 6b is not built), so read it against the source."
    ))
