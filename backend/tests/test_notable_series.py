"""The detector library's input type, and the house number formats its headlines use.

A Series is built from strings or Decimals and is refused, with a plain reason, when it is not usable as it stands: the
library never repairs data.
"""

import json
from datetime import date
from decimal import Decimal

import pytest

from cytonn_weekly.notable.detectors import Provenance, Series, SeriesError
from cytonn_weekly.notable.detectors import wording
from cytonn_weekly.notable.suggestion import InvalidSuggestion, Suggestion
from tests.detector_helpers import FRI, PUBLISHED, SECTION, series, weekly

UNITS = ("pct", "bps", "multiple", "kes_bn", "kes_mn", "usd_mn", "index", "count")


def build(points, **kw):
    kw.setdefault("name", "Invented 91-day yield")
    kw.setdefault("unit", "pct")
    kw.setdefault("provenance", PUBLISHED)
    return Series(kw["name"], kw["unit"], points, kw["provenance"])


def test_a_series_holds_exact_decimals_whatever_it_was_built_from():
    s = build([("2026-10-02", "9.00"), (date(2026, 10, 9), Decimal("9.05")), ])
    assert [p.value for p in s.points] == [Decimal("9.00"), Decimal("9.05")]
    assert [p.date for p in s.points] == [date(2026, 10, 2), date(2026, 10, 9)]
    assert s.latest.date == date(2026, 10, 9) and s.latest.value == Decimal("9.05")
    assert all(isinstance(p.value, Decimal) for p in s.points)
    assert build([(FRI, 7)]).latest.value == Decimal(7)  # a whole number is exact too
    assert s.name == "Invented 91-day yield" and s.unit == "pct" and s.provenance == PUBLISHED


def test_every_unit_is_accepted():
    for unit in UNITS:
        assert build([(FRI, "1")], unit=unit).unit == unit


@pytest.mark.parametrize(
    "points, why",
    [
        ([], "at least one point"),
        ([("2026-10-09", "9.0"), ("2026-10-02", "9.1")], "ascending"),  # unsorted
        ([("2026-10-02", "9.0"), ("2026-10-02", "9.1")], "twice"),  # duplicate date
        ([("2026-10-02", None)], "missing"),
        ([("2026-10-02", "")], "missing"),
        ([("2026-10-02", "  ")], "missing"),
        ([("2026-10-02", 9.05)], "float"),  # never a float
        ([("2026-10-02", True)], "float|bool|number"),
        ([("2026-10-02", "NaN")], "finite"),
        ([("2026-10-02", "Infinity")], "finite"),
        ([("2026-10-02", "-Infinity")], "finite"),
        ([("2026-10-02", Decimal("NaN"))], "finite"),
        ([("2026-10-02", Decimal("Infinity"))], "finite"),
        ([("2026-10-02", "9.05%")], "number"),
        ([("2026-10-02", "abc")], "number"),
        ([("not a date", "9.0")], "date"),
        ([("2026-13-45", "9.0")], "date"),
        ([("2026-10-02",)], "point"),
        ([(date(2026, 10, 2), "9.0", "extra")], "point"),
    ],
)
def test_a_series_that_cannot_be_used_as_it_stands_is_refused_with_the_reason(points, why):
    with pytest.raises(SeriesError, match=why):
        build(points)


def test_the_library_never_repairs_a_series_it_is_given():
    unsorted = [("2026-10-09", "9.0"), ("2026-10-02", "9.1")]
    with pytest.raises(SeriesError):
        build(unsorted)  # not sorted for the caller
    with pytest.raises(SeriesError):
        build([("2026-10-02", "9.0"), ("2026-10-02", "9.0")])  # not de-duplicated for the caller


@pytest.mark.parametrize(
    "kw, why",
    [
        ({"unit": "percent"}, "unit"),
        ({"unit": ""}, "unit"),
        ({"name": ""}, "name"),
        ({"name": "   "}, "name"),
        ({"name": "91-day yield to 2026-10-09"}, "date"),  # a name with a date would change the id every week
        ({"provenance": {"kind": "published", "label": "x"}}, "provenance"),
    ],
)
def test_a_series_needs_a_stable_name_a_known_unit_and_a_provenance_object(kw, why):
    with pytest.raises(SeriesError, match=why):
        build([(FRI, "9.0")], **kw)


@pytest.mark.parametrize(
    "kind, label",
    [("guess", "somewhere"), ("published", ""), ("demo", "real data"), ("analyst_workbook", "from the analyst workbook")],
)
def test_provenance_follows_the_notable_rules(kind, label):
    with pytest.raises(SeriesError):
        Provenance(kind, label)


def test_the_two_fixed_provenance_labels_are_accepted_and_carried_to_the_suggestion_shape():
    assert Provenance("analyst_workbook", "from the analyst workbook, not verified").to_dict() == {
        "kind": "analyst_workbook", "label": "from the analyst workbook, not verified"}
    assert Provenance("typed", "typed on the weekly analyst inputs form").kind == "typed"


