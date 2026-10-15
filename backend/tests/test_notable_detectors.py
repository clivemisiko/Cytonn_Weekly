"""The seven notable detectors: golden cases, boundaries, ranking, stable ids and the wording rules.

Every series here is invented. Expected headlines, figures, points and ranks are written out by hand from the rules in
cytonn_weekly/notable/detectors/library.py's docstring, not worked out by the library.
"""

import re
from datetime import date, timedelta
from decimal import Decimal

import pytest

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
from cytonn_weekly.notable.detectors import wording
from tests.detector_helpers import FRI, INVENTED, PUBLISHED, SECTION, WORKBOOK, dates, fig, points, series, snap, weekly

D = Decimal
KW = dict(section=SECTION, week_ending=FRI)
YIELD = "Invented 91-day yield"
Y182 = "Invented 182-day yield"
STREAK_RULE = ("Consecutive weekly {w} ending at the latest point. An unchanged value, or a gap of more than {g} days between "
               "points, ends the run. At least {m} {w} in a row are needed.")


def one(found):
    assert len(found) == 1, found
    return found[0]


# =========================================================================================================== streak

def test_streak_golden_rises():
    values = ["8.62", "8.70", "8.81", "8.93", "9.00", "9.05"]
    s = one(streak(series(YIELD, "pct", values), **KW))
    assert snap(s) == {
        "kind": "streak", "section": SECTION, "week_ending": "2026-10-09",
        "headline": "The Invented 91-day yield has risen for 5 weeks in a row, from 8.62% to 9.05%.",
        "figures": [fig("Weeks in a row", 5, "5", "weeks"),
                    fig(f"{YIELD}: start of run", "8.62", "8.62%", "pct"), fig(f"{YIELD}: latest", "9.05", "9.05%", "pct")],
        "working": {"series": YIELD, "rule": STREAK_RULE.format(w="rises", g=10, m=4), "window": "current run", "points": points(values)},
        "provenance": {"kind": "published", "label": "CBK weekly bulletin"}, "rank": 50,
    }


def test_streak_golden_falls_at_exactly_the_minimum():
    values = ["9.30", "9.20", "9.10", "9.05", "8.90"]
    s = one(streak(series(YIELD, "pct", values), **KW))
    assert s.headline == "The Invented 91-day yield has fallen for 4 weeks in a row, from 9.30% to 8.90%."
    assert s.rank == 40
    assert s.working["rule"] == STREAK_RULE.format(w="falls", g=10, m=4)
    assert s.working["points"] == points(values)
    assert [f["display"] for f in s.figures] == ["4", "9.30%", "8.90%"]


def test_streak_golden_negative_values_and_a_lower_minimum():
    values = ["0.20", "0.10", "0.00", "-0.10", "-0.20"]
    s = one(streak(series(YIELD, "pct", values), min_run=3, **KW))
    assert s.headline == "The Invented 91-day yield has fallen for 4 weeks in a row, from 0.20% to (0.20%)."
    assert s.rank == 50  # 40 + 10 x (4 - 3)
    assert s.working["rule"] == STREAK_RULE.format(w="falls", g=10, m=3)
    assert s.figures[2] == fig(f"{YIELD}: latest", "-0.20", "(0.20%)", "pct")


def test_streak_takes_the_run_that_ends_at_the_latest_point_and_shows_the_point_before_it():
    values = ["7.00", "9.00", "8.50", "8.00", "7.50", "7.00", "6.50", "6.00"]
    s = one(streak(series(YIELD, "pct", values), **KW))
    assert s.headline == "The Invented 91-day yield has fallen for 6 weeks in a row, from 9.00% to 6.00%."
    assert s.working["points"] == points(values[1:])  # the run and the point it began from, not the earlier rise
    assert s.rank == 60


def test_streak_an_unchanged_value_breaks_the_run():
    values = ["8.00", "8.10", "8.20", "8.30", "8.30", "8.40", "8.50", "8.60", "8.70"]
    s = one(streak(series(YIELD, "pct", values), **KW))
    assert s.headline.endswith("from 8.30% to 8.70%.") and "4 weeks" in s.headline
    assert s.working["points"] == points(values[4:])


def test_streak_a_gap_above_max_gap_days_breaks_the_run():
    values = ["8.00", "8.10", "8.20", "8.30", "8.40", "8.50", "8.60", "8.70"]
    after = [FRI - timedelta(days=21 - 7 * i) for i in range(4)]  # four weekly points ending on the week
    before = [FRI - timedelta(days=35 + 7 * i) for i in range(3, -1, -1)]  # four weekly points, 14 days before those
    gapped = Series(YIELD, "pct", list(zip(before + after, values)), PUBLISHED)
    assert streak(gapped, **KW) == []  # only three rises are unbroken: one short of the minimum
    s = one(streak(gapped, min_run=3, **KW))
    assert s.working["points"] == [{"date": d.isoformat(), "value": D(v), "display": f"{v}%"} for d, v in zip(after, values[4:])]


def test_streak_a_gap_of_exactly_max_gap_days_does_not_break_it():
    tight = [(FRI - timedelta(days=10 * n), f"{9 - n * 0.1:.2f}") for n in range(4, -1, -1)]  # 8.60 ... 9.00 every 10 days
    assert len(streak(Series(YIELD, "pct", tight, PUBLISHED), max_gap_days=10, **KW)) == 1
    assert streak(Series(YIELD, "pct", tight, PUBLISHED), max_gap_days=9, **KW) == []


def test_streak_one_short_of_the_minimum_returns_nothing():
    assert streak(series(YIELD, "pct", ["8.00", "8.10", "8.20", "8.30"]), **KW) == []  # three rises
    assert len(streak(series(YIELD, "pct", ["8.00", "8.10", "8.20", "8.30", "8.40"]), **KW)) == 1  # four


def test_streak_flat_and_mixed_series_return_nothing():
    assert streak(series(YIELD, "pct", ["8.00"] * 10), **KW) == []
    assert streak(series(YIELD, "pct", ["8.00", "8.10", "8.00", "8.10", "8.00", "8.10"]), **KW) == []
    assert streak(series(YIELD, "pct", ["8.00"]), **KW) == []


def test_streak_a_latest_point_that_is_not_on_the_report_week_returns_nothing():
    stale = series(YIELD, "pct", ["8.00", "8.10", "8.20", "8.30", "8.40"], end=FRI - timedelta(days=7))
    assert streak(stale, **KW) == []
    ahead = series(YIELD, "pct", ["8.00", "8.10", "8.20", "8.30", "8.40"], end=FRI)
    assert streak(ahead, section=SECTION, week_ending=FRI - timedelta(days=7)) == []


def test_streak_rejects_a_minimum_below_two():
    with pytest.raises(ValueError, match="min_run"):
        streak(series(YIELD, "pct", ["8.0", "8.1"]), min_run=1, **KW)


# ============================================================================================================ since

