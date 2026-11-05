from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, DivisionByZero, InvalidOperation
from typing import Any, Optional

from cytonn_weekly.common.formatting import round_half_up
from cytonn_weekly.weekly.workbook import Sheet, Workbook, WorkbookError, norm

STOCK_SHEET = "Stock Performance"
EARNINGS_SHEET = "Earnings"

# The Average row covers exactly these seven (the team, 5 Nov); Coinbase, Wise and JPMorgan are listed but not averaged.
AVERAGE_COMPANIES = ("american express", "visa", "mastercard", "circle", "block", "paypal", "global payments")

# A P/E prints to 1 dp, so a cached figure within this of ours is the same figure.
TOLERANCE = Decimal("0.05")

_SUFFIX_WORDS = {"inc", "plc", "co", "corp", "ltd", "limited", "holdings", "group", "internet"}
_REF = re.compile(r"((?:'[^']+'|[A-Za-z_]+)!)?\$?([A-Z]{1,3})\$?(\d+)")
_PRICE_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


class DpWorkbookError(WorkbookError):
    """The Digital Payments workbook cannot be read by company name (a company missing or listed twice, a formula it cannot follow)."""


def open_dp_workbook(source, name: str = "The Digital Payments workbook") -> Workbook:
    book = Workbook(source, name)
    missing = [s for s in (STOCK_SHEET, EARNINGS_SHEET) if s not in book.sheet_names]
    if missing:
        raise WorkbookError(f"{name} is not the Digital Payments workbook: it has no sheet {missing[0]!r}")
    return book


def company_key(name: Any) -> str:
    """A company's name as compared across sheets and against Yahoo's: lower case, no punctuation, no Inc/PLC/Holdings."""
    words = re.sub(r"[^a-z0-9 ]", " ", norm(name)).split()
    return " ".join(w for w in words if w not in _SUFFIX_WORDS)


@dataclass(frozen=True)
class DpRow:
    company: str
    key: str
    year_open: Optional[Decimal]
    year_open_ref: str
    ttm_pe: Decimal
    forward_pe: Decimal


@dataclass
class DpBook:
    rows: list[DpRow]
    average_ttm: Decimal
    average_forward: Decimal
    price_date: Optional[date] = None
    warnings: list[str] = field(default_factory=list)
    blank_quarters: list[str] = field(default_factory=list)

    def row(self, key: str) -> Optional[DpRow]:
        return next((r for r in self.rows if r.key == key), None)


def _blocks(earnings: Sheet) -> list[tuple[int, list[int]]]:
    """(header row, company rows) for each table on the Earnings sheet: a table starts under a row headed "Company"."""
    out: list[tuple[int, list[int]]] = []
    for r in range(1, earnings.max_row + 1):
        if norm(earnings.value(r, 1)) == "company":
            rows = []
            nxt = r + 1
            while nxt <= earnings.max_row and earnings.value(nxt, 1) not in (None, ""):
                rows.append(nxt)
                nxt += 1
            out.append((r, rows))
    return out


def _find_row(earnings: Sheet, header: int, rows: list[int], key: str, company: str) -> int:
    hits = [r for r in rows if company_key(earnings.value(r, 1)) == key]
    where = f"under {EARNINGS_SHEET} row {header}"
    if not hits:
        raise DpWorkbookError(f"{EARNINGS_SHEET}: {company} has no row {where}. Add it, or remove the company from {STOCK_SHEET}.")
    if len(hits) > 1:
        raise DpWorkbookError(f"{EARNINGS_SHEET}: {company} appears twice {where} (rows {', '.join(map(str, hits))}). Keep one.")
    return hits[0]


def _number(sheet: Sheet, row: int, col: int, what: str, blanks: Optional[list[str]] = None) -> Decimal:
    c = sheet.cell(row, col)
    if c.value is None and blanks is not None:
        blanks.append(c.ref)   # Excel adds an empty cell as 0; the draft says so
        return Decimal(0)
    if c.number is None:
        raise DpWorkbookError(f"{what}: {c.ref} {'is empty' if c.value is None else f'holds {c.value!r}'}")
    return Decimal(repr(c.value))


