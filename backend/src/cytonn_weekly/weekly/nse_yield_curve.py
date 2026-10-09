"""The NSE yield curve PDF (text layer): indicative yields for 91 and 182 days and 1 to 29 years.

Read from the 7 October 2026 issue.  Page 2 lists, one per line, "91 day 8.7694",
"182 day 8.8856", then "1 9.0397" to "29 13.0749"; the same lines carry a second table of
tenors and maturity dates to their right, which is ignored (only the first figure after
the tenor is the yield).  The date is printed at the top of page 1 as dd-mm-yyyy.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import pdfplumber

SOURCE_NAME = "Nairobi Securities Exchange yield curve"


class YieldCurveParseError(ValueError):
    pass


_TITLE = "NAIROBI SECURITIES EXCHANGE YIELD CURVE"
_DATE = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")
_SHORT = re.compile(r"^(91|182)\s+day\s+(\d{1,2}\.\d{2,4})\b", re.I)
_YEAR = re.compile(r"^(\d{1,2})\s+(\d{1,2}\.\d{4})\b")


@dataclass
class YieldCurve:
    curve_date: date
    days: dict[int, float] = field(default_factory=dict)    # 91, 182 -> yield %
    years: dict[int, float] = field(default_factory=dict)   # 1..29 -> yield %

    def at(self, tenor_years: float) -> Optional[float]:
        """The yield at a tenor in years, interpolated linearly between the two whole years around it.

        None outside the curve (under 1 year or over its longest tenor): no extrapolation.
        """
        if not self.years:
            return None
        lo, hi = min(self.years), max(self.years)
        if tenor_years < lo or tenor_years > hi:
            return None
        below = int(tenor_years)
        if below == tenor_years or below + 1 not in self.years:
            return self.years.get(below)
        if below not in self.years:
            return None
        share = tenor_years - below
        return self.years[below] + (self.years[below + 1] - self.years[below]) * share

    def to_dict(self) -> dict:
        return {"curve_date": self.curve_date.isoformat(), "days": self.days, "years": self.years}


def parse_yield_curve_text(text: str) -> YieldCurve:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not any(_TITLE in line.upper() for line in lines[:5]):
        raise YieldCurveParseError("not an NSE yield curve: its title is missing")
    when = next((m for m in (_DATE.match(line) for line in lines[:6]) if m), None)
    if when is None:
        raise YieldCurveParseError("no dd-mm-yyyy date under the title")
    curve = YieldCurve(datetime.strptime("-".join(when.groups()), "%d-%m-%Y").date())
    for line in lines:
        m = _SHORT.match(line)
        if m:
            curve.days[int(m.group(1))] = float(m.group(2))
            continue
        m = _YEAR.match(line)
        if m and 1 <= int(m.group(1)) <= 40:
            curve.years.setdefault(int(m.group(1)), float(m.group(2)))
    if not curve.years:
        raise YieldCurveParseError("no yearly yields found")
    missing = [n for n in range(1, max(curve.years) + 1) if n not in curve.years]
    if missing:
        raise YieldCurveParseError(f"the curve skips tenor(s) {missing}")
    return curve


def parse_yield_curve(pdf_bytes: bytes) -> YieldCurve:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    return parse_yield_curve_text(text)
