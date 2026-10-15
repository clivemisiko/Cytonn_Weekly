"""Shared by the notable detector tests: weekly series built from plain strings, and expected values written out by hand.

Nothing here calls the detector library to work out an expectation; expected points, dates and displays are built from the
input strings, so a golden test compares the library with an independent statement of the answer.
"""

from datetime import date, timedelta
from decimal import Decimal

from cytonn_weekly.notable.detectors import Provenance, Series

FRI = date(2026, 10, 9)  # a Friday: the report week every golden case ends on
SECTION = "fixed_income"
PUBLISHED = Provenance("published", "CBK weekly bulletin")
INVENTED = Provenance("demo", "invented demo item")
WORKBOOK = Provenance("analyst_workbook", "from the analyst workbook, not verified")


def dates(n: int, end: date = FRI) -> list[date]:
    """n Fridays, one a week, the last on ``end``."""
    return [end - timedelta(days=7 * (n - 1 - i)) for i in range(n)]


def weekly(values, end: date = FRI) -> list[tuple[date, str]]:
    return list(zip(dates(len(values), end), values))


def series(name: str, unit: str, values, end: date = FRI, provenance: Provenance = PUBLISHED, **kw) -> Series:
    return Series(name, unit, weekly(values, end), provenance, **kw)


def points(values, suffix: str = "%", end: date = FRI, prefix: str = "") -> list[dict]:
    """The working points a detector should show for these values: date, exact value, and the value with a suffix."""
    return [{"date": d.isoformat(), "value": Decimal(v), "display": f"{prefix}{v}{suffix}"} for d, v in weekly(values, end)]


def fig(label: str, value, display: str, unit: str) -> dict:
    return {"label": label, "value": Decimal(str(value)), "display": display, "unit": unit}


def snap(s) -> dict:
    """What a golden test compares: everything a person sees about a suggestion."""
    return {"kind": s.kind, "section": s.section, "week_ending": s.week_ending, "headline": s.headline, "figures": s.figures,
            "working": s.working, "provenance": s.provenance, "rank": s.rank}
