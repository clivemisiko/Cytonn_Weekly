"""The seven "Notable this week" detectors: plain functions over a Series (or a few numbers) that return suggestions.

Nothing here reads the database, a workbook, a file or the network, and nothing is registered anywhere: a later task feeds these
from a history store and registers wrappers. Every function is pure and deterministic, takes keyword-only parameters after the
series, and returns a list of Suggestion in the notable shape (version 1). A detector may only say what the points it was given
support. It never extrapolates, never guesses and never repairs a series.

Rules every detector shares
    Freshness   It returns nothing unless the series' latest point is dated ``week_ending`` (``pace`` takes the as-of date of its
                cumulative figure instead, see below).
    History     Each detector states a minimum number of points and returns nothing below it.
    Regularity  Weekly series. A gap between neighbouring points above ``max_gap_days`` (default 10) ends the usable window: a
                run, a stretch, a mean or a range never spans it.
    Numbers     Exact Decimal throughout. A derived figure is rounded half up to 6 decimals once, and the display (house formats,
                see wording.py) is rounded from that. Dates in a headline are written 2026-10-09.
    Self-check  Each suggestion is verified by verify.py, which shares no code with this module, before it is returned; a mismatch
                raises DetectorSelfCheckError.

Detectors, defaults and what makes each fire
    streak(series, *, section, week_ending, min_run=4, max_gap_days=10)
        Consecutive weekly rises (or falls) ending at the latest point; an unchanged value or a gap ends the run. Needs at least
        min_run + 1 points. Working: the point before the run (oldest, and not part of it: a tie, a move the other way, or a gap
        above max_gap_days, which is what stopped the run from being longer), then the run and the point it began from. When the
        run begins at the first point of the series, nothing is added and the rule says so.
    since(series, *, section, week_ending, min_points=26, min_stretch=12, max_gap_days=10)
        The latest value is the highest (or lowest) since an earlier date, or in all the unbroken points we hold. A value equal to
        the latest counts as at or above (below) it, so a tie ends the stretch. Needs a window of min_points and a stretch of at
        least min_stretch weekly points. The word "record" is used only when the history spans 52 weeks, and then still "in the
        history we hold". Working: from the point that ends the stretch, or the whole window.
    trailing_compare(series, *, section, week_ending, threshold, mode="pct", window_n=12, require_sigma=None, max_gap_days=10)
        The latest against the mean of the previous window_n points (the latest is not in the mean), as a percentage ("pct"),
        an absolute difference ("abs") or basis points ("bps", percentage series only). The caller supplies the threshold; there is
        no default per series. Needs window_n + 1 points. With at least 8 previous points and a spread above zero the number of
        standard deviations (sample) is shown, and required only when require_sigma is set. A zero mean in "pct" mode gives nothing.
    threshold_cross(series, *, section, week_ending, level, min_points=12, max_gap_days=10)
        The previous point was strictly on one side of ``level`` and the latest is at or beyond it (equal to the level counts as
        reaching it). Says when the series was last on that side, or that it was never in the history we hold. The two points must
        be consecutive weeks. Working: from the last time on that side, or the whole window.
    expected_range(series, *, section, week_ending, window_n=26, slip_factor=5, max_gap_days=10)
        The latest is strictly outside the lowest-to-highest of the previous window_n points; and, as a separate signal, the latest
        is at least slip_factor times or at most 1/slip_factor of their median (a decimal-slip check; needs a median and a latest
        value above zero). Needs window_n + 1 points. This is the check the analyst form will reuse.
    pace(cumulative, *, section, week_ending, target, period_start, period_end, as_of, threshold_pp, min_elapsed_days=28)
        The share of ``target`` reached against the share of the period elapsed, counting days as fixed_income/net_borrowing does
        (days from the start to the as-of date, over the days from start to end: pass period_end = start + 364 days for the
        fiscal year). The cumulative figure's latest point must be dated ``as_of``, and ``as_of`` must fall from week_ending to
        seven days after it (a value date after the Friday). Fires at a gap of at least threshold_pp percentage points. States a
        straight-line projection, labelled as one.
    drift(*, name, section, week_ending, price_now, price_previous, target, dividend_per_share, provenance)
        Upside (dividend per share over price plus target over price, less one) in both weeks, with the band from
        equities.weekly.recommendation. Fires only when the band changes. The target and the dividend per share are one pair of
        numbers, passed once, and the suggestion states they did not change. It never says the target should.

Rank (0 to 100, whole numbers, no randomness; each rises with what the detector measures)
    streak            min(100, 40 + 10 x (run - min_run))
    since             min(100, 30 + weeks the latest value has stood)
    trailing_compare  min(100, 40 + floor(20 x (|difference| / threshold - 1)))
    threshold_cross   min(100, 40 + weeks since last on that side, or weeks of history held)
    expected_range    outside the range: 50 + min(35, floor(10 x distance outside / width of the range)), or 60 when the range has
                      no width; decimal slip: 90 (above any range rank, which stops at 85)
    pace              min(100, 40 + floor(2 x |difference in percentage points|))
    drift             min(100, 50 + 10 x steps), steps being the distance between the two bands on the order Sell, no band, Lighten,
                      Hold, Accumulate, Buy
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Optional

from cytonn_weekly.common.formatting import PCT, PRICE, fmt_value, round_half_up
from cytonn_weekly.notable.detectors.series import Provenance, Series
from cytonn_weekly.notable.detectors.verify import verify
from cytonn_weekly.notable.detectors.wording import (
    count,
    difference_text,
    fmt,
    multiple,
    plain_number,
    plain_pct,
    points_text,
    price,
    say,
)
from cytonn_weekly.notable.suggestion import Suggestion

_Q6 = Decimal("0.000001")
MODES = ("pct", "abs", "bps")


# -- small helpers -------------------------------------------------------------------------------------------------------

def _q6(x: Decimal) -> Decimal:
    return x.quantize(_Q6, rounding=ROUND_HALF_UP)


def _floor(x: Decimal) -> int:
    return int(x.to_integral_value(rounding=ROUND_FLOOR))


def _dec(name: str, value: Any, *, positive: bool = False, nonnegative: bool = False) -> Decimal:
    if value is None or isinstance(value, (float, bool)):
        raise ValueError(f"{name} must be given as a string, a whole number or a Decimal, never a float")
    try:
        d = value if isinstance(value, Decimal) else Decimal(value.strip() if isinstance(value, str) else value)
    except (InvalidOperation, TypeError):
        raise ValueError(f"{name} must be a number") from None
    if not d.is_finite():
        raise ValueError(f"{name} must be a finite number")
    if positive and d <= 0:
        raise ValueError(f"{name} must be above zero")
    if nonnegative and d < 0:
        raise ValueError(f"{name} must be zero or more")
    return d


def _whole(name: str, value: Any, at_least: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < at_least:
        raise ValueError(f"{name} must be a whole number of at least {at_least}")
    return value


def _week(week_ending: Any) -> date:
    if not isinstance(week_ending, date):
        raise TypeError("week_ending must be a date")
    return week_ending


def _raw(d: Decimal) -> str:
    """A caller's number as they wrote it (10, 0.30), for the rule text."""
    return format(d, "f")


