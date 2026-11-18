"""The CBK Weekly Bulletin (a PDF with a text layer), Tables 1 to 6.

Published on a Friday and covering the Friday before to the Thursday before (the bulletin
of 2 October 2026 covers 25 September to 1 October).  Read from that issue, 2026-10-09:

* Table 1: Kenya Shilling exchange rates, daily, with a weekly average row per week.
* Table 2: foreign exchange reserves (USD million) and months of import cover, five weeks.
* Table 3: interbank deals, value (KSh M) and KESONIA, daily, with a weekly average row.
* Table 4: Treasury bill auctions, per tenor, six auction dates.
* Table 5: Treasury bond auctions.
* Table 6: daily NASI, NSE 25, NSE 20, deals, shares, equity turnover (KSh million), market
  capitalisation, bond turnover, and Eurobond yields by maturity year.
* "Government Domestic Debt (KSh Billion)": the outstanding Treasury bond stock at eight dates,
  the last two of them consecutive Fridays.  It is Table 7 in this issue and its number shifts
  by one in some issues, so it is found by its title.  Optional: an issue without it still reads.

Rows are found by their printed labels and dates, and only inside their own table: a table is
read from its title down to the next "Source:", "Table N:" or "Chart N:" line, never from the
whole page.  CBK moves charts between pages from issue to issue (in the 9 October 2026 issue
the yield curve chart sits above Table 6, and its legend "28-Jun-24 30-Jun-25 2-Oct-26" starts
with a date like a row does).  Table 6's Eurobond columns are matched
to their maturity years by where the year is printed above the column (word positions),
never by an assumed order.

Each table is read on its own.  One that cannot be read, or that fails its checks, is left
out whole (nothing of it is kept, so no figure is partly read) and named in
``Bulletin.unavailable`` with the reason, the issue date and the file's sha256; the other
tables still load.  Only a PDF that is not the bulletin at all is refused.

It can be fetched by date: the listing page links every issue
under ``/uploads/weekly_bulletin/`` with the issue date in the file name.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Optional
from urllib.parse import quote

import pdfplumber

from cytonn_weekly.common.formatting import clean_pdf_number
from cytonn_weekly.common.http import http_get

SOURCE_NAME = "CBK Weekly Bulletin"
CBK = "https://www.centralbank.go.ke"
LISTING = f"{CBK}/weekly-bulletin/"

TENORS = ("91-day", "182-day", "364-day")
# Table 6's Eurobond columns, by maturity year, as the report names the issues.
EUROBOND_ISSUES = {2028: "2018 10-year", 2031: "2024 7-year", 2032: "2019 12-year", 2034: "2021 13-year",
                   2036: "2025 11-year", 2048: "2018 30-year"}


DEBT = "Government Domestic Debt"
TABLES = ("Table 1", "Table 2", "Table 3", "Table 4", "Table 5", "Table 6", DEBT)


class BulletinParseError(ValueError):
    """The bulletin's text does not read the way the sample did."""


_DAY = r"\d{1,2}-[A-Za-z]{3,4}-\d{2}"
_DAY_ROW = re.compile(rf"^({_DAY})\s+(.+)$")
_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_ISSUE_DATE = re.compile(r"^([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})\s*$")


def _day(text: str) -> date:
    text = text.replace("Sept-", "Sep-")
    return datetime.strptime(text, "%d-%b-%y").date()


def _numbers(text: str) -> list[float]:
    return [float(n.replace(",", "")) for n in _NUM.findall(text)]


# Where a table ends: its own source line, or the next table's or chart's title.
_END = re.compile(r"^(?:Source:|Table \d+:|Chart \d+:)")


def _block(lines: list[str], start: str) -> list[str]:
    """One table's lines: from its title (the line starting ``start``) up to, not including, where it ends."""
    try:
        a = next(n for n, line in enumerate(lines) if line.startswith(start))
    except StopIteration:
        raise BulletinParseError(f"'{start}' not found")
    b = next((n for n in range(a + 1, len(lines)) if _END.match(lines[n])), len(lines))
    return lines[a:b]


