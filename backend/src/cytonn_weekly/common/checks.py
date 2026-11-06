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
from typing import Any, Mapping, Optional

from cytonn_weekly.checkers.digital_payments import (
    MISMATCH,
    MISSING,
    SOURCES_DISAGREE,
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
        # A row can carry a finding no figure comparison makes (``_flags``: [{field, message, sources, kind}]):
        # two readings that differ for a stated reason ("sources disagree", the default kind), or something a
        # source says should be there and is not (``kind: MISSING``).  It is a human call, never a draft error.
        for own in src.get("_flags") or []:
            report.flags.append(Flag(kind=own.get("kind") or SOURCES_DISAGREE, scope=TABLE_SCOPE, subject=subject, field=own.get("field"),
                                     drafted=drow.get(own.get("field")), source_value=src.get(own.get("field")),
                                     message=own["message"], sources=list(own.get("sources") or [])))
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


# ---------------------------------------------------------------------------
# A claim quoted from a supplied source (the Bedrock path)
# ---------------------------------------------------------------------------

_QUOTE_MARKS = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u2032": "'",
                              "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"', "\u2033": '"'})
_DASHES = str.maketrans({c: "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"})


def normalise_quote(text: str) -> str:
    """Whitespace (a non-breaking space included), quotation marks and dashes made plain, and nothing else: no case
    folding, no punctuation removed, no word dropped.  Two texts that match after this say the same words."""
    return " ".join(text.translate(_QUOTE_MARKS).translate(_DASHES).split())


def check_sourced_claim(text: str, quote: str, source_id: str, source_texts: Mapping[str, str]) -> Optional[str]:
    """Why a claim does not hold, as a clause for a warning, or None when it does.

    It holds only if (a) its ``source_id`` is one of the supplied sources, (b) its ``quote`` is in that source's saved
    text word for word (after ``normalise_quote``), and (c) every number in the claim appears in the quote.  Whether the
    words around the numbers say what the source means is never judged here.
    """
    if not (source_id or "").strip():
        return "it names no source"
    if source_id not in source_texts:
        return f"source {source_id} is not one of the supplied sources"
    plain = normalise_quote(quote or "")
    if not plain:
        return "it gives no quote"
    if plain not in normalise_quote(source_texts[source_id]):
        return f"its quote is not in the saved text of source {source_id} word for word"
    in_quote = set(figures_in(plain))
    missing = [f for f in figures_in(text) if f not in in_quote]
    if missing:
        return f"figure(s) {', '.join(_fmt(f) for f in missing)} are in the claim but not in its quote"
    return None


# ---------------------------------------------------------------------------
# A drafted piece as a whole (the Focus of the Week's lead, sections and conclusion)
# ---------------------------------------------------------------------------

JUDGEMENT = "analyst_judgement"   # Flag.kind
RATING = "rating"                 # Flag.kind
JUDGEMENT_MESSAGE = "Analyst judgement: confirm the recommendations"
RATING_RE = re.compile(r"\b(NEUTRAL|POSITIVE|NEGATIVE)\b")
ROLES_WRITTEN_FROM_SECTIONS = ("lead", "conclusion")   # no search, no claims: written from the finished sections


def check_piece(block: dict[str, Any], blocks: list[dict[str, Any]]) -> list[Flag]:
    """Block-level flags of a drafted piece that has a ``role`` (subject: the block's id, scope: claim).

    * A capitalised rating (NEUTRAL, POSITIVE, NEGATIVE) in any lead, section or conclusion: a rating is Cytonn's own
      judgement, never the tool's.
    * A figure in the lead or the conclusion that no section body holds.  Both are written from the sections, so a figure
      they add came from nowhere the tool can show.
    * The conclusion is always flagged for the analyst's judgement.
    """
    role = block.get("role")
    if role not in ("lead", "section", "conclusion"):
        return []
    text = block.get("body") or ""
    flags: list[Flag] = []

    def flag(kind: str, message: str) -> None:
        flags.append(Flag(kind=kind, scope=CLAIM_SCOPE, subject=block["id"], field=None, drafted=text, message=message))

    if role == "conclusion":
        flag(JUDGEMENT, JUDGEMENT_MESSAGE)
    ratings = sorted(set(RATING_RE.findall(text)))
    if ratings:
        flag(RATING, f"the text gives a rating ({', '.join(ratings)}): a rating is Cytonn's own judgement. "
                     "Remove it, or confirm it with the analysts")
    if role in ROLES_WRITTEN_FROM_SECTIONS:
        known = {f for b in blocks if b.get("role") == "section" for f in figures_in(b.get("body") or "")}
        new = [f for f in dict.fromkeys(figures_in(text)) if f not in known]
        if new:
            what = "lead" if role == "lead" else "conclusion"
            flag(UNSOURCED, f"figure(s) {', '.join(_fmt(f) for f in new)} in the {what} do not appear in any section body")
    return flags
