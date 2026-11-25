from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional, Union

from openpyxl import Workbook as XlBook
from openpyxl.utils import get_column_letter

from cytonn_weekly import paths
from cytonn_weekly.history import reads, store
from cytonn_weekly.weekly import analyst, equities_workbook as eq, fi_workbook as fi, kcb_prices
from cytonn_weekly.weekly.week import Week
from cytonn_weekly.weekly.workbook import Workbook, WorkbookError

NO_POINT = "no confirmed point in the store, left empty"


class Sheet:
    """One sheet of the export: a header row, the rows, and the notes printed under them."""

    def __init__(self, title: str, header: list[str]) -> None:
        self.title, self.header, self.rows, self.notes = title, header, [], []

    def missing(self, key: str, day: Any, subject: str = "") -> None:
        self.notes.append(f"{key}{' ' + subject if subject else ''} {day}: {NO_POINT}")


def _layout(master: Optional[Workbook], sheet_name: str, label: str, found: Optional[str], constants: str) -> str:
    if master is None:
        return f"No {label} workbook is uploaded for this week: columns follow the reader's constants ({constants})."
    if found is not None:
        return f"Columns read from the uploaded {label} workbook, by their labels: {found}."
    if sheet_name not in master.sheet_names:
        return f"The uploaded {label} workbook has no sheet '{sheet_name}': columns follow the reader's constants ({constants})."
    return f"The reader finds this sheet's columns by position, in the uploaded {label} workbook as well: {constants}."


def _points(db_path: Any, week: Week, key: str, subject: Optional[str] = "") -> list[dict[str, Any]]:
    return store.current(db_path, key, subject, since=week.monday.isoformat(), through=week.ending.isoformat())


def _week_point(db_path: Any, week: Week, key: str, subject: str = "") -> Optional[dict[str, Any]]:
    return reads._last_on(_points(db_path, week, key, subject), reads._dates(week))


def _value(key: str, point: Optional[dict[str, Any]]) -> Optional[float]:
    return None if point is None else reads._number(key, point)


def _flows(db_path: Any, week: Week, master: Optional[Workbook], title: str, prefix: str, ytd_col: int, head: str) -> Sheet:
    out = Sheet(title, ["Date", head, "Year to date (USD mn)"])
    days = {p["as_of"]: p for p in _points(db_path, week, f"{prefix}.day")}
    for d in week.trading_days:
        point = days.get(d.isoformat())
        if point is None:
            out.missing(f"{prefix}.day", d.isoformat())
        out.rows.append([d, _value(f"{prefix}.day", point), None])
    total, ytd = _week_point(db_path, week, f"{prefix}.week"), _week_point(db_path, week, f"{prefix}.ytd")
    for key, point in ((f"{prefix}.week", total), (f"{prefix}.ytd", ytd)):
        if point is None:
            out.missing(key, week.ending.isoformat())
    out.rows.append([None, _value(f"{prefix}.week", total), _value(f"{prefix}.ytd", ytd)])
    out.notes += [_layout(master, title, "equities", None, f"A date, B figure, {get_column_letter(ytd_col)} year to date"),
                  "The last row is the week's row: its sum and its running year-to-date figure are formulas in the master and are values here."]
    return out


def _valuation(db_path: Any, week: Week, master: Optional[Workbook]) -> Sheet:
    out = Sheet(eq.VALUATION_SHEET, ["Date", "Market P/E", "Market dividend yield"])
    pe, dy = _week_point(db_path, week, "eq.pe"), _week_point(db_path, week, "eq.dividend_yield")
    for key, point in (("eq.pe", pe), ("eq.dividend_yield", dy)):
        if point is None:
            out.missing(key, week.as_at.isoformat())
    out.rows.append([date.fromisoformat((pe or dy or {"as_of": week.as_at.isoformat()})["as_of"]), _value("eq.pe", pe), _value("eq.dividend_yield", dy)])
    out.notes += [_layout(master, eq.VALUATION_SHEET, "equities", None, "A date, B market P/E, D market dividend yield"),
                  "The dividend yield is a fraction, as the master holds it. The AVERAGE row is not exported."]
    return out