BASE25 = ["9.00", "9.10", "9.05", "9.20", "9.15", "9.10", "9.00", "9.05", "9.20", "9.10", "9.00", "9.10", "9.20",
          "9.30", "9.25", "9.10", "9.00", "9.10", "9.20", "9.15", "9.05", "9.00", "9.10", "9.20", "9.10"]
SINCE_RULE = ("{h} value in the unbroken weekly points. A value equal to the latest counts as at or {a} it, so a tie ends the "
              "stretch. Gaps of more than 10 days end the window. The latest value must stand for at least 12 weekly points, "
              "in a window of at least 26 points.")


def test_since_golden_highest_since_a_tie():
    base = BASE25[:3] + ["9.50"] + BASE25[4:]  # an equal value 22 weeks back ends the stretch: ties count as at or above
    values = base + ["9.50"]
    s = one(since(series(Y182, "pct", values), **KW))
    assert snap(s) == {
        "kind": "since", "section": SECTION, "week_ending": "2026-10-09",
        "headline": "The Invented 182-day yield, 9.50%, is the highest since 2026-05-08.",
        "figures": [fig(f"{Y182}: latest", "9.50", "9.50%", "pct"), fig("Weeks the latest value has stood", 22, "22", "weeks")],
        "working": {"series": Y182, "rule": SINCE_RULE.format(h="Highest", a="above"), "window": "unbroken weekly points, highest",
                    "points": points(values[3:])},  # from the equal value to the latest
        "provenance": {"kind": "published", "label": "CBK weekly bulletin"}, "rank": 52,  # 30 + 22
    }


def test_since_golden_highest_in_the_available_history():
    values = BASE25 + ["9.50"]  # nothing as high in the 26 points we hold (25 weeks)
    s = one(since(series(Y182, "pct", values), **KW))
    assert s.kind == "record"
    assert s.headline == ("The Invented 182-day yield, 9.50%, is the highest in the available history, 25 weeks "
                          "(the earliest point we hold is 2026-04-17).")
    assert "record" not in s.headline.lower()  # fewer than 52 weeks of history
    assert s.working["points"] == points(values) and s.rank == 55
    assert s.figures == [fig(f"{Y182}: latest", "9.50", "9.50%", "pct"), fig("Weeks the latest value has stood", 25, "25", "weeks")]
    assert s.working["window"] == "unbroken weekly points, highest"


def test_since_golden_record_only_with_at_least_52_weeks_and_still_in_the_history_we_hold():
    values = (BASE25 + BASE25 + BASE25[:9])[:59] + ["9.50"]  # 60 points, 59 weeks
    s = one(since(series(Y182, "pct", values), **KW))
    assert s.headline == ("The Invented 182-day yield, 9.50%, is a record high in the history we hold: the highest in 59 weeks "
                          "(the earliest point we hold is 2025-08-22).")
    assert s.rank == 89 and s.kind == "record" and s.working["points"] == points(values)


def test_since_52_weeks_exactly_is_enough_for_the_word_record_and_51_is_not():
    for weeks, record in ((52, True), (51, False)):
        values = (BASE25 + BASE25 + BASE25)[:weeks] + ["9.50"]
        s = one(since(series(Y182, "pct", values), **KW))
        assert ("record" in s.headline) is record, (weeks, s.headline)
        assert (f"in the history we hold" in s.headline) is record


def test_since_golden_lowest():
    base = BASE25[:5] + ["8.50"] + BASE25[6:]
    values = base + ["8.50"]  # a tie 20 weeks back
    s = one(since(series(Y182, "pct", values), **KW))
    assert s.headline == "The Invented 182-day yield, 8.50%, is the lowest since 2026-05-22."
    assert s.working["window"] == "unbroken weekly points, lowest"
    assert s.working["rule"] == SINCE_RULE.format(h="Lowest", a="below")
    lone = one(since(series(Y182, "pct", BASE25 + ["8.50"]), **KW))
    assert lone.headline.startswith("The Invented 182-day yield, 8.50%, is the lowest in the available history, 25 weeks")


def test_since_ties_count_as_equal_or_above_so_an_equal_value_just_before_stops_it():
    values = BASE25[:-1] + ["9.50", "9.50"]  # the latest equals last week's: highest since last week, a stretch of one point
    assert since(series(Y182, "pct", values), **KW) == []


def test_since_a_stretch_shorter_than_the_minimum_returns_nothing_and_exactly_the_minimum_fires():
    values = BASE25[:13] + ["9.50"] + BASE25[14:] + ["9.50"]  # the equal value is 12 points back from the latest
    assert len(one(since(series(Y182, "pct", values), **KW)).working["points"]) == 13
    near = BASE25[:14] + ["9.50"] + BASE25[15:] + ["9.50"]  # 11 points back
    assert since(series(Y182, "pct", near), **KW) == []
    assert len(since(series(Y182, "pct", near), min_stretch=11, **KW)) == 1


def test_since_history_one_point_short_of_the_minimum_returns_nothing():
    assert since(series(Y182, "pct", BASE25[:24] + ["9.50"]), **KW) == []  # 25 points
    assert len(since(series(Y182, "pct", BASE25[:25] + ["9.50"]), **KW)) == 1  # 26
    assert len(since(series(Y182, "pct", BASE25[:19] + ["9.50"]), min_points=20, **KW)) == 1


def test_since_a_gap_inside_the_series_ends_the_usable_window():
    values = BASE25 + ["9.50"]
    ds = [FRI - timedelta(days=7 * n) for n in range(25, -1, -1)]
    gapped = [d - timedelta(days=7) if i < 10 else d for i, d in enumerate(ds)]  # a 14-day gap after the 10th point
    assert since(Series(Y182, "pct", list(zip(gapped, values)), PUBLISHED), **KW) == []  # only 16 points are unbroken
    longer = (BASE25 + BASE25)[:30] + ["9.50"]
    ds = [FRI - timedelta(days=7 * n) for n in range(30, -1, -1)]
    gapped = [d - timedelta(days=7) if i < 4 else d for i, d in enumerate(ds)]
    s = one(since(Series(Y182, "pct", list(zip(gapped, longer)), PUBLISHED), **KW))
    assert s.headline == ("The Invented 182-day yield, 9.50%, is the highest in the available history, 26 weeks "
                          "(weekly points unbroken from 2026-04-10).")
    assert len(s.working["points"]) == 27  # the window after the gap only


def test_since_a_flat_series_returns_nothing():
    assert since(series(Y182, "pct", ["9.00"] * 30), **KW) == []


def test_since_the_latest_point_must_be_on_the_week():
    stale = series(Y182, "pct", BASE25 + ["9.50"], end=FRI - timedelta(days=7))
    assert since(stale, **KW) == []


def test_since_negative_values():
    values = ["-1.00"] * 3 + ["-0.50"] * 22 + ["-0.25"]
    s = one(since(series("Invented net foreign position", "usd_mn", values), **KW))
    assert s.headline.startswith("The Invented net foreign position, (USD 0.3 mn), is the highest")  # -0.25 rounds half up to -0.3


# ============================================================================================== trailing_compare