def _fig(label: str, value: Any, display: str, unit: str) -> dict:
    return {"label": label, "value": value, "display": display, "unit": unit}


def _shown(points, unit: str, decimals: Optional[int]) -> list[dict]:
    return [{"date": p.date.isoformat(), "value": p.value, "display": fmt(p.value, unit, decimals)} for p in points]


def _make(kind: str, section: str, week: date, headline: str, figures: list, series_name: str, rule: str, window: str,
          points: list, provenance: Provenance, rank: int) -> Suggestion:
    return Suggestion(
        kind=kind, section=section, week_ending=week.isoformat(), headline=headline, figures=figures,
        working={"series": series_name, "rule": rule, "window": window, "points": points},
        provenance=provenance.to_dict(), rank=min(100, int(rank)),
    )


def _finish(found: list[Suggestion]) -> list[Suggestion]:
    """Every suggestion is checked by the independent verifier before it leaves the library."""
    for s in found:
        verify(s)
    return found


def _weeks(later: date, earlier: date) -> int:
    return (later - earlier).days // 7


# -- 1. streak -------------------------------------------------------------------------------------------------------------

def streak(series: Series, *, section: str, week_ending: date, min_run: int = 4, max_gap_days: int = 10) -> list[Suggestion]:
    min_run = _whole("min_run", min_run, 2)
    week = _week(week_ending)
    pts = series.points
    n = len(pts)
    if pts[-1].date != week or n < min_run + 1:
        return []

    def step(i: int) -> int:  # +1 a rise, -1 a fall, 0 a tie or a gap
        if (pts[i].date - pts[i - 1].date).days > max_gap_days:
            return 0
        return (pts[i].value > pts[i - 1].value) - (pts[i].value < pts[i - 1].value)

    way = step(n - 1)
    if way == 0:
        return []
    run, i = 0, n - 1
    while i >= 1 and step(i) == way:
        run += 1
        i -= 1
    if run < min_run:
        return []
    shown = pts[n - 1 - run:]
    ended_by = pts[n - 2 - run:n - 1 - run]  # the point that stopped the run from being longer; empty when the run begins the series
    unit, dec, name = series.unit, series.decimals, series.name
    rises = "rises" if way > 0 else "falls"
    headline = say("streak.headline", name=name, verb="risen" if way > 0 else "fallen", n=run,
                   first=fmt(shown[0].value, unit, dec), last=fmt(shown[-1].value, unit, dec))
    figures = [_fig("Weeks in a row", run, count(run), "weeks"),
               _fig(f"{name}: start of run", shown[0].value, fmt(shown[0].value, unit, dec), unit),
               _fig(f"{name}: latest", shown[-1].value, fmt(shown[-1].value, unit, dec), unit)]
    rule = say("streak.rule", w=rises, gap=max_gap_days, min_run=min_run)
    rule += " " + say("streak.edge.before" if ended_by else "streak.edge.start")
    return _finish([_make("streak", section, week, headline, figures, name, rule, "current run", _shown(ended_by + shown, unit, dec),
                          series.provenance, 40 + 10 * (run - min_run))])