def test_the_series_name_and_unit_are_kept_exactly_for_the_ids():
    s = series("Invented 91-day yield", "pct", ["9.0", "9.1"])
    assert (s.name, s.unit) == ("Invented 91-day yield", "pct")


# -- the notable shape takes exact numbers ---------------------------------------------------------------------------

def suggestion_with(value):
    return Suggestion(
        kind="streak", section=SECTION, week_ending="2026-10-09", headline="A headline.",
        figures=[{"label": "x", "value": value, "display": "1", "unit": ""}],
        working={"series": "s", "rule": "r", "window": "w", "points": [{"date": "2026-10-09", "value": value, "display": "1"}]},
        provenance={"kind": "published", "label": "CBK"}, rank=50)


def test_a_suggestion_accepts_decimal_figures_and_points_and_still_serializes_for_json():
    s = suggestion_with(Decimal("9.05"))
    assert s.figures[0]["value"] == Decimal("9.05")
    out = s.to_dict()
    assert out["figures"][0]["value"] == 9.05 and out["working"]["points"][0]["value"] == 9.05
    json.dumps(out)  # no Decimal reaches the JSON encoder


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity"), float("nan"), float("inf"), True, "9.05"])
def test_a_suggestion_still_refuses_a_value_that_is_not_a_finite_number(bad):
    with pytest.raises(InvalidSuggestion):
        suggestion_with(bad)


def test_the_id_does_not_change_when_a_decimal_stands_for_the_same_value():
    assert suggestion_with(Decimal("9.05")).id == suggestion_with(9.05).id


# -- the house number formats ------------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value, unit, decimals, shown",
    [
        ("9.05", "pct", None, "9.05%"),
        ("-0.20", "pct", None, "(0.20%)"),  # negative percentages in brackets
        ("0.004", "pct", None, "0.00%"),  # never "(0.00%)" or "-0.00%"
        ("-0.004", "pct", None, "0.00%"),
        ("18.24", "multiple", None, "18.2x"),
        ("3053.14", "index", None, "3,053.1"),
        ("-3.14", "index", None, "(3.1)"),
        ("12.34", "kes_bn", None, "Kshs 12.3 bn"),
        ("1638", "kes_bn", None, "Kshs 1,638.0 bn"),
        ("-12.34", "kes_bn", None, "(Kshs 12.3 bn)"),
        ("12.34", "kes_mn", None, "Kshs 12.3 mn"),
        ("4.56", "usd_mn", None, "USD 4.6 mn"),
        ("-4.56", "usd_mn", None, "(USD 4.6 mn)"),
        ("10.84", "bps", None, "10.8 bps"),
        ("-10.84", "bps", None, "(10.8 bps)"),
        ("12", "count", None, "12"),
        ("9.0549", "pct", 3, "9.055%"),
        ("9.05", "pct", 0, "9%"),
    ],
)
def test_values_are_shown_in_the_house_formats(value, unit, decimals, shown):
    assert wording.fmt(Decimal(value), unit, decimals) == shown


@pytest.mark.parametrize(
    "value, shown",
    [("0.05", "0.1%"), ("0.15", "0.2%"), ("0.25", "0.3%"), ("0.35", "0.4%"), ("0.45", "0.5%"),  # half up, never half to even
     ("-0.05", "(0.1%)"), ("-0.25", "(0.3%)"), ("0.049", "0.0%"), ("0.051", "0.1%")],
)
def test_rounding_is_half_up_exactly_at_the_boundary(value, shown):
    assert wording.fmt(Decimal(value), "pct", 1) == shown


def test_each_unit_has_a_default_number_of_decimals_and_a_series_can_override_it():
    assert wording.DEFAULT_DECIMALS == {"pct": 2, "bps": 1, "multiple": 1, "kes_bn": 1, "kes_mn": 1, "usd_mn": 1, "index": 1, "count": 0}
    assert wording.fmt(Decimal("9.056"), "pct") == "9.06%"
    assert series("Invented x", "pct", ["9.056"], decimals=1).latest.value == Decimal("9.056")
    assert series("Invented x", "pct", ["9.056"], decimals=1).decimals == 1
    assert series("Invented x", "pct", ["9.056"]).decimals is None


def test_a_series_decimals_must_be_a_small_whole_number():
    for bad in (-1, 7, 1.5, True):
        with pytest.raises(SeriesError, match="decimals"):
            series("Invented x", "pct", ["9.0"], decimals=bad)


def test_weekly_helper_builds_fridays_ending_on_the_week():
    assert weekly(["1", "2"])[-1][0] == FRI and weekly(["1", "2"])[0][0] == date(2026, 10, 2)
