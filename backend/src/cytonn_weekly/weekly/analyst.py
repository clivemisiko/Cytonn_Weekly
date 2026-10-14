"""Weekly analyst inputs: the figures only the analysts hold, typed on a form for one report week.

The weekly Fixed Income and Equities sections read some figures that exist nowhere but in the
analysts' two workbooks (audited from the builders on 2026-10-12): the 3-month bank placements
rate, the money market fund table, the daily interbank rates, the Eurobond issue list and the
yields of days the CBK bulletin does not print, the remittances, the net domestic borrowing
target, the large-cap list, the running turnover and foreign-flow totals, the market P/E and
dividend yield with their averages, and the Universe of Coverage inputs.  The team may not send
the workbooks every week, so each of those can be typed here instead.  Nothing the tool reads
from a published source (CBK, KCB IB, the NSE, the previous issue) is on the form.

The form is kept beside the week's files::

    <CYTONN_DATA_DIR>/inputs/weekly/<week-ending date>/analyst.json

Rules:

* **Typed values are analyst inputs**, exactly as workbook cells are: a figure that rests on one
  is shown as "analyst input typed on the weekly form (...)" and is not auto-verified, never
  clean.  The model never sees, writes or fills any of them.
* **A workbook is an optional shortcut.**  When one is uploaded, each item the form leaves empty
  is read from it as before.  A typed value overrides the workbook's, and where the two differ
  the difference is recorded: as a second reading on the figure (a "sources disagree" flag) and
  as a line in the section's warnings.
* **Nothing is filled in.**  An item neither typed nor in a workbook is simply missing: the part
  of the section that needs it is an ``unavailable`` block naming it.
* **Derived figures are never typed.**  The Top 5 funds' average, the Universe of Coverage's
  changes, yield, upside, multiple and recommendation, the pro-rated borrowing target and every
  other worked-out figure still come from the builders' formulas and the exact-match checker.

* **Last week's form can start this week's** (``carry_forward``).  Every carried value is marked
  with the week it came from.  What changes slowly (the Eurobond issue list, year opens, targets,
  DPS, shares, tangible book, remittances) is carried and used.  What changes every week (the
  placements rate, the fund table, the P/E, the borrowing target and log, the interbank rates, the
  foreign positions) is carried but **not used until it is confirmed**: an unconfirmed value is
  read by no builder, so a draft can never rest on last week's figure by oversight.
* **A running total can be suggested, never assumed** (equities/weekly.running_total_suggestions):
  last week's saved total plus this week's figure worked out from KCB IB and CBK, with the working
  shown.  It is stored unconfirmed, like a carried weekly value.
* **The net borrowing log is CBK's, not the analysts'** (fixed_income/net_borrowing.py).  The form
  holds only what CBK cannot say: the full-year target, the day the fiscal year starts (1 July
  unless typed) and, under "Other bond redemptions", a bond redemption CBK prints on no result
  file (a bond maturing on a day with no bond auction).  Switch auctions are not on the form: by the investments team's rule they are not
  new debt and never count.  A typed auction log is still accepted, as an override of CBK's
  results or the fallback when CBK cannot be reached.
* **The Universe of Coverage's Friday price is KCB IB's**, from its weekly report, when no price is
  typed; the previous Friday's is the price stored for the previous week.  Index levels are not on
  the form: the tool reads them from KCB IB and the NSE.

A value is stored as it was typed (a percentage as 9.0, not 0.09).  A builder gets it as a
``Typed`` cell in the workbook's own unit, so the arithmetic is the same whichever the source.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Optional

from cytonn_weekly.weekly import equities_workbook, fi_workbook
from cytonn_weekly.weekly.inputs import InputError, WeeklyInputs, week_dir
from cytonn_weekly.weekly.week import Week, ordinal
from cytonn_weekly.weekly.workbook import Cell, WorkbookError

FORM = "Weekly analyst inputs"
FILE = "analyst.json"
FI = "fixed_income"
EQ = "equities"
WORKBOOKS = {FI: fi_workbook.SOURCE_NAME, EQ: equities_workbook.SOURCE_NAME}

NUMBER, DATE, NAMES, TEXT, RANK, MONTH = "number", "date", "names", "text", "rank", "month"
PASTE, GRID = "paste", "grid"

MAX_PASTE = 40_000
MAX_ROWS = 400
MAX_NAME = 120
MIN_FUNDS = 5   # the Top 5 average needs five funds

# Carry-forward (the team's rule, 2026-10-12).  Slow-changing items carry from last week's form and are used as
# they are; weekly-changing ones carry but must be confirmed before any builder reads them.
SLOW_FIELDS = ("large_caps", "foreign_prior_year", "universe_month_end", "fiscal_year_start")
WEEKLY_FIELDS = ("placements", "pe", "pe_average", "dividend_yield", "dividend_yield_average", "borrowing_target")
SLOW_TABLES = ("eurobond_issues", "eurobond_yields", "remittances", "universe", "borrowing_redemptions")
WEEKLY_TABLES = ("mmf", "interbank", "borrowing_log", "foreign_history")
# Of the Universe of Coverage's columns, the ones that carry: prices do not (this Friday's is KCB IB's, last
# Friday's is the price stored for last week); the month-end price carries only while the month is the same.
UNIVERSE_CARRIED = ("company", "year_open", "target", "dps", "shares_bn", "tbv_bn")
# Running totals: never carried (last week's total is not this week's); a suggestion is worked out instead.
SUGGESTED_FIELDS = ("turnover_ytd", "foreign_ytd")
SUGGESTED = "suggested"

# The names the Universe of Coverage uses and the tickers KCB IB's weekly report lists them under.  Checked against
# the report and the workbook of 2 October 2026: the report's price equals the workbook's for all thirteen.
COVERAGE_TICKERS = {"co-op bank": "COOP", "ncba": "NCBA", "kcb group": "KCB", "absa bank": "ABSA",
                    "standard chartered bank": "SCBK", "stanbic holdings": "SBIC", "jubilee holdings": "JUB",
                    "equity group": "EQTY", "diamond trust bank": "DTK", "cic group": "CIC", "i&m group": "IMH",
                    "britam": "BRIT", "family bank": "FMLY"}


# ---------------------------------------------------------------------------
# What is on the form
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Field:
    key: str
    section: str
    group: str
    label: str
    source: str               # where the analysts read it, shown beside the field and in the review
    used_in: str              # the part of the section that prints it
    help: str = ""
    kind: str = NUMBER
    unit: str = ""
    lo: Optional[float] = None
    hi: Optional[float] = None
    scale: int = 1            # the workbook holds the typed value divided by this (100 for a percentage)


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    kind: str = NUMBER
    unit: str = ""
    lo: Optional[float] = None
    hi: Optional[float] = None
    scale: int = 1
    required: bool = True


@dataclass(frozen=True)
class Table:
    key: str
    section: str
    group: str
    label: str
    source: str
    used_in: str
    columns: tuple[Column, ...]
    help: str = ""
    mode: str = PASTE
    fixed_rows: tuple[tuple[str, str], ...] = ()   # (row key, label): a grid whose rows are given
    example: str = ""


GROUPS = (
    (FI, "money_market", "Money market"),
    (FI, "liquidity", "Liquidity"),
    (FI, "eurobonds", "Kenya Eurobonds"),
    (FI, "shilling", "Kenya Shilling"),
    (FI, "borrowing", "Government borrowing"),
    (EQ, "market", "Market performance"),
    (EQ, "valuation", "Valuation"),
    (EQ, "universe", "Universe of Coverage"),
)

_PCT = dict(unit="%", lo=1, hi=40, scale=100)
_ISSUES = tuple((spec[0], f"{spec[1][0]} {spec[1][1]}") for spec in fi_workbook.EUROBOND_ISSUES)

FIELD_LIST = (
    Field("placements", FI, "money_market", "3-month bank placements", "Rates offered by various banks",
          "Money Market Performance", "The rate the week ended at, as a percentage (9.0, not 0.09).", **_PCT),
    Field("cmmf_last_week", FI, "money_market", "Cytonn Money Market Fund yield, previous week", "Cytonn Money Market Fund",
          "Money Market Performance", "Optional. Left empty, the sentence gives this week's yield only. This week's yield is "
          "the Cytonn row of the fund table.", **_PCT),
    Field("mmf_published", FI, "money_market", "Fund table published on", "Business Daily", "Money Market Performance",
          "The day's paper the fund table below is copied from.", kind=DATE),
    Field("borrowing_target", FI, "borrowing", "Net domestic borrowing target for the fiscal year", "National Treasury budget",
          "Net domestic borrowing against the pro-rated target", "The full-year target. The pro-rated target is worked out.",
          unit="Kshs bn", lo=1, hi=5000),
    Field("fiscal_year_start", FI, "borrowing", "Fiscal year starts on", "National Treasury (Kenya's fiscal year)",
          "Net domestic borrowing against the pro-rated target", "Optional: 1 July is used when this is empty. The net borrowing "
          "log starts on this day and the target is pro-rated from it. Typed once, it is carried forward.", kind=DATE),
    Field("large_caps", EQ, "market", "Large-cap list", "The equities team's large-cap list", "Large-cap movers",
          "One company a line, as the team names them. The movers are picked from this list by KCB IB's week-on-week changes.",
          kind=NAMES),
    Field("turnover_ytd", EQ, "market", "Year-to-date equities turnover", "The equities team's running total",
          "Equities turnover", "Including this week.", unit="USD mn", lo=0, hi=100_000),
    Field("foreign_ytd", EQ, "market", "Year-to-date foreign net position", "The equities team's running total",
          "Foreign investors", "Including this week. Net selling is negative.", unit="USD mn", lo=-20_000, hi=20_000),
    Field("foreign_prior_year", EQ, "market", "Foreign net position recorded in the previous year",
          "The equities team's running total", "Foreign investors", "Optional. Net selling is negative.", unit="USD mn",
          lo=-20_000, hi=20_000),
    Field("pe", EQ, "valuation", "Market P/E", "Bloomberg NASI P/E", "Valuation", "After Friday's close.", unit="x", lo=1, hi=60),
    Field("pe_average", EQ, "valuation", "Historical average P/E", "The equities team's P/E series", "Valuation",
          "The average of the series, this Friday included.", unit="x", lo=1, hi=60),
    Field("dividend_yield", EQ, "valuation", "Market dividend yield", "The equities team's market dividend yield", "Valuation",
          "As a percentage (5.8, not 0.058).", unit="%", lo=0.5, hi=30, scale=100),
    Field("dividend_yield_average", EQ, "valuation", "Historical average dividend yield",
          "The equities team's dividend yield series", "Valuation", "The average of the series, this Friday included.",
          unit="%", lo=0.5, hi=30, scale=100),
    Field("universe_month_end", EQ, "universe", "Previous month's last price is the close of", "Nairobi Securities Exchange",
          "Universe of Coverage", "The date of the month-end price column: the base of the m/m change.", kind=DATE),
)
FIELDS = {f.key: f for f in FIELD_LIST}

_PRICE = dict(unit="Kshs", lo=0.01, hi=100_000, required=False)
TABLE_LIST = (
    Table("mmf", FI, "money_market", "Money market fund table", "Business Daily", "Money Market Performance and its fund table",
          (Column("rank", "Rank", RANK), Column("fund", "Fund Manager", TEXT),
           Column("rate", "Effective Annual Rate", **_PCT)),
          "Paste the rows as the paper prints them: rank, fund, rate. Any number of funds. The Top 5 average is worked out "
          "from this week's five highest rates; it is never typed.",
          example="1  Cytonn Money Market Fund  11.01%"),
    Table("interbank", FI, "liquidity", "Daily interbank rates", "Central Bank of Kenya, interbank rates", "Liquidity",
          (Column("date", "Date", DATE), Column("rate", "Interbank rate", **_PCT)),
          "One day a line, for the two weeks the paragraph compares (Friday to Thursday, twice). Without them the paragraph "
          "gives the bulletin's KESONIA average and no change.",
          example="2026-10-01  8.8012"),
    Table("eurobond_issues", FI, "eurobonds", "Eurobond issues", "The fixed income team's issue list",
          "Kenya Eurobonds table (Amount Issued, Years to Maturity, Yields at Issue)",
          (Column("amount_mn", "Amount issued", unit="USD mn", lo=1, hi=20_000, required=False),
           Column("maturity", "Maturity date", DATE, required=False),
           Column("yield_at_issue", "Yield at issue", unit="%", lo=1, hi=30, required=False)),
          "The amount is the amount before buyback. Years to maturity are worked out from the maturity date.",
          mode=GRID, fixed_rows=_ISSUES),
    Table("eurobond_yields", FI, "eurobonds", "Eurobond yields on days the bulletin does not print",
          "Central Bank of Kenya, Eurobond yields", "Kenya Eurobonds table (YTD and MTD change)",
          (Column("date", "Date", DATE, required=False),)
          + tuple(Column(key, label, unit="%", lo=1, hi=40, scale=100, required=False) for key, label in _ISSUES),
          "The bulletin prints the last days only. The year-to-date and month-to-date rows need the yields on the year's and "
          "the month's first trading day.",
          mode=GRID, fixed_rows=(("year_open", "The year's first trading day"), ("month_open", "The month's first trading day"))),
    Table("remittances", FI, "shilling", "Diaspora remittances by month", "Central Bank of Kenya, diaspora remittances",
          "Kenya Shilling (remittances)",
          (Column("month", "Month", MONTH), Column("north_america", "North America", unit="USD mn", lo=0, hi=5000, required=False),
           Column("total", "Total remittances", unit="USD mn", lo=0.01, hi=5000)),
          "The latest 24 months, one a line: month, North America, total. North America is needed for the latest month only.",
          example="2026-08  225.1  447.3"),
    Table("borrowing_log", FI, "borrowing", "Auction log for the fiscal year", "The fixed income team's borrowing log",
          "Net domestic borrowing against the pro-rated target",
          (Column("date", "Value date", DATE), Column("accepted", "Accepted", unit="Kshs mn", lo=0, hi=2_000_000),
           Column("redemptions", "Redemptions", unit="Kshs mn", lo=-2_000_000, hi=0)),
          "Optional. Leave this empty: the log is built from CBK's auction results. A log typed here is used instead of CBK's, as "
          "analyst input, and is the fallback when CBK cannot be reached. One auction a line since 1 July, up to this "
          "week's. Redemptions are negative, as in the team's log.",
          example="2026-10-05  41196.84  (30511.20)"),
    # CBK prints a bond redemption only in the results of a bond auction settling that day, so a bond that matures on a
    # day with no bond auction is on no result file (first case: IFB1/2014/12, 12 October 2026).  It is typed here.
    Table("borrowing_redemptions", FI, "borrowing", "Other bond redemptions",
          "The fixed income team (a bond redemption CBK prints on no auction result)",
          "Net domestic borrowing against the pro-rated target",
          (Column("date", "Value date", DATE), Column("bond", "Bond", TEXT),
           Column("amount", "Amount redeemed", unit="Kshs mn", lo=0.01, hi=2_000_000)),
          "A bond that matures on a day with no bond auction is on no CBK result file. One a line: value date, bond, the amount "
          "redeemed in Kshs mn (the amount outstanding at maturity, as shown on the NSE Implied Yields sheet, which may "
          "differ from the face value at issue). Each row is subtracted "
          "on its value date in the log built from CBK's results, as analyst input, labelled \"typed, not on a release\". It "
          "is not added to an auction log typed above: put the redemption in that log.",
          example="2026-10-12  IFB1/2014/12  16631.48"),
    Table("foreign_history", EQ, "market", "Foreign net position, previous weeks", "The equities team's weekly sums",
          "Foreign investors (previous week and streak)",
          (Column("week_ending", "Week ending", DATE), Column("net", "Net position", unit="USD mn", lo=-2000, hi=2000)),
          "One week a line, newest weeks back to the last change of direction. Net selling is negative.",
          example="2026-09-25  0.57"),
    Table("universe", EQ, "universe", "Universe of Coverage", "Cytonn analyst estimates and company filings; prices from the NSE",
          "Universe of Coverage table",
          (Column("company", "Company", TEXT),
           Column("last_price", "Price, last Friday", **_PRICE), Column("price", "Price, this Friday", **_PRICE),
           Column("month_end_price", "Price, previous month end", **_PRICE), Column("year_open", "Year open", **_PRICE),
           Column("target", "Target price", **_PRICE), Column("dps", "Dividend per share", unit="Kshs", lo=0, hi=10_000, required=False),
           Column("shares_bn", "Shares", unit="bn", lo=0.0001, hi=1000, required=False),
           Column("tbv_bn", "Tangible book value", unit="Kshs bn", lo=0.0001, hi=100_000, required=False)),
          "Only the inputs. The changes, dividend yield, upside, P/TBV and recommendation are worked out.",
          mode=GRID),
)
TABLES = {t.key: t for t in TABLE_LIST}

# The workbook reading each item comes from (the key its error is kept under), for the "why it is missing" wording.
_READING = {"placements": "placements", "cmmf_last_week": "cmmf_last_week", "mmf_published": "mmf", "mmf": "mmf",
            "interbank": "interbank", "eurobond_issues": "eurobonds", "eurobond_yields": "eurobonds",
            "remittances": "remittances", "borrowing_target": "borrowing", "borrowing_log": "borrowing",
            "fiscal_year_start": "borrowing", "borrowing_redemptions": "borrowing",
            "large_caps": "large_caps", "turnover_ytd": "turnover", "foreign_ytd": "foreign", "foreign_prior_year": "foreign",
            "foreign_history": "foreign", "pe": "valuation", "pe_average": "valuation", "dividend_yield": "valuation",
            "dividend_yield_average": "valuation", "universe_month_end": "universe", "universe": "universe"}


# How an item is named when a part says it is missing, where its label does not read as a noun.
_NAMED = {"universe": "the Universe of Coverage inputs", "universe_month_end": "the date of the previous month's last price",
          "mmf_published": "the date the fund table was published on", "placements": "the 3-month bank placements rate",
          "borrowing_log": "the fiscal year's auction log", "remittances": "the monthly diaspora remittances"}


# ---------------------------------------------------------------------------
# A typed value, as the builders read it
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Typed:
    """One value typed on the form.  It stands where a workbook ``Cell`` would, in the workbook's unit."""

    value: Any
    what: str                       # "3-month bank placements"
    label: str                      # the form's source label for it
    other: Optional[Cell] = None    # the uploaded workbook's cell, when it holds a different value
    sheet: str = FORM
    row: Optional[int] = None

    @property
    def number(self) -> Optional[float]:
        v = self.value
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    @property
    def day(self) -> Optional[date]:
        return self.value if isinstance(self.value, date) else None

    @property
    def a1(self) -> str:
        return self.what

    @property
    def ref(self) -> str:
        return f"the weekly form, {self.what}"

    @property
    def source(self) -> str:
        return f"analyst input typed on the weekly form ({self.what}; source: {self.label})"