@dataclass
class Bulletin:
    issue_date: Optional[date]
    exchange_rates: dict[date, float] = field(default_factory=dict)        # Table 1, KSh per USD
    reserves: list[dict[str, Any]] = field(default_factory=list)           # Table 2: {date, usd_mn, months}
    interbank: list[dict[str, Any]] = field(default_factory=list)          # Table 3 daily: {date, deals, value_mn, kesonia}
    interbank_weeks: list[dict[str, Any]] = field(default_factory=list)    # Table 3 weekly: {label, deals, value_mn, kesonia, last_day}
    tbills: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # Table 4: tenor -> [{date, offered, bids, accepted, rate}]
    tbonds: dict[str, Any] = field(default_factory=dict)                   # Table 5, as printed
    market: list[dict[str, Any]] = field(default_factory=list)             # Table 6 daily: indices, turnover, eurobond yields
    bond_stock: dict[date, float] = field(default_factory=dict)            # "Government Domestic Debt": Treasury bonds, KSh bn
    problems: list[str] = field(default_factory=list)
    sha256: str = ""                                                       # of the PDF, so a refused table can be inspected later
    unavailable: dict[str, str] = field(default_factory=dict)              # a name in TABLES -> why it was left out, whole
    # The same refusals as fields, for the screen: {source, issue_date, sha256, location, reason, text}; ``text`` is the
    # sentence in ``unavailable`` so a screen showing the fields can leave that sentence out.
    notices: list[dict[str, Any]] = field(default_factory=list)

    @property
    def last_day(self) -> Optional[date]:
        days = [row["date"] for row in self.market] or list(self.exchange_rates)
        return max(days) if days else None

    def to_dict(self) -> dict[str, Any]:
        def iso(v):
            if isinstance(v, date):
                return v.isoformat()
            if isinstance(v, dict):
                return {(k.isoformat() if isinstance(k, date) else k): iso(x) for k, x in v.items()}
            if isinstance(v, list):
                return [iso(x) for x in v]
            return v

        return iso({"issue_date": self.issue_date, "exchange_rates": self.exchange_rates, "reserves": self.reserves,
                    "interbank": self.interbank, "interbank_weeks": self.interbank_weeks, "tbills": self.tbills,
                    "tbonds": self.tbonds, "market": self.market, "bond_stock": self.bond_stock,
                    "problems": self.problems, "sha256": self.sha256, "unavailable": self.unavailable})


def _table_1(lines: list[str], out: Bulletin) -> None:
    rows = [(m.group(1), m.group(2).split()) for m in map(_DAY_ROW.match, _block(lines, "Table 1:")) if m]
    if not rows:
        raise BulletinParseError("Table 1 has no dated exchange-rate rows")
    # every dated row is one rate per currency and nothing else, so a line that only starts with a date is not a row
    width = len(rows[0][1])
    for day, cells in rows:
        if len(cells) != width or not all(_NUM.fullmatch(c) for c in cells):
            raise BulletinParseError(f"Table 1 row for {day} does not hold {width} rates like the first row: {' '.join(cells)!r}")
    out.exchange_rates = {_day(day): float(cells[0].replace(",", "")) for day, cells in rows}


def _table_2(lines: list[str], out: Bulletin) -> None:
    block = _block(lines, "Table 2:")
    days = next(([_day(d) for d in re.findall(_DAY, line)] for line in block if re.match(rf"^{_DAY}\s", line)), None)
    usd = next((line for line in block if "Reserves (USD Million)" in line and line[:1].isdigit()), None)
    months = next((line for line in block if "Months of Import Cover" in line), None)
    if not days or usd is None or months is None:
        raise BulletinParseError("Table 2 is missing its dates, reserves or import-cover row")
    usd_values = _numbers(usd.split(")", 1)[1])
    month_values = _numbers(months.split(")*", 1)[-1] if ")*" in months else months.split(")", 1)[1])
    if len(usd_values) != len(days) or len(month_values) != len(days):
        raise BulletinParseError(f"Table 2 prints {len(days)} dates but {len(usd_values)} reserves and "
                                 f"{len(month_values)} import-cover figures")
    out.reserves = [{"date": d, "usd_mn": u, "months": m} for d, u, m in zip(days, usd_values, month_values)]


