"""Invented "Notable this week" items for the end-to-end test instance, and for nothing else.

The items are no longer written by hand: each comes from a clearly invented series (every name begins "Invented") run through
the real detector library, so the headlines, working, figures and ranks are the library's own. Every series carries the demo
provenance, whose label can only read "invented demo item" (cytonn_weekly/notable/suggestion.py), and the panel shows that
label on each card. The numbers are made up; none comes from a source.

This file is how the test instance has suggestions at all. The real app builds its API with no registry argument, which
means the real registry, which is empty. Nothing in backend/ imports this file, and no environment variable or data file
switches it on: only e2e/serve_e2e.py, by passing REGISTRY to create_app().

The series are shaped so that the ranks fall in a fixed order whatever the week (only the dates move with it):
Fixed Income streak 90, record 55, since 52, range 50, threshold 48, trailing 46, pace 42.
"""
from datetime import date, timedelta
from decimal import Decimal

from cytonn_weekly.notable.detectors import Provenance, Series
from cytonn_weekly.notable.detectors import drift, expected_range, pace, since, streak, threshold_cross, trailing_compare

INVENTED = Provenance("demo", "invented demo item")


def series(name: str, unit: str, values: list, week: date) -> Series:
    """The values as weekly points, the last on ``week``."""
    n = len(values)
    return Series(name, unit, [(week - timedelta(days=7 * (n - 1 - i)), v) for i, v in enumerate(values)], INVENTED)


def fixed_income(ctx):
    w, kw = ctx.week_ending, dict(section="fixed_income", week_ending=ctx.week_ending)
    found = []
    # streak: nine weekly rises
    found += streak(series("Invented 91-day yield", "pct",
                           ["8.10", "8.18", "8.27", "8.37", "8.48", "8.60", "8.73", "8.87", "9.00", "9.05"], w), **kw)
    # record: the highest of the 26 points held
    found += since(series("Invented 364-day bill subscription", "pct",
                          ["118.0", "131.5", "124.2", "140.8", "126.0", "133.1", "129.4", "138.0", "122.7", "135.5", "127.9", "141.2",
                           "130.6", "136.4", "125.3", "139.7", "128.8", "134.2", "123.5", "137.9", "131.0", "142.6", "126.9", "138.8",
                           "132.4", "152.3"], w), **kw)
    # since: the lowest since an equal value 22 weeks back
    found += since(series("Invented 3-month bank placement rate", "pct",
                          ["9.90", "9.80", "9.75", "9.40", "9.70", "9.85", "9.65", "9.80", "9.60", "9.75", "9.90", "9.70", "9.55",
                           "9.80", "9.65", "9.75", "9.50", "9.85", "9.60", "9.70", "9.55", "9.80", "9.65", "9.75", "9.60", "9.40"], w), **kw)
    # expected_range: just above the previous 26 weeks
    found += expected_range(series("Invented Cytonn Money Market Fund yield", "pct",
                                   ["10.60", "10.70", "10.80", "10.90", "11.00", "10.75", "10.65", "10.85", "10.95", "10.70", "10.80",
                                    "10.60", "10.90", "10.75", "10.85", "11.00", "10.65", "10.70", "10.80", "10.95", "10.60", "10.85",
                                    "10.75", "10.90", "10.80", "10.70", "11.02"], w), **kw)
    # threshold_cross: through 10% for the first time since 8 weeks back
    found += threshold_cross(series("Invented 182-day yield", "pct",
                                    ["9.60", "9.70", "9.80", "9.75", "9.65", "10.05", "9.80", "9.75", "9.70", "9.65", "9.70", "9.80",
                                     "9.95", "10.10"], w), level="10", **kw)
    # trailing_compare: well above the previous 12 weeks' mean
    found += trailing_compare(series("Invented interbank volume", "kes_bn",
                                     ["14.2", "15.1", "13.8", "14.9", "15.6", "14.4", "15.0", "14.7", "15.3", "14.1", "14.8", "15.2",
                                      "18.4"], w), threshold="18.7", **kw)
    # pace: a little ahead of the period's pace (the gap is 1.2 points in every week; only the elapsed share moves)
    start = date(w.year if w.month >= 7 else w.year - 1, 7, 1)
    target = Decimal("920.0")
    elapsed = Decimal((w - start).days) / Decimal(364)
    actual = (target * (elapsed + Decimal("0.012"))).quantize(Decimal("0.1"))
    found += pace(series("Invented net domestic borrowing", "kes_bn",
                         [str((actual * f).quantize(Decimal("0.1"))) for f in (Decimal("0.55"), Decimal("0.7"), Decimal("0.85"), Decimal(1))], w),
                  target=target, period_start=start, period_end=start + timedelta(days=364), as_of=w, threshold_pp="1", **kw)
    return found


def equities(ctx):
    w, kw = ctx.week_ending, dict(section="equities", week_ending=ctx.week_ending)
    found = drift(name="Invented Equity Co", price_now="49.30", price_previous="48.50", target="52.00", dividend_per_share="2.00",
                  provenance=INVENTED, **kw)
    found += since(series("Invented market P/E", "multiple",
                          ["6.4", "6.2", "6.1", "6.3", "6.0", "6.2", "6.1", "6.3", "6.4", "6.2", "6.0", "6.1", "6.3", "6.2", "6.4",
                           "6.1", "6.0", "6.2", "6.3", "6.1", "6.2", "6.4", "6.0", "6.3", "6.2", "5.9"], w), **kw)
    return found


def company_updates(ctx):
    w, kw = ctx.week_ending, dict(section="company_updates", week_ending=ctx.week_ending)
    found = streak(series("Invented hospitality items named", "count", ["1", "2", "3", "4", "5"], w), **kw)
    found += trailing_compare(series("Invented update text length", "count",
                                     ["300", "310", "290", "305", "295", "315", "300", "310", "290", "305", "300", "295", "420"], w),
                              threshold="20", **kw)
    return found


def _broken(ctx):
    raise RuntimeError("E2E: a deliberate detector failure for the tests (C:/private/path/history.csv)")


# Real Estate, Digital Payments and Focus have none: they show the empty state.
REGISTRY = {
    "fixed_income": [fixed_income],
    "equities": [equities, _broken],
    "company_updates": [company_updates],
}
