"""The independent verifier: it recomputes each claim from working.points and working.rule alone and compares every figure.

It runs on every detector's output before the detector returns, so a mismatch raises DetectorSelfCheckError (the panel then shows
its "one check could not run" line). Here it is shown to accept every correct output and to catch a changed figure, display,
point, rule parameter, headline word or figure list, and the detectors are shown to call it.
"""

import dataclasses
import functools
import re
from datetime import date, timedelta
from decimal import Decimal

import pytest

from cytonn_weekly.notable.detectors import (
    DetectorSelfCheckError,
    Series,
    drift,
    expected_range,
    since,
    streak,
    threshold_cross,
    trailing_compare,
)
from cytonn_weekly.notable.detectors import library
from cytonn_weekly.notable.detectors.verify import verify
from cytonn_weekly.notable.registry import DetectorContext, run_detectors
from tests.detector_helpers import FRI, PUBLISHED, SECTION, dates, series
from tests.test_notable_detectors import (
    BASE25,
    DRIFT,
    EDGE_BEFORE,
    EDGE_START,
    KW,
    WINDOW_GAP,
    WINDOW_HOLD,
    PREV12,
    PREV26,
    UP14,
    Y182,
    YIELD,
    run_pace,
)

D = Decimal
CROSS_TAIL = ["9.60", "9.70", "9.80", "9.75", "9.65", "9.70", "9.80", "9.75", "9.70", "9.65", "9.70", "9.80", "9.95", "10.10"]


def gap_before(n_tail, values, kept="9.00"):
    """Three points held before a 14-day gap, then ``values`` as n_tail weekly points ending on the week."""
    first = FRI - timedelta(days=7 * (n_tail - 1))
    early = [(first - timedelta(days=14 + 7 * k), kept) for k in (2, 1, 0)]
    return early + list(zip(dates(n_tail), values))


STREAK_BEFORE = ["7.00", "9.00", "8.50", "8.00", "7.50", "7.00", "6.50", "6.00"]  # a fall of six weeks, after a rise into 9.00


def builders() -> dict[str, object]:
    """One builder for each case: calling it runs the detector and returns its suggestions, keyed by a short name."""
    return {
        "streak up": lambda: streak(series(YIELD, "pct", ["8.62", "8.70", "8.81", "8.93", "9.00", "9.05"]), **KW),
        "streak down": lambda: streak(series(YIELD, "pct", ["0.20", "0.10", "0.00", "-0.10", "-0.20"]), min_run=3, **KW),
        "streak before": lambda: streak(series(YIELD, "pct", STREAK_BEFORE), **KW),
        "since tie": lambda: since(series(Y182, "pct", BASE25[:3] + ["9.50"] + BASE25[4:] + ["9.50"]), **KW),
        "since history": lambda: since(series(Y182, "pct", BASE25 + ["9.50"]), **KW),
        "since record": lambda: since(series(Y182, "pct", (BASE25 + BASE25 + BASE25[:9])[:59] + ["9.50"]), **KW),
        "since lowest": lambda: since(series(Y182, "pct", BASE25 + ["8.50"]), **KW),
        "since cut": lambda: since(Series(Y182, "pct", gap_before(26, BASE25 + ["9.50"]), PUBLISHED), **KW),
        "trail pct sigma": lambda: trailing_compare(series("Invented interbank volume", "kes_bn", PREV12 + ["18.0"]), threshold="10", **KW),
        "trail bps": lambda: trailing_compare(series(YIELD, "pct", ["9.00"] * 12 + ["9.45"]), threshold="25", mode="bps", **KW),
        "trail abs below": lambda: trailing_compare(series("Invented net borrowing", "kes_bn", ["10.0"] * 12 + ["6.5"]), threshold="3", mode="abs", **KW),
        "trail abs pct": lambda: trailing_compare(series(YIELD, "pct", ["9.00"] * 12 + ["9.45"]), threshold="0.30", mode="abs", **KW),
        "cross up": lambda: threshold_cross(series(Y182, "pct", UP14), level="10", **KW),
        "cross first": lambda: threshold_cross(series(Y182, "pct", UP14[:2] + ["9.90"] + UP14[3:]), level="10", **KW),
        "cross cut": lambda: threshold_cross(Series(Y182, "pct", gap_before(14, CROSS_TAIL, "10.5"), PUBLISHED), level="10", **KW),
        "cross touch": lambda: threshold_cross(series(Y182, "pct", UP14[:-1] + ["10.00"]), level="10", **KW),
        "range above": lambda: expected_range(series(YIELD, "pct", PREV26 + ["9.05"]), **KW),
        "range slip": lambda: expected_range(series(YIELD, "pct", PREV26 + ["87.00"]), **KW),
        "range slip low": lambda: expected_range(series(YIELD, "pct", PREV26 + ["0.87"]), **KW),
        "pace ahead": lambda: run_pace(["150", "280", "390", "450"]),
        "pace behind": lambda: run_pace(["60", "110", "160", "200"], thr="5"),
        "drift down": lambda: drift(price_now="49.30", price_previous="48.50", **DRIFT),
        "drift no band": lambda: drift(price_now="53.97", price_previous="50.00", **DRIFT),
        "drift sell": lambda: drift(price_now="54.50", price_previous="53.00", **DRIFT),
    }