def _table_3(lines: list[str], out: Bulletin) -> None:
    last: Optional[date] = None
    for line in _block(lines, "Table 3:"):
        m = _DAY_ROW.match(line)
        if m:
            nums = _numbers(m.group(2))
            if len(nums) != 3:
                raise BulletinParseError(f"Table 3 row {line!r} does not hold deals, value and KESONIA")
            last = _day(m.group(1))
            out.interbank.append({"date": last, "deals": nums[0], "value_mn": nums[1], "kesonia": nums[2]})
            continue
        # A weekly average row is headed by a span of days ("Sep 18-24", "Sep 25- Oct 1"), never one date.
        w = re.match(r"^([A-Z][a-z]{2,4}\s+\d{1,2}\s*-\s*(?:[A-Z][a-z]{2,4}\s+)?\d{1,2})\s+(.+)$", line)
        if w and last is not None:
            nums = _numbers(w.group(2))
            if len(nums) == 3:
                out.interbank_weeks.append({"label": " ".join(w.group(1).split()), "deals": nums[0],
                                            "value_mn": nums[1], "kesonia": nums[2], "last_day": last})
    if not out.interbank:
        raise BulletinParseError("Table 3 has no dated interbank rows")


def _table_4(lines: list[str], out: Bulletin) -> None:
    block = _block(lines, "Table 4:")
    labels = {"offered": "Amount Offered", "bids": "Bids Received", "accepted": "Amount Accepted",
              "rate": "Average Interest Rate"}
    for tenor in TENORS:
        head = f"{tenor.split('-')[0]}-Day Treasury Bills"
        try:
            at = next(n for n, line in enumerate(block) if line.startswith(head))
        except StopIteration:
            raise BulletinParseError(f"Table 4 has no '{head}' block")
        part = block[at:at + 8]
        dates_line = next((line for line in part if line.startswith("Date of Auction")), None)
        if dates_line is None:
            raise BulletinParseError(f"Table 4, {tenor}: no 'Date of Auction' row")
        days = [_day(d) for d in re.findall(_DAY, dates_line)]
        rows: dict[str, list[float]] = {}
        for key, label in labels.items():
            line = next((x for x in part if x.startswith(label)), None)
            if line is None:
                raise BulletinParseError(f"Table 4, {tenor}: no '{label}' row")
            values = _numbers(line.split(")", 1)[1])
            if len(values) != len(days):
                raise BulletinParseError(f"Table 4, {tenor}, {label}: {len(values)} figures for {len(days)} auctions")
            rows[key] = values
        out.tbills[tenor] = [{"date": d, **{k: rows[k][n] for k in labels}} for n, d in enumerate(days)]


def _table_5(lines: list[str], out: Bulletin) -> None:
    """Table 5 as printed.  Which bonds belong to which auction is not stated in the text layer
    (one offer covers one or two bonds), so the per-bond figures are kept in print order and
    the per-auction offers beside them; nothing is paired by guesswork.

    A row's label wraps differently from issue to issue: "Amount Accepted (KSh" over "M)" on
    2 October 2026, "Amount Accepted" over "(KSh M)" on 9 October, and "Amount offered (KSh M)"
    on one line in the first and cut after "(KSh" in the second.  So a row is found by the
    words of its label alone, and its figures are the ones after the label on that line or,
    when the label stands alone, the line under it if that line is figures and nothing else."""
    block = _block(lines, "Table 5:")
    dates = next(([_day(d) for d in re.findall(_DAY, line)] for line in block if line.startswith("Date of Auction")), [])
    # the codes wrap onto a second line when a week has many bonds (13 November 2026: five, then three)
    prefixes = [p for line in block if re.match(r"^[A-Z]{2,4}\d?/(\s|$)", line) for p in line.split()]
    suffixes = [x for line in block if re.match(r"^(Tenor\s+)?\d{4}/\d{2,3}", line) for x in re.findall(r"\d{4}/\d{2,3}(?:\.\d)?", line)]
    codes = [p + s for p, s in zip(prefixes, suffixes)] if len(prefixes) == len(suffixes) else []

    def row(label: str) -> list[float]:
        at = next((n for n, line in enumerate(block) if line.lower().startswith(label.lower())), None)
        if at is None:
            return []
        # what follows the label, less its unit, which may be whole "(KSh M)", cut by the wrap "(KSh", or "(%)"
        cells = re.sub(r"\(\s*(?:KSh(?:\s*M)?|%)\s*\)?", " ", block[at][len(label):]).split()
        if not cells and at + 1 < len(block):
            cells = block[at + 1].split()
        return [float(c.replace(",", "")) for c in cells] if cells and all(_NUM.fullmatch(c) for c in cells) else []

    tbonds = {
        "auction_dates": dates, "codes": codes,
        "offered": row("Amount offered"), "bids": row("Bids received"),
        "accepted": row("Amount Accepted"), "rates": row("Average interest Rate"),
    }
    if not dates or not codes:
        raise BulletinParseError("Table 5 does not print its auction dates and one code per bond")
    if len(tbonds["offered"]) != len(dates):   # one amount on offer per auction, whether it sells one bond or two
        raise BulletinParseError(f"Table 5: {len(tbonds['offered'])} 'offered' figures for {len(dates)} auctions")
    for key in ("bids", "accepted", "rates"):
        if len(tbonds[key]) != len(codes):
            raise BulletinParseError(f"Table 5: {len(tbonds[key])} '{key}' figures for {len(codes)} bonds")
    out.tbonds = tbonds


