"""Invented "Notable this week" items for the end-to-end test instance, and for nothing else.

Every item is marked provenance "demo", whose label can only read "invented demo item" (cytonn_weekly/notable/suggestion.py),
and the panel shows that label on each one.  The figures are made up; none comes from a source.

This file is how the test instance has suggestions at all.  The real app builds its API with no registry argument, which
means the real registry, which is empty.  Nothing in backend/ imports this file, and no environment variable or data file
switches it on: only e2e/serve_e2e.py, by passing REGISTRY to create_app().
"""
from datetime import timedelta

from cytonn_weekly.notable.suggestion import Suggestion

DEMO = {"kind": "demo", "label": "invented demo item"}

# (kind, rank, headline, series, rule, window, unit, five values oldest first)
FIXED_INCOME = [
    ("streak", 95, "The 91-day T-bill yield has risen for a third week in a row.", "91-day T-bill yield",
     "Three weekly rises in a row.", "last 12 weeks", "%", [9.1, 9.2, 9.4, 9.5, 9.6]),
    ("record", 88, "Subscription on the 364-day bill was the highest this year.", "364-day bill subscription",
     "The highest value of the year so far.", "since 2 January", "%", [118.0, 131.5, 124.2, 140.8, 152.3]),
    ("since", 80, "The 3-month bank placement rate is the lowest since June.", "3-month bank placement rate",
     "The lowest value since the last time it was this low.", "last 26 weeks", "%", [9.9, 9.8, 9.6, 9.5, 9.4]),
    ("trailing_compare", 72, "This week's interbank volume is 24% above its trailing 8-week average.", "Interbank volume",
     "More than 20% above the average of the previous 8 weeks.", "last 8 weeks", " bn", [14.2, 15.1, 13.8, 14.9, 18.4]),
    ("threshold_cross", 60, "The 182-day yield crossed above 10% for the first time this year.", "182-day T-bill yield",
     "Crossed above 10.0% for the first time this year.", "year to date", "%", [9.7, 9.8, 9.9, 9.95, 10.1]),
    ("expected_range", 45, "The Cytonn Money Market Fund yield sits above the range of the last 12 weeks.", "Cytonn Money Market Fund yield",
     "Outside the range it has stayed in over the last 12 weeks.", "last 12 weeks", "%", [10.6, 10.7, 10.7, 10.8, 11.2]),
    ("pace", 30, "Net domestic borrowing is on pace to reach its full-year target in March.", "Net domestic borrowing, share of target",
     "At this week's pace, the full-year target is reached in March.", "fiscal year to date", "%", [190.0, 205.0, 218.0, 231.0, 236.0]),
]
EQUITIES = [
    ("drift", 85, "The market P/E has drifted down for six weeks.", "Market P/E",
     "Fell in each of the last six weeks.", "last 6 weeks", "x", [6.4, 6.3, 6.2, 6.0, 5.9]),
    ("since", 40, "Foreign investors were net buyers for the first time since August.", "Foreign net position",
     "First net purchase since the last one.", "last 26 weeks", " mn", [-3.1, -2.4, -1.2, -0.6, 0.8]),
]
COMPANY_UPDATES = [
    ("record", 70, "The week's update text is the longest since the start of the year.", "Update text length",
     "The highest value of the year so far.", "since 2 January", " words", [310, 280, 350, 340, 420]),
    ("streak", 50, "Updates have named a hospitality item four weeks in a row.", "Hospitality items named",
     "Four weekly appearances in a row.", "last 12 weeks", "", [1, 1, 2, 1, 1]),
]


def _detector(section: str, items: list):
    def detect(ctx):
        out = []
        for kind, rank, headline, series, rule, window, unit, values in items:
            n = len(values)
            points = [{"date": (ctx.week_ending - timedelta(days=7 * (n - 1 - i))).isoformat(), "value": v, "display": f"{v:g}{unit}"}
                      for i, v in enumerate(values)]
            out.append(Suggestion(
                kind=kind, section=section, week_ending=ctx.week_ending.isoformat(), headline=headline,
                figures=[{"label": series, "value": values[-1], "display": points[-1]["display"], "unit": unit.strip()}],
                working={"series": series, "rule": rule, "window": window, "points": points},
                provenance=dict(DEMO), rank=rank,
            ))
        return out

    detect.__name__ = f"demo_{section}"
    return detect


def _broken(ctx):
    raise RuntimeError("E2E: a deliberate detector failure for the tests (C:/private/path/history.csv)")


# Real Estate, Digital Payments and Focus have none: they show the empty state.
REGISTRY = {
    "fixed_income": [_detector("fixed_income", FIXED_INCOME)],
    "equities": [_detector("equities", EQUITIES), _broken],
    "company_updates": [_detector("company_updates", COMPANY_UPDATES)],
}