# -- 2. since --------------------------------------------------------------------------------------------------------------

def since(series: Series, *, section: str, week_ending: date, min_points: int = 26, min_stretch: int = 12,
          max_gap_days: int = 10) -> list[Suggestion]:
    min_points = _whole("min_points", min_points, 2)
    min_stretch = _whole("min_stretch", min_stretch, 1)
    week = _week(week_ending)
    if series.latest.date != week:
        return []
    window = series.unbroken(max_gap_days)
    if len(window) < min_points:
        return []
    latest, n = window[-1], len(window)
    unit, dec, name = series.unit, series.decimals, series.name
    out = []
    for extreme, side, hl in (("highest", "above", "high"), ("lowest", "below", "low")):
        # a tie counts as at or beyond the latest value, so it ends the stretch
        beyond = (lambda v: v >= latest.value) if extreme == "highest" else (lambda v: v <= latest.value)
        j = next((k for k in range(n - 2, -1, -1) if beyond(window[k].value)), None)
        stretch = n - 1 - (j if j is not None else 0)
        if stretch < min_stretch:
            continue
        start = window[j] if j is not None else window[0]
        weeks = _weeks(latest.date, start.date)
        value = fmt(latest.value, unit, dec)
        if j is not None:
            headline = say("since.headline.since", name=name, value=value, extreme=extreme, date=start.date.isoformat())
        else:
            earliest = say("since.earliest.whole" if len(window) == len(series.points) else "since.earliest.window",
                           date=start.date.isoformat())
            key = "since.headline.record" if weeks >= 52 else "since.headline.history"
            headline = say(key, name=name, value=value, extreme=extreme, hl=hl, weeks=weeks, earliest=earliest)
        figures = [_fig(f"{name}: latest", latest.value, value, unit),
                   _fig("Weeks the latest value has stood", weeks, count(weeks), "weeks")]
        rule = say("since.rule", extreme=extreme.capitalize(), side=side, gap=max_gap_days, min_stretch=min_stretch,
                   min_points=min_points)
        shown = window[j:] if j is not None else window
        out.append(_make("since" if j is not None else "record", section, week, headline, figures, name, rule,
                         say("since.window", extreme=extreme), _shown(shown, unit, dec), series.provenance, 30 + weeks))
    return _finish(out)