_MARKET_KEYS = ("nasi", "nse_25", "nse_20", "deals", "shares_mn", "equity_turnover_mn", "market_cap_bn", "bond_turnover_mn")


_TABLE_6_TITLE = re.compile(r"^Table \d+:\s*Performance of Key Market Indicators")   # the number moves between issues, the title does not
_YIELD_COLUMNS = (5, 8, 9)   # the Eurobond yield columns seen: 13, 16 and 17 figures a row with the eight market columns
_INDEX_BASE = "2008"   # the NASI's base year ("100=2008"): one issue's text layer sets it as a word of its own over the NASI column
Table6Row = tuple[date, bool, list[str], dict[int, str]]   # day, a "Public Holiday" row, the market figures, the yields by maturity year


def table_6_rows(page) -> list[Table6Row]:
    """The rows of Table 6 as printed, each Eurobond yield matched to the maturity year printed over its column.

    Known layouts only, else BulletinParseError and nothing is returned: a day is the eight market figures and one yield
    per column (a "Public Holiday" row has the yields alone); the years over the columns are each printed once, and
    the only year read and ignored is the index base left of the first column.
    """
    words = page.extract_words()
    lines: dict[int, str] = {}
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        lines[round(w["top"])] = f"{lines.get(round(w['top']), '')} {w['text']}".strip()
    top = next((t for t, text in sorted(lines.items()) if _TABLE_6_TITLE.match(text)), None)
    if top is None:
        raise BulletinParseError("Table 6's title is not at the start of a line on its page")
    stop = next((t for t, text in sorted(lines.items()) if t > top and _END.match(text)), 10**6)
    band = [w for w in words if top + 2 < w["top"] < stop - 2]
    dates = sorted((w for w in band if re.fullmatch(_DAY, w["text"])), key=lambda w: w["top"])
    if not dates:
        raise BulletinParseError("Table 6 has no dated rows")
    rows = []
    for d in dates:   # the date sits a little above its figures, so a row is the words within 6 points of it
        row = sorted((w for w in band if abs(w["top"] - d["top"]) <= 6 and w["x0"] > d["x1"]), key=lambda w: w["x0"])
        figures = [w for w in row if w["text"].lower() not in ("public", "holiday")]
        if not all(_NUM.fullmatch(w["text"]) for w in figures):
            raise BulletinParseError(f"Table 6 row for {_day(d['text']).isoformat()} holds a cell that is not a number")
        rows.append((_day(d["text"]), len(figures) != len(row), figures))
    first = next((f for _, holiday, f in rows if not holiday), None)
    if first is None or len(first) - 8 not in _YIELD_COLUMNS:
        raise BulletinParseError(f"Table 6 has {'no trading day' if first is None else f'{len(first)} figures a day'}: a layout this tool does not know")
    k = len(first) - 8
    edge = first[-k]["x0"] - 25
    heads = sorted((w for w in band if w["top"] < dates[0]["top"] and re.fullmatch(r"20\d{2}", w["text"]) and (w["x0"] + w["x1"]) / 2 >= edge),
                   key=lambda w: w["x0"])
    outside = [w["text"] for w in band if w["top"] < dates[0]["top"] and re.fullmatch(r"20\d{2}", w["text"]) and (w["x0"] + w["x1"]) / 2 < edge]
    if len(heads) != k or len({w["text"] for w in heads}) != k or outside not in ([], [_INDEX_BASE]):
        raise BulletinParseError(f"Table 6 prints {len(heads)} maturity years over {k} yield columns, and {outside or 'no other year'} outside them")
    out: list[Table6Row] = []
    for (day, holiday, figures), seen in zip(rows, dates):
        if day in {r[0] for r in out} or len(figures) != k + (0 if holiday else 8):
            raise BulletinParseError(f"Table 6 row for {day.isoformat()} has {len(figures)} figures, expected {k + (0 if holiday else 8)}")
        yields: dict[int, str] = {}
        for w in figures[-k:]:
            centre = (w["x0"] + w["x1"]) / 2
            head = min(heads, key=lambda h: abs((h["x0"] + h["x1"]) / 2 - centre))
            if abs((head["x0"] + head["x1"]) / 2 - centre) > 25 or int(head["text"]) in yields:
                raise BulletinParseError(f"Table 6: the yield {w['text']} of {day.isoformat()} is under no single maturity year")
            yields[int(head["text"])] = w["text"].replace(",", "")
        out.append((day, holiday, [w["text"] for w in figures[:-k]], yields))
    return out


