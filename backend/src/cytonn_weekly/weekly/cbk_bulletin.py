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

Rows are found by their printed labels and dates.  Table 6's Eurobond columns are matched
to their maturity years by where the year is printed above the column (word positions),
never by an assumed order.  It can be fetched by date: the listing page links every issue
under ``/uploads/weekly_bulletin/`` with the issue date in the file name.
"""

from __future__ import annotations

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


def _between(lines: list[str], start: str, stop: str) -> list[str]:
    """The lines from the one starting ``start`` up to (not including) the next starting ``stop``."""
    try:
        a = next(n for n, line in enumerate(lines) if line.startswith(start))
    except StopIteration:
        raise BulletinParseError(f"'{start}' not found")
    b = next((n for n in range(a + 1, len(lines)) if lines[n].startswith(stop)), len(lines))
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
    problems: list[str] = field(default_factory=list)

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
                    "tbonds": self.tbonds, "market": self.market, "problems": self.problems})


def _table_1(lines: list[str], out: Bulletin) -> None:
    for line in _between(lines, "Table 1:", "Table 2:"):
        m = _DAY_ROW.match(line)
        if m:
            nums = _numbers(m.group(2))
            if nums:
                out.exchange_rates[_day(m.group(1))] = nums[0]
    if not out.exchange_rates:
        raise BulletinParseError("Table 1 has no dated exchange-rate rows")


def _table_2(lines: list[str], out: Bulletin) -> None:
    block = _between(lines, "Table 2:", "Table 3:")
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
    for line in _between(lines, "Table 3:", "Table 4:"):
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
    block = _between(lines, "Table 4:", "Table 5:")
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
    the per-auction offers beside them; nothing is paired by guesswork."""
    try:
        block = _between(lines, "Table 5:", "Source:")
    except BulletinParseError as exc:
        out.problems.append(f"Table 5: {exc}")
        return
    text = "\n".join(block)
    dates = next(([_day(d) for d in re.findall(_DAY, line)] for line in block if line.startswith("Date of Auction")), [])
    prefixes = next((line.split() for line in block if re.match(r"^[A-Z]{2,4}\d?/(\s|$)", line)), [])
    suffix_line = next((line for line in block if re.match(r"^(Tenor\s+)?\d{4}/\d{2,3}", line)), "")
    suffixes = re.findall(r"\d{4}/\d{2,3}(?:\.\d)?", suffix_line)
    codes = [p + s for p, s in zip(prefixes, suffixes)] if len(prefixes) == len(suffixes) else []

    def row(label: str) -> list[float]:
        m = re.search(rf"{label}[^\n]*\n?([^\n]*)", text)
        if not m:
            return []
        same_line = _numbers(text[m.start():].split("\n", 1)[0].split(")", 1)[-1]) if ")" in text[m.start():].split("\n", 1)[0] else []
        return same_line or _numbers(m.group(1))

    out.tbonds = {
        "auction_dates": dates, "codes": codes,
        "offered": row(r"Amount offered \(KSh M\)"), "bids": row(r"Bids received \(KSh M\)"),
        "accepted": row(r"Amount Accepted \(KSh"), "rates": row(r"Average interest Rate"),
    }
    for key in ("bids", "accepted", "rates"):
        if codes and len(out.tbonds[key]) != len(codes):
            out.problems.append(f"Table 5: {len(out.tbonds[key])} '{key}' figures for {len(codes)} bonds")


_MARKET_KEYS = ("nasi", "nse_25", "nse_20", "deals", "shares_mn", "equity_turnover_mn", "market_cap_bn", "bond_turnover_mn")


def _table_6(page, out: Bulletin) -> None:
    """Daily rows of Table 6, with each Eurobond yield column matched to the year printed above it."""
    words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
    rows: dict[float, list[dict[str, Any]]] = {}
    for w in words:
        rows.setdefault(round(w["top"]), []).append(w)
    lines = sorted(rows.items())
    data: list[tuple[date, list[dict[str, Any]]]] = []
    for _, ws in lines:
        ws.sort(key=lambda w: w["x0"])
        if not re.fullmatch(_DAY, ws[0]["text"]):
            continue
        try:   # the page's chart prints its dates rotated ("52-tcO-03"), which are not rows
            day = _day(ws[0]["text"])
        except ValueError:
            continue
        data.append((day, ws[1:]))
    if not data:
        raise BulletinParseError("Table 6 has no dated rows")
    first_top = min(ws[0]["top"] for _, ws in data)
    years = [w for w in words if w["top"] < first_top and re.fullmatch(r"20\d{2}", w["text"])]
    for day, ws in data:
        if len(ws) != 16:
            raise BulletinParseError(f"Table 6 row for {day.isoformat()} has {len(ws)} figures, expected 16")
        row: dict[str, Any] = {"date": day}
        for key, w in zip(_MARKET_KEYS, ws[:8]):
            row[key] = clean_pdf_number(w["text"])
        yields: dict[int, float] = {}
        for w in ws[8:]:
            centre = (w["x0"] + w["x1"]) / 2
            near = min(years, key=lambda y: abs((y["x0"] + y["x1"]) / 2 - centre), default=None)
            if near is None or abs((near["x0"] + near["x1"]) / 2 - centre) > 25:
                raise BulletinParseError(f"Table 6: no maturity year is printed above the yield {w['text']}")
            year = int(near["text"])
            if year in yields:
                raise BulletinParseError(f"Table 6: two yields fall under {year} on {day.isoformat()}")
            yields[year] = clean_pdf_number(w["text"])
        row["eurobond_yields"] = yields
        out.market.append(row)


def parse_bulletin(pdf_bytes: bytes) -> Bulletin:
    """The bulletin PDF -> Tables 1 to 6.  A table that cannot be read raises, naming the table."""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages = list(pdf.pages)
        texts = [p.extract_text() or "" for p in pages]
        lines = [line.strip() for t in texts for line in t.splitlines() if line.strip()]
        if not any(line.startswith("Table 1:") for line in lines):
            raise BulletinParseError("not a CBK Weekly Bulletin: no 'Table 1:' heading in its text")
        issue = None
        for line in lines[:4]:
            m = _ISSUE_DATE.match(line)
            if m:
                issue = datetime.strptime(f"{m.group(2)} {m.group(1)} {m.group(3)}", "%d %B %Y").date()
                break
        out = Bulletin(issue_date=issue)
        _table_1(lines, out)
        _table_2(lines, out)
        _table_3(lines, out)
        _table_4(lines, out)
        _table_5(lines, out)
        page6 = next((p for p, t in zip(pages, texts) if "Table 6:" in t), None)
        if page6 is None:
            raise BulletinParseError("'Table 6:' not found")
        _table_6(page6, out)
    return out


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
