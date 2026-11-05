from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, DivisionByZero, InvalidOperation
from typing import Any, Callable, Collection, Mapping, Optional, Sequence
from urllib.parse import urlparse

from cytonn_weekly.checkers.digital_payments import check_figure, parse_number
from cytonn_weekly.common.formatting import round_half_up
from cytonn_weekly.digital_payments.highlights import HIGHLIGHT_COMPANIES
from cytonn_weekly.weekly.workbook import Sheet, Workbook, WorkbookError, norm

STOCK_SHEET = "Stock Performance"
EARNINGS_SHEET = "Earnings"
RESULTS_SHEET = "Financial Results"
NET_INCOME = "net income (usd bn)"

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
class Quarter:
    """An Earnings cell a company's TTM P/E reads that is blank."""

    company: str
    key: str
    label: str      # Q3'26, as the Earnings header prints it
    ref: str        # Earnings!I8


@dataclass(frozen=True)
class Fill:
    """A figure found for a blank quarter: not used in a P/E until the analyst accepts it."""

    quarter: Quarter
    value: Decimal  # USD bn
    source: str     # a sheet and cell, or the page address
    fetched: str    # ISO date
    quoted: str     # the text it was read from


@dataclass(frozen=True)
class DpRow:
    company: str
    key: str
    year_open: Optional[Decimal]
    year_open_ref: str
    ttm_pe: Optional[Decimal]           # None when any quarter it reads is blank: a blank is never zero
    forward_pe: Decimal
    filled_ttm: Optional[Decimal] = None    # the TTM P/E with every blank quarter filled; unusable until they are accepted
    needs: tuple[str, ...] = ()             # the blank cells that were filled
    reason: str = ""                        # why ttm_pe is unavailable

    def as_dict(self) -> dict[str, Any]:
        return {"company": self.company, "key": self.key, "ttm_pe": _text(self.ttm_pe), "filled_ttm": _text(self.filled_ttm),
                "needs": list(self.needs), "reason": self.reason}


@dataclass
class DpBook:
    rows: list[DpRow]
    average_ttm: Optional[Decimal]
    average_forward: Decimal
    price_date: Optional[date] = None
    warnings: list[str] = field(default_factory=list)
    blank: list[Quarter] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    left_out: list[dict[str, str]] = field(default_factory=list)   # the companies the TTM Average leaves out, and why

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


def _number(sheet: Sheet, row: int, col: int, what: str) -> Decimal:
    c = sheet.cell(row, col)
    if c.number is None:
        raise DpWorkbookError(f"{what}: {c.ref} {'is empty' if c.value is None else f'holds {c.value!r}'}")
    return Decimal(repr(c.value))


def _text(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else str(value)


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
             what: str, blanks: Optional[list[Quarter]] = None, fills: Optional[Mapping[str, Decimal]] = None
             ) -> tuple[Optional[Decimal], list[str]]:
    """The cell's formula worked out with each Earnings reference moved to the company's own row in the same table.

    Returns the figure and the other companies whose rows the workbook's own formula reads.  A blank Earnings cell is never
    zero: with ``blanks`` it is added there, and it is read from ``fills`` (by cell address) when a figure was found for it,
    else the figure is None.  Without ``blanks`` a blank cell is refused."""
    formula = book.formula(stock.cell(row, col))
    if formula is None:
        raise DpWorkbookError(f"{STOCK_SHEET}: the {what} for {company} ({stock.cell(row, col).ref}) is a typed number, not a formula, "
                              "so it cannot be worked out from the company's earnings by name.")
    strangers: list[str] = []
    unresolved: list[str] = []

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
        cell = earnings.cell(own, c)
        if cell.value is None and blanks is not None:
            blanks.append(Quarter(company, key, _label(earnings.value(block[0], c)), cell.ref))
            if fills and cell.ref in fills:
                return f"({fills[cell.ref]})"
            unresolved.append(cell.ref)
            return "(1)"
        return f"({_number(earnings, own, c, f'{what} for {company}')})"

    try:
        expr = _REF.sub(sub, formula.lstrip("="))
        return (None if unresolved else _arith(expr)), strangers
    except (SyntaxError, ValueError, InvalidOperation, DivisionByZero) as exc:
        if isinstance(exc, DpWorkbookError):
            raise
        raise DpWorkbookError(f"{STOCK_SHEET}: the {what} for {company} ({stock.cell(row, col).ref}) is a formula the tool cannot work out: {formula}") from None


