"""Paragraphs the tool computes rather than drafts, and how each figure in them is checked.

Much of the weekly Fixed Income and Equities sections is arithmetic on published figures:
"the overall subscription rate came in at 170.4%", "the shilling depreciated by 10.8 bps".
No model writes those sentences.  A builder fills fixed wording with figures, and every
figure is recorded beside the paragraph with what it was made from::

    {"kind": "computed", "id": "tbills", "title": "Money Markets, T-Bills Primary Auction",
     "body_md": "...the overall subscription rate coming in at 170.4%...",
     "figures": [
        {"key": "subscription", "label": "Overall subscription rate", "display": "170.4%",
         "fmt": "pct", "decimals": 1, "value": 170.4167...,
         "expr": ["mul", ["div", "bids", "offered"], 100],
         "inputs": {"bids": {"value": 47716.68, "origin": "source", "source": "CBK Weekly Bulletin, Table 4"},
                    "offered": {...}}}]}

The checking policy, applied to every such figure (and to table rows that say where they
came from; see common/review.py):

* **Computed figures carry their source rows and are exact-matched.**  The checker works
  the figure out again from ``inputs`` with ``expr``, rounds it half up to the display
  precision, and requires the printed figure to equal it.  It also requires the figure to
  appear in the paragraph.
* **A figure read from a typed workbook cell is an analyst input**: shown as "analyst input
  from <workbook> <sheet>!<cell>" and counted as not auto-verified, never as clean.  A
  figure worked out from one is not auto-verified either.
* **An OCR'd figure must agree with a second source**; if it does not, or there is none, it
  is flagged.  Two independent sources that differ are a "sources disagree" flag wherever
  they occur.
* **Text carried forward from the previous issue** (a ``carried`` block) is flagged
  "carried forward, edit before approving".
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Union

from cytonn_weekly.checkers.digital_payments import (
    MISMATCH,
    MISSING,
    SOURCES_DISAGREE,
    UNSOURCED,
    CheckReport,
    Flag,
    normalize,
    parse_number,
)
from cytonn_weekly.common.formatting import fmt_value, round_half_up

COMPUTED_SCOPE = "computed"
CARRIED_SCOPE = "carried"
CARRIED_FORWARD = "carried_forward"   # Flag.kind

# Where an input came from.
SOURCE = "source"                # printed in a public or third-party document, or fetched from its publisher
ANALYST = "analyst_input"        # a typed workbook cell
OCR = "ocr"                      # read from a scanned page
ORIGINS = (SOURCE, ANALYST, OCR)

# Extra display formats a paragraph needs beyond a table column's (formatting.fmt_value).
BPS = "bps"                # "10.8 bps": the magnitude; the sentence says which way
PLAIN_PCT = "plain_pct"    # "170.4%": the magnitude with no accounting brackets, for prose
PLAIN = "plain"            # "129.8", "3,053.1": magnitude, thousands separators
POINTS = "points"          # "1.0% points"

CARRIED_MESSAGE = "carried forward, edit before approving"


class ComputeError(ValueError):
    """An expression that cannot be worked out from its inputs."""


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------

Expr = Union[str, int, float, list]

_OPS = ("add", "sub", "mul", "div", "sum", "mean", "abs", "neg")


def evaluate(expr: Expr, inputs: dict[str, Any]) -> Decimal:
    """Work out ``expr`` over ``inputs`` exactly (Decimal arithmetic on each value's shortest form).

    A string names an input; a number is itself; a list is ``[op, *args]`` with op one of
    add, sub, mul, div, sum, mean, abs, neg.
    """
    if isinstance(expr, bool):
        raise ComputeError(f"not a number: {expr!r}")
    if isinstance(expr, (int, float)):
        return Decimal(repr(expr))
    if isinstance(expr, str):
        if expr not in inputs:
            raise ComputeError(f"no input named {expr!r}")
        raw = inputs[expr]
        raw = raw.get("value") if isinstance(raw, dict) else raw
        try:
            return parse_number(raw)
        except ValueError as exc:
            raise ComputeError(f"input {expr!r} is {exc}") from None
    if not isinstance(expr, list) or not expr or expr[0] not in _OPS:
        raise ComputeError(f"not an expression: {expr!r}")
    op, args = expr[0], [evaluate(a, inputs) for a in expr[1:]]
    try:
        if op == "add" and len(args) == 2:
            return args[0] + args[1]
        if op == "sub" and len(args) == 2:
            return args[0] - args[1]
        if op == "mul" and len(args) == 2:
            return args[0] * args[1]
        if op == "div" and len(args) == 2:
            return args[0] / args[1]
        if op == "sum" and args:
            return sum(args, Decimal(0))
        if op == "mean" and args:
            return sum(args, Decimal(0)) / len(args)
        if op == "abs" and len(args) == 1:
            return abs(args[0])
        if op == "neg" and len(args) == 1:
            return -args[0]
    except (InvalidOperation, ZeroDivisionError) as exc:
        raise ComputeError(f"{op} failed: {type(exc).__name__}") from None
    raise ComputeError(f"{op} takes a different number of arguments than {len(args)}")


def pct_change(new: str, old: str) -> list:
    """((new / old) - 1) x 100."""
    return ["mul", ["sub", ["div", new, old], 1], 100]


def ratio_pct(part: str, whole: str) -> list:
    return ["mul", ["div", part, whole], 100]


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def show(value: Any, fmt: str, decimals: int = 1) -> str:
    """One figure as a sentence prints it.  Prose formats print the magnitude: the wording carries the sign."""
    if fmt in (BPS, PLAIN_PCT, PLAIN, POINTS):
        d = abs(round_half_up(value, decimals))
        body = f"{d:,.{decimals}f}"
        return {BPS: f"{body} bps", PLAIN_PCT: f"{body}%", POINTS: f"{body}% points"}.get(fmt, body)
    return fmt_value(value, fmt, decimals)


def _printed_number(display: str) -> Decimal:
    """The number a display string prints ("10.8 bps" -> 10.8, "1.0% points" -> 1.0, "(4.0%)" -> -4.0)."""
    text = display.strip()
    for suffix in (" bps", "% points"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return parse_number(text)


def an_input(value: Any, origin: str, source: str, *, second: Optional[dict[str, Any]] = None,
             decimals: Optional[int] = None) -> dict[str, Any]:
    """One input of a figure: its value, where it came from, and (optionally) an independent second reading.

    ``second`` is ``{"source": ..., "value": ...}``; the two are compared at ``decimals``
    (the precision the less precise of them prints).
    """
    if origin not in ORIGINS:
        raise ValueError(f"unknown origin {origin!r}")
    out: dict[str, Any] = {"value": value, "origin": origin, "source": source}
    if second is not None:
        out["second"] = second
        out["decimals"] = decimals
    return out


def a_figure(key: str, label: str, fmt: str, decimals: int, inputs: dict[str, dict[str, Any]],
             expr: Optional[Expr] = None, *, in_text: bool = True, note: str = "") -> dict[str, Any]:
    """A figure worked out from ``inputs`` by ``expr`` (default: the single input itself), with its display string."""
    if expr is None:
        if len(inputs) != 1:
            raise ValueError(f"figure {key!r} has {len(inputs)} inputs and no expression")
        expr = next(iter(inputs))
    value = evaluate(expr, inputs)
    return {"key": key, "label": label, "fmt": fmt, "decimals": decimals, "value": float(value),
            "display": show(value, fmt, decimals), "expr": expr, "inputs": inputs, "in_text": in_text, "note": note}


def computed_block(block_id: str, title: str, body_md: str, figures: list[dict[str, Any]],
                   sources: Optional[list[dict[str, Any]]] = None, notes: Optional[list[str]] = None) -> dict[str, Any]:
    return {"kind": "computed", "id": block_id, "title": title, "body_md": body_md, "figures": figures,
            "sources": sources or [], "notes": notes or []}


def carried_block(block_id: str, title: str, body_md: str, carried_from: dict[str, Any]) -> dict[str, Any]:
    """Text taken verbatim from the previous issue: ``carried_from`` is {issue_id, url, published, section}."""
    return {"kind": "carried", "id": block_id, "title": title, "body_md": body_md, "carried_from": carried_from}


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------

def figure_subject(block_id: str, key: str) -> str:
    return f"{block_id}/{key}"


def _same(a: Any, b: Any, decimals: Optional[int]) -> bool:
    if decimals is None:
        return parse_number(a) == parse_number(b)
    return normalize(a, decimals) == normalize(b, decimals)


def check_figure_record(block: dict[str, Any], fig: dict[str, Any]) -> tuple[list[Flag], str]:
    """One figure's flags, and the note that says what it rests on when it is not flagged.

    The note is empty for a figure made only of published inputs (it is clean); it names the
    analyst inputs otherwise (not auto-verified).
    """
    subject = figure_subject(block["id"], fig["key"])
    common = dict(scope=COMPUTED_SCOPE, subject=subject, field=fig["key"], drafted=fig.get("display"),
                  decimals=fig.get("decimals"))
    flags: list[Flag] = []
    decimals = fig.get("decimals", 1)

    try:
        worked = evaluate(fig["expr"], fig.get("inputs") or {})
    except ComputeError as exc:
        return [Flag(kind=UNSOURCED, message=f"{fig['label']} cannot be worked out again from its inputs: {exc}", **common)], ""
    expected = round_half_up(worked, decimals)
    magnitude_only = fig.get("fmt") in (BPS, PLAIN_PCT, PLAIN, POINTS)
    try:
        printed = _printed_number(fig.get("display") or "")
    except ValueError:
        printed = None
    target = abs(expected) if magnitude_only else expected
    if printed is None or printed != target:
        flags.append(Flag(kind=MISMATCH, expected=str(target), source_value=float(worked),
                          message=f"{fig['label']}: printed {fig.get('display')!r} != {target} worked out from its inputs",
                          **common))
    if fig.get("in_text", True) and (fig.get("display") or "") not in (block.get("body_md") or ""):
        flags.append(Flag(kind=MISSING, expected=fig.get("display"),
                          message=f"{fig['label']} ({fig.get('display')}) does not appear in the paragraph", **common))

    # A second reading of the figure itself (afx's own week-on-week change, the workbook's weekly sum).
    confirmed = False
    second = fig.get("second")
    if second is not None:
        try:
            confirmed = _same(worked, second["value"], second.get("decimals", decimals))
        except ValueError:
            confirmed = False
        if not confirmed:
            flags.append(Flag(
                kind=SOURCES_DISAGREE, source_value=float(worked),
                message=(f"{fig['label']}: the tool works out {round_half_up(worked, second.get('decimals', decimals))} but "
                         f"{second['source']} gives {second['value']}; a human call is needed on which to use"),
                sources=[{"source": "worked out from the inputs", "value": float(worked), "normalized": str(expected)},
                         {"source": second["source"], "value": second["value"], "normalized": str(second["value"])}],
                **common))

    if fig.get("flag"):
        # The builder itself says this figure needs a human call (an input whose source is unconfirmed).
        flags.append(Flag(kind=UNSOURCED, message=f"{fig['label']}: {fig['flag']}", **common))

    analyst: list[str] = []
    for name, item in (fig.get("inputs") or {}).items():
        second = item.get("second")
        agrees: Optional[bool] = None
        if second is not None:
            try:
                agrees = _same(item["value"], second["value"], item.get("decimals"))
            except ValueError:
                agrees = False
        if agrees is False:
            flags.append(Flag(
                kind=SOURCES_DISAGREE, source_value=item["value"],
                message=(f"{fig['label']}: {name} is {item['value']} in {item['source']} but {second['value']} in "
                         f"{second['source']}; a human call is needed on which to use"),
                sources=[{"source": item["source"], "value": item["value"], "normalized": str(item["value"])},
                         {"source": second["source"], "value": second["value"], "normalized": str(second["value"])}],
                **common))
        elif item["origin"] == OCR and agrees is None and not confirmed:
            flags.append(Flag(kind=UNSOURCED, source_value=item["value"],
                              message=(f"{fig['label']}: {name} ({item['value']}) was read by OCR from {item['source']} "
                                       "and no second source confirms it"), **common))
        elif item["origin"] == ANALYST and not (agrees and second.get("origin") == SOURCE):
            analyst.append(f"{name} ({item['value']}) is an {item['source']}")
        elif item["origin"] == OCR and agrees and second.get("origin") == ANALYST and not confirmed:
            analyst.append(f"{name} ({item['value']}) was read by OCR from {item['source']} and agrees with the "
                           f"{second['source']}, which is itself typed; no published second source")
    note = ""
    if analyst and not flags:
        note = ("Not auto-verified: " + "; ".join(analyst) + ". The arithmetic is checked; the typed values are not. "
                "Check them against the workbook before accepting.")
    return flags, note


def check_computed_block(block: dict[str, Any]) -> CheckReport:
    report = CheckReport()
    for fig in block.get("figures", []):
        flags, _ = check_figure_record(block, fig)
        report.flags.extend(flags)
        report.checked += 1
    return report


def carried_flag(block: dict[str, Any]) -> Flag:
    src = block.get("carried_from") or {}
    where = f"issue {src.get('issue_id')} on cytonnreport.com" if src.get("issue_id") else "the previous issue"
    when = f", published {src['published']}" if src.get("published") else ""
    return Flag(kind=CARRIED_FORWARD, scope=CARRIED_SCOPE, subject=block["id"], field=None,
                message=f"{CARRIED_MESSAGE}: this text is copied from {where}{when} and was not written for this week")