# -- 3. trailing_compare ---------------------------------------------------------------------------------------------------

def trailing_compare(series: Series, *, section: str, week_ending: date, threshold: Any, mode: str = "pct", window_n: int = 12,
                     require_sigma: Any = None, max_gap_days: int = 10) -> list[Suggestion]:
    limit = _dec("threshold", threshold, positive=True)
    if mode not in MODES:
        raise ValueError(f"mode must be one of {list(MODES)}, not {mode!r}")
    if mode == "bps" and series.unit != "pct":
        raise ValueError("bps mode needs a series in pct")
    window_n = _whole("window_n", window_n, 2)
    needed = None if require_sigma is None else _dec("require_sigma", require_sigma, positive=True)
    week = _week(week_ending)
    if series.latest.date != week:
        return []
    window = series.unbroken(max_gap_days)
    if len(window) < window_n + 1:
        return []
    shown, latest = window[-1 - window_n:], window[-1]
    before = [p.value for p in shown[:-1]]
    mean = sum(before, Decimal(0)) / window_n
    if mode == "pct":
        if mean == 0:
            return []
        diff = (latest.value / mean - 1) * 100
    elif mode == "bps":
        diff = (latest.value - mean) * 100
    else:
        diff = latest.value - mean
    sigma = None
    if window_n >= 8:
        variance = sum(((x - mean) ** 2 for x in before), Decimal(0)) / (window_n - 1)
        if variance > 0:
            sigma = (latest.value - mean) / variance.sqrt()
    if abs(diff) < limit or (needed is not None and (sigma is None or abs(sigma) < needed)):
        return []
    unit, dec, name = series.unit, series.decimals, series.name
    mean_q, diff_q = _q6(mean), _q6(diff)
    side = "above" if diff > 0 else "below"
    if mode == "pct":
        label, shown_diff, diff_unit = "Difference from the mean, in percent", fmt_value(diff_q, PCT, 1), "pct"
    elif mode == "bps":
        label, shown_diff, diff_unit = "Difference from the mean, in basis points", fmt(diff_q, "bps", 1), "bps"
    else:
        label, shown_diff = "Difference from the mean (absolute)", fmt(diff_q, unit, dec)
        diff_unit = "pct_points" if unit == "pct" else unit
    figures = [_fig(f"{name}: latest", latest.value, fmt(latest.value, unit, dec), unit),
               _fig(f"{name}: mean of the previous {window_n} weeks", mean_q, fmt(mean_q, unit, dec), unit),
               _fig(label, diff_q, shown_diff, diff_unit)]
    tail = ""
    if sigma is not None:
        sigma_q = _q6(sigma)
        figures.append(_fig("Standard deviations from the mean", sigma_q, plain_number(sigma_q), "standard_deviations"))
        tail = say("trailing.sigma", sigma=plain_number(abs(sigma_q)), side=side)
    headline = say("trailing.headline", name=name, latest=figures[0]["display"], diff=difference_text(mode, abs(diff_q), unit, dec),
                   side=side, n=window_n, mean=figures[1]["display"], sigma=tail)
    rule = say("trailing.rule", n=window_n, mode={"pct": "a percentage difference", "abs": "an absolute difference",
                                                 "bps": "a difference in basis points"}[mode],
               threshold=_raw(limit), unit={"pct": "percent", "abs": "units of the series", "bps": "basis points"}[mode],
               gap=max_gap_days, required="" if needed is None else say("trailing.required", sigma=_raw(needed)))
    rank = 40 + _floor(20 * (abs(diff) / limit - 1))
    return _finish([_make("trailing_compare", section, week, headline, figures, name, rule,
                          say("trailing.window", n=window_n), _shown(shown, unit, dec), series.provenance, rank)])