def cases() -> dict[str, object]:
    """Every case built (a detector that breaks fails here), flattened to "name #index" -> suggestion."""
    flat = {}
    for name, build in builders().items():
        for i, s in enumerate(build()):
            flat[f"{name} #{i}"] = s
    return flat


@functools.lru_cache(maxsize=None)
def case_group(name):
    return builders()[name]()


NAMES = sorted(f"{n} #{i}" for n, count in {
    "streak up": 1, "streak down": 1, "streak before": 1, "since tie": 1, "since history": 1, "since record": 1, "since lowest": 1, "since cut": 1, "cross cut": 1,
    "trail pct sigma": 1, "trail bps": 1, "trail abs below": 1, "trail abs pct": 1, "cross up": 1, "cross first": 1,
    "cross touch": 1, "range above": 1, "range slip": 2, "range slip low": 2, "pace ahead": 1, "pace behind": 1,
    "drift down": 1, "drift no band": 1, "drift sell": 1}.items() for i in range(count))


@functools.lru_cache(maxsize=None)
def cases_cached():
    return cases()


class _Cases:
    """The cases, built on first use: a detector that breaks fails the tests that use it, not the collection of this file."""

    def __getitem__(self, name):
        group, _, index = name.rpartition(" #")
        return case_group(group)[int(index)]  # only this case is built: a broken detector fails only the tests that use it

    def __iter__(self):
        return iter(NAMES)

    def __len__(self):
        return len(NAMES)

    def items(self):
        return cases_cached().items()


CASES = _Cases()


def replaced(s, **changes):
    return dataclasses.replace(s, **changes)


def test_every_case_fires_and_the_verifier_accepts_each_output():
    assert sorted(cases_cached()) == NAMES and len(NAMES) == 26  # every case fires; one that stops firing is noticed
    for name, s in CASES.items():
        assert verify(s) is None, name


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_changed_figure_value_is_caught_for_every_figure(name):
    s = CASES[name]
    for i, f in enumerate(s.figures):
        figures = [dict(x) for x in s.figures]
        figures[i]["value"] = f["value"] + D("1")
        with pytest.raises(DetectorSelfCheckError):
            verify(replaced(s, figures=figures))


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_display_that_does_not_show_its_value_is_caught_for_every_figure(name):
    s = CASES[name]
    for i, f in enumerate(s.figures):
        figures = [dict(x) for x in s.figures]
        figures[i]["display"] = re.sub(r"\d", lambda m: str((int(m.group(0)) + 3) % 10), f["display"])
        with pytest.raises(DetectorSelfCheckError):
            verify(replaced(s, figures=figures))


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_changed_latest_point_is_caught(name):
    s = CASES[name]
    pts = [dict(p) for p in s.working["points"]]
    pts[-1]["value"] = pts[-1]["value"] + D("1")
    with pytest.raises(DetectorSelfCheckError):
        verify(replaced(s, working={**s.working, "points": pts}))