def _universe(price_points: list[dict[str, Any]], week: Week, master: Optional[Workbook]) -> Sheet:
    head = f"Price as at {week.as_at:%d/%m/%Y}"
    out = Sheet(eq.UNIVERSE_SHEET, ["Company", head])
    prices = {}
    for p in price_points:
        if p["as_of"] in reads._dates(week):
            prices[p["subject"]] = p   # oldest first: the latest date wins
    # (the key the store holds, the name shown); an upper-case subject is a KCB ticker for the price blocks, not a company
    names: list[tuple[str, str]] = [(k, k) for k in sorted(prices) if not k.isupper()]
    found = None
    if master is not None and eq.UNIVERSE_SHEET in master.sheet_names:
        try:
            sheet = master.sheet(eq.UNIVERSE_SHEET)
            company = sheet.find("company", rows=range(eq.HEADER_ROW, eq.HEADER_ROW + 1), cols=range(1, 6), what="'Company' header").col
            columns = eq._price_columns(sheet)
            where = columns.get(week.as_at) or (max(columns.values()) + 1 if columns else None)
            names = []
            for r in range(eq.HEADER_ROW + 1, sheet.max_row + 1):
                name = sheet.value(r, company)
                if not isinstance(name, str) or not name.strip():
                    break
                names.append((analyst._key(name), " ".join(name.split())))
            found = (f"'Company' is column {get_column_letter(company)}, in the master's order; the new '{head}' column "
                     + (f"goes in column {get_column_letter(where)}" if where else "has no column yet"))
        except WorkbookError as exc:
            out.notes.append(f"The uploaded equities workbook's sheet could not be read ({exc}): companies are the store's keys, in alphabetical order.")
    for key, name in names:
        point = prices.get(key)
        if point is None:
            out.missing("eq.price", week.as_at.isoformat(), key)
        out.rows.append([name, _value("eq.price", point)])
    out.notes.insert(0, _layout(master, eq.UNIVERSE_SHEET, "equities", found, "Company in A, the price column to the right of the last one"))
    return out


def _kcb_block(price_points: list[dict[str, Any]], week: Week, master: Optional[Workbook], title: str, mapping: dict[str, str], name_col: str) -> Sheet:
    """One price per row of the master's block, from the KCB tickers the store holds for the week's last report date."""
    prices: dict[str, dict[str, Any]] = {}
    for p in price_points:
        if p["subject"].isupper() and p["as_of"] in reads._dates(week):
            prices[p["subject"]] = p   # oldest first: the latest date wins
    day = max((p["as_of"] for p in prices.values()), default=week.as_at.isoformat())
    prices = {t: p for t, p in prices.items() if p["as_of"] == day}
    out = Sheet(title, [name_col, date.fromisoformat(day)])
    rows, found = None, None
    if master is not None and title in master.sheet_names:
        try:
            if title == eq.MARKET_PE_SHEET:
                sheet = master.sheet(title)
                rows = []
                for r in range(2, sheet.max_row + 1):
                    name = sheet.value(r, 1)
                    if not isinstance(name, str) or not name.strip() or name.strip().lower() == "dividend yield":   # the footer row
                        break
                    rows.append(name)
                found = "'Stock' in column A, in the master's order; the prices go in column D, headed by the date"
            else:
                rows = _large_caps(master)
                found = "the tickers in column P, in the master's order; the prices go in a new column headed by the date in row 2"
        except WorkbookError as exc:
            out.notes.append(f"The uploaded equities workbook's sheet could not be read ({exc}): rows follow the tool's map.")
    filled, flags = kcb_prices.fill(rows, {t: _value("eq.price", p) for t, p in prices.items()}, mapping, name_unused=title == eq.MARKET_PE_SHEET)
    out.rows += filled
    if not prices:
        out.missing("eq.price", day, "from a KCB weekly report")
    out.notes += [_layout(master, title, "equities", found, "rows in the tool's map order"), *flags,
                  "Prices in KES from the KCB weekly report the store holds for this week; a blank cell is never guessed."]
    return out


def _large_caps(master: Workbook) -> list[str]:
    sheet = master.sheet(eq.GAINERS_SHEET)
    rows = []
    for r in range(3, sheet.max_row + 1):
        ticker = sheet.value(r, 16)
        if not isinstance(ticker, str) or not ticker.strip():
            break
        rows.append(ticker)
    if not rows:
        raise WorkbookError(f"'{eq.GAINERS_SHEET}' has no tickers in column P from row 3")
    return rows


def _liquidity(db_path: Any, week: Week, master: Optional[Workbook]) -> Sheet:
    out = Sheet(fi.LIQUIDITY_SHEET, ["Date", "Interbank volume (KES mn)", "Interbank rate"])
    vol = {p["as_of"]: p for p in _points(db_path, week, "fi.interbank.volume")}
    rate = {p["as_of"]: p for p in _points(db_path, week, "fi.interbank.rate")}
    for d in week.trading_days:
        for key, got in (("fi.interbank.volume", vol), ("fi.interbank.rate", rate)):
            if d.isoformat() not in got:
                out.missing(key, d.isoformat())
        out.rows.append([d, _value("fi.interbank.volume", vol.get(d.isoformat())), _value("fi.interbank.rate", rate.get(d.isoformat()))])
    out.notes += [_layout(master, fi.LIQUIDITY_SHEET, "fixed income", None, "A date, B volume, C rate"), "The rate is a fraction, as the master holds it."]
    return out