PREV12 = ["14.0"] * 6 + ["16.0"] * 6
TRAIL_RULE = ("Latest value against the mean of the previous {n} weekly points (the latest point is not in the mean), measured as "
              "{mode}. Shown when the difference is at least {t} ({u}). Gaps of more than 10 days between points end the window. "
              "The standard deviation is the sample standard deviation "
              "of the previous {n} points, reported when there are at least 8 of them and it is above zero.")


def test_trailing_compare_golden_percent_with_sigma():
    values = PREV12 + ["18.0"]
    s = one(trailing_compare(series("Invented interbank volume", "kes_bn", values), threshold="10", **KW))
    n = "Invented interbank volume"
    assert snap(s) == {
        "kind": "trailing_compare", "section": SECTION, "week_ending": "2026-10-09",
        "headline": ("The Invented interbank volume, Kshs 18.0 bn, is 20.0% above the average of the previous 12 weeks, "
                     "Kshs 15.0 bn. That is 2.9 standard deviations above the average."),
        "figures": [fig(f"{n}: latest", "18.0", "Kshs 18.0 bn", "kes_bn"),
                    fig(f"{n}: mean of the previous 12 weeks", "15.0", "Kshs 15.0 bn", "kes_bn"),
                    fig("Difference from the mean, in percent", "20", "20.0%", "pct"),
                    fig("Standard deviations from the mean", "2.872281", "2.9", "standard_deviations")],
        "working": {"series": n, "rule": TRAIL_RULE.format(n=12, mode="a percentage difference", t="10", u="percent"),
                    "window": "previous 12 weeks",
                    "points": [{"date": d.isoformat(), "value": D(v), "display": f"Kshs {v} bn"} for d, v in weekly(values)]},
        "provenance": {"kind": "published", "label": "CBK weekly bulletin"}, "rank": 60,  # 40 + 20 x (2 - 1)
    }


def test_trailing_compare_golden_basis_points_and_no_sigma_when_the_spread_is_zero():
    values = ["9.00"] * 12 + ["9.45"]
    s = one(trailing_compare(series(YIELD, "pct", values), threshold="25", mode="bps", **KW))
    assert s.headline == "The Invented 91-day yield, 9.45%, is 45.0 bps above the average of the previous 12 weeks, 9.00%."
    assert [f["label"] for f in s.figures] == [f"{YIELD}: latest", f"{YIELD}: mean of the previous 12 weeks",
                                              "Difference from the mean, in basis points"]
    assert s.figures[2] == fig("Difference from the mean, in basis points", "45", "45.0 bps", "bps")
    assert s.rank == 56  # 40 + floor(20 x 0.8)
    assert s.working["rule"] == TRAIL_RULE.format(n=12, mode="a difference in basis points", t="25", u="basis points")


def test_trailing_compare_golden_absolute_and_below():
    values = ["10.0"] * 12 + ["6.5"]
    s = one(trailing_compare(series("Invented net borrowing", "kes_bn", values), threshold="3", mode="abs", **KW))
    assert s.headline == "The Invented net borrowing, Kshs 6.5 bn, is Kshs 3.5 bn below the average of the previous 12 weeks, Kshs 10.0 bn."
    assert s.figures[2] == fig("Difference from the mean (absolute)", "-3.5", "(Kshs 3.5 bn)", "kes_bn")
    assert s.rank == 43  # 40 + floor(20 x (3.5/3 - 1))
    assert s.working["rule"] == TRAIL_RULE.format(n=12, mode="an absolute difference", t="3", u="units of the series")


def test_trailing_compare_absolute_difference_of_a_percentage_series_is_in_percentage_points():
    values = ["9.00"] * 12 + ["9.45"]
    s = one(trailing_compare(series(YIELD, "pct", values), threshold="0.30", mode="abs", **KW))
    assert s.headline == "The Invented 91-day yield, 9.45%, is 0.45% points above the average of the previous 12 weeks, 9.00%."


def test_trailing_compare_the_mean_excludes_the_latest_point():
    # With the latest in the mean the average would be 9.0346 (13 points); excluded it is exactly 9.00.
    s = one(trailing_compare(series(YIELD, "pct", ["9.00"] * 12 + ["9.45"]), threshold="1", mode="bps", **KW))
    assert s.figures[1]["value"] == D("9.00") and "9.00%" in s.headline


def test_trailing_compare_fires_at_exactly_the_threshold_and_not_below_it():
    values = ["10.0"] * 12 + ["11.0"]  # exactly 10.0%
    assert len(trailing_compare(series(YIELD, "multiple", values), threshold="10", **KW)) == 1
    assert trailing_compare(series(YIELD, "multiple", values), threshold="10.01", **KW) == []


def test_trailing_compare_history_one_point_short_returns_nothing():
    assert trailing_compare(series(YIELD, "pct", ["9.00"] * 11 + ["9.45"]), threshold="1", mode="bps", **KW) == []  # 11 previous
    assert len(trailing_compare(series(YIELD, "pct", ["9.00"] * 12 + ["9.45"]), threshold="1", mode="bps", **KW)) == 1
    assert len(trailing_compare(series(YIELD, "pct", ["9.00"] * 5 + ["9.45"]), threshold="1", mode="bps", window_n=5, **KW)) == 1


def test_trailing_compare_a_zero_mean_in_percent_mode_returns_nothing_but_not_in_absolute_mode():
    values = ["0.0"] * 12 + ["5.0"]
    assert trailing_compare(series("Invented x", "count", values), threshold="1", **KW) == []
    assert len(trailing_compare(series("Invented x", "count", values), threshold="1", mode="abs", **KW)) == 1


def test_trailing_compare_sigma_needs_eight_previous_points_and_a_spread_and_can_be_required():
    spread = ["14.0", "16.0"] * 6
    few = ["14.0", "16.0"] * 3 + ["18.0"]
    s = one(trailing_compare(series("Invented v", "kes_bn", few), threshold="10", window_n=6, **KW))
    assert "standard deviations" not in s.headline and len(s.figures) == 3  # fewer than 8 previous points: no sigma
    eight = ["14.0", "16.0"] * 4 + ["18.0"]
    assert "standard deviations" in one(trailing_compare(series("Invented v", "kes_bn", eight), threshold="10", window_n=8, **KW)).headline
    seven = ["14.0", "16.0"] * 3 + ["14.0", "18.0"]
    assert len(one(trailing_compare(series("Invented v", "kes_bn", seven), threshold="10", window_n=7, **KW)).figures) == 3
    # required: fires only when the sigma is at least the stated number
    assert len(trailing_compare(series("Invented v", "kes_bn", spread + ["18.0"]), threshold="10", require_sigma="2.8", **KW)) == 1
    assert trailing_compare(series("Invented v", "kes_bn", spread + ["18.0"]), threshold="10", require_sigma="2.9", **KW) == []
    assert trailing_compare(series("Invented v", "kes_bn", few), threshold="10", window_n=6, require_sigma="1", **KW) == []  # not computable
    flat = ["15.0"] * 12 + ["18.0"]
    assert trailing_compare(series("Invented v", "kes_bn", flat), threshold="10", require_sigma="1", **KW) == []  # zero spread
    req = one(trailing_compare(series("Invented v", "kes_bn", spread + ["18.0"]), threshold="10", require_sigma="2.8", **KW))
    assert req.working["rule"].endswith(" The difference must also be at least 2.8 standard deviations.")


