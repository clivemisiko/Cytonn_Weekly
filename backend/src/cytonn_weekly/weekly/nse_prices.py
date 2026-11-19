from __future__ import annotations

import json
import re
import statistics
from pathlib import Path
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Optional

from cytonn_weekly.common import atomic
from cytonn_weekly.weekly import nse_price_list as pl
from cytonn_weekly.weekly.inputs import InputError, inputs_root
from cytonn_weekly.weekly.nse_price_list import PriceListError, Word
from cytonn_weekly.weekly.week import Week, day_text

COLUMNS = ("high", "low", "vwap", "previous", "volume")
_HEAD = {"HIGH": "high", "LOW": "low", "VWAP": "vwap", "PREVIOUS": "previous", "VOLUME": "volume", "ISIN": "isin", "TRADING": "status"}
_NUMBER = re.compile(r"^\d[\d,.]*$")


def number(text: str) -> Optional[str]:
    """A printed figure as plain digits: "1,355.00" -> "1355.00"; a decimal point read as a comma ("7,30") -> "7.30"."""
    t = text.strip().rstrip(".")
    if not _NUMBER.match(t):
        return None
    if "." not in t and re.search(r",\d{2}$", t):
        t = t[:-3] + "." + t[-2:]
    t = t.replace(",", "")
    try:
        return t if t.count(".") <= 1 and Decimal(t) >= 0 else None
    except InvalidOperation:
        return None


BAD = "?"


def shaped(col: str, value: Optional[str]) -> Optional[str]:
    """A price prints with two decimals and a volume with none; any other shape is BAD (both readings can drop the same point)."""
    if value is None:
        return None
    ok = re.fullmatch(r"\d+", value) if col == "volume" else re.fullmatch(r"\d+\.\d{2}", value)
    return value if ok else BAD


def headers(words: list[Word]) -> Optional[dict[str, float]]:
    """The centre x of each column heading on the page, or None when the page has no heading row (a continuation page)."""
    found: dict[str, float] = {}
    for w in words:
        key = _HEAD.get(re.sub(r"\s+", "", w[4]).upper())
        if key and key not in found:
            found[key] = (w[0] + w[2]) / 2
    return found if set(_HEAD.values()) <= set(found) else None


def _lines(words: list[Word]) -> list[list[Word]]:
    if not words:
        return []
    tol = 0.5 * statistics.median(w[3] - w[1] for w in words)
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w[1] + w[3]) / 2):
        cy = (w[1] + w[3]) / 2
        if lines and cy - sum((v[1] + v[3]) / 2 for v in lines[-1]) / len(lines[-1]) <= tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    return lines


def rows_of(words: list[Word], cols: dict[str, float]) -> list[dict[str, Any]]:
    """One reading's security rows: the name as printed, ISIN, status mark and the five figures (None when blank)."""
    gap = min(abs(cols[a] - cols[b]) for a, b in zip(COLUMNS, COLUMNS[1:]))
    out = []
    for line in _lines(words):
        line.sort(key=lambda w: w[0])
        row: dict[str, Any] = {"y": statistics.mean((w[1] + w[3]) / 2 for w in line), "name": "", "isin": "", "status": "",
                               **dict.fromkeys(COLUMNS)}
        name = []
        for w in line:
            cx, text = (w[0] + w[2]) / 2, w[4].strip()
            if w[2] < cols["isin"] - gap / 2:
                name.append(text)
            elif abs(cx - cols["isin"]) < gap / 2 and re.fullmatch(r"[A-Z]{2}[0-9A-Z]{8,11}", re.sub(r"[^0-9A-Z]", "", text.upper())):
                row["isin"] = re.sub(r"[^0-9A-Z]", "", text.upper())
            elif abs(cx - cols["status"]) < gap / 2 and not number(text):
                row["status"] = text.lower()
            else:
                col = min(COLUMNS, key=lambda c: abs(cx - cols[c]))
                if abs(cx - cols[col]) < gap / 2 and number(text) is not None:
                    row[col] = shaped(col, number(text))
        # the 52-week high and low print left of the name and the low often merges into it: drop the leading figures
        row["name"] = re.sub(r"^(?:[\d.,]+\s*)+", "", " ".join(t for t in name if number(t) is None)).strip()
        if row["name"] and row["isin"]:   # a security row; a sector heading, the index box and the notes have no ISIN
            out.append(row)
    return out