# -- 4. threshold_cross ----------------------------------------------------------------------------------------------------

def threshold_cross(series: Series, *, section: str, week_ending: date, level: Any, min_points: int = 12,
                    max_gap_days: int = 10) -> list[Suggestion]:
    line = _dec("level", level)
    min_points = _whole("min_points", min_points, 2)
    week = _week(week_ending)
    pts = series.points
    if pts[-1].date != week or len(pts) < 2:
        return []
    before, latest = pts[-2], pts[-1]
    if (latest.date - before.date).days > max_gap_days:
        return []
    window = series.unbroken(max_gap_days)
    if len(window) < min_points:
        return []
    if before.value < line <= latest.value:
        up = True
    elif before.value > line >= latest.value:
        up = False
    else:
        return []
    on_side = (lambda v: v >= line) if up else (lambda v: v <= line)
    j = next((k for k in range(len(window) - 3, -1, -1) if on_side(window[k].value)), None)  # earlier than the previous point
    unit, dec, name = series.unit, series.decimals, series.name
    side, other = ("above", "below") if up else ("below", "above")
    start = window[j] if j is not None else window[0]
    weeks = _weeks(latest.date, start.date)
    reached = latest.value == line
    verb = "reached" if reached else f"moved {side}"
    when = say("cross.when.since", date=start.date.isoformat()) if j is not None else say("cross.when.never")
    level_shown = fmt(line, unit, dec)
    headline = say("cross.headline", name=name, verb=verb, level=level_shown, when=when, previous=fmt(before.value, unit, dec),
                   latest=fmt(latest.value, unit, dec))
    weeks_label = f"Weeks since the series was last at or {side} the level" if j is not None else "Weeks of history held"
    figures = [_fig(f"{name}: latest", latest.value, fmt(latest.value, unit, dec), unit),
               _fig(f"{name}: previous week", before.value, fmt(before.value, unit, dec), unit),
               _fig("Level", line, level_shown, unit), _fig(weeks_label, weeks, count(weeks), "weeks")]
    rule = say("cross.rule", side=side, other=other, level=_raw(line), gap=max_gap_days)
    shown = window[j:] if j is not None else window
    return _finish([_make("threshold_cross", section, week, headline, figures, name, rule,
                          say("cross.window", level=_raw(line)), _shown(shown, unit, dec), series.provenance, 40 + weeks)])


# -- 5. expected_range -----------------------------------------------------------------------------------------------------