def test_trailing_compare_a_gap_in_the_window_returns_nothing():
    ds = [FRI - timedelta(days=7 * n) for n in range(12, -1, -1)]
    ds = [d - timedelta(days=7) if i < 6 else d for i, d in enumerate(ds)]
    assert trailing_compare(Series(YIELD, "pct", list(zip(ds, ["9.00"] * 12 + ["9.45"])), PUBLISHED), threshold="1", mode="bps", **KW) == []


def test_trailing_compare_the_latest_must_be_on_the_week_and_the_threshold_is_the_callers():
    stale = series(YIELD, "pct", ["9.00"] * 12 + ["9.45"], end=FRI - timedelta(days=7))
    assert trailing_compare(stale, threshold="1", mode="bps", **KW) == []
    with pytest.raises(TypeError):
        trailing_compare(series(YIELD, "pct", ["9.00"] * 13), **KW)  # no default threshold per series
    for bad in ("0", "-1", "abc", None):
        with pytest.raises(ValueError, match="threshold"):
            trailing_compare(series(YIELD, "pct", ["9.00"] * 13), threshold=bad, **KW)
    with pytest.raises(ValueError, match="bps"):
        trailing_compare(series("Invented v", "kes_bn", ["9.0"] * 13), threshold="1", mode="bps", **KW)  # basis points need a percentage
    with pytest.raises(ValueError, match="mode"):
        trailing_compare(series(YIELD, "pct", ["9.00"] * 13), threshold="1", mode="relative", **KW)


def test_trailing_compare_a_flat_series_returns_nothing():
    assert trailing_compare(series(YIELD, "pct", ["9.00"] * 13), threshold="0.01", **KW) == []


# ============================================================================================== threshold_cross

CROSS_RULE = ("The latest point is at or {s} {level} and the previous point was strictly {o} it. Equal to the level counts as "
              "reaching it. The last time the series was at or {s} the level is looked up in the unbroken weekly points (gaps of "
              "more than 10 days end the window).")
UP14 = ["9.60", "9.70", "10.05", "9.80", "9.75", "9.70", "9.65", "9.70", "9.80", "9.85", "9.90", "9.90", "9.95", "10.10"]


def test_threshold_cross_golden_up_first_time_since():
    s = one(threshold_cross(series(Y182, "pct", UP14), level="10", **KW))
    assert snap(s) == {
        "kind": "threshold_cross", "section": SECTION, "week_ending": "2026-10-09",
        "headline": "The Invented 182-day yield moved above 10.00% for the first time since 2026-07-24, from 9.95% to 10.10%.",
        "figures": [fig(f"{Y182}: latest", "10.10", "10.10%", "pct"), fig(f"{Y182}: previous week", "9.95", "9.95%", "pct"),
                    fig("Level", "10", "10.00%", "pct"),
                    fig("Weeks since the series was last at or above the level", 11, "11", "weeks")],
        "working": {"series": Y182, "rule": CROSS_RULE.format(s="above", o="below", level="10"),
                    "window": "level 10, unbroken weekly points", "points": points(UP14[2:])},
        "provenance": {"kind": "published", "label": "CBK weekly bulletin"}, "rank": 51,  # 40 + 11
    }


def test_threshold_cross_golden_first_time_in_the_history_we_hold():
    values = [v for v in UP14[:2]] + ["9.90"] + UP14[3:]  # nothing at or above 10.00 before the latest
    s = one(threshold_cross(series(Y182, "pct", values), level="10", **KW))
    assert s.headline == ("The Invented 182-day yield moved above 10.00% for the first time in the history we hold, "
                          "from 9.95% to 10.10%.")
    assert s.figures[3] == fig("Weeks of history held", 13, "13", "weeks")
    assert s.working["points"] == points(values) and s.rank == 53


def test_threshold_cross_golden_down_and_touching():
    down = ["10.40", "10.30", "9.95", "10.20", "10.25", "10.30", "10.35", "10.30", "10.20", "10.15", "10.10", "10.10", "10.05", "9.90"]
    s = one(threshold_cross(series(Y182, "pct", down), level="10", **KW))
    assert s.headline == "The Invented 182-day yield moved below 10.00% for the first time since 2026-07-24, from 10.05% to 9.90%."
    assert s.working["rule"] == CROSS_RULE.format(s="below", o="above", level="10")
    assert s.figures[3].get("label") == "Weeks since the series was last at or below the level"
    touch = UP14[:-1] + ["10.00"]  # reaching the level exactly counts
    t = one(threshold_cross(series(Y182, "pct", touch), level="10", **KW))
    assert t.headline == "The Invented 182-day yield reached 10.00% for the first time since 2026-07-24, from 9.95% to 10.00%."


def test_threshold_cross_a_previous_point_on_the_level_means_it_had_already_reached_it():
    on = UP14[:-2] + ["10.00", "10.10"]
    assert threshold_cross(series(Y182, "pct", on), level="10", **KW) == []


def test_threshold_cross_same_side_returns_nothing():
    assert threshold_cross(series(Y182, "pct", UP14[:-1] + ["9.99"]), level="10", **KW) == []
    assert threshold_cross(series(Y182, "pct", UP14[:-2] + ["10.20", "10.30"]), level="10", **KW) == []


def test_threshold_cross_history_one_point_short_returns_nothing():
    assert threshold_cross(series(Y182, "pct", UP14[3:]), level="10", **KW) == []  # 11 points
    assert len(threshold_cross(series(Y182, "pct", UP14[2:]), level="10", **KW)) == 1  # 12
    assert len(threshold_cross(series(Y182, "pct", UP14[4:]), level="10", min_points=10, **KW)) == 1


def test_threshold_cross_the_two_points_must_be_consecutive_weeks():
    ds = [d - timedelta(days=7) for d in dates(14)[:-1]] + [FRI]  # 14 days between the previous point and the latest
    assert threshold_cross(Series(Y182, "pct", list(zip(ds, UP14)), PUBLISHED), level="10", **KW) == []


def test_threshold_cross_latest_must_be_on_the_week_and_level_needs_a_number():
    assert threshold_cross(series(Y182, "pct", UP14, end=FRI - timedelta(days=7)), level="10", **KW) == []
    for bad in (None, "abc", ""):
        with pytest.raises(ValueError, match="level"):
            threshold_cross(series(Y182, "pct", UP14), level=bad, **KW)


# ================================================================================================ expected_range

RANGE_RULE = ("Latest value against the lowest and highest of the previous {n} weekly points (the latest point is not in the "
              "range). Outside the range when strictly below the lowest or strictly above the highest. Gaps of more than 10 days "
              "between points end the window.")
SLIP_RULE = ("A magnitude check: the latest value against the median of the previous {n} weekly points (the latest point is not "
             "in it). Shown when the latest is at least {f} times the median or at most 1/{f} of it, for a median and a latest "
             "value above zero. Gaps of more than 10 days between points end the window.")