@pytest.mark.parametrize("name", sorted(n for n in CASES if n.startswith(("streak up", "streak down", "trail", "range above", "drift"))))
def test_a_changed_first_point_is_caught_where_it_feeds_a_figure(name):
    # not "streak before": its first point is the one before the run, which may be any value that still ends the run (see below)
    s = CASES[name]
    pts = [dict(p) for p in s.working["points"]]
    pts[0]["value"] = pts[0]["value"] + D("1")
    with pytest.raises(DetectorSelfCheckError):
        verify(replaced(s, working={**s.working, "points": pts}))


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_figure_taken_out_or_added_is_caught(name):
    s = CASES[name]
    with pytest.raises(DetectorSelfCheckError):
        verify(replaced(s, figures=s.figures[:-1]))
    with pytest.raises(DetectorSelfCheckError):
        verify(replaced(s, figures=s.figures + [{"label": "Extra", "value": D("1"), "display": "1", "unit": ""}]))


def bump_last_digit(text: str) -> str:
    last = list(re.finditer(r"\d", text))[-1]
    return text[: last.start()] + str((int(last.group(0)) + 1) % 10) + text[last.end():]


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_headline_that_says_something_else_is_caught(name):
    s = CASES[name]
    with pytest.raises(DetectorSelfCheckError):
        verify(replaced(s, headline=bump_last_digit(s.headline)))  # a number that no longer matches the figures
    words = {"risen": "fallen", "fallen": "risen", "highest": "lowest", "lowest": "highest", "above": "below", "below": "above",
             "ahead of": "behind", "behind": "ahead of", "moved above": "moved below", "moved below": "moved above"}
    for old, new in words.items():
        if re.search(rf"\b{old}\b", s.headline):
            with pytest.raises(DetectorSelfCheckError):
                verify(replaced(s, headline=re.sub(rf"\b{old}\b", new, s.headline, count=1)))  # the opposite direction
            break


RULE_EDITS = {  # case: (what the rule says, what is put in its place); each must change a parameter the claim depends on
    "streak up #0": ("At least 4 rises", "At least 6 rises"),
    "since tie #0": ("at least 12 weekly points", "at least 30 weekly points"),
    "trail pct sigma #0": ("previous 12 weekly points", "previous 11 weekly points"),
    "trail bps #0": ("at least 25 (basis points)", "at least 50 (basis points)"),
    "cross up #0": ("at or above 10 and", "at or above 11 and"),
    "range above #0": ("previous 26 weekly points", "previous 25 weekly points"),
    "range slip #1": ("at least 5 times the median or at most 1/5", "at least 11 times the median or at most 1/11"),
    "pace ahead #0": ("at least 10 percentage points", "at least 20 percentage points"),
    "drift down #0": ("Buy at 20% or more", "Buy at 25% or more"),
}


@pytest.mark.parametrize("name", sorted(RULE_EDITS))
def test_a_changed_rule_parameter_is_caught(name):
    s = CASES[name]
    old, new = RULE_EDITS[name]
    assert old in s.working["rule"], (name, s.working["rule"])
    with pytest.raises(DetectorSelfCheckError):
        verify(replaced(s, working={**s.working, "rule": s.working["rule"].replace(old, new, 1)}))


def test_a_rule_the_verifier_cannot_read_is_a_mismatch_not_a_pass():
    s = CASES["streak up #0"]
    with pytest.raises(DetectorSelfCheckError, match="rule"):
        verify(replaced(s, working={**s.working, "rule": "Some other wording."}))


