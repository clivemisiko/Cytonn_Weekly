from __future__ import annotations

import hashlib
import io
import re
from datetime import date, timedelta
from typing import Callable, Optional

import pdfplumber

from cytonn_weekly.common.http import NotFound, http_get
from cytonn_weekly.weekly import cbk_bulletin as bulletin
from cytonn_weekly.weekly.fi_workbook import EUROBOND_ISSUES

KEY = {spec[5]: spec[0] for spec in EUROBOND_ISSUES}   # maturity year printed over a column -> the form's issue key
SOURCE_NAME = "Central Bank of Kenya, Weekly Bulletin"


def parse(pdf_bytes: bytes) -> dict[date, dict[int, str]]:
    """The bulletin's Table 6 -> {day: {maturity year: yield as printed}}, holiday rows included (CBK prints yields on them).

    The reader is the weekly parser's (``cbk_bulletin.table_6_rows``), so a layout it refuses is refused here; and the
    columns must include the five issues the form uses.  Anything else raises ValueError and nothing is returned.
    """
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = next((p for p in pdf.pages if re.search(bulletin._TABLE_6_TITLE.pattern, p.extract_text() or "", re.M)), None)
        if page is None:
            raise ValueError("no 'Performance of Key Market Indicators' table")
        rows = bulletin.table_6_rows(page)
    if not all(set(KEY) <= set(yields) for _, _, _, yields in rows):
        raise ValueError("the yield columns do not include the five Eurobond issues of the form")
    return {day: yields for day, _, _, yields in rows}


def opening(year: int, month: int, cap: int, until: date,
            get: Callable[[str], bytes] = http_get, skip: frozenset[date] = frozenset()) -> tuple[date, dict[str, str], str, str]:
    """The month's first printed day (no later than ``cap``): (day, {issue key: yield}, bulletin URL, its sha256).

    Read from the first issue, dated a Friday from the 2nd to the 14th and not after ``until``, that is in CBK's archive,
    reads, and prints a day before the 1st and every weekday from there to the first it takes (so that day is the month's first printed day).
    ``skip`` days are not taken (the year's opening skips 1 January: markets are shut and the yields are carried forward).
    LookupError, saying why, when no issue does: the analyst types the row.
    """
    first, why = date(year, month, 1), []
    for n in range(1, 14):
        friday = first + timedelta(n)
        if friday.weekday() != 4 or friday > until:
            continue
        try:
            pdf, url = bulletin.fetch_bulletin(friday, get)
            days = parse(pdf)
        except (LookupError, NotFound):
            why.append(f"the issue of {friday.isoformat()} is not in CBK's archive")
            continue
        except ValueError as exc:
            why.append(f"the issue of {friday.isoformat()} was refused: {exc}")
            continue
        mine = sorted(d for d in days if (d.year, d.month) == (year, month) and d not in skip)
        before = max((d for d in days if d < first), default=None)
        run = [] if not mine or before is None else [before + timedelta(n) for n in range(1, (mine[0] - before).days)]
        if not mine or before is None or any(d.weekday() < 5 and d not in days for d in run):   # the 6 Nov 2026 issue prints 2 to 5 Oct, then 23 to 30 Oct
            why.append(f"the issue of {friday.isoformat()} does not print every day from before the 1st to the month's first, so it cannot be trusted")
            continue
        yields = days[mine[0]]
        if mine[0].day > cap or not set(KEY) <= set(yields):
            raise LookupError(f"CBK's bulletin of {friday.isoformat()} prints no complete row for the first days of {first.strftime('%B %Y')}")
        return mine[0], {KEY[y]: v for y, v in yields.items() if y in KEY}, url, hashlib.sha256(pdf).hexdigest()
    raise LookupError("; ".join(why) or f"no bulletin is dated between {first.strftime('%B')} 2nd and 14th yet")