_SORTED = ["8.40"] * 3 + ["8.55"] * 5 + ["8.70"] * 10 + ["8.80"] * 5 + ["8.95"] * 3  # 26 values: lowest 8.40, highest 8.95, median 8.70
PREV26 = [_SORTED[(i * 7) % 26] for i in range(26)]  # the same values in a scattered order


def test_expected_range_golden_above():
    values = PREV26 + ["9.05"]
    s = one(expected_range(series(YIELD, "pct", values), **KW))
    assert snap(s) == {
        "kind": "expected_range", "section": SECTION, "week_ending": "2026-10-09",
        "headline": "The Invented 91-day yield, 9.05%, is above the range of the previous 26 weeks, 8.40% to 8.95%.",
        "figures": [fig(f"{YIELD}: latest", "9.05", "9.05%", "pct"),
                    fig(f"{YIELD}: lowest of the previous 26 weeks", "8.40", "8.40%", "pct"),
                    fig(f"{YIELD}: highest of the previous 26 weeks", "8.95", "8.95%", "pct"),
                    fig("Distance outside the range", "0.10", "0.10%", "pct")],
        "working": {"series": YIELD, "rule": RANGE_RULE.format(n=26), "window": "previous 26 weeks", "points": points(values)},
        "provenance": {"kind": "published", "label": "CBK weekly bulletin"}, "rank": 51,  # 50 + floor(10 x 0.10 / 0.55)
    }


def test_expected_range_golden_below_and_a_flat_history():
    s = one(expected_range(series(YIELD, "pct", PREV26 + ["8.00"]), **KW))
    assert s.headline == "The Invented 91-day yield, 8.00%, is below the range of the previous 26 weeks, 8.40% to 8.95%."
    assert s.figures[3] == fig("Distance outside the range", "0.40", "0.40%", "pct") and s.rank == 57  # 50 + floor(10 x 0.40/0.55)
    flat = one(expected_range(series(YIELD, "pct", ["9.00"] * 26 + ["9.10"]), **KW))
    assert flat.rank == 60  # a history with no spread: a fixed 60
    assert flat.headline == "The Invented 91-day yield, 9.10%, is above the range of the previous 26 weeks, 9.00% to 9.00%."


def test_expected_range_golden_decimal_slip_is_a_separate_signal_beside_the_range():
    values = PREV26 + ["87.00"]  # 10 times the median of 8.70, and far above the range
    found = expected_range(series(YIELD, "pct", values), **KW)
    assert [f.working["window"] for f in found] == ["previous 26 weeks", "previous 26 weeks, magnitude check"]
    slip = found[1]
    assert snap(slip) == {
        "kind": "expected_range", "section": SECTION, "week_ending": "2026-10-09",
        "headline": "The Invented 91-day yield, 87.00%, is 10.0x the median of the previous 26 weeks, 8.70%.",
        "figures": [fig(f"{YIELD}: latest", "87.00", "87.00%", "pct"),
                    fig(f"{YIELD}: median of the previous 26 weeks", "8.70", "8.70%", "pct"),
                    fig("Latest as a multiple of the median", "10", "10.0x", "multiple")],
        "working": {"series": YIELD, "rule": SLIP_RULE.format(n=26, f=5), "window": "previous 26 weeks, magnitude check", "points": points(values)},
        "provenance": {"kind": "published", "label": "CBK weekly bulletin"}, "rank": 90,
    }
    assert found[0].id != slip.id


def test_expected_range_decimal_slip_low_and_the_exact_factor():
    low = expected_range(series(YIELD, "pct", PREV26 + ["0.87"]), **KW)
    s = [f for f in low if f.working["window"].endswith("magnitude check")][0]
    assert s.headline == "The Invented 91-day yield, 0.87%, is 0.10x the median of the previous 26 weeks, 8.70%."
    at = expected_range(series(YIELD, "pct", PREV26 + ["43.50"]), **KW)  # exactly 5 x 8.70
    assert any(f.working["window"].endswith("magnitude check") for f in at)
    under = expected_range(series(YIELD, "pct", PREV26 + ["43.40"]), **KW)  # just under 5 x
    assert not any(f.working["window"].endswith("magnitude check") for f in under)
    one_fifth = expected_range(series(YIELD, "pct", PREV26 + ["1.74"]), **KW)  # exactly 1/5 of 8.70
    assert any(f.working["window"].endswith("magnitude check") for f in one_fifth)
    above_fifth = expected_range(series(YIELD, "pct", PREV26 + ["1.75"]), **KW)
    assert not any(f.working["window"].endswith("magnitude check") for f in above_fifth)


def test_expected_range_inside_the_range_or_on_its_edge_returns_nothing():
    assert expected_range(series(YIELD, "pct", PREV26 + ["8.95"]), **KW) == []  # equal to the highest: not outside
    assert expected_range(series(YIELD, "pct", PREV26 + ["8.40"]), **KW) == []
    assert expected_range(series(YIELD, "pct", PREV26 + ["8.70"]), **KW) == []


def test_expected_range_history_one_point_short_returns_nothing():
    assert expected_range(series(YIELD, "pct", PREV26[:25] + ["9.05"]), **KW) == []  # 25 previous
    assert len(expected_range(series(YIELD, "pct", PREV26 + ["9.05"]), **KW)) == 1
    assert len(expected_range(series(YIELD, "pct", PREV26[:10] + ["9.05"]), window_n=10, **KW)) == 1


def test_expected_range_no_slip_for_a_zero_or_negative_median_or_latest():
    zero = expected_range(series("Invented x", "count", ["0"] * 26 + ["5"]), **KW)
    assert [f.working["window"] for f in zero] == ["previous 26 weeks"]  # a median of zero has no multiple
    neg = expected_range(series("Invented x", "index", PREV26 + ["-90"]), **KW)
    assert [f.working["window"] for f in neg] == ["previous 26 weeks"]


def test_expected_range_a_gap_in_the_window_and_a_stale_latest_return_nothing():
    ds = [FRI - timedelta(days=7 * n) for n in range(26, -1, -1)]
    ds = [d - timedelta(days=7) if i < 10 else d for i, d in enumerate(ds)]
    assert expected_range(Series(YIELD, "pct", list(zip(ds, PREV26 + ["9.05"])), PUBLISHED), **KW) == []
    assert expected_range(series(YIELD, "pct", PREV26 + ["9.05"], end=FRI - timedelta(days=7)), **KW) == []


def test_expected_range_slip_factor_is_a_parameter():
    found = expected_range(series(YIELD, "pct", PREV26 + ["26.10"]), slip_factor=3, **KW)  # exactly 3 x 8.70
    slip = [f for f in found if f.working["window"].endswith("magnitude check")][0]
    assert slip.working["rule"] == SLIP_RULE.format(n=26, f=3)
    with pytest.raises(ValueError, match="slip_factor"):
        expected_range(series(YIELD, "pct", PREV26 + ["9.05"]), slip_factor=1, **KW)


