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
_TITLE = re.compile(r"^Table \d+:\s*Performance of Key Market Indicators")   # the table's number moves between issues, its title does not
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_MARKET = 8   # the equity and bond columns that come before the yields


def parse(pdf_bytes: bytes) -> dict[date, dict[int, str]]:
    """The bulletin's Table 6 -> {day: {maturity year: yield as printed}}; a "Public Holiday" row is read like any other (CBK prints the yields on it).

    Known layouts only: five or eight yield columns, each under a printed year, and every day a row of
    the market columns plus one yield per column, or a "Public Holiday" row with the yields alone.
    Anything else raises ValueError and nothing is returned.
    """
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = next((p for p in pdf.pages if any(_TITLE.match(t.strip()) for t in (p.extract_text() or "").splitlines())), None)
        if page is None:
            raise ValueError("no 'Performance of Key Market Indicators' table")
        words = page.extract_words()
    lines: dict[int, str] = {}
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        lines[round(w["top"])] = f"{lines.get(round(w['top']), '')} {w['text']}".strip()
    top = next((t for t, text in sorted(lines.items()) if _TITLE.match(text)), None)
    if top is None:
        raise ValueError("the table's title is not at the start of a line")
    stop = next((t for t, text in sorted(lines.items()) if t > top and bulletin._END.match(text)), 10**6)
    band = [w for w in words if top + 2 < w["top"] < stop - 2]
    dates = sorted((w for w in band if re.fullmatch(bulletin._DAY, w["text"])), key=lambda w: w["top"])
    if not dates:
        raise ValueError("the table has no dated rows")
    heads = sorted((w for w in band if w["top"] < dates[0]["top"] and re.fullmatch(r"20\d{2}", w["text"])), key=lambda w: w["x0"])
    years = [int(w["text"]) for w in heads]
    if len(years) not in (5, 8) or len(set(years)) != len(years) or not set(KEY) <= set(years):
        raise ValueError(f"the yield columns are not ones this tool knows ({len(years)} years printed)")
    out: dict[date, dict[int, str]] = {}
    for d in dates:
        row = sorted((w for w in band if abs(w["top"] - d["top"]) <= 6 and w["x0"] > d["x1"]), key=lambda w: w["x0"])
        figures = [w for w in row if w["text"].lower() not in ("public", "holiday")]
        holiday = len(figures) != len(row)
        day = bulletin._day(d["text"])
        if day in out or not all(_NUMBER.fullmatch(w["text"]) for w in figures) or len(figures) != len(years) + (0 if holiday else _MARKET):
            raise ValueError(f"the row of {day.isoformat()} is not a layout this tool knows")
        yields: dict[int, str] = {}
        for w in figures[-len(years):]:
            centre = (w["x0"] + w["x1"]) / 2
            head = min(heads, key=lambda h: abs((h["x0"] + h["x1"]) / 2 - centre))
            if abs((head["x0"] + head["x1"]) / 2 - centre) > 25 or int(head["text"]) in yields:
                raise ValueError(f"a yield of {day.isoformat()} is under no single printed year")
            yields[int(head["text"])] = w["text"].replace(",", "")
        out[day] = yields
    return out


def opening(year: int, month: int, cap: int, until: date,
            get: Callable[[str], bytes] = http_get) -> tuple[date, dict[str, str], str, str]:
    """The month's first printed day (no later than ``cap``): (day, {issue key: yield}, bulletin URL, its sha256).

    Read from the first issue, dated a Friday from the 2nd to the 14th and not after ``until``, that is in CBK's archive,
    reads, and prints a day before the 1st (so its first printed day of the month is the month's first printed day).
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
        mine = sorted(d for d in days if (d.year, d.month) == (year, month))
        if not mine or min(days) >= first:
            why.append(f"the issue of {friday.isoformat()} does not print the days before the 1st, so its first day cannot be trusted")
            continue
        yields = days[mine[0]]
        if mine[0].day > cap or not set(KEY) <= set(yields):
            raise LookupError(f"CBK's bulletin of {friday.isoformat()} prints no complete row for the first days of {first.strftime('%B %Y')}")
        return mine[0], {KEY[y]: v for y, v in yields.items() if y in KEY}, url, hashlib.sha256(pdf).hexdigest()
    raise LookupError("; ".join(why) or f"no bulletin is dated between {first.strftime('%B')} 2nd and 14th yet")
