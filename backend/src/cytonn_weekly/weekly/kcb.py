"""KCB Investment Bank's daily and weekly trading market reports (one-page PDFs with a text layer).

They cover NSE equities only: no T-bills, money market, Eurobonds or shilling (checked on
the 2 October 2026 daily, the Week 40 weekly and the September monthly, 2026-10-09).

What is read, each by its printed label, never by position on the page:

* the date printed under the title ("Friday, 02 October 2026") and the report kind;
* KEY NSE MARKET INDICATORS: NASI, NSE-20, NSE-25, market cap, shares traded, "Equities TO",
  foreign buy, sell and net flows, each for the two dates printed in the header row;
* TRADING STATS: the Equities row (volume, deals, turnover).  This turnover, not the
  "Equities TO" indicator, is the equities turnover: on the weekly report the indicator
  includes ETFs (2,279,873,699 = 2,273,368,956 equities + 6,504,743 ETFs, Week 40);
* per security: price and the day's (daily report) or week's (weekly report) change;
* the weekly report's DAILY FOREIGN FLOWS by weekday.

The text layer kerns digits apart ("1 2,327,385" is 12,327,385), so a row's figures are
recovered by ``split_numbers``: the only way to cut the row's tokens into the expected
count of well-formed numbers.  If there is no such way, or more than one, the row raises
``KcbParseError``; nothing is guessed.  Foreign flows are also checked arithmetically
(inflows - outflows = net, and the weekdays add up to the printed total), to within the
report's own rounding: it prints whole shillings, so three rounded figures can be 2 apart.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from itertools import combinations
from typing import Any, Optional

import pdfplumber

SOURCE_NAME = "KCB Investment Bank"
DAILY = "daily"
WEEKLY = "weekly"
MONTHLY = "monthly"

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")


ROUNDING = 2  # KES: the most three figures each rounded to a whole shilling can disagree by


def _adds_up(a: float, b: float, net: float) -> bool:
    return abs((a - b) - net) <= ROUNDING


class KcbParseError(ValueError):
    """The report's text does not read the way the samples did."""


