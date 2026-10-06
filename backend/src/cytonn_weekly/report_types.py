"""The kinds of report that go out in the Cytonn Weekly slot, and their period labels.

Verified against the published issues on cytonnreport.com (read 2026-10-05; see
CLAUDE.md, "Report types"):

* ``weekly``     -- the normal Cytonn Weekly, "#38.2026" (2026-09-27).
* ``quarterly``  -- "Cytonn Q1'2026 Markets Review" (2026-04-05) and "Cytonn Q3' 2026 Markets
                    Review" (2026-10-04).  Only Q1 and Q3 exist as quarterly reviews: the Q2
                    slot is the half-year review and the Q4 slot is the annual review.
* ``half_year``  -- "Cytonn H1'2026 Markets Review" (2026-07-05).
* ``annual``     -- "Cytonn Annual Markets Review - 2025" (2026-01-04).
* ``companion``  -- the themed research reports that ride along with a weekly ("Kenya's Listed
                    Banks H1'2026 Report, & Cytonn Weekly #37.2026").  Each is that issue's
                    Focus of the Week, not a separate document, so its period is the weekly
                    issue it rides with.

A period label is part of a review's key (with the report type and the section), so the
Q3'2026 Fixed Income review and a weekly Fixed Income review are different reviews.
Labels are stored normalized, with a straight apostrophe: "Q3'2026", "H1'2026",
"FY'2025", "Weekly #38.2026".  A weekly review may have no label (every review saved
before report types existed has none); every other type requires one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

WEEKLY = "weekly"
QUARTERLY = "quarterly"
HALF_YEAR = "half_year"
ANNUAL = "annual"
COMPANION = "companion"

REPORT_TYPES = (WEEKLY, QUARTERLY, HALF_YEAR, ANNUAL, COMPANION)
PERIODIC = (QUARTERLY, HALF_YEAR, ANNUAL)  # the Markets Reviews, which share one section set


@dataclass(frozen=True)
class ReportTypeSpec:
    slug: str
    title: str                 # as the screen names it
    published_as: str          # how the real issue is titled, with the reference issue
    period_hint: str           # placeholder for the period input
    period_required: bool


TYPES: dict[str, ReportTypeSpec] = {
    WEEKLY: ReportTypeSpec(
        WEEKLY, "Weekly", "Cytonn Weekly #38.2026 (27 Sept 2026)", "Weekly #39.2026", period_required=False),
    QUARTERLY: ReportTypeSpec(
        QUARTERLY, "Quarterly Markets Review", "Cytonn Q3' 2026 Markets Review (4 Oct 2026)", "Q3'2026",
        period_required=True),
    HALF_YEAR: ReportTypeSpec(
        HALF_YEAR, "Half-year Markets Review", "Cytonn H1'2026 Markets Review (5 July 2026)", "H1'2026",
        period_required=True),
    ANNUAL: ReportTypeSpec(
        ANNUAL, "Annual Markets Review", "Cytonn Annual Markets Review - 2025 (4 Jan 2026)", "FY'2025",
        period_required=True),
    COMPANION: ReportTypeSpec(
        COMPANION, "Companion research report",
        "Kenya's Listed Banks H1'2026 Report, & Cytonn Weekly #37.2026 (20 Sept 2026)", "Weekly #37.2026",
        period_required=True),
}


class PeriodError(ValueError):
    """A period label that does not fit its report type."""


_APOS = r"\s*['’‘`]?\s*"
_WEEKLY_RE = re.compile(r"^(?:weekly)?\s*#?\s*(\d{1,2})\s*[./]\s*(\d{4})$", re.I)
_QUARTER_RE = re.compile(r"^Q\s*([1-4])" + _APOS + r"(\d{4})$", re.I)
_HALF_RE = re.compile(r"^H\s*([12])" + _APOS + r"(\d{4})$", re.I)
_ANNUAL_RE = re.compile(r"^(?:FY" + _APOS + r")?(\d{4})$", re.I)


def normalize_period(report_type: str, period: Optional[str]) -> str:
    """The stored form of ``period`` for ``report_type``; raises PeriodError if it does not fit.

    Returns "" only for a weekly review with no label.
    """
    if report_type not in TYPES:
        raise PeriodError(f"unknown report type {report_type!r}; expected one of {', '.join(REPORT_TYPES)}")
    raw = " ".join((period or "").split())
    spec = TYPES[report_type]
    if not raw:
        if spec.period_required:
            raise PeriodError(f"the {spec.title} needs a period, e.g. {spec.period_hint}")
        return ""
    if report_type in (WEEKLY, COMPANION):
        m = _WEEKLY_RE.match(raw)
        if not m or not 1 <= int(m.group(1)) <= 53:
            raise PeriodError(f"{raw!r} is not a weekly issue number; write it as {spec.period_hint}")
        return f"Weekly #{int(m.group(1)):02d}.{m.group(2)}"
    if report_type == QUARTERLY:
        m = _QUARTER_RE.match(raw)
        if not m:
            raise PeriodError(f"{raw!r} is not a quarter; write it as {spec.period_hint}")
        q = int(m.group(1))
        if q == 2:
            raise PeriodError("Cytonn publishes the second quarter as the half-year review (H1); choose Half-year")
        if q == 4:
            raise PeriodError("Cytonn publishes the fourth quarter as the annual review (FY); choose Annual")
        return f"Q{q}'{m.group(2)}"
    if report_type == HALF_YEAR:
        m = _HALF_RE.match(raw)
        if not m:
            raise PeriodError(f"{raw!r} is not a half-year; write it as {spec.period_hint}")
        if m.group(1) == "2":
            raise PeriodError("Cytonn publishes the second half as the annual review (FY); choose Annual")
        return f"H1'{m.group(2)}"
    m = _ANNUAL_RE.match(raw)
    if not m:
        raise PeriodError(f"{raw!r} is not a year; write it as {spec.period_hint}")
    return f"FY'{m.group(1)}"


def period_window(report_type: str, period: str) -> Optional[tuple[date, date]]:
    """First and last day the period covers, or None for a weekly-issue label (a rolling week)."""
    if report_type in (WEEKLY, COMPANION) or not period:
        return None
    m = re.match(r"^(Q|H|FY)(\d)?'(\d{4})$", period)
    if not m:
        raise PeriodError(f"{period!r} is not a normalized period label")
    kind, n, year = m.group(1), m.group(2), int(m.group(3))
    if kind == "FY":
        return date(year, 1, 1), date(year, 12, 31)
    if kind == "H":
        return date(year, 1, 1), date(year, 6, 30)
    q = int(n)
    start = date(year, 3 * (q - 1) + 1, 1)
    end_month = 3 * q
    end = date(year, 12, 31) if end_month == 12 else date(year, end_month + 1, 1) - timedelta(days=1)
    return start, end


def year_ago(period: str) -> str:
    """The same period one year earlier ("Q3'2026" -> "Q3'2025"), the report's usual comparison."""
    m = re.match(r"^(.*')(\d{4})$", period)
    if not m:
        raise PeriodError(f"{period!r} has no year to step back from")
    return f"{m.group(1)}{int(m.group(2)) - 1}"


def prose_label(period: str) -> str:
    """The period as the report's prose writes it, with a typographic apostrophe ("Q3’2026")."""
    return period.replace("'", "’")


def suggested_period(report_type: str, today: date) -> str:
    """The most recent period of this type that has ended by ``today`` ("" for weekly-issue labels).

    A Markets Review goes out in the first Sunday slot after its period ends (Q3'2026 on
    4 Oct 2026), so the period just ended is the one a coordinator is most likely drafting.
    """
    year = today.year
    if report_type == QUARTERLY:
        if today > date(year, 9, 30):
            return f"Q3'{year}"
        if today > date(year, 3, 31):
            return f"Q1'{year}"
        return f"Q3'{year - 1}"
    if report_type == HALF_YEAR:
        return f"H1'{year}" if today > date(year, 6, 30) else f"H1'{year - 1}"
    if report_type == ANNUAL:
        return f"FY'{year - 1}"
    return ""