BLANK = Cell(None, FORM, 0, 0)   # a cell of a typed row that was left empty


@dataclass(frozen=True)
class Reading:
    """A figure the tool read for a typed row from somewhere else: KCB IB's report, or a previous week's stored price."""

    value: Any
    source: str
    row: Optional[int] = None

    @property
    def number(self) -> Optional[float]:
        v = self.value
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    @property
    def day(self) -> Optional[date]:
        return None

    @property
    def ref(self) -> str:
        return self.source


def is_typed(cell: Any) -> bool:
    return isinstance(cell, Typed)


def _plain(d: Decimal) -> str:
    """A number as a person would type it: no exponent, no trailing zeros."""
    text = format(d, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def shown(value: Any, scale: int = 1) -> str:
    """A workbook value in the form's unit and wording."""
    if isinstance(value, (Cell, Typed)):
        value = value.value
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        return _plain(Decimal(repr(value)) * scale)
    return " ".join(str(value).split())


def _key(name: Any) -> str:
    """A fund or company name as compared: lower case, single-spaced, no space inside brackets."""
    return " ".join(str(name).replace("( ", "(").replace(" )", ")").split()).lower()


CYTONN_FUND = fi_workbook.CYTONN_FUND   # "cytonn money market fund"


def fund_key(name: Any) -> str:
    """A fund's name as matched between the paper and the workbook.

    The workbook writes Cytonn's fund with its dial code ("Cytonn Money Market Fund ( Dial *809# or
    download Cytonn App)"); the paper prints "Cytonn Money Market Fund".  They are the same fund,
    as the fixed income builder already takes any name starting that way to be.
    """
    key = _key(name)
    return CYTONN_FUND if key.startswith(CYTONN_FUND) else key


# ---------------------------------------------------------------------------
# Reading what was typed: cleaning and checking
# ---------------------------------------------------------------------------

_NUM = re.compile(r"^-?\d+(\.\d+)?$")
_MONTHS = {m: n for n, names in enumerate((("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
                                            ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
                                            ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
                                            ("dec", "december")), 1) for m in names}
_DMY = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?[\s/.-]+([A-Za-z]+|\d{1,2})[\s/.,-]+(\d{4}|\d{2})$")
_MY = re.compile(r"^([A-Za-z]+|\d{1,2})[\s/.-]+(\d{4}|\d{2})$")


def _range(col: Any) -> str:
    unit = f" {col.unit}" if col.unit and col.unit not in ("%", "x") else col.unit
    return f"{_plain(Decimal(repr(col.lo)))} to {_plain(Decimal(repr(col.hi)))}{unit}"


def clean_number(raw: Any, col: Any, where: str) -> str:
    text = str(raw).strip().replace(",", "").replace("−", "-").replace(" ", "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    text = text.rstrip("%xX")
    if text.startswith("."):
        text = "0" + text
    if not _NUM.match(text):
        raise InputError(f"{where}: {str(raw).strip()!r} is not a number")
    value = Decimal(text)
    if (col.lo is not None and value < Decimal(repr(col.lo))) or (col.hi is not None and value > Decimal(repr(col.hi))):
        hint = " Type a percentage as 9.0, not 0.09." if col.unit == "%" and abs(value) < 1 else ""
        raise InputError(f"{where}: {text} is outside the expected range, {_range(col)}.{hint}")
    return text


def _year(text: str) -> int:
    return int(text) + 2000 if len(text) == 2 else int(text)


def clean_date(raw: Any, where: str) -> str:
    text = str(raw).strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        pass
    m = _DMY.match(text)
    if m:
        month = int(m.group(2)) if m.group(2).isdigit() else _MONTHS.get(m.group(2).lower())
        try:
            return date(_year(m.group(3)), month, int(m.group(1))).isoformat()
        except (TypeError, ValueError):
            pass
    raise InputError(f"{where}: {text!r} is not a date; write it as 2026-10-02 or 2 October 2026 (day first)")


def clean_month(raw: Any, where: str) -> str:
    text = str(raw).strip()
    m = re.match(r"^(\d{4})[-/](\d{1,2})$", text)
    year, month = (int(m.group(1)), int(m.group(2))) if m else (None, None)
    if m is None:
        m = _MY.match(text)
        if m:
            year = _year(m.group(2))
            month = int(m.group(1)) if m.group(1).isdigit() else _MONTHS.get(m.group(1).lower())
    if not year or not month or not 1 <= month <= 12:
        raise InputError(f"{where}: {text!r} is not a month; write it as 2026-08 or August 2026")
    return f"{year:04d}-{month:02d}"


def clean_cell(raw: Any, col: Column, where: str) -> str:
    """One cell as stored, or InputError.  An empty cell of an optional column is ""."""
    text = "" if raw is None else str(raw).strip()
    if not text:
        if col.required:
            raise InputError(f"{where}: {col.label.lower()} is missing")
        return ""
    if col.kind == NUMBER:
        return clean_number(text, col, where)
    if col.kind == RANK:
        digits = text.rstrip(".)")
        if not digits.isdigit() or int(digits) < 1:
            raise InputError(f"{where}: {text!r} is not a rank")
        return str(int(digits))
    if col.kind == DATE:
        return clean_date(text, where)
    if col.kind == MONTH:
        return clean_month(text, where)
    name = " ".join(text.split())
    if len(name) > MAX_NAME:
        raise InputError(f"{where}: the name is {len(name)} characters; the limit is {MAX_NAME}")
    return name


def parse_paste(table: Table, text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Pasted lines as raw rows (each with its line number), and what could not be read.

    A line is cut on tabs when it has any, else on spaces.  One column per table takes whatever
    is left between the others (the fund's name, a date written in words), so "1  Cytonn Money
    Market Fund  11.01%" reads as rank, fund and rate.  A line with no digit is a heading.
    """
    cols = table.columns
    wide = next(n for n, c in enumerate(cols) if c.kind in (TEXT, DATE, MONTH))
    left, right = cols[:wide], cols[wide + 1:]
    rows, errors = [], []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or not any(ch.isdigit() for ch in line):
            continue
        cells = [c.strip() for c in line.split("\t")]
        if "\t" in line and len(cells) == len(cols):
            rows.append({"_line": n, **{c.key: v for c, v in zip(cols, cells)}})
            continue
        tokens = [t for t in (cells if "\t" in line else line.split()) if t and t != "%"]
        if len(tokens) < len(cols):
            errors.append(f"{table.label}, line {n}: expected {', '.join(c.label.lower() for c in cols)}; read "
                          f"{len(tokens)} value{'s' if len(tokens) != 1 else ''}")
            continue
        row: dict[str, Any] = {"_line": n}
        row.update({c.key: t for c, t in zip(left, tokens)})
        row.update({c.key: t for c, t in zip(reversed(right), reversed(tokens))})
        row[cols[wide].key] = " ".join(tokens[len(left): len(tokens) - len(right)])
        rows.append(row)
    return rows, errors


def to_text(table: Table, rows: list[dict[str, str]]) -> str:
    """Stored rows as lines the paste box reads back."""
    return "\n".join("\t".join(r.get(c.key, "") for c in table.columns) for r in rows)


def _clean_rows(table: Table, raw_rows: list[dict[str, Any]], errors: list[str]) -> list[dict[str, str]]:
    fixed = dict(table.fixed_rows)
    out = []
    for n, raw in enumerate(raw_rows, 1):
        if not isinstance(raw, dict):
            errors.append(f"{table.label}: row {n} is not a row")
            continue
        if fixed:
            if raw.get("row") not in fixed:
                errors.append(f"{table.label}: no row {raw.get('row')!r}")
                continue
            where, row = f"{table.label}, {fixed[raw['row']]}", {"row": raw["row"]}
        else:
            where, row = f"{table.label}, {'line' if '_line' in raw else 'row'} {raw.get('_line', n)}", {}
        try:
            for col in table.columns:
                value = clean_cell(raw.get(col.key), col, f"{where}, {col.label.lower()}" if fixed or table.mode == GRID else where)
                if value:
                    row[col.key] = value
        except InputError as exc:
            errors.append(str(exc))
            continue
        if len(row) > (1 if fixed else 0):
            out.append(row)
    return out


def _check_table(table: Table, rows: list[dict[str, str]], week: Week, errors: list[str]) -> None:
    """What a table must satisfy as a whole (rank order, dates in the week, no month skipped)."""
    name = table.label

    def unique(key: str, what: str) -> None:
        seen: set[str] = set()
        for r in rows:
            k = _key(r.get(key, ""))
            if k in seen:
                errors.append(f"{name}: {r[key]} appears twice; each {what} is listed once")
            seen.add(k)

    if table.key == "mmf":
        for n, r in enumerate(rows, 1):
            if int(r["rank"]) != n:
                errors.append(f"{name}: row {n} ({r['fund']}) has rank {r['rank']}; ranks must run 1, 2, 3 in order with none "
                              "skipped or repeated")
                break
        unique("fund", "fund")
        if len(rows) < MIN_FUNDS:
            errors.append(f"{name}: {len(rows)} fund{'s' if len(rows) != 1 else ''} read; the Top 5 average needs at least "
                          f"{MIN_FUNDS}")
    elif table.key == "interbank":
        first, last = week.previous.previous_friday, week.thursday
        unique("date", "day")
        for r in rows:
            day = date.fromisoformat(r["date"])
            if not first <= day <= last or day.weekday() >= 5:
                errors.append(f"{name}: {r['date']} is not a weekday from {first.isoformat()} to {last.isoformat()}, the two "
                              "weeks the paragraph compares")
    elif table.key == "eurobond_yields":
        labels = dict(table.fixed_rows)
        for r in rows:
            yields = [k for k in r if k not in ("row", "date")]
            if "date" not in r or not yields:
                errors.append(f"{name}, {labels[r['row']]}: give the date and at least one yield, or leave the row empty")
                continue
            day = date.fromisoformat(r["date"])
            if r["row"] == "year_open" and not (day.year == week.ending.year and day.month == 1 and day.day <= 8):
                errors.append(f"{name}, {labels[r['row']]}: {r['date']} is not in the first week of January "
                              f"{week.ending.year}")
            if r["row"] == "month_open" and not ((day.year, day.month) == (week.thursday.year, week.thursday.month)
                                                 and day.day <= 7 and day <= week.thursday):
                errors.append(f"{name}, {labels[r['row']]}: {r['date']} is not in the first week of "
                              f"{week.thursday.strftime('%B %Y')}, on or before {week.thursday.isoformat()}")
    elif table.key == "eurobond_issues":
        labels = dict(table.fixed_rows)
        for r in rows:
            if "maturity" in r and date.fromisoformat(r["maturity"]) <= week.ending:
                errors.append(f"{name}, {labels[r['row']]}: the maturity date {r['maturity']} is not after this week")
    elif table.key == "remittances":
        unique("month", "month")
        months = sorted((r["month"] for r in rows), reverse=True)
        for a, b in zip(months, months[1:]):
            if (int(a[:4]) * 12 + int(a[5:])) - (int(b[:4]) * 12 + int(b[5:])) != 1:
                errors.append(f"{name}: {b} is followed by {a}; the months must run with none skipped")
                break
        if months and months[0] > week.ending.strftime("%Y-%m"):
            errors.append(f"{name}: {months[0]} is after this week")
        newest = next((r for r in rows if months and r["month"] == months[0]), None)
        if newest is not None and "north_america" not in newest:
            errors.append(f"{name}: the latest month ({newest['month']}) needs its North America figure")
    elif table.key == "borrowing_log":
        limit = week.value_date_window[1]
        for r in rows:
            day = date.fromisoformat(r["date"])
            if day > limit or day < fiscal_year_start(week):
                errors.append(f"{name}: {r['date']} is not between the start of the fiscal year "
                              f"({fiscal_year_start(week).isoformat()}) and {limit.isoformat()}, when this week's auction settles")
    elif table.key == "borrowing_redemptions":
        # Any day of the fiscal year: a redemption after this week's auctions settle is kept and counts from its own week.
        start = fiscal_year_start(week)
        end = start.replace(year=start.year + 1) - timedelta(days=1)
        seen: set[tuple[str, str]] = set()
        for r in rows:
            if not start <= date.fromisoformat(r["date"]) <= end:
                errors.append(f"{name}: {r['date']} is not in the fiscal year ({start.isoformat()} to {end.isoformat()})")
            if (r["date"], _key(r["bond"])) in seen:
                errors.append(f"{name}: {r['bond']} on {r['date']} appears twice; each redemption is listed once")
            seen.add((r["date"], _key(r["bond"])))
    elif table.key == "foreign_history":
        unique("week_ending", "week")
        for r in rows:
            # The week's last trading day: a Friday, or an earlier day when the Friday was a holiday.
            day = date.fromisoformat(r["week_ending"])
            if day.weekday() >= 5 or day >= week.monday:
                errors.append(f"{name}: {r['week_ending']} is not a trading day before this week")
    elif table.key == "universe":
        unique("company", "company")


def _check_field(spec: Field, value: Any, week: Week) -> None:
    if spec.key == "mmf_published" and not week.monday <= date.fromisoformat(value) <= week.ending:
        raise InputError(f"{spec.label}: {value} is not in the week {week.monday.isoformat()} to {week.ending.isoformat()}")
    if spec.key == "fiscal_year_start":
        day, settles = date.fromisoformat(value), week.value_date_window[0]
        if not settles - timedelta(days=366) < day <= settles:
            raise InputError(f"{spec.label}: {value} is not within the year before {settles.isoformat()}, when this week's "
                             "auction settles")
    if spec.key == "universe_month_end":
        day, month_start = date.fromisoformat(value), week.ending.replace(day=1)
        if not month_start - timedelta(days=31) <= day < month_start:
            raise InputError(f"{spec.label}: {value} is not in the month before {week.ending.strftime('%B %Y')}")


def clean_field(spec: Field, raw: Any, week: Week) -> Any:
    """One field as stored (None to clear it), or InputError."""
    if spec.kind == NAMES:
        lines = raw if isinstance(raw, list) else str(raw or "").replace(",", "\n").splitlines()
        names = [" ".join(str(n).split()) for n in lines if str(n).strip()]
        if len(names) > 60 or any(len(n) > MAX_NAME for n in names):
            raise InputError(f"{spec.label}: at most 60 names of up to {MAX_NAME} characters")
        if len({_key(n) for n in names}) != len(names):
            raise InputError(f"{spec.label}: a name appears twice")
        return names or None
    text = "" if raw is None else str(raw).strip()
    if not text:
        return None
    value = clean_date(text, spec.label) if spec.kind == DATE else clean_number(text, spec, spec.label)
    _check_field(spec, value, week)
    return value


def fiscal_year_start(week: Week) -> date:
    """1 July: Kenya's fiscal year, the one this week's auction settles in."""
    settles = week.value_date_window[0]
    return date(settles.year if settles.month >= 7 else settles.year - 1, 7, 1)


# ---------------------------------------------------------------------------
# The stored form
# ---------------------------------------------------------------------------

def _path(week: Week, root: Optional[Path]) -> Path:
    return week_dir(week, root) / FILE


def read_form(week: Week, root: Optional[Path] = None) -> dict[str, Any]:
    """What was typed for the week: {"fields": {...}, "tables": {...}, "saved_at"}.  Empty if nothing was."""
    path = _path(week, root)
    data: Any = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
    data = data if isinstance(data, dict) else {}
    fields = {k: v for k, v in (data.get("fields") or {}).items() if k in FIELDS and v not in (None, "", [])}
    tables = {k: v for k, v in (data.get("tables") or {}).items() if k in TABLES and isinstance(v, list) and v}
    held = {**fields, **tables}
    # carried: item -> {"from": the week it came from (or "suggested"), "value": what was carried, "note"?}
    carried = {k: v for k, v in (data.get("carried") or {}).items() if k in held and isinstance(v, dict) and v.get("from")}
    unconfirmed = sorted(k for k in (data.get("unconfirmed") or []) if k in held)
    return {"fields": fields, "tables": tables, "saved_at": data.get("saved_at"), "carried": carried, "unconfirmed": unconfirmed}


def _write(week: Week, root: Optional[Path], form: dict[str, Any]) -> dict[str, Any]:
    held = {**form["fields"], **form["tables"]}
    form["carried"] = {k: v for k, v in form.get("carried", {}).items() if k in held}
    form["unconfirmed"] = sorted(k for k in form.get("unconfirmed", []) if k in held)
    form["saved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path = _path(week, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(form, indent=1, sort_keys=True), encoding="utf-8")
    return form


def usable_form(form: dict[str, Any]) -> dict[str, Any]:
    """The form as a builder may read it: without what was carried or suggested and is not yet confirmed."""
    waiting = set(form["unconfirmed"])
    return {**form, "fields": {k: v for k, v in form["fields"].items() if k not in waiting},
            "tables": {k: v for k, v in form["tables"].items() if k not in waiting}}


def save_form(week: Week, changes: dict[str, Any], root: Optional[Path] = None) -> dict[str, Any]:
    """Check and keep what was typed; an item given as None (or empty) is cleared, one left out is kept.

    ``changes`` is {"fields": {key: value}, "tables": {key: {"text": pasted} | {"rows": [...]} | None},
    "confirm": [keys]}.  Saving an item confirms it: a carried value someone has typed over, or
    saved again, is theirs.  ``confirm`` accepts carried or suggested values as they stand.
    If anything is refused, nothing is stored and InputError lists every reason, one a line.
    """
    form = read_form(week, root)
    errors: list[str] = []
    touched: set[str] = set()
    for key in changes.get("confirm") or []:
        if key not in form["unconfirmed"]:
            errors.append(f"nothing waits to be confirmed for {key!r}")
        touched.add(key)
    for key, raw in (changes.get("fields") or {}).items():
        spec = FIELDS.get(key)
        if spec is None:
            errors.append(f"unknown field {key!r}")
            continue
        try:
            value = clean_field(spec, raw, week)
        except InputError as exc:
            errors.append(str(exc))
            continue
        touched.add(key)
        if value is None:
            form["fields"].pop(key, None)
        else:
            form["fields"][key] = value
    for key, given in (changes.get("tables") or {}).items():
        table = TABLES.get(key)
        if table is None:
            errors.append(f"unknown table {key!r}")
            continue
        before = len(errors)
        if not given:
            raw_rows: list[dict[str, Any]] = []
        elif isinstance(given, dict) and isinstance(given.get("text"), str):
            if table.mode != PASTE:
                errors.append(f"{table.label}: this table is typed cell by cell")
                continue
            if len(given["text"]) > MAX_PASTE:
                errors.append(f"{table.label}: the pasted text is {len(given['text']):,} characters; the limit is {MAX_PASTE:,}")
                continue
            raw_rows, problems = parse_paste(table, given["text"])
            errors.extend(problems)
            if given["text"].strip() and not raw_rows and not problems:
                errors.append(f"{table.label}: no row could be read; a row looks like: {table.example}")
        elif isinstance(given, dict) and isinstance(given.get("rows"), list):
            raw_rows = given["rows"]
        else:
            errors.append(f"{table.label}: send the pasted text or the rows")
            continue
        if len(raw_rows) > MAX_ROWS:
            errors.append(f"{table.label}: {len(raw_rows)} rows; the limit is {MAX_ROWS}")
            continue
        rows = _clean_rows(table, raw_rows, errors)
        if len(errors) == before and rows:
            _check_table(table, rows, week, errors)
        if len(errors) == before:
            touched.add(key)
            if rows:
                form["tables"][key] = rows
            else:
                form["tables"].pop(key, None)
    if errors:
        more = f"\n...and {len(errors) - 12} more." if len(errors) > 12 else ""
        raise InputError("\n".join(errors[:12]) + more)
    form["unconfirmed"] = [k for k in form["unconfirmed"] if k not in touched]
    return _write(week, root, form)


def carry_forward(week: Week, root: Optional[Path] = None) -> dict[str, Any]:
    """Start this week's form from last week's: copy what last week's holds into every item still empty here.

    Only what was confirmed last week is copied, and only where it is still valid for this week
    (a month-end date of the same month, interbank days still in the two weeks compared).  Each
    copied item is marked with the week it came from.  Slow-changing items are then used as they
    are; weekly-changing ones wait to be confirmed.  The fund table's date and the running totals
    are never copied, and the Cytonn fund's yield "the previous week" is last week's table's.
    Returns {"form", "carried": [keys], "unconfirmed": [keys]}; InputError if there is nothing to copy.
    """
    last_week = week.previous
    stamp = last_week.ending.isoformat()
    last = usable_form(read_form(last_week, root))
    if not last["fields"] and not last["tables"]:
        raise InputError(f"No analyst inputs are saved for the week ending {stamp}, so there is nothing to start from.")
    form = read_form(week, root)
    carried: list[str] = []

    def take(kind: str, key: str, value: Any, weekly: bool) -> None:
        form[kind][key] = value
        form["carried"][key] = {"from": stamp, "value": value}
        carried.append(key)
        if weekly:
            form["unconfirmed"] = sorted(set(form["unconfirmed"]) | {key})

    for key in SLOW_FIELDS + WEEKLY_FIELDS:
        raw = last["fields"].get(key)
        if raw is None or key in form["fields"]:
            continue
        if key == "foreign_prior_year" and last_week.ending.year != week.ending.year:
            continue
        try:
            take("fields", key, clean_field(FIELDS[key], raw, week), key in WEEKLY_FIELDS)
        except InputError:
            continue   # not valid for this week (last month's month-end date): left empty, to be typed
    if "cmmf_last_week" not in form["fields"]:
        cytonn = next((r for r in last["tables"].get("mmf", []) if fund_key(r["fund"]) == CYTONN_FUND), None)
        if cytonn is not None:
            take("fields", "cmmf_last_week", cytonn["rate"], False)   # last week's table is the previous week's yield
    same_month_end = "universe_month_end" in carried
    for key in SLOW_TABLES + WEEKLY_TABLES:
        rows = last["tables"].get(key)
        if not rows or key in form["tables"]:
            continue
        table = TABLES[key]
        if key == "universe":
            keep = UNIVERSE_CARRIED + (("month_end_price",) if same_month_end else ())
            rows = [{k: v for k, v in r.items() if k in keep} for r in rows]
        elif key in ("eurobond_yields", "interbank", "borrowing_log", "foreign_history", "borrowing_redemptions"):
            rows = [r for r in rows if not _row_problems(table, r, week)]
        problems: list[str] = []
        if rows:
            _check_table(table, rows, week, problems)
        if rows and not problems:
            take("tables", key, rows, key in WEEKLY_TABLES)
    if not carried:
        raise InputError(f"Nothing to carry from the week ending {stamp}: every item it holds is already typed for this week, "
                         "or is no longer valid for it.")
    _write(week, root, form)
    return {"form": form, "carried": carried, "unconfirmed": [k for k in carried if k in form["unconfirmed"]]}


def _row_problems(table: Table, row: dict[str, str], week: Week) -> list[str]:
    problems: list[str] = []
    _check_table(table, [row], week, problems)
    return problems


def suggest(week: Week, key: str, value: str, note: str, root: Optional[Path] = None) -> dict[str, Any]:
    """Keep a worked-out suggestion for a running total as an unconfirmed value, with its working.

    It never replaces a value someone typed or confirmed: that one must be cleared first.
    """
    if key not in SUGGESTED_FIELDS:
        raise InputError(f"no suggestion is worked out for {key!r}")
    form = read_form(week, root)
    if key in form["fields"] and key not in form["unconfirmed"]:
        raise InputError(f"{FIELDS[key].label} is already typed for this week; clear it to have a suggestion worked out.")
    value = clean_field(FIELDS[key], value, week)
    form["fields"][key] = value
    form["carried"][key] = {"from": SUGGESTED, "value": value, "note": note}
    form["unconfirmed"] = sorted(set(form["unconfirmed"]) | {key})
    return _write(week, root, form)


# ---------------------------------------------------------------------------
# What the builders read: the typed value, else the workbook's
# ---------------------------------------------------------------------------

def _names(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


class Analyst:
    """One week's analyst inputs as the builders read them: typed on the form, else from the uploaded workbook.

    Every reader returns None (or an empty list) for what is in neither; ``why()`` words the
    reason for the ``unavailable`` block.  ``differences`` collects, as they are met, the typed
    values that differ from the uploaded workbook's.
    """

    def __init__(self, inputs: WeeklyInputs):
        self.inputs = inputs
        self.week = inputs.week
        self.stored = read_form(inputs.week, inputs.root)
        self.form = usable_form(self.stored)             # a carried or suggested value is read only once confirmed
        self.errors: dict[str, str] = {}             # workbook reading -> why it could not be read
        self.incomplete: dict[str, str] = {}         # item -> what is typed for it but cannot be used yet
        self.differences: list[dict[str, str]] = []  # {"item", "text"}
        self._memo: dict[str, Any] = {}

    # -- the workbooks ------------------------------------------------------

    def _once(self, key: str, load: Callable[[], Any]) -> Any:
        if key not in self._memo:
            self._memo[key] = load()
        return self._memo[key]

    def book(self, which: str) -> Any:
        return self.inputs.fi_book if which == FI else self.inputs.equities_book

    def _read(self, which: str, name: str, read: Callable[[Any], Any]) -> Any:
        """One workbook reading, or None (the reason kept) when the workbook is absent or does not hold it."""
        def load() -> Any:
            book = self.book(which)
            if book is None:
                return None
            try:
                return read(book)
            except WorkbookError as exc:
                self.errors[name] = str(exc)
                return None

        return self._once(f"wb:{name}", load)

    def wb_mmf(self) -> Optional[dict[str, Any]]:
        return self._read(FI, "mmf", lambda b: fi_workbook.read_mmf_table(b, self.week))

    def wb_eurobonds(self) -> Optional[list[fi_workbook.EurobondSeries]]:
        return self._read(FI, "eurobonds", fi_workbook.read_eurobonds)

    def wb_borrowing(self) -> Optional[dict[str, Any]]:
        return self._read(FI, "borrowing", fi_workbook.read_borrowing)

    def wb_turnover(self) -> Optional[equities_workbook.WeeklySeries]:
        return self._read(EQ, "turnover", lambda b: equities_workbook.read_turnover(b, self.week))

    def wb_foreign(self) -> Optional[equities_workbook.WeeklySeries]:
        return self._read(EQ, "foreign", lambda b: equities_workbook.read_foreign_flows(b, self.week))

    def wb_valuation(self) -> dict[str, Any]:
        return self._read(EQ, "valuation", lambda b: equities_workbook.read_valuation(b, self.week)) or {}

    def wb_universe(self) -> Optional[dict[str, Any]]:
        return self._read(EQ, "universe", lambda b: equities_workbook.read_universe(b, self.week))

    def wb_field(self, key: str) -> Any:
        """The uploaded workbook's cell for a field (a list of cells for the large-cap list), or None."""
        if key == "placements":
            return self._read(FI, key, fi_workbook.read_placements)
        if key == "cmmf_last_week":
            return self._read(FI, key, fi_workbook.read_mmf_last_week)
        if key == "mmf_published":
            table = self.wb_mmf()
            return None if table is None else Cell(table["published"], table["title_cell"].sheet, table["title_cell"].row,
                                                   table["title_cell"].col)
        if key == "borrowing_target":
            return (self.wb_borrowing() or {}).get("target_bn")
        if key == "fiscal_year_start":
            return (self.wb_borrowing() or {}).get("fy_start")
        if key == "large_caps":
            return self._read(EQ, key, equities_workbook.read_large_caps)
        if key == "turnover_ytd":
            series = self.wb_turnover()
            return series.ytd if series else None
        if key == "foreign_ytd":
            series = self.wb_foreign()
            return series.ytd if series else None
        if key == "foreign_prior_year":
            series = self.wb_foreign()
            return equities_workbook.prior_year_total(series, self.week.ending.year) if series else None
        if key in ("pe", "pe_average", "dividend_yield", "dividend_yield_average"):
            return self.wb_valuation().get(key)
        if key == "universe_month_end":
            return (self.wb_universe() or {}).get("month_end_cell")
        raise KeyError(key)

    def wb_rows(self, key: str) -> Optional[list[dict[str, Any]]]:
        """The uploaded workbook's rows for a table, in the form's columns (cells, or plain dates), or None."""
        week = self.week
        if key == "mmf":
            table = self.wb_mmf()
            return None if table is None else [dict(f) for f in table["funds"]]
        if key == "interbank":
            return self._read(FI, key, lambda b: fi_workbook.read_interbank(b, week.previous.previous_friday, week.thursday)) or None
        if key in ("eurobond_issues", "eurobond_yields"):
            series = self.wb_eurobonds()
            if series is None:
                return None
            if key == "eurobond_issues":
                return [{"row": s.key, "amount_mn": s.issue["amount_before"], "maturity": s.issue["maturity"]}
                        for s in series if s.issue is not None] or None
            last = week.thursday
            days = sorted({d for s in series for d in s.yields if d.year == week.ending.year and d <= last})
            rows = []
            year_open = next((d for d in days if d.month == 1 and d.day <= 8), None)
            month_open = next((d for d in days if (d.year, d.month) == (last.year, last.month) and d.day <= 7), None)
            for name, day in (("year_open", year_open), ("month_open", month_open)):
                if day is not None:
                    rows.append({"row": name, "date": day, **{s.key: s.yields[day] for s in series if day in s.yields}})
            return rows or None
        if key == "remittances":
            months = self._read(FI, key, fi_workbook.read_remittances)
            return None if not months else [{"month": f"{m['year']:04d}-{m['month']:02d}", "north_america": m["north_america"],
                                             "total": m["total"]} for m in months[:24]]
        if key == "borrowing_log":
            data = self.wb_borrowing()
            limit = week.value_date_window[1]
            return None if data is None else [{"date": r["date"], "accepted": r["accepted"], "redemptions": r["redemptions"]}
                                              for r in data["log"] if r["date"] <= limit]
        if key == "borrowing_redemptions":
            return None     # the workbook's log has no such rows: a redemption CBK prints nowhere is only ever typed
        if key == "foreign_history":
            series = self.wb_foreign()
            if series is None:
                return None
            earlier = [(d, t) for d, t, _, _ in series.history if d < week.monday]
            return [{"week_ending": d, "net": series.sums.get(d, t)} for d, t in earlier] or None
        if key == "universe":
            data = self.wb_universe()
            return None if data is None else [dict(c) for c in data["companies"]]
        raise KeyError(key)

    # -- one typed value ----------------------------------------------------

    def _differs(self, item: str, what: str, typed_text: str, wb: Any, wb_text: str, which: str) -> None:
        self.differences.append({"item": item, "text": (
            f"{what}: typed as {typed_text}, but the uploaded {WORKBOOKS[which].lower()} has {wb_text} "
            f"({getattr(wb, 'ref', 'the workbook')}). The typed value is used.")})

    def _typed(self, item: str, which: str, text: str, kind: str, scale: int, unit: str, what: str, label: str, wb: Any) -> Typed:
        """A stored value as a ``Typed`` cell; the workbook's cell rides along when it holds something else."""
        cell = wb if isinstance(wb, (Cell, Typed)) else None
        if kind == DATE:
            day = date.fromisoformat(text)
            other = cell if cell is not None and cell.day is not None and cell.day != day else None
            if other is not None:
                self._differs(item, what, text, other, other.day.isoformat(), which)
            return Typed(day, what, label, other)
        if kind in (TEXT, MONTH):
            return Typed(text, what, label)
        typed = Decimal(text)
        other = None
        if cell is not None and cell.number is not None and Decimal(repr(cell.number)) * scale != typed:
            other = cell
            suffix = unit if unit in ("%", "x") else ""
            self._differs(item, what, f"{text}{suffix}", cell, f"{shown(cell, scale)}{suffix}", which)
        return Typed(float(typed / scale) if scale != 1 else float(typed), what, label, other)

    def field(self, key: str) -> Any:
        """A field's value: typed on the form, else the workbook's cell, else None."""
        def load() -> Any:
            spec, raw, wb = FIELDS[key], self.form["fields"].get(key), self.wb_field(key)
            if raw is None:
                return wb
            if spec.kind == NAMES:
                theirs = [shown(c) for c in wb] if wb else []
                if theirs and [_key(n) for n in theirs] != [_key(n) for n in raw]:
                    self.differences.append({"item": key, "text": (
                        f"{spec.label}: the typed list ({', '.join(raw)}) is not the uploaded "
                        f"{WORKBOOKS[spec.section].lower()}'s ({', '.join(theirs)}). The typed list is used.")})
                return [Typed(n, spec.label.lower(), spec.source) for n in raw]
            return self._typed(key, spec.section, raw, spec.kind, spec.scale, spec.unit, spec.label, spec.source, wb)

        return self._once(f"field:{key}", load)

    def _cell(self, table: Table, col: Column, row: dict[str, str], what: str, wb: Any) -> Any:
        """One cell of a typed row: typed, else BLANK."""
        text = row.get(col.key)
        if not text:
            return BLANK
        return self._typed(table.key, table.section, text, col.kind, col.scale, col.unit, f"{what}: {col.label.lower()}",
                           table.source, wb)

    def typed_rows(self, key: str) -> list[dict[str, str]]:
        return self.form["tables"].get(key) or []

    def _only_in(self, table: Table, typed: set[str], theirs: dict[str, str]) -> None:
        """Say which rows are on one side only, when a typed table replaces the workbook's."""
        missing = [name for k, name in theirs.items() if k not in typed]
        added = len(typed - set(theirs))
        if missing or added:
            parts = []
            if missing:
                parts.append(f"{len(missing)} in the workbook only ({', '.join(missing[:6])}{', ...' if len(missing) > 6 else ''})")
            if added:
                parts.append(f"{added} typed only")
            self.differences.append({"item": table.key, "text": (
                f"{table.label}: the typed rows are not the uploaded {WORKBOOKS[table.section].lower()}'s rows: "
                f"{'; '.join(parts)}. The typed table is used.")})

    # -- fixed income ---------------------------------------------------------

    def mmf(self) -> Optional[dict[str, Any]]:
        """The fund table: {published, title, funds: [{rank, fund, rate}], origin}; None if it is in neither place."""
        def load() -> Optional[dict[str, Any]]:
            table, rows, wb = TABLES["mmf"], self.typed_rows("mmf"), self.wb_mmf()
            if not rows:
                if wb is None:
                    return None
                first, last = wb["funds"][0]["rank"], wb["funds"][-1]["rate"]
                return {**wb, "origin": f"analyst input from {fi_workbook.SOURCE_NAME} {first.ref}:{last.a1}, typed from "
                                        "Business Daily"}
            published = self.field("mmf_published")
            if published is None or published.day is None:
                self.incomplete["mmf"] = (f"The money market fund table is typed under \"{FORM}\", but the date it was "
                                          "published on is not.")
                return None
            theirs = {fund_key(f["fund"].value): f for f in wb["funds"]} if wb else {}
            funds = []
            for r in rows:
                base = theirs.get(fund_key(r["fund"]), {})
                what = f"money market fund table, {r['fund']}"
                funds.append({"rank": Typed(int(r["rank"]), f"{what}: rank", table.source),
                              "fund": Typed(r["fund"], what, table.source),
                              "rate": self._cell(table, table.columns[2], r, what, base.get("rate"))})
            if wb:
                self._only_in(table, {fund_key(r["fund"]) for r in rows}, {k: shown(f["fund"]) for k, f in theirs.items()})
            return {"published": published.day, "funds": funds,
                    "title": f"Money Market Fund Yield for Fund Managers as published on {ordinal(published.day)}",
                    "origin": f"analyst input typed on the weekly form (money market fund table; source: {table.source})"}

        return self._once("mmf", load)

    def interbank(self) -> list[dict[str, Any]]:
        """The daily interbank rows of the two weeks compared, oldest first: [{date, volume (or None), rate}]."""
        def load() -> list[dict[str, Any]]:
            table, rows, wb = TABLES["interbank"], self.typed_rows("interbank"), self.wb_rows("interbank") or []
            if not rows:
                return wb
            theirs = {r["date"]: r for r in wb}
            out = []
            for r in sorted(rows, key=lambda r: r["date"]):
                day = date.fromisoformat(r["date"])
                base = theirs.get(day, {})
                out.append({"date": day, "volume": base.get("volume"),
                            "rate": self._cell(table, table.columns[1], r, f"interbank rate, {r['date']}", base.get("rate"))})
            return out

        return self._once("interbank", load)

    def eurobonds(self) -> list[Optional[fi_workbook.EurobondSeries]]:
        """The five printed issues, each None if nothing about it was typed or uploaded."""
        def load() -> list[Optional[fi_workbook.EurobondSeries]]:
            wb = self.wb_eurobonds()
            issues, days = TABLES["eurobond_issues"], TABLES["eurobond_yields"]
            typed_issues = {r["row"]: r for r in self.typed_rows("eurobond_issues")}
            typed_days = self.typed_rows("eurobond_yields")
            cols = {c.key: c for c in issues.columns}
            out: list[Optional[fi_workbook.EurobondSeries]] = []
            for n, spec in enumerate(fi_workbook.EUROBOND_ISSUES):
                key, head, maturity_year = spec[0], spec[1], spec[5]
                name = f"{head[0]} {head[1]}"
                base = wb[n] if wb else None
                series = fi_workbook.EurobondSeries(key, head, maturity_year, dict(base.yields) if base else {},
                                                    dict(base.issue) if base and base.issue else None)
                for r in typed_days:
                    if r.get(key):
                        day = date.fromisoformat(r["date"])
                        col = next(c for c in days.columns if c.key == key)
                        series.yields[day] = self._typed(days.key, FI, r[key], NUMBER, col.scale, col.unit,
                                                         f"Eurobond yield, {name}, {r['date']}", days.source, series.yields.get(day))
                row = typed_issues.get(key, {})
                if row.get("amount_mn") or row.get("maturity"):
                    issue = dict(series.issue or {"amount_before": BLANK, "maturity": BLANK})
                    if row.get("amount_mn"):
                        issue["amount_before"] = self._cell(issues, cols["amount_mn"], row, f"Eurobond issues, {name}",
                                                            issue.get("amount_before"))
                    if row.get("maturity"):
                        issue["maturity"] = self._cell(issues, cols["maturity"], row, f"Eurobond issues, {name}", issue.get("maturity"))
                    series.issue = issue
                if row.get("yield_at_issue"):
                    series.yield_at_issue = self._cell(issues, cols["yield_at_issue"], row, f"Eurobond issues, {name}", None)
                out.append(series if base is not None or series.yields or series.issue or series.yield_at_issue else None)
            return out

        return self._once("eurobonds", load)

    def remittances(self) -> list[dict[str, Any]]:
        """Monthly remittances, newest first: [{year, month, north_america, total}]; empty if in neither place."""
        def load() -> list[dict[str, Any]]:
            table, rows = TABLES["remittances"], self.typed_rows("remittances")
            wb = self._read(FI, "remittances", fi_workbook.read_remittances) or []
            if not rows:
                return wb
            theirs = {(m["year"], m["month"]): m for m in wb}
            cols = {c.key: c for c in table.columns}
            out = []
            for r in sorted(rows, key=lambda r: r["month"], reverse=True):
                year, month = int(r["month"][:4]), int(r["month"][5:])
                base, what = theirs.get((year, month), {}), f"remittances, {r['month']}"
                out.append({"year": year, "month": month,
                            "north_america": self._cell(table, cols["north_america"], r, what, base.get("north_america")),
                            "total": self._cell(table, cols["total"], r, what, base.get("total"))})
            return out

        return self._once("remittances", load)

    def borrowing(self) -> dict[str, Any]:
        """{target_bn, log, fy_start, fy_start_typed, typed_log, redemptions}.

        The target and the analysts' own log are None where they are in neither place.  The
        fiscal year starts on the typed day, else the workbook's, else 1 July.  ``redemptions``
        is the typed "Other bond redemptions", oldest first: [{date, bond, amount}], the amount a
        typed cell in Kshs mn.
        """
        def load() -> dict[str, Any]:
            table, rows, wb = TABLES["borrowing_log"], self.typed_rows("borrowing_log"), self.wb_borrowing()
            log = wb["log"] if wb else None
            if rows:
                # A bill and a bond auction can settle on the same day, so a row is matched by its date and its turn on it.
                theirs: dict[tuple[date, int], dict[str, Any]] = {}
                for r in (wb["log"] if wb else []):
                    theirs[(r["date"], sum(1 for k in theirs if k[0] == r["date"]))] = r
                cols = {c.key: c for c in table.columns}
                log, turn = [], {}
                for r in sorted(rows, key=lambda r: r["date"]):   # stable: rows of one day keep their typed order
                    day = date.fromisoformat(r["date"])
                    turn[day] = turn.get(day, -1) + 1
                    base, what = theirs.get((day, turn[day]), {}), f"auction log, {r['date']}"
                    log.append({"date": day, "accepted": self._cell(table, cols["accepted"], r, what, base.get("accepted")),
                                "redemptions": self._cell(table, cols["redemptions"], r, what, base.get("redemptions"))})
            start = self.field("fiscal_year_start")
            typed_start = is_typed(start)
            if start is None or start.day is None:
                start = Typed(fiscal_year_start(self.week), "start of the fiscal year", "1 July")
            other, amount = TABLES["borrowing_redemptions"], TABLES["borrowing_redemptions"].columns[2]
            redemptions = [{"date": date.fromisoformat(r["date"]), "bond": r["bond"],
                            "amount": self._cell(other, amount, r, f"other bond redemptions, {r['bond']} on {r['date']}", None)}
                           for r in sorted(self.typed_rows("borrowing_redemptions"), key=lambda r: r["date"])]
            return {"target_bn": self.field("borrowing_target"), "log": log, "fy_start": start, "fy_start_typed": typed_start,
                    "typed_log": bool(rows), "redemptions": redemptions}

        return self._once("borrowing", load)

    # -- equities -------------------------------------------------------------

    def foreign_history(self) -> list[tuple[date, float, Any]]:
        """The weekly net positions before this week, oldest first: (the week's Friday, USD mn, its cell or None)."""
        def load() -> list[tuple[date, float, Any]]:
            table, rows, series = TABLES["foreign_history"], self.typed_rows("foreign_history"), self.wb_foreign()
            theirs = {d: series.sums.get(d) for d, _, _, _ in series.history} if series else {}
            if not rows:
                return [(d, t, theirs.get(d)) for d, t, _, _ in (series.history if series else []) if d < self.week.monday]
            out = []
            for r in sorted(rows, key=lambda r: r["week_ending"]):
                day = date.fromisoformat(r["week_ending"])
                cell = self._cell(table, table.columns[1], r, f"foreign net position, week ending {r['week_ending']}", theirs.get(day))
                out.append((day, cell.number, cell))
            return out

        return self._once("foreign_history", load)

    def kcb_price(self, company: Any) -> Optional[Reading]:
        """The company's price in KCB IB's weekly report for this Friday, or None (no report, or a name with no ticker)."""
        report = self.inputs.kcb_weekly
        ticker = COVERAGE_TICKERS.get(_key(company))
        if report is None or ticker is None or report.report_date != self.week.ending:
            return None
        price = (report.securities.get(ticker) or {}).get("price")
        return None if price is None else Reading(price, f"KCB IB weekly report of {self.week.ending.isoformat()}, {ticker}")

    def friday_price(self, company: Any) -> Any:
        """This week's Friday price as stored: typed, else KCB IB's, else the uploaded workbook's.  None if in none."""
        name = _key(company)
        typed = next((r for r in self.typed_rows("universe") if _key(r["company"]) == name and r.get("price")), None)
        if typed is not None:
            return Typed(float(Decimal(typed["price"])), f"Universe of Coverage, {typed['company']}: price", TABLES["universe"].source)
        kcb = self.kcb_price(company)
        if kcb is not None:
            return kcb
        row = next((c for c in (self.wb_universe() or {}).get("companies", []) if _key(c["company"].value) == name), None)
        return row["price"] if row is not None and row["price"].number is not None else None

    def last_friday_price(self, company: Any) -> Optional[Reading]:
        """The previous Friday's price: the Friday price stored for the previous week, named as such."""
        previous = self._once("previous", lambda: WeeklyInputs(self.week.previous, self.inputs.root).analyst)
        cell = previous.friday_price(company)
        if cell is None or cell.number is None:
            return None
        where = cell.source if isinstance(cell, (Typed, Reading)) else f"{equities_workbook.SOURCE_NAME} {cell.ref}"
        return Reading(cell.number, f"the price stored for the week ending {self.week.previous_friday.isoformat()} ({where})")

    def universe(self) -> Optional[dict[str, Any]]:
        """{companies: [{company, price, ...}], month_end, typed}: typed rows first, then the workbook's other rows.

        In a typed row, a price left empty is KCB IB's for this Friday and the stored previous
        week's for last Friday (else the uploaded workbook's); a typed price that differs from
        KCB IB's is used, and the difference recorded.
        """
        def load() -> Optional[dict[str, Any]]:
            table, rows, wb = TABLES["universe"], self.typed_rows("universe"), self.wb_universe()
            if not rows:
                return None if wb is None else {**wb, "typed": False}
            month_end = self.field("universe_month_end")
            theirs = {_key(c["company"].value): c for c in (wb["companies"] if wb else [])}
            companies = []
            for r in rows:
                base = theirs.get(_key(r["company"]))
                what = f"Universe of Coverage, {r['company']}"
                row: dict[str, Any] = {"company": Typed(r["company"], what, table.source)}
                kcb = self.kcb_price(r["company"])
                for col in table.columns[1:]:
                    cell = self._cell(table, col, r, what, base[col.key] if base else None)
                    if cell is BLANK:
                        found = kcb if col.key == "price" else None
                        found = found or (base[col.key] if base else None)
                        if found is None and col.key == "last_price":
                            found = self.last_friday_price(r["company"])
                        cell = found if found is not None else BLANK
                    elif col.key == "price" and kcb is not None and cell.other is None and Decimal(repr(kcb.number)) != Decimal(r["price"]):
                        cell = Typed(cell.value, cell.what, cell.label, kcb)
                        self.differences.append({"item": table.key, "text": (
                            f"{what}: price: typed as {r['price']}, but the {kcb.source} has {shown(kcb.number)}. "
                            "The typed value is used.")})
                    row[col.key] = cell
                companies.append(row)
            typed_names = {_key(r["company"]) for r in rows}
            companies += [c for k, c in theirs.items() if k not in typed_names]
            return {"companies": companies, "month_end": month_end.day if month_end is not None else None, "typed": True}

        return self._once("universe", load)

    # -- wording --------------------------------------------------------------

    def why(self, which: str, items: list[str]) -> tuple[str, str]:
        """(reason, unblock) for a part that needs ``items`` (field or table keys) and found them in neither place."""
        labels = [_NAMED.get(k) or "the " + (lambda t: t[0].lower() + t[1:])((FIELDS.get(k) or TABLES.get(k)).label) for k in items]
        workbook = WORKBOOKS[which].lower()
        half_typed = [self.incomplete[k] for k in items if k in self.incomplete]
        for key in items:
            if key in self.stored["unconfirmed"]:
                came = self.stored["carried"].get(key, {}).get("from")
                label = (FIELDS.get(key) or TABLES.get(key)).label
                half_typed.append(f"{label} is {'a suggestion' if came == SUGGESTED else f'carried from the week ending {came}'} "
                                  "and has not been confirmed for this week.")
        if half_typed:
            return " ".join(half_typed), f"Complete or confirm it under \"{FORM}\" on the start screen and draft again."
        verb, them = ("has", "it") if len(labels) == 1 and not labels[0].endswith("s") else ("have", "them")
        said = []
        for key in items:
            problem = self.errors.get(_READING[key])
            if problem and problem not in said:
                said.append(problem)
        listed = _names(labels)
        listed = listed[0].upper() + listed[1:]
        if self.book(which) is None:
            reason = (f"{listed} {verb} not been typed under \"{FORM}\", and the {workbook} for this week is not among this "
                      "week's inputs.")
        elif said:
            reason = " ".join(s if s.endswith(".") else s + "." for s in said) + f" {listed} {verb} not been typed under \"{FORM}\" either."
        else:
            reason = f"{listed} {verb} not been typed under \"{FORM}\", and the uploaded {workbook} does not hold {them}."
        return reason, (f"Type {them} under \"{FORM}\" on the start screen, or upload the {workbook} updated for this week, "
                        "and draft again.")

    def difference_lines(self) -> list[str]:
        """Every difference met so far between a typed value and the uploaded workbook's, worded for the reviewer."""
        seen: list[str] = []
        for d in self.differences:
            if d["text"] not in seen:
                seen.append(d["text"])
        return [f"{FORM}: {text}" for text in seen]


# ---------------------------------------------------------------------------
# What the form shows
# ---------------------------------------------------------------------------

def _wb_ref(value: Any) -> Optional[str]:
    return value.ref if isinstance(value, Cell) else None


def _wb_row(table: Table, row: dict[str, Any]) -> dict[str, str]:
    out = {"row": row["row"]} if "row" in row else {}
    for col in table.columns:
        text = shown(row.get(col.key), col.scale)
        if text:
            out[col.key] = text
    return out


def _table_warnings(table: Table, rows: list[dict[str, str]]) -> list[str]:
    if table.key == "mmf":
        for a, b in zip(rows, rows[1:]):
            if Decimal(b["rate"]) > Decimal(a["rate"]):
                return [f"{b['fund']} (rank {b['rank']}) has a higher rate than {a['fund']} (rank {a['rank']}): check the ranks "
                        "and rates against the paper."]
    if table.key == "remittances" and 0 < len(rows) < 24:
        return [f"{len(rows)} month{'s' if len(rows) != 1 else ''} typed; the remittances sentence compares the latest twelve "
                "months with the twelve before, so it needs 24."]
    return []


def status(week: Week, root: Optional[Path] = None, section: Optional[str] = None) -> dict[str, Any]:
    """The form for one week: every item with what was typed, what the uploaded workbook holds, and where they differ."""
    analyst = Analyst(WeeklyInputs(week, root))
    form = analyst.stored          # what is held, confirmed or not; the readers below see only what is confirmed
    last = usable_form(read_form(week.previous, root))   # what carry_forward() would copy: only what was confirmed

    def carried(key: str, value: Any) -> Optional[dict[str, Any]]:
        """Where the item's value came from, while it is still what was carried or suggested."""
        mark = form["carried"].get(key)
        if mark is None or value is None:
            return None
        same = mark["value"] == value
        cells = None
        if not same and isinstance(value, list) and isinstance(mark["value"], list) and key in TABLES:
            # a grid someone edited: say which cells are still the carried ones
            name = "row" if TABLES[key].fixed_rows else TABLES[key].columns[0].key
            before = {_key(r.get(name, "")): r for r in mark["value"] if isinstance(r, dict)}
            cells = {r[name]: [c.key for c in TABLES[key].columns if c.key != name and c.key in r
                               and before.get(_key(r[name]), {}).get(c.key) == r[c.key]]
                     for r in value if isinstance(r, dict) and name in r}
            cells = {k: v for k, v in cells.items() if v}
        if not same and not cells:
            return None
        return {"from": mark["from"], "note": mark.get("note", ""), "whole": same, "cells": cells or {}}
    # Run every reader the builders use, so the differences shown here are the ones a draft will report.
    for key in FIELDS:
        analyst.field(key)
    for read in (analyst.mmf, analyst.interbank, analyst.eurobonds, analyst.remittances, analyst.borrowing,
                 analyst.foreign_history, analyst.universe):
        read()
    differences: dict[str, list[str]] = {}
    for d in analyst.differences:
        if d["text"] not in differences.setdefault(d["item"], []):
            differences[d["item"]].append(d["text"])

    def field_view(spec: Field) -> dict[str, Any]:
        wb = analyst.wb_field(spec.key)
        workbook = None
        if wb:
            workbook = ({"value": [shown(c) for c in wb], "ref": wb[0].ref} if spec.kind == NAMES
                        else {"value": shown(wb, spec.scale), "ref": wb.ref})
        return {"type": "field", "key": spec.key, "label": spec.label, "kind": spec.kind, "unit": spec.unit, "min": spec.lo,
                "max": spec.hi, "source": spec.source, "help": spec.help, "used_in": spec.used_in,
                "value": form["fields"].get(spec.key), "workbook": workbook,
                "workbook_note": analyst.errors.get(_READING[spec.key]), "differences": differences.get(spec.key, []),
                "carried": carried(spec.key, form["fields"].get(spec.key)),
                "needs_confirmation": spec.key in form["unconfirmed"], "suggestable": spec.key in SUGGESTED_FIELDS,
                "default": fiscal_year_start(week).isoformat() if spec.key == "fiscal_year_start" else None}

    def table_view(table: Table) -> dict[str, Any]:
        rows = form["tables"].get(table.key)
        wb = analyst.wb_rows(table.key)
        first = next((v for r in (wb or []) for v in r.values() if isinstance(v, Cell)), None)
        auto = None
        if table.key == "universe":
            # What a row gets without typing: this Friday's price from KCB IB, last Friday's from the stored week.
            name = table.columns[0].key
            listed = [r[name] for r in rows or []] + [shown(r[name]) for r in wb or []]
            auto = []
            for company in dict.fromkeys(listed):
                now, before = analyst.kcb_price(company), analyst.last_friday_price(company)
                found = {name: company, **({"price": shown(now.number)} if now else {}),
                         **({"last_price": shown(before.number)} if before else {})}
                if len(found) > 1:
                    auto.append(found)
        return {"type": "table", "key": table.key, "label": table.label, "mode": table.mode, "source": table.source,
                "help": table.help, "example": table.example, "used_in": table.used_in,
                "columns": [{"key": c.key, "label": c.label, "kind": c.kind, "unit": c.unit, "min": c.lo, "max": c.hi,
                             "required": c.required} for c in table.columns],
                "fixed_rows": [{"key": k, "label": label} for k, label in table.fixed_rows],
                "rows": rows, "text": to_text(table, rows) if rows and table.mode == PASTE else "",
                "workbook_rows": [_wb_row(table, r) for r in wb] if wb else None,
                "workbook_ref": f"{WORKBOOKS[table.section]} '{first.sheet}'" if first is not None else None,
                "workbook_note": analyst.errors.get(_READING[table.key]),
                "warnings": _table_warnings(table, rows or []), "differences": differences.get(table.key, []),
                "carried": carried(table.key, rows), "needs_confirmation": table.key in form["unconfirmed"],
                "auto_rows": auto or None,
                "auto_note": ("This Friday's price is read from KCB IB's weekly report and last Friday's from the price stored "
                              "for the previous week, where you type none.") if auto else ""}

    groups = []
    for sec, key, title in GROUPS:
        if section is not None and sec != section:
            continue
        items = [field_view(f) for f in FIELD_LIST if (f.section, f.group) == (sec, key)]
        items += [table_view(t) for t in TABLE_LIST if (t.section, t.group) == (sec, key)]
        groups.append({"section": sec, "key": key, "title": title, "items": items})
    shown_keys = {i["key"] for g in groups for i in g["items"]}
    return {"form": FORM, "week_ending": week.ending.isoformat(), "saved_at": form.get("saved_at"), "groups": groups,
            "workbooks": {FI: analyst.book(FI) is not None, EQ: analyst.book(EQ) is not None},
            "previous_week": week.previous_friday.isoformat(),
            "can_carry": bool(last["fields"] or last["tables"]),
            # what still waits to be confirmed, on this section's part of the form: the draft button waits for it
            "unconfirmed": [{"key": k, "label": (FIELDS.get(k) or TABLES.get(k)).label}
                            for k in form["unconfirmed"] if k in shown_keys]}