def _arith(expr: str) -> Decimal:
    def go(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return Decimal(repr(node.value))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            return -go(node.operand) if isinstance(node.op, ast.USub) else go(node.operand)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            a, b = go(node.left), go(node.right)
            if isinstance(node.op, ast.Add):
                return a + b
            if isinstance(node.op, ast.Sub):
                return a - b
            return a * b if isinstance(node.op, ast.Mult) else a / b
        raise ValueError("not plain arithmetic")

    return go(ast.parse(expr, mode="eval").body)


def _by_name(book: Workbook, stock: Sheet, earnings: Sheet, blocks, row: int, col: int, company: str, key: str,
             what: str, blanks: list[str]) -> tuple[Decimal, list[str]]:
    """The cell's formula worked out with each Earnings reference moved to the company's own row in the same table.

    Returns the figure and the other companies whose rows the workbook's own formula reads; an empty
    Earnings cell counts as 0, as it does in Excel, and its address is added to ``blanks``."""
    formula = book.formula(stock.cell(row, col))
    if formula is None:
        raise DpWorkbookError(f"{STOCK_SHEET}: the {what} for {company} ({stock.cell(row, col).ref}) is a typed number, not a formula, "
                              "so it cannot be worked out from the company's earnings by name.")
    strangers: list[str] = []

    def sub(m: re.Match) -> str:
        sheet = (m.group(1) or "").rstrip("!").strip("'")
        r, c = int(m.group(3)), _col(m.group(2))
        if sheet in ("", STOCK_SHEET):
            return f"({_number(stock, r, c, f'{what} for {company}')})"
        if sheet != EARNINGS_SHEET:
            raise DpWorkbookError(f"{STOCK_SHEET}: the {what} for {company} reads sheet {sheet!r}, which the tool does not follow.")
        block = next(((h, rows) for h, rows in blocks if r in rows), None)
        if block is None:
            raise DpWorkbookError(f"{STOCK_SHEET}: the {what} for {company} reads {EARNINGS_SHEET} row {r}, which is in no company table.")
        own = _find_row(earnings, block[0], block[1], key, company)
        if own != r:
            strangers.append(f"{str(earnings.value(r, 1)).strip()} (row {r})")
        return f"({_number(earnings, own, c, f'{what} for {company}', blanks)})"

    try:
        return _arith(_REF.sub(sub, formula.lstrip("="))), strangers
    except (SyntaxError, ValueError, InvalidOperation, DivisionByZero) as exc:
        if isinstance(exc, DpWorkbookError):
            raise
        raise DpWorkbookError(f"{STOCK_SHEET}: the {what} for {company} ({stock.cell(row, col).ref}) is a formula the tool cannot work out: {formula}") from None


def _col(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def _price_date(stock: Sheet, header: int) -> Optional[date]:
    last = None
    for c in stock.cells(range(header, header + 1)):
        m = _PRICE_DATE.search(str(c.value)) if norm(c.value).startswith("price") else None
        if m:
            try:
                last = datetime.strptime(m.group(0), "%d/%m/%Y").date()
            except ValueError:
                last = None
    return last


def _differs(cached: Any, ours: Decimal) -> bool:
    return not isinstance(cached, (int, float)) or abs(Decimal(repr(cached)) - ours) > TOLERANCE


def _shown(value: Any) -> str:
    return f"{round_half_up(value, 1)}x" if isinstance(value, (int, float, Decimal)) else "nothing"


def read_dp_workbook(book: Workbook) -> DpBook:
    """Each company's TTM and forward P/E worked out from its own earnings, found by name, never by row.

    Raises DpWorkbookError naming the company when one is missing or listed twice.  ``warnings`` lists every
    cached P/E or Average in the workbook that is not the figure worked out here."""
    stock, earnings = book.sheet(STOCK_SHEET), book.sheet(EARNINGS_SHEET)
    blocks = _blocks(earnings)
    header = next((r for r in range(1, stock.max_row + 1) if norm(stock.value(r, 1)) == "company"), None)
    if header is None:
        raise DpWorkbookError(f"{STOCK_SHEET} has no row headed 'Company'")
    cols = {name: next((c.col for c in stock.cells(range(header, header + 1)) if norm(c.value).startswith(name)), None)
            for name in ("year open", "ttm p/e", "forward p/e")}
    if None in (cols["ttm p/e"], cols["forward p/e"]):
        raise DpWorkbookError(f"{STOCK_SHEET} has no 'TTM P/E' and 'Forward P/E' columns")
    average_row = None
    rows: list[DpRow] = []
    warnings: list[str] = []
    blank_quarters: list[str] = []
    seen: dict[str, int] = {}
    for r in range(header + 1, stock.max_row + 1):
        label = stock.value(r, 1)
        if label in (None, ""):
            break
        if norm(label) == "average":
            average_row = r
            break
        name, key = str(label).strip(), company_key(label)
        if key in seen:
            raise DpWorkbookError(f"{STOCK_SHEET}: {name} appears twice (rows {seen[key]} and {r}). Keep one.")
        seen[key] = r
        ttm, ttm_other = _by_name(book, stock, earnings, blocks, r, cols["ttm p/e"], name, key, "TTM P/E", blank_quarters)
        fwd, fwd_other = _by_name(book, stock, earnings, blocks, r, cols["forward p/e"], name, key, "forward P/E", blank_quarters)
        for what, col, ours, other in (("TTM P/E", cols["ttm p/e"], ttm, ttm_other), ("forward P/E", cols["forward p/e"], fwd, fwd_other)):
            cell = stock.cell(r, col)
            if _differs(cell.value, ours):
                cause = (f"; its formula reads {' and '.join(sorted(set(other)))} on {EARNINGS_SHEET}, so the workbook's P/E for "
                         f"{name} uses another company's earnings" if other else "")
                warnings.append(f"{name}: the workbook's {what} ({cell.ref}) shows {_shown(cell.value)} but worked out from "
                                f"{name}'s own earnings it is {_shown(ours)}{cause}. The tool's figure is the one to use.")
        yo = stock.cell(r, cols["year open"]) if cols["year open"] else None
        rows.append(DpRow(name, key, Decimal(repr(yo.value)) if yo is not None and yo.number is not None else None,
                          yo.ref if yo is not None else "", ttm, fwd))
    by_key = {x.key: x for x in rows}
    missing = [k for k in AVERAGE_COMPANIES if k not in by_key]
    if missing:
        raise DpWorkbookError(f"{STOCK_SHEET}: the Average covers {', '.join(AVERAGE_COMPANIES)}, but {', '.join(missing)} "
                              "has no row")
    mean = lambda f: sum((f(by_key[k]) for k in AVERAGE_COMPANIES), Decimal(0)) / len(AVERAGE_COMPANIES)  # noqa: E731 - a negative P/E stays in
    avg_ttm, avg_fwd = mean(lambda x: x.ttm_pe), mean(lambda x: x.forward_pe)
    if average_row is not None:
        for what, col, ours in (("TTM P/E", cols["ttm p/e"], avg_ttm), ("forward P/E", cols["forward p/e"], avg_fwd)):
            cell = stock.cell(average_row, col)
            if _differs(cell.value, ours):
                warnings.append(f"Average: the workbook's {what} average ({cell.ref}) shows {_shown(cell.value)} but the seven companies "
                                f"({', '.join(AVERAGE_COMPANIES)}) give {_shown(ours)} worked out by name. The tool's figure is the one to use.")
    return DpBook(rows, avg_ttm, avg_fwd, _price_date(stock, header), warnings, sorted(set(blank_quarters)))


def year_open_warnings(book: DpBook, fetched: list[dict[str, Any]]) -> list[str]:
    """A line for each tracked company whose Year Open in the workbook is not the first trading day's close in the fetched rows."""
    out = []
    for key in AVERAGE_COMPANIES:
        mine = book.row(key)
        row = next((f for f in fetched if company_key(f.get("company")) == key), None)
        if mine is None or mine.year_open is None:
            continue
        if row is None or row.get("error") or not isinstance(row.get("ytd_open"), (int, float)):
            out.append(f"{mine.company}: Year Open ({mine.year_open_ref}) could not be compared with the first trading day's close, "
                       "which was not fetched.")
        elif round_half_up(mine.year_open, 2) != round_half_up(row["ytd_open"], 2):
            out.append(f"{mine.company}: Year Open is {round_half_up(mine.year_open, 2)} in the workbook ({mine.year_open_ref}) but the "
                       f"close of the first trading day ({row.get('ytd_open_date') or 'date not known'}) is "
                       f"{round_half_up(row['ytd_open'], 2)}. The table prints {round_half_up(row['ytd_open'], 2)}.")
    return out
