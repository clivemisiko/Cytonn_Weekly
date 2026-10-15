"""The independent verifier: it recomputes each claim from working.points and working.rule alone and compares every figure.

It runs on every detector's output before the detector returns, so a mismatch raises DetectorSelfCheckError (the panel then shows
its "one check could not run" line). Here it is shown to accept every correct output and to catch a changed figure, display,
point, rule parameter, headline word or figure list, and the detectors are shown to call it.
"""

import dataclasses
import functools
import re
from decimal import Decimal

import pytest

from cytonn_weekly.notable.detectors import (
    DetectorSelfCheckError,
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
from tests.detector_helpers import FRI, SECTION, series
from tests.test_notable_detectors import (
    BASE25,
    DRIFT,
    KW,
    PREV12,
    PREV26,
    UP14,
    Y182,
    YIELD,
    run_pace,
)

D = Decimal


def cases() -> dict[str, object]:
    """One suggestion of every kind of finding, each from a different case, keyed by a short name."""
    out = {
        "streak up": streak(series(YIELD, "pct", ["8.62", "8.70", "8.81", "8.93", "9.00", "9.05"]), **KW),
        "streak down": streak(series(YIELD, "pct", ["0.20", "0.10", "0.00", "-0.10", "-0.20"]), min_run=3, **KW),
        "since tie": since(series(Y182, "pct", BASE25[:3] + ["9.50"] + BASE25[4:] + ["9.50"]), **KW),
        "since history": since(series(Y182, "pct", BASE25 + ["9.50"]), **KW),
        "since record": since(series(Y182, "pct", (BASE25 + BASE25 + BASE25[:9])[:59] + ["9.50"]), **KW),
        "since lowest": since(series(Y182, "pct", BASE25 + ["8.50"]), **KW),
        "trail pct sigma": trailing_compare(series("Invented interbank volume", "kes_bn", PREV12 + ["18.0"]), threshold="10", **KW),
        "trail bps": trailing_compare(series(YIELD, "pct", ["9.00"] * 12 + ["9.45"]), threshold="25", mode="bps", **KW),
        "trail abs below": trailing_compare(series("Invented net borrowing", "kes_bn", ["10.0"] * 12 + ["6.5"]), threshold="3", mode="abs", **KW),
        "trail abs pct": trailing_compare(series(YIELD, "pct", ["9.00"] * 12 + ["9.45"]), threshold="0.30", mode="abs", **KW),
        "cross up": threshold_cross(series(Y182, "pct", UP14), level="10", **KW),
        "cross first": threshold_cross(series(Y182, "pct", UP14[:2] + ["9.90"] + UP14[3:]), level="10", **KW),
        "cross touch": threshold_cross(series(Y182, "pct", UP14[:-1] + ["10.00"]), level="10", **KW),
        "range above": expected_range(series(YIELD, "pct", PREV26 + ["9.05"]), **KW),
        "range slip": expected_range(series(YIELD, "pct", PREV26 + ["87.00"]), **KW),
        "range slip low": expected_range(series(YIELD, "pct", PREV26 + ["0.87"]), **KW),
        "pace ahead": run_pace(["150", "280", "390", "450"]),
        "pace behind": run_pace(["60", "110", "160", "200"], thr="5"),
        "drift down": drift(price_now="49.30", price_previous="48.50", **DRIFT),
        "drift no band": drift(price_now="53.97", price_previous="50.00", **DRIFT),
        "drift sell": drift(price_now="54.50", price_previous="53.00", **DRIFT),
    }
    flat = {}
    for name, found in out.items():
        for i, s in enumerate(found):
            flat[f"{name} #{i}"] = s
    return flat


NAMES = sorted(f"{n} #{i}" for n, count in {
    "streak up": 1, "streak down": 1, "since tie": 1, "since history": 1, "since record": 1, "since lowest": 1,
    "trail pct sigma": 1, "trail bps": 1, "trail abs below": 1, "trail abs pct": 1, "cross up": 1, "cross first": 1,
    "cross touch": 1, "range above": 1, "range slip": 2, "range slip low": 2, "pace ahead": 1, "pace behind": 1,
    "drift down": 1, "drift no band": 1, "drift sell": 1}.items() for i in range(count))


@functools.lru_cache(maxsize=None)
def cases_cached():
    return cases()


class _Cases:
    """The cases, built on first use: a detector that breaks fails the tests that use it, not the collection of this file."""

    def __getitem__(self, name):
        return cases_cached()[name]

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
    assert sorted(cases_cached()) == NAMES and len(NAMES) == 23  # every case fires; one that stops firing is noticed
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


@pytest.mark.parametrize("name", sorted(n for n in CASES if n.startswith(("streak", "trail", "range above", "drift"))))
def test_a_changed_first_point_is_caught_where_it_feeds_a_figure(name):
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
    "drift down #0": ("The target (Kshs 52.00)", "The target (Kshs 53.00)"),
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
    assert len(seen) == len(got) == 23
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
