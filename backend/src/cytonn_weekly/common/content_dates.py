from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

# How long after a period ends its results can still be news. Kenyan listed companies publish annual results within four
# months of the year end (half-year and quarterly ones sooner), so a period that ended earlier than this before the report
# week is not this week's story. ponytail: one bound for every kind of period; to confirm with the equities team.
RESULTS_LAG = timedelta(days=122)
DATELINE_CHARS = 300   # a press release states its date at the top
# A dateline this far before the week marks old content even when the page's stated date is inside it (the stated date is
# what the window judges exactly; an article in the week may open on an event a few days earlier, which is not old news).
DATELINE_GRACE = timedelta(days=30)
LEAD_CHARS = 600       # the periods a page reports are read from its title and its opening

_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_DAY_FIRST = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MON},?\s+(20\d\d)\b", re.I)
_MONTH_FIRST = re.compile(rf"\b{_MON}\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d\d)\b", re.I)
_ISO = re.compile(r"\b(20\d\d)-(\d{2})-(\d{2})\b")
_ENDED = re.compile(r"(ended|ending|end(?:ed)? of|period|as at|as of|quarter|half|year|months)\W*$", re.I)
_YEAR = r"[\s'’_-]*(20\d\d)"   # "Q3 2026", "Q3'2026", "Q3’2026", and in an address "Q3-2026", "Q3_2026"
_PERIODS = (   # (pattern, how the period's end is read from the match)
    (re.compile(rf"\bQ([1-4]){_YEAR}\b", re.I), lambda m: (int(m[2]), 3 * int(m[1]))),
    (re.compile(r"\b(20\d\d)[\s_-]*Q([1-4])\b", re.I), lambda m: (int(m[1]), 3 * int(m[2]))),
    (re.compile(rf"\b(first|second|third|fourth)\s+quarter\s+(?:of\s+)?(?:the\s+year\s+)?{_YEAR}\b", re.I),
     lambda m: (int(m[2]), 3 * ("first", "second", "third", "fourth").index(m[1].lower()) + 3)),
    (re.compile(rf"\bquarter\s+([1-4]){_YEAR}\b", re.I), lambda m: (int(m[2]), 3 * int(m[1]))),
    (re.compile(r"\b(20\d\d)\s+(half|full)[\s-]year\b", re.I), lambda m: (int(m[1]), 6 if m[2].lower() == "half" else 12)),
    (re.compile(rf"\b(H[12]|HY|FY){_YEAR}\b", re.I), lambda m: (int(m[2]), 6 if m[1].upper() in ("H1", "HY") else 12)),
    (re.compile(r"\b(20\d\d)[\s_-]*(H[12]|HY|FY)\b", re.I), lambda m: (int(m[1]), 6 if m[2].upper() in ("H1", "HY") else 12)),
    (re.compile(rf"\b(half[\s-]year|full[\s-]year)\s+(?:results\s+)?(?:of\s+)?{_YEAR}\b", re.I),
     lambda m: (int(m[2]), 6 if m[1].lower().startswith("half") else 12)),
)


def _month_end(year: int, month: int) -> date:
    return (date(year + month // 12, month % 12 + 1, 1)) - timedelta(days=1)


def _dates(text: str) -> list[tuple[int, date]]:
    """Every plain date in ``text`` with where it starts: "18 November 2026", "November 18, 2026", "2026-11-18"."""
    out = []
    for rx, order in ((_DAY_FIRST, "dmy"), (_MONTH_FIRST, "mdy"), (_ISO, "iso")):
        for m in rx.finditer(text):
            try:
                if order == "iso":
                    d = date(int(m[1]), int(m[2]), int(m[3]))
                else:
                    day, mon = (m[1], m[2]) if order == "dmy" else (m[2], m[1])
                    d = date(int(m[3]), _MONTHS.index(mon[:3].lower()) + 1, int(day))
            except ValueError:
                continue
            out.append((m.start(), d))
    return sorted(out)


def dateline(text: str) -> Optional[date]:
    """The date a document states at its top ("Press Release November 18, 2026"), or None. A date that ends a period
    ("for the nine months ended 30 September 2026") is the period's, not the document's, and is passed over."""
    head = " ".join((text or "")[:DATELINE_CHARS].split())
    return next((d for at, d in _dates(head) if not _ENDED.search(head[max(0, at - 30):at])), None)


def latest_period(text: str) -> Optional[tuple[str, date]]:
    """(the words, the last day) of the newest reporting period ``text`` names: Q3 2026, Q3'2026, 2026 Q1, third quarter
    of 2026, H1 2026, FY2025, full year 2025, or "... ended 30 September 2026". None when it names none."""
    found: list[tuple[date, int, str]] = []   # (last day, where it is named, words)
    text = (text or "").replace("_", " ")   # "Investor_Presentation_Q3_2025.pdf": \b does not break at "_"
    for rx, end in _PERIODS:
        for m in rx.finditer(text):
            year, month = end(m)
            found.append((_month_end(year, month), m.start(), " ".join(m[0].split())))
    flat = " ".join((text or "").split())
    for at, d in _dates(flat):
        if re.search(r"(ended|ending)\W*$", flat[max(0, at - 15):at], re.I):
            found.append((d, at, f"the period ended {d.isoformat()}"))
    if not found:
        return None
    day, _, words = max(found, key=lambda f: (f[0], -f[1]))   # on a tie, the first mention (a title comes first)
    return words, day


def stale_period(text: str, window: tuple[date, date]) -> Optional[str]:
    """The period ``text`` reports when the newest one it names ended too long before the window to be its news (see
    RESULTS_LAG), else None."""
    got = latest_period(text)
    if got and got[1] + RESULTS_LAG < window[0]:
        return got[0] if got[0].startswith("the period ended") else f"{got[0]} (ended {got[1].isoformat()})"
    return None


def content_problem(title: str, text: str, window: tuple[date, date]) -> Optional[str]:
    """Why a page's own words date it outside the window, or None: its dateline is outside the window, or the newest
    reporting period its title and opening name is too old. The page's stated date is judged elsewhere; this reads the
    content, which a wrong stated date cannot hide."""
    line = dateline(text)
    if line and line < window[0] - DATELINE_GRACE:
        return f"its text is dated {line.isoformat()}"
    period = stale_period(f"{title}\n{(text or '')[:LEAD_CHARS]}", window)
    return f"it reports {period}" if period else None
