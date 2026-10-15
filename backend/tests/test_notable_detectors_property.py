"""Seeded property loops: 500 random cases per detector (fixed seed, so every run is the same).

hypothesis is not a dependency of this project, so each loop draws its own cases from random.Random(SEED). For every
suggestion a detector returns, the independent verifier passes, the notable shape accepts it, the headline fits in 300
characters, its working points end at the latest point, and calling again gives the same answer. A detector given a stale
series or too little history returns nothing. Each loop also checks that enough cases fire for the checks to mean something.
"""

import dataclasses
import json
import random
from datetime import date, timedelta
from decimal import Decimal

from cytonn_weekly.notable.detectors import (
    Series,
    drift,
    expected_range,
    pace,
    since,
    streak,
    threshold_cross,
    trailing_compare,
)
from cytonn_weekly.notable.detectors.verify import verify
from tests.detector_helpers import FRI, PUBLISHED, SECTION, snap

SEED = 20261015
CASES = 500
START = date(2026, 7, 1)
END = START + timedelta(days=364)


def dec(rng, lo, hi, places=2) -> Decimal:
    return Decimal(rng.randint(int(lo * 10**places), int(hi * 10**places))).scaleb(-places)


def weekly_dates(rng, n, end=FRI, gap=0.1):
    """n weekly dates ending on ``end``; with chance ``gap`` one 14-day gap somewhere inside."""
    dates = [end - timedelta(days=7 * (n - 1 - i)) for i in range(n)]
    if n > 2 and rng.random() < gap:
        at = rng.randint(1, n - 1)
        dates = [d - timedelta(days=7) if i < at else d for i, d in enumerate(dates)]
    return dates


def walk(rng, n, start, step, ties=0.2):
    out, x = [], start
    for _ in range(n):
        out.append(x)
        x = x if rng.random() < ties else x + dec(rng, -step, step)
    return out


def build(dates, values, unit="pct"):
    return Series("Invented random series", unit, list(zip(dates, [str(v) for v in values])), PUBLISHED)


def check(s, week, latest_date, latest_value):
    """Everything that must hold of a returned suggestion."""
    assert verify(s) is None
    assert dataclasses.replace(s) == s  # still passes the notable shape's own validation
    json.dumps(s.to_dict())
    assert len(s.headline) <= 300 and s.headline.strip()
    assert s.week_ending == week.isoformat() and s.section == SECTION
    for value in [f["value"] for f in s.figures] + [p["value"] for p in s.working["points"]]:
        assert isinstance(value, (Decimal, int)) and not isinstance(value, (bool, float)), f"a {type(value).__name__} was stored: {value!r}"
    last = s.working["points"][-1]
    assert last["date"] == latest_date.isoformat() and last["value"] == latest_value, (last, latest_date, latest_value)
    assert isinstance(s.rank, int) and 0 <= s.rank <= 100


def loop(name, make_case, minimum, stale_days=7):
    """Run CASES random cases; each case returns (call, week, latest_date, latest_value, expect_nothing)."""
    rng = random.Random(SEED)
    fired = 0
    for i in range(CASES):
        call, week, latest_date, latest_value, nothing = make_case(rng)
        found = call(week)
        assert found == [] or not nothing, (name, i, "returned something it must not")
        again = call(week)
        assert [snap(x) for x in found] == [snap(x) for x in again], (name, i, "not deterministic")
        for s in found:
            check(s, week, latest_date, latest_value)
        if found:
            fired += 1
            assert call(week - timedelta(days=stale_days)) == [], (name, i, "fired for a week the latest point is not on")
    assert fired >= minimum, f"{name}: only {fired} of {CASES} random cases fired"
    return fired


