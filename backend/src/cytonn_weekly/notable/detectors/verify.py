"""The independent check on a detector's output.

``verify(suggestion)`` takes a returned suggestion and works the claim out again from nothing but ``working.points`` and
``working.rule``: it reads the rule's parameters back out of the rule text, redoes the arithmetic on the points with its own
code, and compares every figure's value (to 6 decimals, as the figures are stored) and every display (against the value, at
the number of decimals it shows). It then checks that the headline says exactly what the recomputed figures say, with the
right direction words. Any difference raises DetectorSelfCheckError.

It shares no code with the detectors: it does not import the library, the wording or the series modules, and a test reads its
imports to keep it so. It writes its own copy of each sentence it checks, so a template that is changed without changing this
module fails here, loudly, rather than shipping. It may call the house helpers the detectors may not copy: the band rule of the
Universe of Coverage (equities.weekly.recommendation) and round-half-up.

The rule texts are the contract between the two modules. A rule it cannot read is a mismatch, never a pass.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from cytonn_weekly.common.formatting import round_half_up
from cytonn_weekly.notable.suggestion import Suggestion

_Q6 = Decimal("0.000001")


class DetectorSelfCheckError(Exception):
    """A detector's output did not survive being worked out again; the message says which figure or word."""


def _fail(message: str) -> None:
    raise DetectorSelfCheckError(message)


def _q6(x: Decimal) -> Decimal:
    return x.quantize(_Q6, rounding=ROUND_HALF_UP)