# A plain or comma-grouped number with no leading zeros ("00.00" and "045.6" are not figures).
_NUMBER = re.compile(r"^\(?-?(?:0|[1-9]\d{0,2}(?:,\d{3})+|[1-9]\d*)(?:\.\d+)?\)?$")
_TITLE = re.compile(r"\b(DAILY|WEEKLY|MONTHLY)\s+MARKET\s+REPORT\b")
_DATE_LINE = re.compile(r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s*$")
_HEADER = re.compile(r"^Indicator\s+(\d{1,2}-[A-Za-z]{3}-\d{4})\s+(\d{1,2}-[A-Za-z]{3}-\d{4})\b")
_PCT = re.compile(r"^-?\d[\d,]*(?:\.\d+)?%$")
_SECURITY = re.compile(r"(?<![A-Za-z])([A-Z]{2,5})\s+(KES|USD)\s+((?:\d[\d,]*\s?)*\d*\.\d+)\s+(-?\d+(?:\.\d+)?)%")

# The indicator rows, by their printed label.
INDICATORS = {
    "nasi": "NASI",
    "nse_20": "NSE-20",
    "nse_25": "NSE-25",
    "market_cap_bn": "Mkt cap, KES Bn",
    "shares_traded": "Shares traded",
    "equities_to_indicator": "Equities TO, KES",
    "foreign_buy": "Foreign buy, KES",
    "foreign_sell": "Foreign sell, KES",
    "net_flows": "Net flows, KES",
}


def _value(token: str) -> float:
    neg = token.startswith("(") and token.endswith(")")
    d = Decimal(token.strip("()").replace(",", ""))
    return float(-d if neg else d)


def _decimals(group: str) -> int:
    return len(group.strip("()").split(".")[1]) if "." in group else 0


def split_numbers(tokens: list[str], count: int, same_decimals: bool = False) -> list[float]:
    """Cut ``tokens`` (in order) into exactly ``count`` well-formed numbers; raise unless one way exists.

    A number's digits may be spread over neighbouring tokens ("1", "2,327,385"); joined
    without the space they must form a plain or comma-grouped number.  ``same_decimals``
    adds that the figures print the same number of decimals, which holds for one indicator
    on two dates ("251.33 2 45.60" is 251.33 and 245.60, not 251.332 and 45.60).
    """
    if count < 1 or len(tokens) < count:
        raise KcbParseError(f"expected {count} figures, found {len(tokens)} token(s): {' '.join(tokens)!r}")
    found: list[list[str]] = []
    for cuts in combinations(range(1, len(tokens)), count - 1):
        edges = (0, *cuts, len(tokens))
        groups = ["".join(tokens[a:b]) for a, b in zip(edges, edges[1:])]
        if all(_NUMBER.match(g) for g in groups) and (not same_decimals or len({_decimals(g) for g in groups}) == 1):
            found.append(groups)
    if len(found) != 1:
        raise KcbParseError(f"{len(found)} ways to read {count} figures from {' '.join(tokens)!r}")
    return [_value(g) for g in found[0]]


def _is_numeric_token(token: str) -> bool:
    return bool(re.match(r"^[()\-\d,.]+$", token)) and any(ch.isdigit() for ch in token)


def _leading_tokens(rest: str) -> list[str]:
    """The run of number-like tokens at the start of ``rest`` (the text after a row's label)."""
    out = []
    for token in rest.split():
        if not _is_numeric_token(token):
            break
        out.append(token)
    return out


def _report_date(text: str) -> date:
    for line in text.splitlines()[:6]:
        m = _DATE_LINE.match(line.strip())
        if m:
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y").date()
    raise KcbParseError("no report date under the title (expected a line like 'Friday, 02 October 2026')")


def _rows(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _after_label(rows: list[str], label: str) -> Optional[str]:
    for row in rows:
        if row.startswith(label + " "):
            return row[len(label):].strip()
    return None


@dataclass
class KcbReport:
    kind: str                       # daily / weekly / monthly
    report_date: date               # the date printed under the title
    previous_date: date             # the first date of the indicators' header row
    indicators: dict[str, dict[str, Optional[float]]] = field(default_factory=dict)  # key -> {previous, current}
    equities_turnover: Optional[float] = None   # TRADING STATS, Equities row, KES
    equities_volume: Optional[float] = None
    equities_deals: Optional[float] = None
    securities: dict[str, dict[str, Any]] = field(default_factory=dict)  # ticker -> {price, change_pct, currency}
    daily_foreign_flows: dict[str, dict[str, float]] = field(default_factory=dict)  # weekly only: weekday -> flows
    foreign_flows_total: Optional[dict[str, float]] = None
    problems: list[str] = field(default_factory=list)   # rows that could not be read, each named

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "report_date": self.report_date.isoformat(),
            "previous_date": self.previous_date.isoformat(), "indicators": self.indicators,
            "equities_turnover": self.equities_turnover, "equities_volume": self.equities_volume,
            "equities_deals": self.equities_deals, "securities": self.securities,
            "daily_foreign_flows": self.daily_foreign_flows, "foreign_flows_total": self.foreign_flows_total,
            "problems": self.problems,
        }


def parse_kcb_text(text: str) -> KcbReport:
    """One report's text layer -> its figures.  Raises KcbParseError if it is not a KCB market report."""
    title = _TITLE.search(text[:400])
    if not title:
        raise KcbParseError("not a KCB IB market report: no 'DAILY/WEEKLY/MONTHLY MARKET REPORT' title")
    kind = title.group(1).lower()
    rows = _rows(text)
    header = next((m for m in (_HEADER.match(r) for r in rows) if m), None)
    if header is None:
        raise KcbParseError("no 'Indicator <date> <date>' header row")
    previous = datetime.strptime(header.group(1), "%d-%b-%Y").date()
    report = KcbReport(kind=kind, report_date=_report_date(text), previous_date=previous)
    if datetime.strptime(header.group(2), "%d-%b-%Y").date() != report.report_date:
        raise KcbParseError(f"the indicators are for {header.group(2)} but the report is dated "
                            f"{report.report_date.isoformat()}")

    for key, label in INDICATORS.items():
        rest = _after_label(rows, label)
        if rest is None:
            report.problems.append(f"{label}: row not found")
            continue
        tokens = []
        for token in rest.split():   # the two figures end at the row's % change
            if _PCT.match(token) or not _is_numeric_token(token):
                break
            tokens.append(token)
        try:
            prev, cur = split_numbers(tokens, 2, same_decimals=True)
        except KcbParseError as exc:
            report.problems.append(f"{label}: {exc}")
            continue
        report.indicators[key] = {"previous": prev, "current": cur}

    flows = report.indicators
    if all(k in flows for k in ("foreign_buy", "foreign_sell", "net_flows")):
        for when in ("previous", "current"):
            if not _adds_up(flows["foreign_buy"][when], flows["foreign_sell"][when], flows["net_flows"][when]):
                # A negative net may be printed without its sign; the arithmetic decides.
                if _adds_up(flows["foreign_buy"][when], flows["foreign_sell"][when], -flows["net_flows"][when]):
                    flows["net_flows"][when] = -flows["net_flows"][when]
                else:
                    report.problems.append(f"Net flows ({when}): foreign buy less sell does not equal the printed net")
                    flows.pop("net_flows")
                    break

    stats_at = next((n for n, r in enumerate(rows) if r.startswith("TRADING STATS")), None)
    if stats_at is None:
        report.problems.append("TRADING STATS: block not found")
    else:
        rest = next((r[len("Equities"):].strip() for r in rows[stats_at:stats_at + 6] if r.startswith("Equities ")), None)
        if rest is None:
            report.problems.append("TRADING STATS: no Equities row")
        else:
            try:
                report.equities_volume, report.equities_deals, report.equities_turnover = split_numbers(
                    _leading_tokens(rest), 3)
            except KcbParseError as exc:
                report.problems.append(f"TRADING STATS, Equities: {exc}")

    for row in rows:
        for m in _SECURITY.finditer(row):
            ticker = m.group(1)
            if ticker in report.securities:
                continue
            report.securities[ticker] = {
                "price": float(Decimal(m.group(3).replace(" ", "").replace(",", ""))),
                "change_pct": float(Decimal(m.group(4))), "currency": m.group(2),
            }

    if kind == WEEKLY:
        _daily_foreign_flows(rows, report)
    return report


def _daily_foreign_flows(rows: list[str], report: KcbReport) -> None:
    start = next((n for n, r in enumerate(rows) if r.startswith("DAILY FOREIGN FLOWS")), None)
    if start is None:
        report.problems.append("DAILY FOREIGN FLOWS: block not found")
        return
    block = rows[start:start + 9]
    for day in (*WEEKDAYS, "Total"):
        rest = next((r[len(day):].strip() for r in block if r.startswith(day + " ")), None)
        if rest is None:
            if day != "Total":
                report.problems.append(f"DAILY FOREIGN FLOWS: no {day} row (a holiday, or a changed layout)")
            continue
        try:
            inflow, outflow, net = split_numbers(_leading_tokens(rest), 3)
        except KcbParseError as exc:
            report.problems.append(f"DAILY FOREIGN FLOWS, {day}: {exc}")
            continue
        if not _adds_up(inflow, outflow, net):
            report.problems.append(f"DAILY FOREIGN FLOWS, {day}: inflows less outflows does not equal the printed net")
            continue
        flows = {"inflows": inflow, "outflows": outflow, "net": net}
        if day == "Total":
            report.foreign_flows_total = flows
        else:
            report.daily_foreign_flows[day] = flows
    if report.foreign_flows_total and report.daily_foreign_flows:
        days = report.daily_foreign_flows.values()
        if abs(sum(f["net"] for f in days) - report.foreign_flows_total["net"]) > ROUNDING * len(days):
            report.problems.append("DAILY FOREIGN FLOWS: the weekdays do not add up to the printed total")


def pdf_text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def parse_kcb_pdf(pdf_bytes: bytes) -> KcbReport:
    text = pdf_text(pdf_bytes)
    if not text.strip():
        raise KcbParseError("the PDF has no text layer; a KCB IB market report is expected to have one")
    return parse_kcb_text(text)
