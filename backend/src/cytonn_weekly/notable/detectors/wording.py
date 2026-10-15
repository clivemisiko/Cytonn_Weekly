"""Every headline, every rule and every number format the detectors print, in one module.

A headline states what the points show and nothing more: no cause, no prediction, no advice. The words that would make it
more are kept out of every template here (tests scan this module for them). Numbers use the house formats of the weekly
report: negatives in brackets, round half up to the displayed decimals, "x" on a multiple, "Kshs 12.3 bn" and "USD 12.3 mn"
for amounts, "10.8 bps" for basis points, and a magnitude with no brackets where a sentence names the direction in words.
Dates are written 2026-10-09, as the notable panel shows them.

Each rule is written so that someone with only the working points can redo the check, and so that the independent verifier
(verify.py) can read its parameters back out of it. The verifier has its own copy of these sentences' shape and shares no
code with this module, so changing a template without changing the verifier fails loudly.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from cytonn_weekly.common.computed import BPS, PLAIN_PCT, POINTS, show
from cytonn_weekly.common.formatting import MULTIPLE, NUMBER, PCT, PRICE, fmt_value

DEFAULT_DECIMALS = {"pct": 2, "bps": 1, "multiple": 1, "kes_bn": 1, "kes_mn": 1, "usd_mn": 1, "index": 1, "count": 0}
_AFFIX = {"bps": ("", " bps"), "kes_bn": ("Kshs ", " bn"), "kes_mn": ("Kshs ", " mn"), "usd_mn": ("USD ", " mn")}


def fmt(value: Decimal, unit: str, decimals: Optional[int] = None) -> str:
    """A value as the report prints it: 9.05%, (0.20%), 18.2x, 3,053.1, Kshs 12.3 bn, (USD 4.6 mn), 10.8 bps."""
    d = DEFAULT_DECIMALS[unit] if decimals is None else decimals
    if unit == "pct":
        return fmt_value(value, PCT, d)
    if unit == "multiple":
        return fmt_value(value, MULTIPLE, d)
    if unit in ("index", "count"):
        return fmt_value(value, NUMBER, d)
    prefix, suffix = _AFFIX[unit]
    body = fmt_value(value, NUMBER, d)  # "(12.3)" for a negative
    return f"({prefix}{body[1:-1]}{suffix})" if body.startswith("(") else f"{prefix}{body}{suffix}"


def price(value: Decimal) -> str:
    """A share price or per-share amount: "Kshs 49.30"."""
    return f"Kshs {fmt_value(value, PRICE, 2)}"


def count(n: int) -> str:
    return fmt_value(Decimal(n), NUMBER, 0)


def multiple(ratio: Decimal) -> str:
    """"10.0x", or "0.10x" for a ratio below one so that it does not round to nothing."""
    return fmt_value(ratio, MULTIPLE, 1 if ratio >= 1 else 2)


def difference_text(mode: str, magnitude: Decimal, unit: str, decimals: Optional[int]) -> str:
    """The size of a difference as a sentence names it: 20.0%, 45.0 bps, 0.45% points, Kshs 3.5 bn."""
    if mode == "pct":
        return show(magnitude, PLAIN_PCT, 1)
    if mode == "bps":
        return show(magnitude, BPS, 1)
    if unit == "pct":
        return show(magnitude, POINTS, DEFAULT_DECIMALS["pct"] if decimals is None else decimals)
    return fmt(magnitude, unit, decimals)


def points_text(magnitude: Decimal) -> str:
    """A gap between two shares: "17.5% points"."""
    return show(magnitude, POINTS, 1)


def plain_pct(value: Decimal) -> str:
    return show(value, PLAIN_PCT, 1)


def plain_number(value: Decimal, decimals: int = 1) -> str:
    return fmt_value(value, NUMBER, decimals)


TEMPLATES = {
    "streak.headline": "The {name} has {verb} for {n} weeks in a row, from {first} to {last}.",
    "streak.rule": ("Consecutive weekly {w} ending at the latest point. An unchanged value, or a gap of more than {gap} days between "
                    "points, ends the run. At least {min_run} {w} in a row are needed."),
    "streak.edge.before": "The first point shown is the one before the run and is not part of it.",
    "streak.edge.start": "The run begins at the first point we hold, which is the first point shown; nothing earlier is held.",
    "since.headline.since": "The {name}, {value}, is the {extreme} since {date}.",
    "since.headline.history": "The {name}, {value}, is the {extreme} in the available history, {weeks} weeks ({earliest}).",
    "since.headline.record": ("The {name}, {value}, is a record {hl} in the history we hold: the {extreme} in {weeks} weeks "
                              "({earliest})."),
    "since.earliest.whole": "the earliest point we hold is {date}",
    "since.headline.window": "The {name}, {value}, is the {extreme} in the {weeks} weeks checked, since {date}.",
    "since.rule": ("{extreme} value in the unbroken weekly points. A value equal to the latest counts as at or {side} it, so a tie "
                   "ends the stretch. Gaps of more than {gap} days end the window. The latest value must stand for at least "
                   "{min_stretch} weekly points, in a window of at least {min_points} points."),
    "since.window": "unbroken weekly points, {extreme}",
    "window.edge.start": "The window begins at the first point we hold.",
    "window.edge.gap": "The window begins after a gap of more than {gap} days; points before the gap are not looked at.",
    "trailing.headline": ("The {name}, {latest}, is {diff} {side} the average of the previous {n} weeks, {mean}.{sigma}"),
    "trailing.sigma": " That is {sigma} standard deviations {side} the average.",
    "trailing.rule": ("Latest value against the mean of the previous {n} weekly points (the latest point is not in the mean), "
                      "measured as {mode}. Shown when the difference is at least {threshold} ({unit}). Gaps of more than {gap} days "
                      "between points end the window. The standard deviation is the sample standard deviation of the previous {n} "
                      "points, reported when there are at least 8 of them and it is above zero.{required}"),
    "trailing.required": " The difference must also be at least {sigma} standard deviations.",
    "trailing.window": "previous {n} weeks",
    "cross.headline": "The {name} {verb} {level} for the first time {when}, from {previous} to {latest}.",
    "cross.when.since": "since {date}",
    "cross.when.never.whole": "in the {weeks} weeks we hold, since {date}",
    "cross.when.never.cut": "in the {weeks} weeks checked, since {date}",
    "cross.rule": ("The latest point is at or {side} {level} and the previous point was strictly {other} it. Equal to the level "
                   "counts as reaching it. The last time the series was at or {side} the level is looked up in the unbroken "
                   "weekly points (gaps of more than {gap} days end the window)."),
    "cross.window": "level {level}, unbroken weekly points",
    "range.headline": "The {name}, {latest}, is {side} the range of the previous {n} weeks, {low} to {high}.",
    "range.rule": ("Latest value against the lowest and highest of the previous {n} weekly points (the latest point is not in the "
                   "range). Outside the range when strictly below the lowest or strictly above the highest. Gaps of more than "
                   "{gap} days between points end the window."),
    "slip.headline": "The {name}, {latest}, is {ratio} the median of the previous {n} weeks, {median}.",
    "slip.rule": ("A magnitude check: the latest value against the median of the previous {n} weekly points (the latest point is "
                  "not in it). Shown when the latest is at least {factor} times the median or at most 1/{factor} of it, for a "
                  "median and a latest value above zero. Gaps of more than {gap} days between points end the window."),
    "range.window": "previous {n} weeks",
    "slip.window": "previous {n} weeks, magnitude check",
    "pace.headline": ("The {name} is at {share} of its target with {elapsed} of the period elapsed, {gap} {side} the period's "
                      "pace. Continued in a straight line, the pace so far gives about {projection} by the end of the period "
                      "(a straight-line projection)."),
    "pace.rule": ("The share of the target ({target}, in the series' unit) reached, against the share of the period elapsed, "
                  "counting {days} days from {start} to {as_of} out of {period} days from {start} to {end}, as the net borrowing "
                  "figure counts days. Shown when the two differ by at least {threshold} percentage points and at least "
                  "{min_days} days have elapsed. The projection continues the average pace so far in a straight line; it is "
                  "not a forecast."),
    "pace.window": "period to date",
    "drift.headline": ("{name} moves from {was} to {now} on price alone: upside {upside_was} to {upside_now}, target unchanged at "
                       "Kshs {target}."),
    "drift.rule": ("Upside is the dividend per share over the price plus the target over the price, less one. The target and the "
                   "dividend per share are shown for both weeks, and a move is shown only when each is the same in both weeks. "
                   "Bands from the equities team's rule: Buy at 20% or more, Accumulate at 10% or more, Hold at 5% or more, "
                   "Lighten at 0.1% or more, Sell at 0% or less; between 0% and 0.1% there is no band."),
    "drift.window": "week on week",
}


def say(key: str, **fields: object) -> str:
    return TEMPLATES[key].format(**fields)