# -- a streak is the longest run: the point that ended it must really end it ----------------------------------------------------

def _streak_ended_by_a_tie():
    return streak(series(YIELD, "pct", ["8.00", "8.10", "8.20", "8.30", "8.30", "8.40", "8.50", "8.60", "8.70"]), **KW)[0]


def _streak_ended_by_a_gap():
    after = [FRI - timedelta(days=21 - 7 * i) for i in range(4)]
    before = [FRI - timedelta(days=35 + 7 * i) for i in range(3, -1, -1)]
    values = ["8.00", "8.10", "8.20", "8.30", "8.40", "8.50", "8.60", "8.70"]
    return streak(Series(YIELD, "pct", list(zip(before + after, values)), PUBLISHED), min_run=3, **KW)[0]


def _first_point(s, **changes):
    pts = [dict(p) for p in s.working["points"]]
    pts[0].update(changes)
    return replaced(s, working={**s.working, "points": pts})


def test_every_way_a_run_can_end_is_accepted_as_the_proof_that_it_is_the_longest():
    assert verify(CASES["streak before #0"]) is None  # a reversal
    assert verify(_streak_ended_by_a_tie()) is None
    assert verify(_streak_ended_by_a_gap()) is None
    assert verify(CASES["streak up #0"]) is None  # the run begins at the first point held, and the rule says so


def test_the_verifier_refuses_a_pre_run_point_that_would_continue_a_reversed_run():
    s = CASES["streak before #0"]  # falls from 9.00; the point before is 7.00, a rise into 9.00
    with pytest.raises(DetectorSelfCheckError, match="point before the run"):
        verify(_first_point(s, value=D("9.50"), display="9.50%"))  # 9.50 to 9.00 is one more fall: the run was longer


def test_the_verifier_refuses_a_pre_run_point_that_would_continue_a_run_ended_by_a_tie():
    s = _streak_ended_by_a_tie()  # rises from 8.30; the point before is 8.30, level with it
    with pytest.raises(DetectorSelfCheckError, match="point before the run"):
        verify(_first_point(s, value=D("8.20"), display="8.20%"))  # 8.20 to 8.30 is one more rise


def test_the_verifier_refuses_a_pre_run_point_that_is_not_a_gap_away_after_all():
    s = _streak_ended_by_a_gap()  # rises from 8.40; the point before is 8.30, 14 days earlier: a rise, but across a gap
    run_start = date.fromisoformat(s.working["points"][1]["date"])
    with pytest.raises(DetectorSelfCheckError, match="point before the run"):
        verify(_first_point(s, date=(run_start - timedelta(days=7)).isoformat()))  # a week earlier it is part of the run


@pytest.mark.parametrize("make, value", [(lambda: CASES["streak before #0"], "0.00"), (lambda: CASES["streak before #0"], "9.00"),
                                         (_streak_ended_by_a_tie, "99.00")])
def test_a_pre_run_point_that_still_ends_the_run_is_accepted_whatever_its_value(make, value):
    s = make()
    verify(_first_point(s, value=D(value), display=f"{value}%"))  # a rise into a fall, a tie, or a fall into a rise: all end it


def test_a_working_that_leaves_out_the_pre_run_point_but_whose_rule_names_it_is_refused():
    for s in (CASES["streak before #0"], _streak_ended_by_a_tie(), _streak_ended_by_a_gap()):
        left_out = replaced(s, working={**s.working, "points": s.working["points"][1:]})  # the run alone, rule unchanged
        with pytest.raises(DetectorSelfCheckError):
            verify(left_out)  # the run's own first point is now taken as the one before it, and it continues the run