def isin_key(isin: str) -> str:
    """An ISIN as compared across readings: the letters OCR takes for a zero (O, C, D, Q, U) read as 0 after the country code."""
    return isin[:2] + re.sub(r"[OCDQU]", "0", isin[2:]) if isin else ""


def pair(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows of two readings of one page, side by side; a cell is kept only when both read it the same (blank counts)."""
    gaps = [y2["y"] - y1["y"] for y1, y2 in zip(a, a[1:])]
    tol = 0.4 * statistics.median(gaps) if gaps else 6.0
    rows, i, j = [], 0, 0
    while i < len(a) or j < len(b):
        x = a[i] if i < len(a) else None
        y = b[j] if j < len(b) else None
        if x and y and abs(x["y"] - y["y"]) <= tol:
            row = {"names": [x["name"], y["name"]], "isin": x["isin"] if isin_key(x["isin"]) == isin_key(y["isin"]) else "",
                   "isins": [isin_key(x["isin"]), isin_key(y["isin"])], "status": x["status"] if x["status"] == y["status"] else "",
                   "once": False}
            row.update({c: x[c] if x[c] == y[c] else None for c in COLUMNS})
            row["unresolved"] = [c for c in COLUMNS if x[c] != y[c]]
            i, j = i + 1, j + 1
        else:
            lone, i, j = (x, i + 1, j) if x and (not y or x["y"] < y["y"]) else (y, i, j + 1)
            row = {"names": [lone["name"]], "isin": "", "isins": [isin_key(lone["isin"])], "status": "", "once": True,
                   **dict.fromkeys(COLUMNS), "unresolved": list(COLUMNS)}
        rows.append(row)
    return rows


def bands(words: list[Word], height: int, size: int = 10) -> list[tuple[int, int]]:
    """The page cut into bands of ``size`` lines, each cut halfway between two lines so no word is split."""
    centres = [statistics.mean((w[1] + w[3]) / 2 for w in line) for line in _lines(words)]
    cuts = [0] + [int((centres[k - 1] + centres[k]) / 2) for k in range(size, len(centres), size)] + [height]
    return [(a, b) for a, b in zip(cuts, cuts[1:]) if b > a]


def read_prices(pdf_bytes: bytes, week: Week, engine: Optional[pl.Engine] = None,
                render: Callable[[bytes], list[Any]] = pl._page_images) -> list[dict[str, Any]]:
    """Every security row of the week's price list, each band of about ten rows read twice (at the scan's size and doubled).

    A whole page is only read once, to find the headings and the rows' heights: read whole, the engine shrinks the page and
    some figures come out as noise in both readings; a band of rows, cut into its name part and its figures part, reads clean.
    PriceListError, saying why, when the list is not dated the week's last trading day, or no heading row is found.
    """
    engine = engine or pl.rapidocr_engine()
    pages = render(pdf_bytes)
    if not pages:
        raise PriceListError("the price list PDF has no pages")
    dated = pl.read_list_date(engine(pages[0][: max(pages[0].shape[0] // 6, 1)]))
    if dated != week.as_at:
        raise PriceListError(f"the price list is dated {day_text(dated) if dated else 'a day that could not be read'}; "
                             f"the report's day is {day_text(week.as_at)}")
    cols, rows = None, []
    for page in pages:
        whole = engine(page)
        cols = headers(whole) or cols   # a continuation page has no heading row: the first page's columns hold
        if cols is None:
            raise PriceListError("the column headings (ISIN, HIGH, LOW, VWAP, PREVIOUS, VOLUME) were not found on the first page")
        split = int(cols["isin"] - (cols["status"] - cols["isin"]) / 2)
        readings = []
        for scale in pl.SCALES:
            words = []
            for top, bottom in bands(whole, page.shape[0]):
                for left, right in ((0, split), (split, page.shape[1])):
                    words += [(left + x0 / scale, top + y0 / scale, left + x1 / scale, top + y1 / scale, t)
                              for x0, y0, x1, y1, t in engine(pl._enlarge(page[top:bottom, left:right], scale))]
            readings.append(words)
        rows += pair(rows_of(readings[0], cols), rows_of(readings[1], cols))
    return [{"id": n, **r} for n, r in enumerate(rows)]


def state(row: dict[str, Any]) -> str:
    """traded (a VWAP and a volume), untraded (no volume, high or low; the VWAP column then repeats the previous price), or unread."""
    if row["once"] or "vwap" in row["unresolved"] or "previous" in row["unresolved"] or "volume" in row["unresolved"] or row["vwap"] in (None, BAD):
        return "unread"
    if row["volume"]:
        return "traded"
    return "untraded" if row["high"] is None and row["low"] is None and "high" not in row["unresolved"] and "low" not in row["unresolved"] else "unread"




# ---------------------------------------------------------------------------
# The 62 stocks of the market dividend yield, each mapped to one security line of the list
# ---------------------------------------------------------------------------

STATES = ("traded", "untraded", "unmatched", "unread")
MAX_STOCKS = 200


def compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def is_isin(key: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{2}[0-9A-Z]{10}", key))   # Umeme is listed with a Ugandan ISIN


def _settings_file(root: Optional[Path]) -> Path:
    return inputs_root(root).parent / "settings" / "stock_map.json"


def read_map(root: Optional[Path] = None) -> dict[str, Any]:
    """{"stocks": the workbook's stock names in order, "keys": stock -> an ISIN or a piece of the printed name}."""
    try:
        data = json.loads(_settings_file(root).read_text(encoding="utf-8"))
        return {"stocks": list(data["stocks"]), "keys": dict(data["keys"])}
    except (OSError, ValueError, KeyError, TypeError):
        return {"stocks": [], "keys": {}}


def parse_map(text: str) -> dict[str, Any]:
    """The editor's text, one stock a line, "name" or "name | key".  InputError listing every bad line."""
    stocks, keys, errors = [], {}, []
    for n, line in enumerate(text.splitlines(), 1):
        name, _, key = (part.strip() for part in line.partition("|"))
        name = " ".join(name.split())
        if not name:
            continue
        if compact(name) in {compact(s) for s in stocks}:
            errors.append(f"line {n}: {name} is listed twice")
        elif len(name) > 120 or (key and not (is_isin(key.upper()) or len(compact(key)) >= 3)):
            errors.append(f"line {n}: the key must be an ISIN (2 letters and 10 letters or digits) or at least 3 letters of the printed name")
        else:
            stocks.append(name)
            if key:
                keys[name] = key.upper() if is_isin(key.upper()) else key
    if len(stocks) > MAX_STOCKS:
        errors.append(f"up to {MAX_STOCKS} stocks")
    if errors:
        raise InputError("\n".join(errors[:12]))
    return {"stocks": stocks, "keys": keys}


@atomic.locked
def write_map(text: str, root: Optional[Path] = None) -> dict[str, Any]:
    data = parse_map(text)
    atomic.write_atomic(_settings_file(root), json.dumps(data, indent=1))
    return data


def map_text(data: dict[str, Any]) -> str:
    return "\n".join(f"{s} | {data['keys'][s]}" if s in data["keys"] else s for s in data["stocks"])


def candidates(stock: str, key: Optional[str], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows a stock's key finds: by ISIN (as both readings compare it), else by a piece of the printed name (either reading);
    with no key, by the stock's first word."""
    if key and is_isin(key):
        return [r for r in rows if isin_key(key) in r["isins"]]
    piece = compact(key) if key else compact(stock.split()[0])
    return [r for r in rows if any(piece in compact(n) for n in r["names"])]


def classify(data: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each stock: traded, untraded, unread (its one row has a cell the readings disagree on), or unmatched (no row, or several)."""
    out = []
    for stock in data["stocks"]:
        found = candidates(stock, data["keys"].get(stock), rows)
        row = found[0] if len(found) == 1 else None
        out.append({"stock": stock, "key": data["keys"].get(stock), "found": len(found), "row": row["id"] if row else None,
                    "state": state(row) if row else "unmatched",
                    "vwap": row["vwap"] if row else None, "previous": row["previous"] if row else None})
    return out