def _label(value: Any) -> str:
    return str(value).strip().replace("’", "'")


def _qkey(label: str) -> Optional[tuple[int, int]]:
    """Q3'26 -> (26, 3), to order quarters; None for a header that is not a quarter (FY'25)."""
    m = re.fullmatch(r"Q([1-4])'(\d\d)", label)
    return (int(m.group(2)), int(m.group(1))) if m else None


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


def _results(book: Workbook) -> tuple[dict[tuple[str, str], tuple[Decimal, str, str]], dict[str, tuple[int, int]]]:
    """Net income per company and quarter on the Financial Results sheet: ({(company key, Q3'26): (value, cell, row text)}, {company key: latest quarter}).

    A block starts at a row whose first cell reads "Visa (Fiscal Q4)" or "PayPal (Q3)"; the year of each column is read from its header."""
    if RESULTS_SHEET not in book.sheet_names:
        return {}, {}
    sheet = book.sheet(RESULTS_SHEET)
    header = next((r for r in range(1, sheet.max_row + 1) if norm(sheet.value(r, 1)) == "company"), None)
    if header is None:
        return {}, {}
    years = {c.col: int(m.group(1)) % 100 for c in sheet.cells(range(header, header + 1))
             if c.col >= 3 and (m := re.search(r"\b(20\d\d)\b", str(c.value)))}
    found: dict[tuple[str, str], tuple[Decimal, str, str]] = {}
    latest: dict[str, tuple[int, int]] = {}
    key, number, title = None, 0, ""
    for r in range(header + 1, sheet.max_row + 1):
        first = sheet.value(r, 1)
        if first not in (None, ""):
            m = re.fullmatch(r"(.*?)\s*\(([^)]*)\)\s*", str(first))
            q = re.search(r"Q([1-4])", m.group(2)) if m else None
            key, number, title = (company_key(m.group(1)), int(q.group(1)), str(first).strip()) if q else (None, 0, "")
        if key and norm(sheet.value(r, 2)) == NET_INCOME:
            for col, yy in years.items():
                cell = sheet.cell(r, col)
                if cell.number is not None:
                    found[(key, f"Q{number}'{yy:02d}")] = (Decimal(repr(cell.value)), cell.ref, f"{title}: Net income (USD bn) {cell.value}")
                    latest[key] = max(latest.get(key, (yy, number)), (yy, number))
    return found, latest


def _latest(earnings: Sheet, block: tuple[int, list[int]], key: str, fills: Mapping[str, Decimal]) -> Optional[tuple[int, int]]:
    """The company's latest quarter on Earnings that holds a figure (or has one found for it)."""
    header, rows = block
    row = next((r for r in rows if company_key(earnings.value(r, 1)) == key), None)
    best = None
    for c in earnings.cells(range(header, header + 1)):
        q = _qkey(_label(c.value))
        if row and q and (earnings.cell(row, c.col).number is not None or earnings.cell(row, c.col).ref in fills):
            best = max(best or q, q)
    return best


def _quarter(q: tuple[int, int]) -> str:
    return f"Q{q[1]}'{q[0]:02d}"


def pe_table(rows: Sequence[Mapping[str, Any]], accepted: Collection[str] = ()) -> dict[str, Any]:
    """Each company's TTM P/E where it is available, and the Average over the seven that have one.

    ``rows`` are DpRow.as_dict() (or the section's stored copy).  A P/E that needed a blank quarter filled is available only
    when every cell it needed is in ``accepted``; otherwise it is None with its reason, never a figure worked out
    from fewer quarters.  ``left_out`` names the companies the Average leaves out."""
    out, left, values = [], [], []
    for r in rows:
        value = Decimal(r["ttm_pe"]) if r["ttm_pe"] is not None else None
        if value is None and r["filled_ttm"] is not None and set(r["needs"]) <= set(accepted):
            value = Decimal(r["filled_ttm"])
        out.append({"company": r["company"], "key": r["key"], "ttm_pe": value, "reason": "" if value is not None else r["reason"]})
        if r["key"] in AVERAGE_COMPANIES:
            if value is None:
                left.append({"company": r["company"], "reason": r["reason"]})
            else:
                values.append(value)
    return {"rows": out, "average": sum(values, Decimal(0)) / len(values) if values else None, "left_out": left}


