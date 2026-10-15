"""The input of every detector: a named, dated series of exact numbers, and where its values came from.

A Series is built from strings or Decimals, never floats, and is refused with a SeriesError when it cannot be used as it
stands: unsorted or repeated dates, a missing or non-finite value, no points. The library never repairs data; a caller that
has a gap or a duplicate must say so by fixing the series, not by hoping it is smoothed over.

The name and the unit are kept exactly: the name is half of a suggestion's id, so it must be stable text with no date in it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional

from cytonn_weekly.notable.suggestion import FIXED_LABELS, PROVENANCE_KINDS

UNITS = ("pct", "bps", "multiple", "kes_bn", "kes_mn", "usd_mn", "index", "count")
MAX_DECIMALS = 6
_DATE_IN_NAME = re.compile(r"\d{4}-\d{2}-\d{2}")


class SeriesError(ValueError):
    """A series that cannot be used as it stands; the message says why."""


@dataclass(frozen=True)
class Provenance:
    """Where a series' values came from, in the notable shape's own terms (kind and label)."""

    kind: str
    label: str

    def __post_init__(self) -> None:
        if self.kind not in PROVENANCE_KINDS:
            raise SeriesError(f"provenance kind must be one of {list(PROVENANCE_KINDS)}")
        if not isinstance(self.label, str) or not self.label.strip():
            raise SeriesError("the provenance label must be a non-empty string")
        if self.kind in FIXED_LABELS and self.label != FIXED_LABELS[self.kind]:
            raise SeriesError(f"a {self.kind} provenance label must read {FIXED_LABELS[self.kind]!r}")

    def to_dict(self) -> dict:
        return {"kind": self.kind, "label": self.label}


@dataclass(frozen=True)
class Point:
    date: date
    value: Decimal


def _date(value: Any) -> date:
    if isinstance(value, datetime):
        raise SeriesError(f"a point's date must be a date, not a datetime ({value!r})")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise SeriesError(f"{value!r} is not a date; write it as 2026-10-09")


def _value(value: Any, when: date) -> Decimal:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise SeriesError(f"the value for {when.isoformat()} is missing")
    if isinstance(value, (float, bool)):
        raise SeriesError(f"the value for {when.isoformat()} is a {type(value).__name__}: give it as a string or a Decimal, never a float")
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, (int, str)):
        try:
            number = Decimal(value.strip() if isinstance(value, str) else value)
        except InvalidOperation:
            raise SeriesError(f"the value for {when.isoformat()} ({value!r}) is not a number") from None
    else:
        raise SeriesError(f"the value for {when.isoformat()} is a {type(value).__name__}, not a number")
    if not number.is_finite():
        raise SeriesError(f"the value for {when.isoformat()} ({value!r}) is not finite")
    return number


@dataclass(frozen=True)
class Series:
    """``points`` are (date, value) pairs, oldest first, one date each."""

    name: str
    unit: str
    points: Any  # normalized to a tuple of Point
    provenance: Provenance
    decimals: Optional[int] = None  # None: the unit's own number of decimals (wording.DEFAULT_DECIMALS)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise SeriesError("the series needs a name")
        if _DATE_IN_NAME.search(self.name):
            raise SeriesError(f"the series name {self.name!r} contains a date, which would change the suggestion's id every week")
        if self.unit not in UNITS:
            raise SeriesError(f"unit must be one of {list(UNITS)}, not {self.unit!r}")
        if not isinstance(self.provenance, Provenance):
            raise SeriesError("provenance must be a Provenance object")
        if self.decimals is not None and (isinstance(self.decimals, bool) or not isinstance(self.decimals, int)
                                          or not 0 <= self.decimals <= MAX_DECIMALS):
            raise SeriesError(f"decimals must be a whole number from 0 to {MAX_DECIMALS}")
        object.__setattr__(self, "points", _points(self.points))

    @property
    def latest(self) -> Point:
        return self.points[-1]

    def unbroken(self, max_gap_days: int) -> tuple[Point, ...]:
        """The points that end at the latest one with no gap above ``max_gap_days`` between neighbours."""
        pts = self.points
        start = len(pts) - 1
        while start > 0 and (pts[start].date - pts[start - 1].date) <= timedelta(days=max_gap_days):
            start -= 1
        return pts[start:]


def _points(raw: Iterable[Any]) -> tuple[Point, ...]:
    out: list[Point] = []
    for item in raw:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise SeriesError(f"a point is a (date, value) pair, not {item!r}")
        when = _date(item[0])
        out.append(Point(when, _value(item[1], when)))
    if not out:
        raise SeriesError("a series needs at least one point")
    for before, after in zip(out, out[1:]):
        if after.date == before.date:
            raise SeriesError(f"the date {after.date.isoformat()} appears twice")
        if after.date < before.date:
            raise SeriesError(f"the dates must be in ascending order: {after.date.isoformat()} comes after {before.date.isoformat()}")
    return tuple(out)