def test_streak_random_series():
    def make_case(rng):
        n = rng.randint(1, 40)
        values = walk(rng, n, dec(rng, 5, 15), Decimal("0.30"))
        if rng.random() < 0.5:
            sign = rng.choice([1, -1])
            for _ in range(rng.randint(2, 9)):
                values.append(values[-1] + sign * dec(rng, 0.01, 0.4))
        dates = weekly_dates(rng, len(values))
        series, min_run = build(dates, values), rng.choice([2, 3, 4, 5])

        def call(week):
            found = streak(series, section=SECTION, week_ending=week, min_run=min_run)
            for s in found:
                run = true_run(series.points)
                assert s.figures[0]["value"] == run >= min_run
                held, shown = len(series.points), s.working["points"]
                begins_at_start = run + 1 == held  # nothing is earlier than the run
                assert len(shown) == (run + 1 if begins_at_start else run + 2)
                assert [p["date"] for p in shown] == [p.date.isoformat() for p in series.points[held - len(shown):]]
                assert s.working["rule"].endswith("nothing earlier is held.") == begins_at_start
                assert s.working["rule"].endswith("is not part of it.") != begins_at_start
            return found

        return call, FRI, dates[-1], values[-1], len(values) < min_run + 1

    assert loop("streak", make_case, 100) >= 100


def true_run(pts, max_gap_days=10):
    """The length of the unbroken run of rises (or falls) that ends at the latest point, counted here without the library."""
    way = None
    run = 0
    for i in range(len(pts) - 1, 0, -1):
        step = (pts[i].value > pts[i - 1].value) - (pts[i].value < pts[i - 1].value)
        if (pts[i].date - pts[i - 1].date).days > max_gap_days or step == 0 or (way is not None and step != way):
            break
        way, run = step, run + 1
    return run


def test_since_random_series():
    def make_case(rng):
        n = rng.randint(1, 80)
        values = walk(rng, n, dec(rng, 5, 15), Decimal("0.25"))
        mode = rng.random()
        if n > 5 and mode < 0.25:
            values[-1] = max(values[:-1]) + rng.choice([Decimal(0), dec(rng, 0.01, 1)])  # a new high or a tie with the high
        elif n > 5 and mode < 0.5:
            values[-1] = min(values[:-1]) - rng.choice([Decimal(0), dec(rng, 0.01, 1)])
        dates = weekly_dates(rng, n)
        series = build(dates, values)
        min_points, min_stretch = rng.choice([8, 20, 26]), rng.choice([3, 8, 12])
        return (lambda week: since(series, section=SECTION, week_ending=week, min_points=min_points, min_stretch=min_stretch),
                FRI, dates[-1], values[-1], n < min_points)

    assert loop("since", make_case, 60) >= 60


def test_trailing_compare_random_series():
    def make_case(rng):
        n = rng.randint(1, 40)
        unit = rng.choice(["pct", "kes_bn", "index", "count"])
        base = dec(rng, 5, 20)
        values = [base + dec(rng, -0.5, 0.5) for _ in range(n)]
        if n > 3 and rng.random() < 0.7:
            values[-1] = (base * (1 + rng.choice([-1, 1]) * dec(rng, 0.05, 0.3))).quantize(Decimal("0.01"))
        dates = weekly_dates(rng, n)
        series = build(dates, values, unit)
        mode = rng.choice(["pct", "abs"] + (["bps"] if unit == "pct" else []))
        threshold = {"pct": dec(rng, 1, 20, 1), "abs": dec(rng, 0.2, 3, 1), "bps": dec(rng, 5, 60, 0)}[mode]
        window_n, sigma = rng.choice([6, 8, 12]), rng.choice([None, None, "1", "2"])
        return (lambda week: trailing_compare(series, section=SECTION, week_ending=week, threshold=threshold, mode=mode,
                                              window_n=window_n, require_sigma=sigma), FRI, dates[-1], values[-1], n < window_n + 1)

    assert loop("trailing_compare", make_case, 60) >= 60


def test_threshold_cross_random_series():
    def make_case(rng):
        n = rng.randint(1, 30)
        level = dec(rng, 5, 15)
        values = [level + dec(rng, -1, 1) for _ in range(n)]
        if n >= 2 and rng.random() < 0.7:
            side = rng.choice([1, -1])
            values[-2] = level - side * dec(rng, 0.01, 0.5)
            values[-1] = rng.choice([level + side * dec(rng, 0.01, 0.5), level])
        dates = weekly_dates(rng, n, gap=0.05)
        series = build(dates, values)
        min_points = rng.choice([6, 12])
        return (lambda week: threshold_cross(series, section=SECTION, week_ending=week, level=level, min_points=min_points),
                FRI, dates[-1], values[-1], n < min_points)

    assert loop("threshold_cross", make_case, 40) >= 40