def read_dp_workbook(book: Workbook, fills: Sequence[Fill] = (), reasons: Optional[Mapping[str, str]] = None) -> DpBook:
    """Each company's TTM and forward P/E worked out from its own earnings, found by name, never by row.

    A blank quarter a TTM P/E reads is never counted as zero and the sum is never shortened: that P/E is None
    (``blank`` lists the cells), and ``fills`` (a figure found for a blank cell, see ``fill_blanks``) only
    give ``filled_ttm``, which ``pe_table`` releases once the analyst accepts them.  ``reasons`` says, by cell, why none was found.

    Raises DpWorkbookError naming the company when one is missing or listed twice.  ``warnings`` lists every
    cached P/E or Average in the workbook that is not the figure worked out here, every P/E left unavailable
    and every company whose TTM window may be behind the Financial Results sheet."""
    stock, earnings = book.sheet(STOCK_SHEET), book.sheet(EARNINGS_SHEET)
    blocks = _blocks(earnings)
    header = next((r for r in range(1, stock.max_row + 1) if norm(stock.value(r, 1)) == "company"), None)
    if header is None:
        raise DpWorkbookError(f"{STOCK_SHEET} has no row headed 'Company'")
    cols = {name: next((c.col for c in stock.cells(range(header, header + 1)) if norm(c.value).startswith(name)), None)
            for name in ("year open", "ttm p/e", "forward p/e")}
    if None in (cols["ttm p/e"], cols["forward p/e"]):
        raise DpWorkbookError(f"{STOCK_SHEET} has no 'TTM P/E' and 'Forward P/E' columns")
    by_ref = {f.quarter.ref: f for f in fills}
    values = {ref: f.value for ref, f in by_ref.items()}
    reasons = reasons or {}
    _, results_latest = _results(book)
    average_row = None
    rows: list[DpRow] = []
    warnings: list[str] = []
    blank: list[Quarter] = []
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
        miss: list[Quarter] = []
        ttm, ttm_other = _by_name(book, stock, earnings, blocks, r, cols["ttm p/e"], name, key, "TTM P/E", miss, values)
        fwd, fwd_other = _by_name(book, stock, earnings, blocks, r, cols["forward p/e"], name, key, "forward P/E")
        blank.extend(miss)
        ttm_cell = stock.cell(r, cols["ttm p/e"])
        for what, col, ours, other in (("TTM P/E", cols["ttm p/e"], ttm, ttm_other), ("forward P/E", cols["forward p/e"], fwd, fwd_other)):
            cell = stock.cell(r, col)
            if ours is not None and not (miss and what == "TTM P/E") and _differs(cell.value, ours):
                cause = (f"; its formula reads {' and '.join(sorted(set(other)))} on {EARNINGS_SHEET}, so the workbook's P/E for "
                         f"{name} uses another company's earnings" if other else "")
                warnings.append(f"{name}: the workbook's {what} ({cell.ref}) shows {_shown(cell.value)} but worked out from "
                                f"{name}'s own earnings it is {_shown(ours)}{cause}. The tool's figure is the one to use.")
        reason = ""
        if miss:
            parts = []
            for q in miss:
                f = by_ref.get(q.ref)
                parts.append(f"{q.label} ({q.ref}) is blank and USD {f.value} bn was found in {f.source} on {f.fetched}; accept it in the "
                             "review to use it" if f else f"{q.label} ({q.ref}) is blank and {reasons.get(q.ref, 'no other source was tried')}")
            reason = "; ".join(parts)
            warnings.append(f"{name}: TTM P/E unavailable: {reason}. A blank is never counted as zero. The workbook's own TTM P/E "
                            f"({ttm_cell.ref}) shows {_shown(ttm_cell.value)} and adds the blank as 0, so it is not used.")
        latest = _latest(earnings, blocks[0], key, values) if blocks else None
        behind = results_latest.get(key)
        if latest and behind and behind > latest:
            n = (behind[0] * 4 + behind[1]) - (latest[0] * 4 + latest[1])
            warnings.append(f"{name}: the TTM window may be {'one quarter' if n == 1 else f'{n} quarters'} behind: its latest quarter on "
                            f"{EARNINGS_SHEET} is {_quarter(latest)} but {RESULTS_SHEET} has {_quarter(behind)}.")
        yo = stock.cell(r, cols["year open"]) if cols["year open"] else None
        rows.append(DpRow(name, key, Decimal(repr(yo.value)) if yo is not None and yo.number is not None else None,
                          yo.ref if yo is not None else "", None if miss else ttm, fwd, ttm if miss else None,
                          tuple(q.ref for q in miss) if miss and ttm is not None else (), reason))
    by_key = {x.key: x for x in rows}
    missing = [k for k in AVERAGE_COMPANIES if k not in by_key]
    if missing:
        raise DpWorkbookError(f"{STOCK_SHEET}: the Average covers {', '.join(AVERAGE_COMPANIES)}, but {', '.join(missing)} "
                              "has no row")
    table = pe_table([x.as_dict() for x in rows])
    avg_ttm, left_out = table["average"], table["left_out"]
    avg_fwd = sum((by_key[k].forward_pe for k in AVERAGE_COMPANIES), Decimal(0)) / len(AVERAGE_COMPANIES)
    used = [x["company"] for x in table["rows"] if x["ttm_pe"] is not None and x["key"] in AVERAGE_COMPANIES]
    left = f"; left out, because their TTM P/E is unavailable: {', '.join(x['company'] for x in left_out)}" if left_out else ""
    said = False
    if average_row is not None:
        for what, col, ours in (("TTM P/E", cols["ttm p/e"], avg_ttm), ("forward P/E", cols["forward p/e"], avg_fwd)):
            cell = stock.cell(average_row, col)
            if ours is not None and _differs(cell.value, ours):
                ttm_side = what == "TTM P/E"
                who = (f"the {len(used)} companies with an available P/E ({', '.join(used)})" if left_out
                       else f"the seven companies ({', '.join(AVERAGE_COMPANIES)})") if ttm_side else f"the seven companies ({', '.join(AVERAGE_COMPANIES)})"
                warnings.append(f"Average: the workbook's {what} average ({cell.ref}) shows {_shown(cell.value)} but {who} give "
                                f"{_shown(ours)} worked out by name{left if ttm_side else ''}. The tool's figure is the one to use.")
                said = said or ttm_side
    if left_out and not said:
        warnings.append(f"Average: the TTM P/E average covers {len(used)} of the seven companies{left}.")
    return DpBook(rows, avg_ttm, avg_fwd, _price_date(stock, header), warnings, blank, list(fills), left_out)