def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def expected_range(series: Series, *, section: str, week_ending: date, window_n: int = 26, slip_factor: Any = 5,
                   max_gap_days: int = 10) -> list[Suggestion]:
    window_n = _whole("window_n", window_n, 2)
    factor = _dec("slip_factor", slip_factor, positive=True)
    if factor <= 1:
        raise ValueError("slip_factor must be above 1")
    week = _week(week_ending)
    if series.latest.date != week:
        return []
    window = series.unbroken(max_gap_days)
    if len(window) < window_n + 1:
        return []
    shown, latest = window[-1 - window_n:], window[-1]
    before = [p.value for p in shown[:-1]]
    low, high = min(before), max(before)
    unit, dec, name = series.unit, series.decimals, series.name
    latest_shown = fmt(latest.value, unit, dec)
    out = []
    if latest.value < low or latest.value > high:
        excess = low - latest.value if latest.value < low else latest.value - high
        width = high - low
        excess_q = _q6(excess)
        figures = [_fig(f"{name}: latest", latest.value, latest_shown, unit),
                   _fig(f"{name}: lowest of the previous {window_n} weeks", low, fmt(low, unit, dec), unit),
                   _fig(f"{name}: highest of the previous {window_n} weeks", high, fmt(high, unit, dec), unit),
                   _fig("Distance outside the range", excess_q, fmt(excess_q, unit, dec), unit)]
        headline = say("range.headline", name=name, latest=latest_shown, side="below" if latest.value < low else "above", n=window_n,
                       low=figures[1]["display"], high=figures[2]["display"])
        rank = 60 if width == 0 else 50 + min(35, _floor(10 * excess / width))
        out.append(_make("expected_range", section, week, headline, figures, name,
                         say("range.rule", n=window_n, gap=max_gap_days), say("range.window", n=window_n), _shown(shown, unit, dec), series.provenance, rank))
    median = _median(before)
    if median > 0 and latest.value > 0 and (latest.value >= factor * median or latest.value * factor <= median):
        median_q, ratio_q = _q6(median), _q6(latest.value / median)
        figures = [_fig(f"{name}: latest", latest.value, latest_shown, unit),
                   _fig(f"{name}: median of the previous {window_n} weeks", median_q, fmt(median_q, unit, dec), unit),
                   _fig("Latest as a multiple of the median", ratio_q, multiple(ratio_q), "multiple")]
        headline = say("slip.headline", name=name, latest=latest_shown, ratio=figures[2]["display"], n=window_n,
                       median=figures[1]["display"])
        out.append(_make("expected_range", section, week, headline, figures, name,
                         say("slip.rule", n=window_n, factor=_raw(factor), gap=max_gap_days), say("slip.window", n=window_n),
                         _shown(shown, unit, dec), series.provenance, 90))
    return _finish(out)


# -- 6. pace ---------------------------------------------------------------------------------------------------------------

def pace(cumulative: Series, *, section: str, week_ending: date, target: Any, period_start: date, period_end: date, as_of: date,
         threshold_pp: Any, min_elapsed_days: int = 28) -> list[Suggestion]:
    total = _dec("target", target, positive=True)
    limit = _dec("threshold_pp", threshold_pp, positive=True)
    min_days = _whole("min_elapsed_days", min_elapsed_days, 1)
    week = _week(week_ending)
    if not (isinstance(period_start, date) and isinstance(period_end, date) and isinstance(as_of, date)):
        raise TypeError("period_start, period_end and as_of must be dates")
    if period_end <= period_start:
        raise ValueError("period_end must be after period_start")
    if cumulative.latest.date != as_of or not (week <= as_of <= week + timedelta(days=7)):
        return []
    if not (period_start < as_of <= period_end):
        return []
    if cumulative.points[0].date < period_start:
        raise ValueError(f"a point is outside the period: {cumulative.points[0].date.isoformat()} is before it starts")
    from cytonn_weekly.fixed_income.net_borrowing import Log  # imported here: it pulls in the CBK PDF reader

    elapsed = Log(fy_start=period_start, limit=as_of, as_at=as_of).days  # net_borrowing's own day count
    period = (period_end - period_start).days
    if elapsed < min_days:
        return []
    actual = cumulative.latest.value
    share_target = actual / total * 100
    share_period = Decimal(elapsed) / Decimal(period) * 100
    gap = share_target - share_period
    if abs(gap) < limit:
        return []
    projection = actual / Decimal(elapsed) * Decimal(period)
    unit, dec, name = cumulative.unit, cumulative.decimals, cumulative.name
    st, sp, gq, pq = _q6(share_target), _q6(share_period), _q6(gap), _q6(projection)
    figures = [_fig(f"{name}: to date", actual, fmt(actual, unit, dec), unit), _fig("Target", total, fmt(total, unit, dec), unit),
               _fig("Share of target reached", st, plain_pct(st), "pct"), _fig("Share of period elapsed", sp, plain_pct(sp), "pct"),
               _fig("Difference in percentage points", gq, plain_number(gq), "pct_points"),
               _fig("Straight-line projection for the end of the period", pq, fmt(pq, unit, dec), unit),
               _fig("Days elapsed", elapsed, count(elapsed), "days"), _fig("Days in the period", period, count(period), "days")]
    headline = say("pace.headline", name=name, share=plain_pct(st), elapsed=plain_pct(sp), gap=points_text(abs(gq)),
                   side="ahead of" if gap > 0 else "behind", projection=figures[5]["display"])
    rule = say("pace.rule", target=_raw(total), days=elapsed, start=period_start.isoformat(), as_of=as_of.isoformat(), period=period,
               end=period_end.isoformat(), threshold=_raw(limit), min_days=min_days)
    return _finish([_make("pace", section, week, headline, figures, name, rule, say("pace.window"), _shown(cumulative.points, unit, dec),
                          cumulative.provenance, 40 + _floor(2 * abs(gap)))])