def _d(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(value)


# -- reading the suggestion ----------------------------------------------------------------------------------------------

def _points(s: Suggestion) -> list[tuple[date, Decimal]]:
    out = [(date.fromisoformat(p["date"]), _d(p["value"])) for p in s.working["points"]]
    for (a, _), (b, _) in zip(out, out[1:]):
        if b <= a:
            _fail("points: the dates are not in ascending order")
    return out


def _rule(s: Suggestion, pattern: str) -> "re.Match[str]":
    m = re.fullmatch(pattern, s.working["rule"])
    if not m:
        _fail("rule: the rule text is not one this check can read")
    return m


def _gaps_within(pts: list[tuple[date, Decimal]], limit: int, what: str = "points") -> None:
    for (a, _), (b, _) in zip(pts, pts[1:]):
        if (b - a).days > limit:
            _fail(f"{what}: {a.isoformat()} to {b.isoformat()} is a gap of more than {limit} days")


def _on_the_week(s: Suggestion, pts: list[tuple[date, Decimal]]) -> None:
    if pts[-1][0].isoformat() != s.week_ending:
        _fail(f"week: the latest point is {pts[-1][0].isoformat()}, not the week ending {s.week_ending}")


def _kind(s: Suggestion, *allowed: str) -> None:
    if s.kind not in allowed:
        _fail(f"kind: {s.kind!r} is not what the working shows ({' or '.join(allowed)})")


def _window(s: Suggestion, wanted: str) -> None:
    if s.working["window"] != wanted:
        _fail(f"window: {s.working['window']!r}, expected {wanted!r}")


def _shown_number(text: str) -> tuple[bool, Decimal, int]:
    """(is it in brackets, the number it shows, its decimals): "(Kshs 12.3 bn)" is (True, 12.3, 1)."""
    negative = text.startswith("(") and text.endswith(")")
    digits = re.sub(r"[^0-9.]", "", text)
    if not digits or digits.count(".") > 1 or digits == ".":
        _fail(f"display: {text!r} shows no number")
    return negative, Decimal(digits), len(digits.split(".")[1]) if "." in digits else 0


def _figures(s: Suggestion, expected: list[tuple[str, Any]]) -> None:
    """The figures are exactly these, in this order, with these values, and each display shows its value."""
    labels = [f["label"] for f in s.figures]
    if labels != [label for label, _ in expected]:
        _fail(f"figures: expected {[label for label, _ in expected]}, found {labels}")
    for f, (label, value) in zip(s.figures, expected):
        shown = _d(f["value"])
        if _q6(shown) != _q6(_d(value)):
            _fail(f"{label}: shown {shown}, recomputed {_q6(_d(value))}")
        negative, number, decimals = _shown_number(f["display"])
        want = round_half_up(shown, decimals)
        if (-number if negative else number) != want:
            _fail(f"{label}: the display {f['display']!r} does not show {shown} at {decimals} decimals")


def _display(s: Suggestion, index: int) -> str:
    return s.figures[index]["display"]


def _magnitude(text: str) -> str:
    return text[1:-1] if text.startswith("(") and text.endswith(")") else text


def _headline(s: Suggestion, *accepted: str) -> None:
    if s.headline not in accepted:
        _fail(f"headline: {s.headline!r} is not what the figures say ({' | '.join(accepted)})")


# -- one check per detector ----------------------------------------------------------------------------------------------

def _streak(s: Suggestion) -> None:
    m = _rule(s, r"Consecutive weekly (rises|falls) ending at the latest point\. An unchanged value, or a gap of more than (\d+) "
                 r"days between points, ends the run\. At least (\d+) (rises|falls) in a row are needed\. "
                 r"(The first point shown is the one before the run and is not part of it\.|"
                 r"The run begins at the first point we hold, which is the first point shown; nothing earlier is held\.)")
    way = 1 if m[1] == "rises" else -1
    if m[4] != m[1]:
        _fail("rule: the run is named as rises and as falls")
    gap, minimum = int(m[2]), int(m[3])
    ended_by_a_point = m[5].startswith("The first point")
    pts = _points(s)
    _on_the_week(s, pts)
    _kind(s, "streak")
    _window(s, "current run")
    run = pts[1:] if ended_by_a_point else pts  # the rule says which: the first point shown is not part of the run, or it is
    steps = len(run) - 1
    if steps < minimum:
        _fail(f"run: {steps} {m[1]} in the points, the rule needs {minimum}")
    _gaps_within(run, gap)
    for (_, a), (_, b) in zip(run, run[1:]):
        if (b > a) - (b < a) != way:
            _fail(f"run: the points are not {m[1]} all the way")
    if ended_by_a_point:
        # The run is the longest ending at the latest point only if the point before it could not be part of it: it must be level
        # with the run's first point, or move the other way into it, or lie more than the gap earlier.
        (before_day, before), (first_day, first) = pts[0], run[0]
        if (first_day - before_day).days <= gap and (first > before) - (first < before) == way:
            _fail("run: the point before the run continues it, so the run is longer than shown")
    name = s.working["series"]
    _figures(s, [("Weeks in a row", steps), (f"{name}: start of run", run[0][1]), (f"{name}: latest", run[-1][1])])
    _headline(s, f"The {name} has {'risen' if way > 0 else 'fallen'} for {steps} weeks in a row, from {_display(s, 1)} to {_display(s, 2)}.")


def _since(s: Suggestion) -> None:
    m = _rule(s, r"(Highest|Lowest) value in the unbroken weekly points\. A value equal to the latest counts as at or (above|below) "
                 r"it, so a tie ends the stretch\. Gaps of more than (\d+) days end the window\. The latest value must stand for "
                 r"at least (\d+) weekly points, in a window of at least (\d+) points\.")
    highest = m[1] == "Highest"
    if m[2] != ("above" if highest else "below"):
        _fail("rule: the tie rule does not match the direction")
    gap, min_stretch, min_points = int(m[3]), int(m[4]), int(m[5])
    extreme = m[1].lower()
    pts = _points(s)
    _on_the_week(s, pts)
    _gaps_within(pts, gap)
    _window(s, f"unbroken weekly points, {extreme}")
    latest = pts[-1][1]
    beyond = (lambda v: v >= latest) if highest else (lambda v: v <= latest)
    n = len(pts)
    if n - 1 < min_stretch:
        _fail(f"stretch: {n - 1} weekly points, the rule needs {min_stretch}")
    since_case = beyond(pts[0][1])
    if since_case:
        if any(beyond(v) for _, v in pts[1:-1]):
            _fail("stretch: a later point is as extreme as the latest, so the stretch is shorter than shown")
        _kind(s, "since")
    else:
        if any(beyond(v) for _, v in pts[:-1]):
            _fail("stretch: an earlier point is as extreme as the latest")
        _kind(s, "record")
        if n < min_points:
            _fail(f"history: {n} points, the rule needs {min_points}")
    weeks = (pts[-1][0] - pts[0][0]).days // 7
    name = s.working["series"]
    _figures(s, [(f"{name}: latest", latest), ("Weeks the latest value has stood", weeks)])
    value, first = _display(s, 0), pts[0][0].isoformat()
    if since_case:
        _headline(s, f"The {name}, {value}, is the {extreme} since {first}.")
        return
    earliest = (f"the earliest point we hold is {first}", f"weekly points unbroken from {first}")
    if weeks >= 52:
        hl = "high" if highest else "low"
        _headline(s, *[f"The {name}, {value}, is a record {hl} in the history we hold: the {extreme} in {weeks} weeks ({e})." for e in earliest])
    else:
        _headline(s, *[f"The {name}, {value}, is the {extreme} in the available history, {weeks} weeks ({e})." for e in earliest])


def _trailing(s: Suggestion) -> None:
    m = _rule(s, r"Latest value against the mean of the previous (\d+) weekly points \(the latest point is not in the mean\), "
                 r"measured as (a percentage difference|an absolute difference|a difference in basis points)\. Shown when the "
                 r"difference is at least ([0-9.]+) \((percent|units of the series|basis points)\)\. Gaps of more than (\d+) days "
                 r"between points end the window\. The standard deviation is the sample standard deviation of the previous (\d+) "
                 r"points, reported when there are at least 8 of them and it is above zero\.(?: The difference must also be at "
                 r"least ([0-9.]+) standard deviations\.)?")
    n = int(m[1])
    if int(m[6]) != n:
        _fail("rule: the window is named with two different lengths")
    mode = {"a percentage difference": "pct", "an absolute difference": "abs", "a difference in basis points": "bps"}[m[2]]
    if m[4] != {"pct": "percent", "abs": "units of the series", "bps": "basis points"}[mode]:
        _fail("rule: the threshold's unit does not match the way the difference is measured")
    threshold, gap = Decimal(m[3]), int(m[5])
    needed = Decimal(m[7]) if m[7] else None
    pts = _points(s)
    _on_the_week(s, pts)
    _kind(s, "trailing_compare")
    _window(s, f"previous {n} weeks")
    if len(pts) != n + 1:
        _fail(f"points: {len(pts)} points shown, the rule names {n} before the latest and the latest")
    _gaps_within(pts, gap)
    before, latest = [v for _, v in pts[:-1]], pts[-1][1]
    mean = sum(before, Decimal(0)) / n
    if mode == "pct":
        if mean == 0:
            _fail("mean: a zero mean has no percentage difference")
        diff = (latest / mean - 1) * 100
    elif mode == "bps":
        diff = (latest - mean) * 100
    else:
        diff = latest - mean
    if abs(diff) < threshold:
        _fail(f"difference: {_q6(diff)} is below the stated threshold {threshold}")
    sigma = None
    if n >= 8:
        variance = sum(((x - mean) ** 2 for x in before), Decimal(0)) / (n - 1)
        if variance > 0:
            sigma = (latest - mean) / variance.sqrt()
    if needed is not None and (sigma is None or abs(sigma) < needed):
        _fail("difference: the stated number of standard deviations is not reached")
    name = s.working["series"]
    label = {"pct": "Difference from the mean, in percent", "bps": "Difference from the mean, in basis points",
             "abs": "Difference from the mean (absolute)"}[mode]
    expected = [(f"{name}: latest", latest), (f"{name}: mean of the previous {n} weeks", mean), (label, diff)]
    if sigma is not None:
        expected.append(("Standard deviations from the mean", sigma))
    _figures(s, expected)
    side = "above" if diff > 0 else "below"
    size = _magnitude(_display(s, 2))
    if s.figures[2]["unit"] == "pct_points":
        size += " points"
    tail = f" That is {_magnitude(_display(s, 3))} standard deviations {side} the average." if sigma is not None else ""
    _headline(s, f"The {name}, {_display(s, 0)}, is {size} {side} the average of the previous {n} weeks, {_display(s, 1)}.{tail}")


def _cross(s: Suggestion) -> None:
    m = _rule(s, r"The latest point is at or (above|below) (-?[0-9.]+) and the previous point was strictly (below|above) it\. Equal "
                 r"to the level counts as reaching it\. The last time the series was at or (above|below) the level is looked up in "
                 r"the unbroken weekly points \(gaps of more than (\d+) days end the window\)\.")
    up = m[1] == "above"
    if m[4] != m[1] or m[3] != ("below" if up else "above"):
        _fail("rule: the sides of the level do not agree")
    level, gap = Decimal(m[2]), int(m[5])
    pts = _points(s)
    _on_the_week(s, pts)
    _kind(s, "threshold_cross")
    _window(s, f"level {m[2]}, unbroken weekly points")
    _gaps_within(pts, gap)
    if len(pts) < 2:
        _fail("points: a crossing needs a previous point and a latest point")
    (_, before), (_, latest) = pts[-2], pts[-1]
    at_or_beyond = (lambda v: v >= level) if up else (lambda v: v <= level)
    strictly_other = (lambda v: v < level) if up else (lambda v: v > level)
    if not (strictly_other(before) and at_or_beyond(latest)):
        _fail("crossing: the previous point is not strictly on the other side, or the latest is not at or beyond the level")
    since_case = len(pts) > 2 and at_or_beyond(pts[0][1])
    if since_case:
        if not all(strictly_other(v) for _, v in pts[1:-1]):
            _fail("history: a later point is on the same side, so it was not the last time")
    elif not all(strictly_other(v) for _, v in pts[:-1]):
        _fail("history: an earlier point is on the same side, so it is not the first time")
    weeks = (pts[-1][0] - pts[0][0]).days // 7
    name, side = s.working["series"], m[1]
    _figures(s, [(f"{name}: latest", latest), (f"{name}: previous week", before), ("Level", level),
                 (f"Weeks since the series was last at or {side} the level" if since_case else "Weeks of history held", weeks)])
    verb = "reached" if latest == level else f"moved {side}"
    when = f"since {pts[0][0].isoformat()}" if since_case else "in the history we hold"
    _headline(s, f"The {name} {verb} {_display(s, 2)} for the first time {when}, from {_display(s, 1)} to {_display(s, 0)}.")


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    k = len(ordered)
    return ordered[k // 2] if k % 2 else (ordered[k // 2 - 1] + ordered[k // 2]) / 2


def _range(s: Suggestion) -> None:
    slip = s.working["window"].endswith(", magnitude check")
    gap_clause = r"Gaps of more than (\d+) days between points end the window\."
    if slip:
        m = _rule(s, r"A magnitude check: the latest value against the median of the previous (\d+) weekly points \(the latest point "
                     r"is not in it\)\. Shown when the latest is at least ([0-9.]+) times the median or at most 1/([0-9.]+) of it, "
                     r"for a median and a latest value above zero\. " + gap_clause)
        n, factor, gap = int(m[1]), Decimal(m[2]), int(m[4])
        if Decimal(m[3]) != factor:
            _fail("rule: the factor is named two ways")
    else:
        m = _rule(s, r"Latest value against the lowest and highest of the previous (\d+) weekly points \(the latest point is not in "
                     r"the range\)\. Outside the range when strictly below the lowest or strictly above the highest\. " + gap_clause)
        n, gap = int(m[1]), int(m[2])
    pts = _points(s)
    _on_the_week(s, pts)
    _kind(s, "expected_range")
    _window(s, f"previous {n} weeks, magnitude check" if slip else f"previous {n} weeks")
    if len(pts) != n + 1:
        _fail(f"points: {len(pts)} points shown, the rule names {n} before the latest and the latest")
    _gaps_within(pts, gap)
    before, latest = [v for _, v in pts[:-1]], pts[-1][1]
    name = s.working["series"]
    if slip:
        median = _median(before)
        if not (median > 0 and latest > 0 and (latest >= factor * median or latest * factor <= median)):
            _fail("slip: the latest is not that far from the median, or the median or latest is not above zero")
        _figures(s, [(f"{name}: latest", latest), (f"{name}: median of the previous {n} weeks", median),
                     ("Latest as a multiple of the median", latest / median)])
        _headline(s, f"The {name}, {_display(s, 0)}, is {_display(s, 2)} the median of the previous {n} weeks, {_display(s, 1)}.")
        return
    low, high = min(before), max(before)
    if not (latest < low or latest > high):
        _fail("range: the latest is inside the range")
    excess = low - latest if latest < low else latest - high
    _figures(s, [(f"{name}: latest", latest), (f"{name}: lowest of the previous {n} weeks", low),
                 (f"{name}: highest of the previous {n} weeks", high), ("Distance outside the range", excess)])
    _headline(s, f"The {name}, {_display(s, 0)}, is {'below' if latest < low else 'above'} the range of the previous {n} weeks, "
                 f"{_display(s, 1)} to {_display(s, 2)}.")


def _pace(s: Suggestion) -> None:
    m = _rule(s, r"The share of the target \(([0-9.]+), in the series' unit\) reached, against the share of the period elapsed, "
                 r"counting (\d+) days from (\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2}) out of (\d+) days from (\d{4}-\d{2}-\d{2}) to "
                 r"(\d{4}-\d{2}-\d{2}), as the net borrowing figure counts days\. Shown when the two differ by at least ([0-9.]+) "
                 r"percentage points and at least (\d+) days have elapsed\. The projection continues the average pace so far in a "
                 r"straight line; it is not a forecast\.")
    target, threshold, min_days = Decimal(m[1]), Decimal(m[8]), int(m[9])
    start, as_of, end = date.fromisoformat(m[3]), date.fromisoformat(m[4]), date.fromisoformat(m[7])
    if m[3] != m[6]:
        _fail("rule: the period has two different starts")
    pts = _points(s)
    if pts[-1][0] != as_of:
        _fail(f"as-of: the latest point is {pts[-1][0].isoformat()}, the rule says {as_of.isoformat()}")
    week = date.fromisoformat(s.week_ending)
    if not (0 <= (as_of - week).days <= 7):
        _fail(f"week: the as-of date {as_of.isoformat()} is not within a week after the week ending {s.week_ending}")
    _kind(s, "pace")
    _window(s, "period to date")
    elapsed, period = (as_of - start).days, (end - start).days
    if int(m[2]) != elapsed or int(m[5]) != period:
        _fail(f"days: the rule says {m[2]} of {m[5]}, the dates make it {elapsed} of {period}")
    if not (0 < elapsed <= period) or elapsed < min_days:
        _fail("period: the as-of date is outside the period or too early in it")
    if pts[0][0] < start:
        _fail("points: a point is before the period starts")
    actual = pts[-1][1]
    share_target = actual / target * 100
    share_period = Decimal(elapsed) / Decimal(period) * 100
    gap = share_target - share_period
    if abs(gap) < threshold:
        _fail(f"gap: {_q6(gap)} points is below the stated threshold {threshold}")
    name = s.working["series"]
    _figures(s, [(f"{name}: to date", actual), ("Target", target), ("Share of target reached", share_target),
                 ("Share of period elapsed", share_period), ("Difference in percentage points", gap),
                 ("Straight-line projection for the end of the period", actual / Decimal(elapsed) * Decimal(period)),
                 ("Days elapsed", elapsed), ("Days in the period", period)])
    _headline(s, f"The {name} is at {_display(s, 2)} of its target with {_display(s, 3)} of the period elapsed, "
                 f"{_magnitude(_display(s, 4))}% points {'ahead of' if gap > 0 else 'behind'} the period's pace. Continued in a "
                 f"straight line, the pace so far gives about {_display(s, 5)} by the end of the period (a straight-line projection).")


def _drift(s: Suggestion) -> None:
    from cytonn_weekly.equities.weekly import recommendation  # imported here: the module pulls in the workbook readers

    m = _rule(s, r"Upside is the dividend per share over the price plus the target over the price, less one\. The target \(Kshs "
                 r"([0-9.]+)\) and the dividend per share \(Kshs ([0-9.]+)\) are the same in both weeks, and nothing here changes "
                 r"them\. Bands from the equities team's rule: Buy at 20% or more, Accumulate at 10% or more, Hold at 5% or more, "
                 r"Lighten at 0\.1% or more, Sell at 0% or less; between 0% and 0\.1% there is no band\.")
    target, dividend = Decimal(m[1]), Decimal(m[2])
    pts = _points(s)
    _on_the_week(s, pts)
    _kind(s, "drift")
    _window(s, "week on week")
    if len(pts) != 2 or (pts[1][0] - pts[0][0]).days != 7:
        _fail("points: two prices a week apart are the working")
    (_, before), (_, now) = pts
    up_before, up_now = (dividend + target - before) / before * 100, (dividend + target - now) / now * 100
    # called as the Universe of Coverage table calls it, with float(Decimal): its thresholds are float literals
    band_before, band_now = recommendation(float(up_before)), recommendation(float(up_now))
    if band_before == band_now:
        _fail("band: the band is the same in both weeks")
    name = s.working["series"]
    if not name.endswith(" price"):
        _fail("series: a drift's series is the company's price")
    name = name[: -len(" price")]
    _figures(s, [(f"{name}: price now", now), (f"{name}: price a week earlier", before), ("Upside now", up_now),
                 ("Upside a week earlier", up_before), ("Target", target), ("Dividend per share", dividend)])
    for index, band in ((2, band_now), (3, band_before)):  # the displayed upside must fall in the band it is named with
        negative, number, _ = _shown_number(_display(s, index))
        if recommendation(float(-number if negative else number)) != band:
            _fail(f"{s.figures[index]['label']}: the display {_display(s, index)!r} falls in a different band")
    shown_target = _display(s, 4)[len("Kshs "):]
    _headline(s, f"{name} moves from {band_before or 'no band'} to {band_now or 'no band'} on price alone: upside {_display(s, 3)} to "
                 f"{_display(s, 2)}, target unchanged at Kshs {shown_target}.")


_CHECKS = {"streak": _streak, "since": _since, "record": _since, "trailing_compare": _trailing, "threshold_cross": _cross,
           "expected_range": _range, "pace": _pace, "drift": _drift}


def verify(s: Suggestion) -> None:
    """Work the suggestion out again from its working and compare; raise DetectorSelfCheckError on any difference."""
    check: Optional[Any] = _CHECKS.get(s.kind)
    if check is None:
        _fail(f"kind: no check for {s.kind!r}")
    try:
        check(s)
    except DetectorSelfCheckError:
        raise
    except Exception as exc:  # noqa: BLE001 - anything unreadable is a mismatch, not a pass
        raise DetectorSelfCheckError(f"{s.kind}: the working could not be checked ({type(exc).__name__}: {exc})") from None