# ---- finding a figure for a blank quarter -----------------------------------------------------------------------------

Search = Callable[[Quarter, list[str]], list[dict[str, Any]]]
# The company's investor relations site where the highlights already name one; every company's SEC filings are allowed.
_IR_DOMAINS = {company_key(c["name"]): c["ir_domain"] for c in HIGHLIGHT_COMPANIES}
_AMOUNT = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(billion|million|bn|mn)\b", re.IGNORECASE)
_NET_INCOME = re.compile(r"net income[^.$]{0,80}?" + _AMOUNT.pattern, re.IGNORECASE)
_ORDINALS = ("first", "second", "third", "fourth")


def _bn(number: str, unit: str) -> Decimal:
    value = parse_number(number)
    return value if unit.lower() in ("billion", "bn") else value / 1000


def _squash(text: str) -> str:
    return " ".join(text.split())


def _extract(q: Quarter, text: str, claimed: Optional[str]) -> tuple[Decimal, str] | str:
    """(USD bn, the sentence it is quoted from) read from a page by fixed rules, or the reason there is none.

    The page must say it covers the quarter and the year.  A figure the search backend claims must appear verbatim in the
    page text; with none claimed the page's own "net income ... $X billion|million" is used, and only when it gives one figure."""
    text, (yy, n) = _squash(text), _qkey(q.label) or (0, 0)
    if not (re.search(rf"\b({_ORDINALS[n - 1]} quarter|Q{n})\b", text, re.IGNORECASE) and str(2000 + yy) in text):
        return f"the page does not say it covers {q.label}"
    if claimed:
        claimed = _squash(claimed)
        if claimed not in text:
            return f"the figure {claimed!r} is not in the page text"
        m = _AMOUNT.search(claimed)
        hits = [(m, claimed)] if m else []
    else:
        hits = [(m, m.group(0)) for m in _NET_INCOME.finditer(text)]
    if not hits:
        return "no net income figure with a unit was found on the page"
    figures = {_bn(*m.groups()[-2:]) for m, _ in hits}
    if len(figures) > 1:
        return "the page gives more than one net income figure, so none was chosen"
    m, quote = hits[0]
    value = next(iter(figures))
    token = m.group(1)
    decimals = (len(token.split(".")[1]) if "." in token else 0) + (3 if m.group(2).lower() in ("million", "mn") else 0)
    if check_figure("workbook", q.company, f"Net income {q.label}", str(value), _bn(token, m.group(2)), decimals):
        return "the figure did not match its own source text"
    at = text.find(quote)
    start, end = text.rfind(". ", 0, at) + 2 if text.rfind(". ", 0, at) >= 0 else 0, text.find(". ", at + len(quote))
    return value, text[start: end + 1 if end >= 0 else len(text)][:400]