def _table_6(page, out: Bulletin) -> None:
    """Daily rows of Table 6; a holiday row is left out (no market figures: it is not a trading day)."""
    for day, holiday, market, yields in table_6_rows(page):
        if not holiday:
            out.market.append({"date": day, **{k: clean_pdf_number(t) for k, t in zip(_MARKET_KEYS, market)},
                               "eurobond_yields": {y: clean_pdf_number(t) for y, t in yields.items()}})


_DEBT_TITLE = re.compile(r"^Table \d+:\s*Government Domestic Debt\b", re.I)
_BONDS_ROW = re.compile(r"^(?:\d+\.\s*)?Treasury Bonds\b(.*)$", re.I)


def _domestic_debt(lines: list[str], out: Bulletin) -> None:
    """The Treasury bond stock by date, found by the table's title (its number is not the same in every issue).

    Used only for an advisory check.  A bulletin without it, or one that prints it another way,
    raises like any other table, and like any other table it is then left out on its own.
    """
    start = next((n for n, line in enumerate(lines) if _DEBT_TITLE.match(line)), None)
    if start is None:
        raise BulletinParseError("'Government Domestic Debt' table not found")
    stop = next((n for n in range(start + 1, len(lines)) if _END.match(lines[n])), len(lines))
    body = lines[start + 1:stop]
    days = next((found for found in (re.findall(_DAY, line) for line in body) if len(found) >= 2), None)
    row = next((m.group(1) for m in (_BONDS_ROW.match(line) for line in body) if m), None)
    figures = _numbers(row) if row is not None else []
    if days is None or len(figures) != len(days):
        raise BulletinParseError("'Government Domestic Debt': the Treasury Bonds row does not have one figure per date")
    try:
        out.bond_stock = {_day(d): v for d, v in zip(days, figures)}
    except ValueError:
        raise BulletinParseError("'Government Domestic Debt': a column's date could not be read")


