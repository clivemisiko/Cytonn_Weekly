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

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

FRIDAY = 4


class NotAFriday(ValueError):
    """A week-ending date that is not a Friday."""


def latest_friday(today: date) -> date:
    """The most recent Friday on or before ``today``."""
    return today - timedelta(days=(today.weekday() - FRIDAY) % 7)


def require_friday(day: date) -> date:
    if day.weekday() != FRIDAY:
        raise NotAFriday(f"{day.isoformat()} is a {day.strftime('%A')}; a weekly report's week ends on a Friday")
    return day


@dataclass(frozen=True)
class Week:
    """One report week, named by the Friday it ends on."""

    ending: date

    def __post_init__(self) -> None:
        require_friday(self.ending)

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
        """Monday to Friday (public holidays are not known here; a day with no report is simply missing)."""
        return [self.monday + timedelta(days=n) for n in range(5)]

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