# ================================================================================================================ pace

START = date(2026, 7, 1)
END = START + timedelta(days=364)  # 2027-06-30: net_borrowing counts a 364-day year
PACE_RULE = ("The share of the target ({target}, in the series' unit) reached, against the share of the period elapsed, counting "
             "{elapsed} days from {start} to {as_of} out of {period} days from {start} to {end}, as the net borrowing figure "
             "counts days. Shown when the two differ by at least {thr} percentage points and at least {min_days} days have "
             "elapsed. The projection continues the average pace so far in a straight line; it is not a forecast.")
NB = "Invented net domestic borrowing"


def cumulative(values, end=FRI):
    return series(NB, "kes_bn", values, end=end)


def run_pace(values, target="1000", thr="10", as_of=FRI, week=FRI, **kw):
    return pace(cumulative(values, end=as_of), section=SECTION, week_ending=week, target=target, period_start=START,
                period_end=END, as_of=as_of, threshold_pp=thr, **kw)


def test_pace_golden_ahead():
    values = ["150", "280", "390", "450"]
    s = one(run_pace(values))
    assert snap(s) == {
        "kind": "pace", "section": SECTION, "week_ending": "2026-10-09",
        "headline": ("The Invented net domestic borrowing is at 45.0% of its target with 27.5% of the period elapsed, 17.5% points "
                     "ahead of the period's pace. Continued in a straight line, the pace so far gives about Kshs 1,638.0 bn by "
                     "the end of the period (a straight-line projection)."),
        "figures": [fig(f"{NB}: to date", "450", "Kshs 450.0 bn", "kes_bn"), fig("Target", "1000", "Kshs 1,000.0 bn", "kes_bn"),
                    fig("Share of target reached", "45", "45.0%", "pct"),
                    fig("Share of period elapsed", "27.472527", "27.5%", "pct"),
                    fig("Difference in percentage points", "17.527473", "17.5", "pct_points"),
                    fig("Straight-line projection for the end of the period", "1638", "Kshs 1,638.0 bn", "kes_bn"),
                    fig("Days elapsed", 100, "100", "days"), fig("Days in the period", 364, "364", "days")],
        "working": {"series": NB, "rule": PACE_RULE.format(target="1000", elapsed=100, start="2026-07-01", as_of="2026-10-09",
                                                           period=364, end="2027-06-30", thr="10", min_days=28),
                    "window": "period to date",
                    "points": [{"date": d.isoformat(), "value": D(v), "display": f"Kshs {v}.0 bn"} for d, v in weekly(values)]},
        "provenance": {"kind": "published", "label": "CBK weekly bulletin"}, "rank": 75,  # 40 + floor(2 x 17.527)
    }


def test_pace_golden_behind():
    s = one(run_pace(["60", "110", "160", "200"], thr="5"))
    assert s.headline == ("The Invented net domestic borrowing is at 20.0% of its target with 27.5% of the period elapsed, 7.5% points "
                          "behind the period's pace. Continued in a straight line, the pace so far gives about Kshs 728.0 bn by "
                          "the end of the period (a straight-line projection).")
    assert s.figures[4] == fig("Difference in percentage points", "-7.472527", "(7.5)", "pct_points")
    assert s.rank == 54  # 40 + floor(2 x 7.47)


def test_pace_within_the_threshold_returns_nothing_and_exactly_at_it_fires():
    assert run_pace(["100", "200", "300", "350"], thr="10") == []  # 35.0 - 27.47 = 7.5 points
    assert len(run_pace(["100", "200", "300", "350"], thr="7.5")) == 1  # 7.527 >= 7.5
    assert run_pace(["100", "200", "300", "350"], thr="7.53") == []


def test_pace_counts_days_as_net_borrowing_does_and_agrees_with_it():
    """The elapsed days are the days from the period's start to the as-of date, no day added, over the 364-day period."""
    from cytonn_weekly.fixed_income.net_borrowing import Log

    as_of, week = date(2026, 10, 5), date(2026, 10, 2)  # the value date after the Friday
    s = one(run_pace(["100", "200", "300", "700"], target="919.36", thr="1", as_of=as_of, week=week))
    log = Log(fy_start=START, limit=as_of, as_at=as_of)
    assert log.days == 96 and s.figures[6]["value"] == 96
    actual, target = D("700"), D("919.36")
    assert log.prorated_bn(target) == target / 364 * 96  # the pro-rated target net_borrowing prints
    # share of the pro-rated target as net_borrowing words it equals share of target over share of period
    share_of_prorated = actual / log.prorated_bn(target) * 100
    assert abs(share_of_prorated - s.figures[2]["value"] / s.figures[3]["value"] * 100) < D("0.001")


def test_pace_the_projection_is_the_average_pace_so_far_in_a_straight_line():
    s = one(run_pace(["450"]))
    assert s.figures[5]["value"] == D("450") / 100 * 364


def test_pace_freshness_the_latest_point_must_be_the_as_of_date_and_the_as_of_date_in_the_report_week():
    assert run_pace(["150", "280", "390", "450"], as_of=FRI - timedelta(days=7), week=FRI) == []  # a week stale
    assert len(run_pace(["150", "280", "390", "450"], as_of=FRI + timedelta(days=3), week=FRI)) == 1  # a value date after the Friday
    assert run_pace(["150", "280", "390", "450"], as_of=FRI + timedelta(days=8), week=FRI) == []  # beyond the next Friday
    series_end = cumulative(["150", "280", "390", "450"], end=FRI - timedelta(days=7))
    assert pace(series_end, section=SECTION, week_ending=FRI, target="1000", period_start=START, period_end=END, as_of=FRI,
                threshold_pp="10") == []  # the series ends before the as-of date


def test_pace_minimum_elapsed_days_and_the_period_bounds():
    early = date(2026, 7, 20)  # 19 days in
    assert run_pace(["300"], thr="1", as_of=early, week=early) == []
    assert len(run_pace(["300"], thr="1", as_of=early, week=early, min_elapsed_days=19)) == 1
    assert run_pace(["300"], thr="1", as_of=date(2027, 7, 2), week=date(2027, 7, 2)) == []  # after the period ends


def test_pace_refuses_inputs_that_make_no_sense():
    base = dict(section=SECTION, week_ending=FRI, period_start=START, period_end=END, as_of=FRI, threshold_pp="10")
    for bad in ("0", "-5", "abc", None):
        with pytest.raises(ValueError, match="target"):
            pace(cumulative(["450"]), target=bad, **base)
    with pytest.raises(ValueError, match="threshold_pp"):
        pace(cumulative(["450"]), target="1000", **{**base, "threshold_pp": "0"})
    with pytest.raises(ValueError, match="period"):
        pace(cumulative(["450"]), target="1000", **{**base, "period_end": START})
    with pytest.raises(ValueError, match="outside the period"):
        pace(series(NB, "kes_bn", ["100", "450"], end=FRI, provenance=PUBLISHED), target="1000",
             **{**base, "period_start": date(2026, 10, 5)})  # the 2 October point is before the period starts