def test_a_rule_that_claims_the_start_of_the_series_is_accepted_only_when_every_point_is_in_the_run():
    before = CASES["streak before #0"]
    claims_start = replaced(before, working={**before.working, "rule": before.working["rule"].replace(EDGE_BEFORE, EDGE_START)})
    with pytest.raises(DetectorSelfCheckError, match="all the way"):
        verify(claims_start)  # the rise into 9.00 is in the working, so the run does not begin at the first point
    start = CASES["streak up #0"]
    claims_before = replaced(start, working={**start.working, "rule": start.working["rule"].replace(EDGE_START, EDGE_BEFORE)})
    with pytest.raises(DetectorSelfCheckError, match="point before the run"):
        verify(claims_before)  # the first point is not the end of anything: it rises into the second


def test_a_rule_with_neither_ending_is_unreadable_and_therefore_refused():
    s = CASES["streak up #0"]
    with pytest.raises(DetectorSelfCheckError, match="rule"):
        verify(replaced(s, working={**s.working, "rule": s.working["rule"].replace(EDGE_START, "").rstrip()}))


# -- threshold_cross: the headline claims only the stretch that was checked ------------------------------------------------------

def swapped(s, old, new):
    assert old in s.headline, (old, s.headline)
    return replaced(s, headline=s.headline.replace(old, new, 1))


def rule_swapped(s, old, new):
    assert old in s.working["rule"], (old, s.working["rule"])
    return replaced(s, working={**s.working, "rule": s.working["rule"].replace(old, new, 1)})


FIRST = "in the 13 weeks we hold, since 2026-07-10"


def test_a_threshold_cross_headline_that_claims_the_whole_history_is_refused():
    s = CASES["cross first #0"]
    assert FIRST in s.headline
    with pytest.raises(DetectorSelfCheckError, match="headline"):
        verify(swapped(s, FIRST, "in the history we hold"))  # the old claim: more than the working shows


def test_a_threshold_cross_headline_that_counts_more_weeks_than_the_working_shows_is_refused():
    s = CASES["cross first #0"]
    with pytest.raises(DetectorSelfCheckError, match="headline"):
        verify(swapped(s, FIRST, "in the 20 weeks we hold, since 2026-07-10"))
    with pytest.raises(DetectorSelfCheckError, match="headline"):
        verify(swapped(s, FIRST, "in the 20 weeks we hold, since 2026-05-22"))  # consistent with itself, but before the first point shown


def test_a_threshold_cross_headline_must_use_the_wording_its_rule_allows():
    whole, cut = CASES["cross first #0"], CASES["cross cut #0"]
    assert "weeks we hold" in whole.headline and "weeks checked" in cut.headline
    assert whole.working["rule"].endswith(WINDOW_HOLD) and cut.working["rule"].endswith(WINDOW_GAP)
    with pytest.raises(DetectorSelfCheckError, match="headline"):
        verify(swapped(cut, "weeks checked", "weeks we hold"))  # claims points held that a gap kept out of the check
    with pytest.raises(DetectorSelfCheckError, match="headline"):
        verify(swapped(whole, "weeks we hold", "weeks checked"))
    with pytest.raises(DetectorSelfCheckError):
        verify(rule_swapped(cut, WINDOW_GAP, WINDOW_HOLD))  # the rule says the window began at the first point held: it did not
    with pytest.raises(DetectorSelfCheckError):
        verify(rule_swapped(whole, WINDOW_HOLD, WINDOW_GAP))


def test_a_first_time_crossing_needs_its_window_sentence_and_a_last_time_crossing_has_none():
    with pytest.raises(DetectorSelfCheckError, match="window"):
        verify(rule_swapped(CASES["cross first #0"], " " + WINDOW_HOLD, ""))
    up = CASES["cross up #0"]
    with pytest.raises(DetectorSelfCheckError, match="window"):
        verify(replaced(up, working={**up.working, "rule": up.working["rule"] + " " + WINDOW_HOLD}))


# -- since, the record form: where the window starts, and the weeks counted ----------------------------------------------------