# -- 7. drift --------------------------------------------------------------------------------------------------------------

_BAND_ORDER = {"Sell": 0, None: 1, "Lighten": 2, "Hold": 3, "Accumulate": 4, "Buy": 5}


def drift(*, name: str, section: str, week_ending: date, price_now: Any, price_previous: Any, target: Any, dividend_per_share: Any,
          provenance: Provenance) -> list[Suggestion]:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be the company's name")
    if not isinstance(provenance, Provenance):
        raise TypeError("provenance must be a Provenance object")
    week = _week(week_ending)
    now, before = _dec("price_now", price_now, positive=True), _dec("price_previous", price_previous, positive=True)
    goal = _dec("target", target, positive=True)
    dividend = _dec("dividend per share", dividend_per_share, nonnegative=True)
    from cytonn_weekly.equities.weekly import recommendation  # imported here: the module pulls in the workbook readers

    def upside(p: Decimal) -> Decimal:  # (dividend + target - price) / price, the Universe of Coverage's formula in one division
        return (dividend + goal - p) / p * 100

    def band(up: Decimal) -> Optional[str]:
        # The Universe of Coverage table calls the rule with float(Decimal): its thresholds are float literals, and a Decimal
        # 0.1 compares as below the float 0.1, so a bare Decimal would give no band at exactly 0.1%.
        return recommendation(float(up))

    up_now, up_before = upside(now), upside(before)
    band_now, band_before = band(up_now), band(up_before)
    if band_now == band_before:
        return []

    def show_upside(exact: Decimal, wanted: Optional[str]) -> tuple[Decimal, str]:
        """Enough decimals that the displayed upside falls in the same band as the exact one (0.06%, not 0.1%, for no band)."""
        rounded = _q6(exact)
        for d in range(1, 7):
            if band(round_half_up(rounded, d)) == wanted:
                return rounded, fmt_value(rounded, PCT, d)
        return rounded, fmt_value(rounded, PCT, 6)

    u_now, text_now = show_upside(up_now, band_now)
    u_before, text_before = show_upside(up_before, band_before)
    headline = say("drift.headline", name=name, was=band_before or "no band", now=band_now or "no band", upside_was=text_before,
                   upside_now=text_now, target=fmt_value(goal, PRICE, 2))
    figures = [_fig(f"{name}: price now", now, price(now), "kes"), _fig(f"{name}: price a week earlier", before, price(before), "kes"),
               _fig("Upside now", u_now, text_now, "pct"), _fig("Upside a week earlier", u_before, text_before, "pct"),
               _fig("Target", goal, price(goal), "kes"), _fig("Dividend per share", dividend, price(dividend), "kes")]
    points = [{"date": (week - timedelta(days=7)).isoformat(), "value": before, "display": price(before)},
              {"date": week.isoformat(), "value": now, "display": price(now)}]
    rule = say("drift.rule", target=_raw(goal), dividend=_raw(dividend))
    steps = abs(_BAND_ORDER[band_now] - _BAND_ORDER[band_before])
    return _finish([_make("drift", section, week, headline, figures, f"{name} price", rule, say("drift.window"), points, provenance,
                          50 + 10 * steps)])