# ================================================================================================================ drift

DRIFT = dict(name="Equity Group", target="52.00", dividend_per_share="2.00", provenance=PUBLISHED, **KW)
DRIFT_RULE = ("Upside is the dividend per share over the price plus the target over the price, less one. The target (Kshs {t}) and "
              "the dividend per share (Kshs {d}) are the same in both weeks, and nothing here changes them. Bands from the equities "
              "team's rule: Buy at 20% or more, Accumulate at 10% or more, Hold at 5% or more, Lighten at 0.1% or more, Sell at "
              "0% or less; between 0% and 0.1% there is no band.")


def test_drift_golden_accumulate_to_hold():
    s = one(drift(price_now="49.30", price_previous="48.50", **DRIFT))
    assert snap(s) == {
        "kind": "drift", "section": SECTION, "week_ending": "2026-10-09",
        "headline": "Equity Group moves from Accumulate to Hold on price alone: upside 11.3% to 9.5%, target unchanged at Kshs 52.00.",
        "figures": [fig("Equity Group: price now", "49.30", "Kshs 49.30", "kes"), fig("Equity Group: price a week earlier", "48.50", "Kshs 48.50", "kes"),
                    fig("Upside now", "9.533469", "9.5%", "pct"), fig("Upside a week earlier", "11.340206", "11.3%", "pct"),
                    fig("Target", "52.00", "Kshs 52.00", "kes"), fig("Dividend per share", "2.00", "Kshs 2.00", "kes")],
        "working": {"series": "Equity Group price", "rule": DRIFT_RULE.format(t="52.00", d="2.00"), "window": "week on week",
                    "points": [{"date": "2026-10-02", "value": D("48.50"), "display": "Kshs 48.50"},
                               {"date": "2026-10-09", "value": D("49.30"), "display": "Kshs 49.30"}]},
        "provenance": {"kind": "published", "label": "CBK weekly bulletin"}, "rank": 60,
    }


def test_drift_golden_into_no_band_is_named_and_shows_enough_decimals_to_be_consistent():
    s = one(drift(price_now="53.97", price_previous="50.00", **DRIFT))
    assert s.headline == "Equity Group moves from Hold to no band on price alone: upside 8.0% to 0.06%, target unchanged at Kshs 52.00."
    assert s.rank == 70  # Hold -> no band is two steps on the order Sell, no band, Lighten, Hold, Accumulate, Buy
    back = one(drift(price_now="50.00", price_previous="53.97", **DRIFT))
    assert back.headline == "Equity Group moves from no band to Hold on price alone: upside 0.06% to 8.0%, target unchanged at Kshs 52.00."


def test_drift_golden_lighten_to_sell_with_a_negative_upside_in_brackets():
    s = one(drift(price_now="54.50", price_previous="53.00", **DRIFT))
    assert s.headline == "Equity Group moves from Lighten to Sell on price alone: upside 1.9% to (0.9%), target unchanged at Kshs 52.00."
    assert s.figures[2] == fig("Upside now", "-0.917431", "(0.9%)", "pct") and s.rank == 70


def test_drift_the_band_edges_are_the_recommendation_functions_edges():
    from cytonn_weekly.equities.weekly import recommendation

    d = dict(name="Equity Group", dividend_per_share="0", provenance=PUBLISHED, **KW)
    # exactly 20%: price 45 against a target of 54 is 20.0%, which is Buy, and 45.01 is just under (Accumulate)
    s = one(drift(price_now="45.00", price_previous="45.01", target="54", **d))
    assert "from Accumulate to Buy" in s.headline and "upside 19.97% to 20.0%" in s.headline
    assert recommendation(20.0) == "Buy"
    # exactly 10%: 50 against 55
    t = one(drift(price_now="50", price_previous="50.10", target="55", **d))
    assert "from Hold to Accumulate" in t.headline
    # exactly 0.1%: 1000 against 1001 is Lighten, and 1001.5 is below zero (Sell)
    u = one(drift(price_now="1000", price_previous="1001.5", target="1001", **d))
    assert "from Sell to Lighten" in u.headline
    # exactly 0%: price equals target plus dividend is Sell
    v = one(drift(price_now="54", price_previous="53", target="54", **d))
    assert "from Lighten to Sell" in v.headline and v.figures[2]["value"] == D("0")


def test_drift_the_rule_text_states_the_real_functions_thresholds():
    """The bands written in the rule are checked against equities.weekly.recommendation at each edge."""
    from cytonn_weekly.equities.weekly import recommendation

    # called with floats, as the Universe of Coverage table and its own tests call it
    edges = {"Buy": 20.0, "Accumulate": 10.0, "Hold": 5.0, "Lighten": 0.1}
    for name, edge in edges.items():
        assert recommendation(edge) == name and recommendation(edge - 0.0001) != name
    assert recommendation(0.0) == "Sell" and recommendation(0.05) is None and recommendation(-0.01) == "Sell"
    text = DRIFT_RULE.format(t="52.00", d="2.00")
    for fragment in ("Buy at 20% or more", "Accumulate at 10% or more", "Hold at 5% or more", "Lighten at 0.1% or more",
                     "Sell at 0% or less", "between 0% and 0.1% there is no band"):
        assert fragment in text


def test_drift_no_change_of_band_returns_nothing():
    assert drift(price_now="49.40", price_previous="49.30", **DRIFT) == []
    assert drift(price_now="49.30", price_previous="49.30", **DRIFT) == []
    assert drift(price_now="53.97", price_previous="53.98", **DRIFT) == []  # both in no band


def test_drift_states_that_the_target_did_not_change_and_never_says_it_should():
    s = one(drift(price_now="49.30", price_previous="48.50", **DRIFT))
    assert "target unchanged at Kshs 52.00" in s.headline
    assert "are the same in both weeks" in s.working["rule"]
    text = (s.headline + " " + s.working["rule"]).lower()
    assert not re.search(r"revis|should|raise the target|cut the target|lower the target", text)


def test_drift_refuses_prices_and_inputs_that_make_no_sense():
    for kw in ({"price_now": "0"}, {"price_now": "-1"}, {"price_previous": "abc"}, {"price_previous": None}):
        with pytest.raises(ValueError):
            drift(**{"price_now": "49.30", "price_previous": "48.50", **DRIFT, **kw})
    with pytest.raises(ValueError, match="target"):
        drift(price_now="49.30", price_previous="48.50", **{**DRIFT, "target": "0"})
    with pytest.raises(ValueError, match="dividend"):
        drift(price_now="49.30", price_previous="48.50", **{**DRIFT, "dividend_per_share": "-1"})
    with pytest.raises(ValueError, match="name"):
        drift(price_now="49.30", price_previous="48.50", **{**DRIFT, "name": " "})


# ============================================================================================ ranks, ids, wording