def _from_search(q: Quarter, today: date, search: Optional[Search]) -> tuple[Optional[Fill], str]:
    domains = [d for d in (_IR_DOMAINS.get(q.key), "sec.gov") if d]
    if search is None:
        return None, "no web search is configured"
    try:
        pages = search(q, domains)
    except Exception as exc:    # a search that fails leaves the quarter unavailable; it never stops the draft
        return None, str(exc) if type(exc).__name__ == "SearchKeyError" else f"the web search failed ({type(exc).__name__})"
    tried = []
    for page in pages:
        url, host = str(page.get("url", "")), urlparse(str(page.get("url", ""))).hostname or ""
        if not any(host == d or host.endswith("." + d) for d in domains):
            tried.append(f"{url or 'a result'} is not an investor relations or SEC page")
            continue
        got = _extract(q, str(page.get("text", "")), page.get("figure"))
        if isinstance(got, str):
            tried.append(f"{url}: {got}")
            continue
        return Fill(q, got[0], url, today.isoformat(), got[1]), ""
    return None, "the web search (investor relations and SEC pages) found nothing usable: " + ("; ".join(tried) or "it returned no pages")


def fill_blanks(book: Workbook, today: date, search: Optional[Search] = None) -> tuple[list[Fill], dict[str, str]]:
    """A figure for each blank quarter a TTM P/E reads, in this order: the company's row on the Financial Results sheet,
    then ``search`` (investor relations release or SEC filing, the figure read by fixed rules and found verbatim in the page),
    else nothing.  Returns (the fills, {cell: why nothing was found}).  The model supplies no number."""
    found, _ = _results(book)
    fills: list[Fill] = []
    reasons: dict[str, str] = {}
    for q in read_dp_workbook(book).blank:
        if hit := found.get((q.key, q.label)):
            fills.append(Fill(q, hit[0], hit[1], today.isoformat(), hit[2]))
        else:
            fill, why = _from_search(q, today, search)
            if fill:
                fills.append(fill)
            else:
                reasons[q.ref] = f"{RESULTS_SHEET} has no {q.label} net income for it and {why}"
    return fills, reasons


def exa_search(q: Quarter, domains: list[str]) -> list[dict[str, Any]]:
    """The tool's Exa search, limited to ``domains``."""
    from cytonn_weekly.digital_payments.providers.local_provider import LocalProvider

    results = LocalProvider()._exa_search(f"{q.company} {q.label} results net income", date(2000 + (_qkey(q.label) or (0, 1))[0], 1, 1), domains)
    return [{"url": r.get("url", ""), "title": r.get("title", ""), "text": r.get("text", "")} for r in results]


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