def test_expected_range_random_series():
    def make_case(rng):
        n = rng.randint(1, 60)
        unit = rng.choice(["pct", "index"])
        values = [dec(rng, 8.0, 9.5) for _ in range(n)]
        mode = rng.random()
        if n > 5 and mode < 0.25:
            values[-1] = rng.choice([dec(rng, 9.6, 12), dec(rng, 5, 7.9)])
        elif n > 5 and mode < 0.4:
            values[-1] = dec(rng, 8.7, 9.0) * rng.choice([Decimal(5), Decimal(8), Decimal(12), Decimal("0.2"), Decimal("0.1")])
        elif n > 5 and mode < 0.45:
            values[-1] = -dec(rng, 1, 20)
        dates = weekly_dates(rng, n)
        series = build(dates, values, unit)
        window_n, factor = rng.choice([10, 26]), rng.choice([3, 5, 10])
        return (lambda week: expected_range(series, section=SECTION, week_ending=week, window_n=window_n, slip_factor=factor),
                FRI, dates[-1], values[-1], n < window_n + 1)

    assert loop("expected_range", make_case, 80) >= 80


def test_pace_random_cases():
    def make_case(rng):
        as_of = START + timedelta(days=rng.randint(10, 364))
        week = as_of - timedelta(days=(as_of.weekday() - 4) % 7)  # the Friday on or before it
        days = (as_of - START).days
        k = rng.randint(1, min(8, days // 7 + 1))
        target = dec(rng, 100, 2000, rng.choice([0, 2]))
        actual = dec(rng, 5, int(target * Decimal("1.2")))
        cum = sorted(dec(rng, 0, int(actual)) for _ in range(k - 1)) + [actual]
        dates = [as_of - timedelta(days=7 * (k - 1 - i)) for i in range(k)]
        series = Series("Invented cumulative total", "kes_bn", list(zip(dates, [str(v) for v in cum])), PUBLISHED)
        thr, min_days = dec(rng, 1, 25, 1), rng.choice([14, 28])
        return (lambda wk: pace(series, section=SECTION, week_ending=wk, target=target, period_start=START, period_end=END,
                                as_of=as_of, threshold_pp=thr, min_elapsed_days=min_days), week, as_of, actual, days < min_days)

    # the as-of date may fall up to a week after the Friday, so "stale" for pace is two weeks before it
    assert loop("pace", make_case, 100, stale_days=14) >= 100


def test_drift_random_cases():
    def make_case(rng):
        target, dps = dec(rng, 20, 200), dec(rng, 0, 10)
        now, before = (dec(rng, 0.7, 1.4) * target).quantize(Decimal("0.01")), (dec(rng, 0.7, 1.4) * target).quantize(Decimal("0.01"))
        now = max(now, Decimal("0.01"))
        before = max(before, Decimal("0.01"))
        return (lambda week: drift(name="Invented Co", section=SECTION, week_ending=week, price_now=now, price_previous=before,
                                   target=target, dividend_per_share=dps, provenance=PUBLISHED), FRI, FRI, now, False)

    rng = random.Random(SEED)
    # drift has no series, so "a week the latest point is not on" does not apply: the loop's last check is for series only
    fired = 0
    for i in range(CASES):
        call, week, latest_date, latest_value, _ = make_case(rng)
        found = call(week)
        assert [snap(x) for x in found] == [snap(x) for x in call(week)]
        for s in found:
            check(s, week, latest_date, latest_value)
        fired += bool(found)
    assert fired >= 100, fired


def test_every_loop_is_reproducible():
    """The same seed gives the same cases, so a failure found here can be rerun exactly."""
    a, b = random.Random(SEED), random.Random(SEED)
    assert [dec(a, 5, 15) for _ in range(20)] == [dec(b, 5, 15) for _ in range(20)]