def test_a_record_headline_is_accepted_only_for_the_window_start_its_rule_states():
    whole, cut = CASES["since history #0"], CASES["since cut #0"]
    assert whole.working["rule"].endswith(WINDOW_HOLD) and "the earliest point we hold is" in whole.headline
    assert cut.working["rule"].endswith(WINDOW_GAP) and "weeks checked, since" in cut.headline
    with pytest.raises(DetectorSelfCheckError):
        verify(rule_swapped(whole, WINDOW_HOLD, WINDOW_GAP))  # the earliest-point wording under a rule that says a gap cut the window
    with pytest.raises(DetectorSelfCheckError):
        verify(rule_swapped(cut, WINDOW_GAP, WINDOW_HOLD))  # the weeks-checked wording under a rule that says it began at the first point


def test_a_record_needs_the_window_sentence_and_a_since_has_none():
    whole = CASES["since history #0"]
    with pytest.raises(DetectorSelfCheckError, match="window"):
        verify(rule_swapped(whole, " " + WINDOW_HOLD, ""))
    tie = CASES["since tie #0"]
    with pytest.raises(DetectorSelfCheckError, match="window"):
        verify(replaced(tie, working={**tie.working, "rule": tie.working["rule"] + " " + WINDOW_HOLD}))


def test_a_record_whose_weeks_do_not_equal_the_points_shown_is_refused():
    for name in ("since history #0", "since cut #0", "since record #0"):
        s = CASES[name]
        pts = [dict(p) for p in s.working["points"]]
        mid = len(pts) // 2
        extra = dict(pts[mid])
        extra["date"] = (date.fromisoformat(pts[mid]["date"]) + timedelta(days=3)).isoformat()
        pts.insert(mid + 1, extra)  # the first and last dates, and so the weeks, stay as they were; one point more than weeks is shown
        with pytest.raises(DetectorSelfCheckError, match="weeks"):
            verify(replaced(s, working={**s.working, "points": pts}))


def test_a_record_whose_first_point_is_not_the_start_it_names_is_refused():
    s = CASES["since history #0"]
    pts = [dict(p) for p in s.working["points"]]
    pts[0]["date"] = "2026-04-10"  # the headline names 2026-04-17 as the earliest point we hold
    with pytest.raises(DetectorSelfCheckError):
        verify(replaced(s, working={**s.working, "points": pts}))
    with pytest.raises(DetectorSelfCheckError, match="headline"):
        verify(swapped(s, "the earliest point we hold is 2026-04-17", "the earliest point we hold is 2026-04-24"))


# -- drift: a move "on price alone" needs the same target and dividend in both weeks --------------------------------------------

def drift_with(s, **by_label):
    """The suggestion with some figures replaced, each as (value, display); nothing else is touched."""
    figures = [dict(f) for f in s.figures]
    for f in figures:
        if f["label"] in by_label:
            f["value"], f["display"] = by_label[f["label"]]
    return replaced(s, figures=figures)


def test_a_drift_whose_target_changed_is_refused_even_when_every_figure_is_consistent():
    s = CASES["drift down #0"]  # Accumulate to Hold, 52.00 in both weeks
    assert verify(s) is None
    # last week's target 53.00: last week's upside is then 13.4% (still a different band from now), headline and figures agree
    changed = drift_with(s, **{"Target a week earlier": (D("53.00"), "Kshs 53.00"), "Upside a week earlier": (D("13.402062"), "13.4%")})
    changed = swapped(changed, "upside 11.3% to 9.5%", "upside 13.4% to 9.5%")
    with pytest.raises(DetectorSelfCheckError, match="target"):
        verify(changed)


def test_a_drift_whose_dividend_changed_is_refused_even_when_every_figure_is_consistent():
    s = CASES["drift down #0"]
    changed = drift_with(s, **{"Dividend per share a week earlier": (D("3.00"), "Kshs 3.00"), "Upside a week earlier": (D("13.402062"), "13.4%")})
    changed = swapped(changed, "upside 11.3% to 9.5%", "upside 13.4% to 9.5%")
    with pytest.raises(DetectorSelfCheckError, match="dividend"):
        verify(changed)