def parse_bulletin(pdf_bytes: bytes) -> Bulletin:
    """The bulletin PDF -> Tables 1 to 6 and the domestic debt table, each read on its own.

    A table that cannot be read, or fails its checks, is left out whole and named in
    ``unavailable`` (and in ``problems``) with the reason, the issue date and the file's sha256;
    the other tables still load.  BulletinParseError only for a PDF that is not the bulletin.
    """
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages = list(pdf.pages)
        texts = [p.extract_text() or "" for p in pages]
        lines = [line.strip() for t in texts for line in t.splitlines() if line.strip()]
        issue = None
        for line in lines[:4]:
            m = _ISSUE_DATE.match(line)
            if m:
                issue = datetime.strptime(f"{m.group(2)} {m.group(1)} {m.group(3)}", "%d %B %Y").date()
                break
        if not any(line.startswith("Table 1:") for line in lines):
            raise BulletinParseError("not a CBK Weekly Bulletin: no 'Table 1:' heading in its text (issue date read from "
                                     f"the file: {issue.isoformat() if issue else 'none'}; sha256 {sha})")
        dated = f"of {issue.isoformat()}" if issue else "with no issue date read"
        out = Bulletin(issue_date=issue, sha256=sha)

        def table_6() -> None:
            page = next((p for p, t in zip(pages, texts) if re.search(_TABLE_6_TITLE.pattern, t, re.M)), None)
            if page is None:
                raise BulletinParseError("'Performance of Key Market Indicators' not found")
            _table_6(page, out)

        readers: tuple[tuple[str, tuple[str, ...], Callable[[], None]], ...] = (
            ("Table 1", ("exchange_rates",), lambda: _table_1(lines, out)),
            ("Table 2", ("reserves",), lambda: _table_2(lines, out)),
            ("Table 3", ("interbank", "interbank_weeks"), lambda: _table_3(lines, out)),
            ("Table 4", ("tbills",), lambda: _table_4(lines, out)),
            ("Table 5", ("tbonds",), lambda: _table_5(lines, out)),
            ("Table 6", ("market",), table_6),
            (DEBT, ("bond_stock",), lambda: _domestic_debt(lines, out)),
        )
        for name, fields, read in readers:
            try:
                read()
            except Exception as exc:  # noqa: BLE001 - whatever stops one table stops that table only
                for attr in fields:   # nothing a failed table gave is kept, so no figure is partly read
                    setattr(out, attr, type(getattr(out, attr))())
                reason = str(exc) if isinstance(exc, BulletinParseError) else f"{type(exc).__name__}: {exc}"
                out.unavailable[name] = (f"{SOURCE_NAME} {dated} (sha256 {sha}): {name} could not be read and is left "
                                         f"out: {reason}")
                out.problems.append(out.unavailable[name])
                out.notices.append({"source": SOURCE_NAME, "issue_date": issue.isoformat() if issue else None, "sha256": sha,
                                    "location": name, "reason": reason, "text": out.unavailable[name]})
    return out


def refused(exc: Exception, pdf_bytes: bytes, issue_date: date) -> str:
    """Why a fetched file was refused as the bulletin, in one line that says which file it was.

    A refused file is not kept, so the issue asked for and the file's sha256 are what is left
    to find it again by.  A message that already carries the sha256 is returned as it is.
    """
    text = str(exc)
    if "sha256" in text:
        return text
    return f"{text} (the issue asked for: {issue_date.isoformat()}; sha256 {hashlib.sha256(pdf_bytes).hexdigest()})"


# ---------------------------------------------------------------------------
# Fetch by date
# ---------------------------------------------------------------------------

Getter = Callable[[str], bytes]
_LINK = re.compile(r'href="(/uploads/weekly_bulletin/[^"]+\.pdf)"', re.I)
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december"]


def link_date(href: str) -> Optional[date]:
    """The issue date in a bulletin link's file name ("...Weekly CBK Bulletin, 2 October, 2026.pdf").

    CBK writes it several ways ("Feb 6 2026", "April 24, 2026", "04 September 2026"); a
    name read no way returns None.
    """
    name = href.rsplit("/", 1)[-1].lower().replace(",", " ").replace("_", " ")
    m = re.search(r"(\d{1,2})\s+([a-z]{3,9})\.?\s+(20\d{2})", name) or None
    if m:
        day, month, year = m.group(1), m.group(2), m.group(3)
    else:
        m = re.search(r"([a-z]{3,9})\.?\s+(\d{1,2})\s+(20\d{2})", name)
        if not m:
            return None
        month, day, year = m.group(1), m.group(2), m.group(3)
    index = next((n for n, full in enumerate(_MONTHS) if full.startswith(month[:3]) and month in (full, full[:3], full[:4])), None)
    if index is None:
        return None
    try:
        return date(int(year), index + 1, int(day))
    except ValueError:
        return None


def bulletin_url(listing_html: str, issue_date: date) -> Optional[str]:
    for href in _LINK.findall(listing_html):
        if link_date(href) == issue_date:
            return CBK + quote(href, safe="/")
    return None


def fetch_bulletin(issue_date: date, get: Getter = http_get) -> tuple[bytes, str]:
    """The bulletin issued on ``issue_date`` (a Friday): (PDF bytes, its URL).

    LookupError if CBK's listing has no issue of that date (not yet published).
    """
    listing = get(LISTING).decode("utf-8", errors="replace")
    url = bulletin_url(listing, issue_date)
    if url is None:
        raise LookupError(f"CBK's weekly bulletin page lists no issue dated {issue_date.isoformat()}")
    return get(url), url