def _eurobond(db_path: Any, week: Week, master: Optional[Workbook]) -> Sheet:
    issues = [(key, " ".join(head)) for key, head, *_ in fi.EUROBOND_ISSUES]
    out = Sheet(fi.EUROBOND_SHEET, ["Date", *(label for _, label in issues)])
    got = {(p["subject"], p["as_of"]): p for p in _points(db_path, week, "fi.eurobond.yield", None)}
    for d in week.trading_days:
        row: list[Any] = [d]
        for key, _ in issues:
            point = got.get((key, d.isoformat()))
            if point is None:
                out.missing("fi.eurobond.yield", d.isoformat(), key)
            row.append(_value("fi.eurobond.yield", point))
        out.rows.append(row)
    out.notes += [_layout(master, fi.EUROBOND_SHEET, "fixed income", None, "a date column and one yield column per issue, in the reader's issue order"),
                  "The yields are fractions, as the master holds them."]
    return out


def _funds(db_path: Any, week: Week, master: Optional[Workbook]) -> Sheet:
    labels, names, found = ["Rank", "Fund Manager", "Effective Annual Rate"], {}, None
    out = Sheet(fi.MMF_SHEET, labels)
    if master is not None and fi.MMF_SHEET in master.sheet_names:
        try:
            sheet = master.sheet(fi.MMF_SHEET)
            title = sheet.find(lambda s: s.startswith("money market fund yield for fund managers as published on"), what="fund table title")
            rank = sheet.find("rank", rows=range(title.row + 1, title.row + 3), what="'Rank' header")
            # the rate heading by its start, as fi_workbook.read_mmf_table reads it ("Effective" alone in the 14 Nov 2026 workbook)
            heads = (("fund manager", "fund manager"), (lambda s: s.startswith("effective"), "effective annual rate"))
            cols = [rank, *(sheet.find(m, rows=range(rank.row, rank.row + 1), what=f"'{h}' header") for m, h in heads)]
            out.header = [str(c.value).strip() for c in cols]
            found = ", ".join(f"{c.value.strip()} in {get_column_letter(c.col)}" for c in cols)
            for r in range(rank.row + 1, sheet.max_row + 1):
                name = sheet.value(r, cols[1].col)
                if not isinstance(name, str) or not name.strip():
                    break
                names[analyst.fund_key(name)] = " ".join(name.split())
        except WorkbookError as exc:
            out.notes.append(f"The uploaded fixed income workbook's fund table could not be read ({exc}): the default headings are used.")
    points = [p for p in _points(db_path, week, "fi.mmf.rate", None) if p["as_of"] in reads._dates(week)]
    if not points:
        out.missing("fi.mmf.rate", week.as_at.isoformat())
    else:
        day = points[-1]["as_of"]
        for n, p in enumerate(sorted((p for p in points if p["as_of"] == day), key=lambda p: -Decimal(p["value"])), 1):
            out.rows.append([n, names.get(p["subject"], p["subject"]), _value("fi.mmf.rate", p)])
        out.notes.append(f"The table published on {day}, best rate first; a fund the master does not name is shown by the store's key.")
    out.notes.insert(0, _layout(master, fi.MMF_SHEET, "fixed income", found, "Rank, Fund Manager, Effective Annual Rate"))
    return out


def build(week: Week, db_path: Any = None, equities: Optional[Workbook] = None, fixed_income: Optional[Workbook] = None) -> XlBook:
    """This week's rows from the store's confirmed points, one sheet per workbook sheet that has weekly rows, as values only.  The masters are only read."""
    price_points = _points(db_path, week, "eq.price", None)   # read once: the Universe and both price blocks share it
    sheets = [
        _flows(db_path, week, equities, eq.TURNOVER_SHEET, "eq.turnover", 6, "Turnover (USD mn)"),
        _flows(db_path, week, equities, eq.FOREIGN_SHEET, "eq.foreign", 5, "Foreign net position (USD mn)"),
        _valuation(db_path, week, equities),
        _universe(price_points, week, equities),
        _kcb_block(price_points, week, equities, eq.MARKET_PE_SHEET, kcb_prices.MARKET_PE, "Stock"),
        _kcb_block(price_points, week, equities, eq.GAINERS_SHEET, kcb_prices.LARGE_CAPS, "Ticker"),
        _liquidity(db_path, week, fixed_income),
        _eurobond(db_path, week, fixed_income),
        _funds(db_path, week, fixed_income),
    ]
    wb = XlBook()
    wb.remove(wb.active)
    for s in sheets:
        ws = wb.create_sheet(s.title)
        ws.append(s.header)
        for row in s.rows:
            ws.append(row)
        ws.append([])
        for note in s.notes:
            ws.append([f"Note: {note}"])
        ws.column_dimensions["A"].width = 28
    return wb


def export_dir(root: Optional[Union[Path, str]] = None) -> Path:
    return Path(root) if root is not None else paths.DATA_DIR / "exports" / "weekly-rows"


def write(week: Week, db_path: Any = None, out_dir: Optional[Union[Path, str]] = None, equities: Optional[Workbook] = None,
          fixed_income: Optional[Workbook] = None) -> Path:
    folder = export_dir(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"Weekly rows, week ending {week.ending.isoformat()}.xlsx"
    build(week, db_path, equities, fixed_income).save(str(path))
    return path