def test_ranks_rise_with_what_each_detector_measures():
    rank = lambda f: one(f).rank
    longer = rank(streak(series(YIELD, "pct", ["1.0", "2.0", "3.0", "4.0", "5.0", "6.0"]), **KW))
    shorter = rank(streak(series(YIELD, "pct", ["2.0", "3.0", "4.0", "5.0", "6.0"]), **KW))
    assert longer > shorter and rank(streak(series(YIELD, "pct", [str(i) for i in range(30)]), **KW)) == 100  # capped
    lo = rank(since(series(Y182, "pct", BASE25 + ["9.50"]), **KW))
    hi = rank(since(series(Y182, "pct", (BASE25 + BASE25)[:49] + ["9.50"]), **KW))
    assert hi > lo
    bigger = rank(trailing_compare(series(YIELD, "pct", ["9.00"] * 12 + ["9.60"]), threshold="25", mode="bps", **KW))
    smaller = rank(trailing_compare(series(YIELD, "pct", ["9.00"] * 12 + ["9.30"]), threshold="25", mode="bps", **KW))
    assert bigger > smaller
    far = rank(expected_range(series(YIELD, "pct", PREV26 + ["9.30"]), **KW))
    near = rank(expected_range(series(YIELD, "pct", PREV26 + ["9.00"]), **KW))
    assert far > near
    slip = [f for f in expected_range(series(YIELD, "pct", PREV26 + ["87.00"]), **KW) if "magnitude" in f.working["window"]][0]
    assert slip.rank == 90 and slip.rank > 85  # above any range rank, which stops at 85
    assert rank(run_pace(["150", "280", "390", "450"])) > rank(run_pace(["100", "200", "300", "350"], thr="7"))
    two = rank(drift(price_now="54.50", price_previous="53.00", **DRIFT))
    onee = rank(drift(price_now="49.30", price_previous="48.50", **DRIFT))
    assert two > onee
    cross_new = rank(threshold_cross(series(Y182, "pct", UP14[:2] + ["9.90"] + UP14[3:]), level="10", **KW))
    cross_old = rank(threshold_cross(series(Y182, "pct", UP14), level="10", **KW))
    assert cross_new > cross_old  # 13 weeks of history against 11 weeks since


def test_a_streak_ranks_40_at_the_minimum_plus_10_for_each_further_week_capped_at_100():
    for n_rises, want in ((4, 40), (5, 50), (6, 60), (9, 90), (10, 100), (14, 100)):
        values = [str(i) for i in range(n_rises + 1)]
        assert one(streak(series(YIELD, "multiple", values), **KW)).rank == want


def every_detector_firing(week):
    kw = dict(section=SECTION, week_ending=week)
    return {
        "streak": (streak(series(YIELD, "pct", ["1.0", "2.0", "3.0", "4.0", "5.0"], end=week), **kw), "5.00%"),
        "since": (since(series(Y182, "pct", BASE25 + ["9.50"], end=week), **kw), "9.50%"),
        "trailing_compare": (trailing_compare(series(YIELD, "pct", ["9.00"] * 12 + ["9.45"], end=week), threshold="25", mode="bps", **kw), "9.45%"),
        "threshold_cross": (threshold_cross(series(Y182, "pct", UP14, end=week), level="10", **kw), "10.10%"),
        "expected_range": (expected_range(series(YIELD, "pct", PREV26 + ["9.05"], end=week), **kw), "9.05%"),
        "pace": (pace(cumulative(["150", "280", "390", "450"], end=week), target="1000", period_start=START, period_end=END,
                      as_of=week, threshold_pp="10", **kw), "450.0"),
        "drift": (drift(price_now="49.30", price_previous="48.50", **{**DRIFT, "week_ending": week}), "49.30"),
    }


def test_the_series_name_and_window_do_not_change_from_one_week_to_the_next():
    """The id hashes the series name and window, so neither may carry a date or the latest value."""
    date_like = re.compile(r"\d{4}-\d{2}-\d{2}")
    this_week, next_week = every_detector_firing(FRI), every_detector_firing(FRI + timedelta(days=7))
    for kind, (found, latest) in this_week.items():
        s = one(found)
        assert not date_like.search(s.working["series"]) and not date_like.search(s.working["window"]), (kind, s.working)
        assert latest not in s.working["series"] and latest not in s.working["window"], kind
        t = one(next_week[kind][0])
        assert (t.working["series"], t.working["window"]) == (s.working["series"], s.working["window"]), kind
        assert t.id != s.id and t.week_ending == "2026-10-16", kind  # the week is in the id, so it is a new suggestion


def test_the_same_finding_in_another_week_has_the_same_series_and_window_but_a_different_id():
    a = one(streak(series(YIELD, "pct", ["1.0", "2.0", "3.0", "4.0", "5.0"]), **KW))
    b = one(streak(series(YIELD, "pct", ["1.0", "2.0", "3.0", "4.0", "5.0"], end=FRI + timedelta(days=7)),
                   section=SECTION, week_ending=FRI + timedelta(days=7)))
    assert (a.working["series"], a.working["window"]) == (b.working["series"], b.working["window"]) and a.id != b.id


BANNED = re.compile(r"signal|indicat|trend|should|expect|predict|likely|because|caused|driven|reflect|suggest|advis|recommend|revis", re.I)


def test_no_template_uses_a_banned_word():
    assert wording.TEMPLATES, "the templates must be listed in one place"
    for name, text in wording.TEMPLATES.items():
        assert not BANNED.search(text), (name, BANNED.search(text).group(0))
        assert len(text) < 700, name


def test_headlines_and_rules_of_every_golden_case_avoid_the_banned_words_and_stay_within_300_characters():
    found = []
    found += streak(series(YIELD, "pct", ["8.62", "8.70", "8.81", "8.93", "9.00", "9.05"]), **KW)
    found += since(series(Y182, "pct", BASE25 + ["9.50"]), **KW)
    found += trailing_compare(series("Invented interbank volume", "kes_bn", PREV12 + ["18.0"]), threshold="10", **KW)
    found += threshold_cross(series(Y182, "pct", UP14), level="10", **KW)
    found += expected_range(series(YIELD, "pct", PREV26 + ["87.00"]), **KW)
    found += run_pace(["150", "280", "390", "450"])
    found += drift(price_now="53.97", price_previous="50.00", **DRIFT)
    assert len(found) >= 8
    for s in found:
        assert len(s.headline) <= 300, s.headline
        assert not BANNED.search(s.headline), s.headline
        assert not BANNED.search(s.working["rule"]), s.working["rule"]
        assert "record" not in s.headline.lower() or "history we hold" in s.headline


def test_a_provenance_other_than_published_is_carried_through_unchanged():
    s = one(streak(series(YIELD, "pct", ["8.0", "8.1", "8.2", "8.3", "8.4"], provenance=WORKBOOK), **KW))
    assert s.provenance == {"kind": "analyst_workbook", "label": "from the analyst workbook, not verified"}
    t = one(streak(series(YIELD, "pct", ["8.0", "8.1", "8.2", "8.3", "8.4"], provenance=INVENTED), **KW))
    assert t.provenance == {"kind": "demo", "label": "invented demo item"}


def test_the_real_registry_is_still_empty_after_the_library_exists():
    from cytonn_weekly import notable

    assert notable.REGISTRY == {}
