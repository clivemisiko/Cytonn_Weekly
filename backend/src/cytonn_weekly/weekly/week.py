"""The week a weekly report covers, and the windows its figures use.

A weekly report is for a week ending on a Friday.  Its figures do not all use the same
days (read from the workbooks and checked against the published issues, 2026-10-09):

* equities, turnover and foreign flows: Monday to Friday;
* the shilling: Friday to Friday;
* the interbank market: Friday to Thursday (the CBK Weekly Bulletin's weekly row);
* Eurobond yields: up to Thursday (the bulletin's last day);
* T-bills: that week's Thursday auction, whose value date is the following Monday.

The year-to-date base everywhere is the year's first trading day (2 January 2026 for
2026): its close or rate, read from the source, never typed here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

FRIDAY = 4

# Known market closures, ISO date to name, edited by hand; read on every use so an edit takes effect at once.
CLOSURES_FILE = Path(__file__).with_name("market_closures.json")


def closures() -> dict[date, str]:
    try:
        raw = json.loads(CLOSURES_FILE.read_text(encoding="utf-8"))
        return {date.fromisoformat(k): str(v) for k, v in raw.items()}
    except (OSError, ValueError, AttributeError) as exc:
        raise ValueError(f"The list of market closures ({CLOSURES_FILE.name}) cannot be read: {exc}. "
                         'It holds {"YYYY-MM-DD": "name"} lines.') from exc


class NotAFriday(ValueError):
    """A week-ending date that is not a Friday."""


def latest_friday(today: date) -> date:
    """The most recent Friday on or before ``today``."""
    return today - timedelta(days=(today.weekday() - FRIDAY) % 7)


def day_text(d: date) -> str:
    """A date as the screen writes it ("15 Oct 2026"; frontend/src/lib/format.ts friendlyDate)."""
    return f"{d.day} {d:%b %Y}"


def require_friday(day: date) -> date:
    if day.weekday() != FRIDAY:
        raise NotAFriday(f"{day_text(day)} is a {day.strftime('%A')}. A weekly report's week ends on a Friday, "
                         "so choose a Friday.")
    return day


@dataclass(frozen=True)
class Week:
    """One report week, named by the Friday it ends on, even when that Friday is a market holiday.

    Its figures are as at ``as_at``: the last trading day Monday to Friday, or the day the coordinator set.
    """

    ending: date
    as_at_set: Optional[date] = None

    def __post_init__(self) -> None:
        require_friday(self.ending)
        if self.as_at_set is not None:
            if not self.monday <= self.as_at_set <= self.ending or self.as_at_set.weekday() > FRIDAY:
                raise ValueError(f"The as-at date {day_text(self.as_at_set)} is not a weekday of the week ending "
                                 f"{day_text(self.ending)}.")
            if self.as_at_set in closures():
                raise ValueError(f"{day_text(self.as_at_set)} was a market holiday, so figures cannot be as at that day.")

    def with_as_at(self, day: Optional[date]) -> "Week":
        return self if day is None else Week(self.ending, day)

    @property
    def closed_days(self) -> list[date]:
        shut = closures()
        return [d for d in (self.monday + timedelta(days=n) for n in range(5)) if d in shut]

    @property
    def as_at(self) -> date:
        """The day this week's prices and rates are as at (the Friday, unless it was closed or the coordinator chose another)."""
        if self.as_at_set is not None:
            return self.as_at_set
        shut = closures()
        return max((d for d in (self.monday + timedelta(days=n) for n in range(5)) if d not in shut), default=self.ending)

    @property
    def previous_as_at(self) -> date:
        """The previous week's as-at date: the day this week's w/w moves are measured from."""
        return self.previous.as_at

    @property
    def holiday_note(self) -> Optional[str]:
        """The reviewer note for a week whose Friday was closed, or whose as-at date was chosen by hand."""
        shut = closures()
        parts = []
        if self.ending in shut:
            parts.append(f"Friday {day_text(self.ending)} was a market holiday; figures are as at "
                         f"{self.as_at:%A} {day_text(self.as_at)}.")
        elif self.as_at != self.ending:
            parts.append(f"Figures are as at {self.as_at:%A} {day_text(self.as_at)}, the date set for this week.")
        parts += [f"{d:%A} {day_text(d)} was a market holiday; its data is skipped."
                  for d in self.closed_days if d != self.ending]
        return " ".join(parts) or None

    @property
    def monday(self) -> date:
        return self.ending - timedelta(days=4)

    @property
    def thursday(self) -> date:
        return self.ending - timedelta(days=1)

    @property
    def previous_friday(self) -> date:
        return self.ending - timedelta(days=7)

    @property
    def trading_days(self) -> list[date]:
        """Monday to the as-at day, without the known closures (a day with no report is simply missing)."""
        shut, last = closures(), self.as_at
        return [d for d in (self.monday + timedelta(days=n) for n in range(5)) if d not in shut and d <= last]

    @property
    def days_text(self) -> str:
        """The days a Monday-to-Friday sum covers, for the note under it."""
        days = self.trading_days
        return "Monday to Friday" if len(days) == 5 else f"{len(days)} trading days ({', '.join(f'{d:%A}' for d in days)})"

    def days_note(self) -> str:
        """The days used by a Monday-to-Friday sum, and when the previous week had a different number, that its total is not like for like."""
        before = len(self.previous.trading_days)
        text = f"{self.days_text}"
        if before != len(self.trading_days):
            text += f"; the previous week had {before} trading days, so the change compares weekly totals over different numbers of days"
        return text

    @property
    def report_dates(self) -> tuple[date, ...]:
        """The dates a document for this week can carry: the Friday, or the as-at day when the Friday was closed."""
        return (self.ending,) if self.as_at == self.ending else (self.ending, self.as_at)

    @property
    def previous(self) -> "Week":
        return Week(self.previous_friday)

    @property
    def value_date_window(self) -> tuple[date, date]:
        """Where this week's auctions settle: the Saturday after the Friday to the Friday after."""
        return self.ending + timedelta(days=1), self.ending + timedelta(days=7)

    def label(self) -> str:
        return f"Week ending {self.ending.isoformat()}"


def week_for(ending: Optional[date] = None, today: Optional[date] = None) -> Week:
    """The week ending on ``ending``, or the latest week that has ended by ``today``."""
    return Week(ending if ending is not None else latest_friday(today or date.today()))


def ordinal(day: date) -> str:
    """"2nd October 2026", as the report writes a date in prose."""
    n = day.day
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix} {day.strftime('%B %Y')}"


def table_date(day: date) -> str:
    """"02-Oct-26", as the report's Eurobond table heads a row."""
    return day.strftime("%d-%b-%y")
