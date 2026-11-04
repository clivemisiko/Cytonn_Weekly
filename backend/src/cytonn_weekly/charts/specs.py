"""The charts the tool draws itself, from series it reads out of the analysts' workbooks.

One ``ChartSpec`` per chart says where its series sits (a sheet and a header text, never a row
number: the workbooks grow every week), its unit, how many years the picture shows and how fresh
the series has to be.  Nothing here reads a workbook; ``charts/series.py`` does.

The two NASI charts share one sheet and are the only specs so far.  A chart's numbers are the
analysts' typed workbook values: they are never "verified" unless a second source agrees.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from cytonn_weekly.weekly.equities_workbook import VALUATION_SHEET

# The "Average = x" the team puts on these charts is the mean of every point from here on, not just
# the years the picture shows.  It is a named constant so it is one line to change.
AVERAGE_FROM = date(2009, 1, 1)
# The window the picture shows (Ryan, 3 Nov 2026): it follows the month the report is in and is fixed within that month,
# starting on the first of that month this many years earlier.  The October 2026 published charts start at Oct-19.
NASI_WINDOW_YEARS = 7


@dataclass(frozen=True)
class ChartSpec:
    id: str
    title: str                      # short name in the review ("NASI P/E chart")
    caption: str                    # as listed in the section's CHARTS, so the Word export can place it
    sheet: str                      # verbatim from the workbook (some end in a space)
    header: str                     # the label above the dates; the values are in the next column
    unit: str                       # "multiple" (10.0x), or "pct": stored as a fraction and formatted as a percentage
    window_years: int               # the picture starts on the first of the week's month, this many years earlier
    newest_not_before_days: int     # freshness: the newest point is dated this many days after the week's Friday or later
    ceiling_days: int               # no point is dated later than this many days after the Friday
    quoted: tuple[tuple[str, str], ...]   # (what the draft quotes, its figure key in the section): ("point", "pe")
    decimals: int = 1               # display precision of the quoted figures, as the report prints them
    name: str = ""                  # the published chart's own name, after "Cytonn Report: "
    y_top: Optional[int] = None     # the y axis runs from 0 to this; None: the next multiple of y_step above the data
    y_step: int = 2
    min_points: int = 52            # a year of weekly points; fewer is not a chart

    @property
    def scale(self) -> int:
        """A percentage is stored as a fraction (0.05 shown as 5.0%); the chart works in percentage points."""
        return 100 if self.unit == "pct" else 1


NASI_PE = ChartSpec(
    id="nasi_pe",
    title="NASI P/E chart",
    caption="The charts below indicate the historical P/E and dividend yields of the market (P/E chart)",
    sheet=VALUATION_SHEET, header="Price to Earnings", unit="multiple", window_years=NASI_WINDOW_YEARS,
    newest_not_before_days=0, ceiling_days=0,
    quoted=(("point", "pe"), ("average", "pe_average")),
    name="NASI P/E", y_top=19,
)
NASI_YIELD = ChartSpec(
    id="nasi_yield",
    title="NASI dividend yield chart",
    caption="The charts below indicate the historical P/E and dividend yields of the market (dividend yield chart)",
    sheet=VALUATION_SHEET, header="Dividend Yield", unit="pct", window_years=NASI_WINDOW_YEARS,
    newest_not_before_days=0, ceiling_days=0,
    quoted=(("point", "dividend_yield"), ("average", "dividend_yield_average")),
    name="NASI Dividend Yield",
)

SPECS = {s.id: s for s in (NASI_PE, NASI_YIELD)}