def test_a_drift_that_shows_only_one_weeks_target_or_dividend_is_refused():
    s = CASES["drift down #0"]
    for label in ("Target a week earlier", "Dividend per share a week earlier"):
        gone = replaced(s, figures=[f for f in s.figures if f["label"] != label])
        with pytest.raises(DetectorSelfCheckError):
            verify(gone)


def test_the_week_and_the_latest_point_must_agree():
    s = CASES["streak up #0"]
    with pytest.raises(DetectorSelfCheckError, match="week"):
        verify(replaced(s, week_ending="2026-10-02"))


def test_the_error_names_what_did_not_match():
    s = CASES["trail pct sigma #0"]
    figures = [dict(x) for x in s.figures]
    figures[2]["value"] = D("21")
    with pytest.raises(DetectorSelfCheckError) as err:
        verify(replaced(s, figures=figures))
    assert "Difference from the mean, in percent" in str(err.value) and "21" in str(err.value)


# -- the detectors call it -----------------------------------------------------------------------------------------------

def test_every_detector_runs_the_verifier_on_each_suggestion_before_returning(monkeypatch):
    seen = []
    monkeypatch.setattr(library, "verify", lambda s: seen.append(s))
    got = cases()  # builds every case again, now through the spy
    assert len(seen) == len(got) == 26
    assert {s.id for s in seen} == {s.id for s in got.values()}
    assert {s.kind for s in seen} == {"streak", "since", "record", "trailing_compare", "threshold_cross", "expected_range", "pace", "drift"}


def test_a_mismatch_found_by_the_verifier_stops_the_detector_with_the_self_check_error(monkeypatch):
    def refuse(s):
        raise DetectorSelfCheckError("a figure did not match")

    monkeypatch.setattr(library, "verify", refuse)
    for call in (
        lambda: streak(series(YIELD, "pct", ["8.0", "8.1", "8.2", "8.3", "8.4"]), **KW),
        lambda: since(series(Y182, "pct", BASE25 + ["9.50"]), **KW),
        lambda: trailing_compare(series(YIELD, "pct", ["9.00"] * 12 + ["9.45"]), threshold="25", mode="bps", **KW),
        lambda: threshold_cross(series(Y182, "pct", UP14), level="10", **KW),
        lambda: expected_range(series(YIELD, "pct", PREV26 + ["9.05"]), **KW),
        lambda: run_pace(["150", "280", "390", "450"]),
        lambda: drift(price_now="49.30", price_previous="48.50", **DRIFT),
    ):
        with pytest.raises(DetectorSelfCheckError):
            call()


def test_nothing_is_verified_when_nothing_fires(monkeypatch):
    monkeypatch.setattr(library, "verify", lambda s: pytest.fail("verified a suggestion that was never returned"))
    assert streak(series(YIELD, "pct", ["8.0"] * 6), **KW) == []
    assert since(series(Y182, "pct", BASE25[:10]), **KW) == []


def test_a_self_check_failure_reaches_the_panel_as_one_check_that_could_not_run(monkeypatch):
    monkeypatch.setattr(library, "verify", lambda s: (_ for _ in ()).throw(DetectorSelfCheckError("mismatch")))
    registry = {SECTION: [lambda ctx: streak(series(YIELD, "pct", ["8.0", "8.1", "8.2", "8.3", "8.4"]), section=SECTION, week_ending=ctx.week_ending),
                          lambda ctx: []]}
    found, failed = run_detectors(registry, SECTION, DetectorContext(week_ending=FRI))
    assert (found, failed) == ([], 1)  # the existing "one check could not run" path, no stack trace
    assert issubclass(DetectorSelfCheckError, Exception)
