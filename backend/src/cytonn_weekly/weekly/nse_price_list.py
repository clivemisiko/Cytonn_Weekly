"""The NSE Daily Equity Price List: fetched by date and read by OCR (it is a scanned image).

``https://www.nse.co.ke/wp-content/uploads/DD-MON-YY.pdf`` (08-OCT-26.pdf), listed on
nse.co.ke under Data Services > Market Statistics > Equity Statistics.  The PDF has no text
layer (checked 2026-10-09: three pages, each one 2480 x 3507 image, 300 dpi).

What is read is the index box under the price table, the only public source of the NSE 10
and the Banking Sector index:

    NSE ALL SHARE INDEX (NASI) - 01st Jan 2008 = 100      Market Capitalization in Kes. Billion
    Down 0.32 points to close at 245.34                   Today        Previous
    NSE 20-SHARE INDEX - (1966 = 100 )                    4,117.371    4,122.718
    Up 10.23 points to close at 4323.26
    ...

OCR engine: RapidOCR on ONNX Runtime (``rapidocr-onnxruntime``).  It installs with pip alone
on Windows and in the Linux image (its models ship inside the wheel; no system binary, no
download at run time), where Tesseract needs a separate program installed and EasyOCR pulls
in PyTorch and fetches its models on first use.

OCR is not trusted on its own.  A whole-page pass finds the box; the box is then cut out
and read twice, at the scan's own size and enlarged, and a figure is kept only when both
readings agree (on the 8 October 2026 list a whole-page reading turned the equity turnover
429,514,861 into 420,514,861; the two readings of the cut-out box both give 429,514,861).
A figure the readings disagree on is left out and named in ``problems``.  The section
builders then require an OCR'd figure to agree with a second source before it is clean.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Optional

from cytonn_weekly.common.http import NotFound, http_get_pdf

SOURCE_NAME = "NSE Daily Equity Price List (OCR)"
BASE = "https://www.nse.co.ke/wp-content/uploads"
DPI = 300
SCALES = (1.0, 2.0)

# One OCR result: (left, top, right, bottom, text).
Word = tuple[float, float, float, float, str]
# An engine reads an image (numpy BGR array) into words.
Engine = Callable[[Any], list[Word]]

INDEX_KEYS = ("nasi", "nse_20", "nse_25", "nse_10", "banking")
STAT_KEYS = ("market_cap_bn", "shares_traded", "equity_turnover")
INDEX_NAMES = {"nasi": "NASI", "nse_20": "NSE 20", "nse_25": "NSE 25", "nse_10": "NSE 10", "banking": "Banking Sector index"}

# Matched on a word's compact form (see ``_compact``): OCR drops and adds spaces freely
# ("NSEALLSHAREINDEX(NASI)-01stJan2008=100") and misreads letters ("to closo at"), so only the
# digits and the few letters around them are relied on.
_HEADERS = {
    "nasi": re.compile(r"ALLSHARE"),
    "nse_20": re.compile(r"(?<!\d)20-?SHARE"),
    "nse_25": re.compile(r"(?<!\d)25-?SHARE"),
    "nse_10": re.compile(r"(?<!\d)10-?SHARE"),
    "banking": re.compile(r"BANKINGSECTOR"),
}
_CLOSE = re.compile(r"AT(\d[\d,]*\.\d+)$")
_FIGURE = re.compile(r"^\d[\d,.]*\d$")
_HEADER_DATE = re.compile(r"([A-Z][a-z]+)\s*(\d{1,2})\s*,\s*(\d{4})")


class PriceListError(ValueError):
    pass


def price_list_url(day: date) -> str:
    return f"{BASE}/{day.strftime('%d-%b-%y').upper()}.pdf"


def fetch_price_list(day: date, get: Callable[[str], bytes] = http_get_pdf) -> bytes:
    """The day's price list.  LookupError if NSE has none for that date (a holiday, or not yet posted)."""
    try:
        return get(price_list_url(day))
    except NotFound:
        raise LookupError(f"NSE has no daily price list for {day.isoformat()} ({price_list_url(day)})")


@dataclass
class IndexBox:
    list_date: Optional[date]                       # the date printed at the top of the list
    values: dict[str, float] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"list_date": self.list_date.isoformat() if self.list_date else None, "values": self.values,
                "problems": self.problems}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IndexBox":
        return cls(date.fromisoformat(data["list_date"]) if data.get("list_date") else None,
                   dict(data.get("values") or {}), list(data.get("problems") or []))


# ---------------------------------------------------------------------------
# Reading one set of OCR words
# ---------------------------------------------------------------------------

def _compact(text: str) -> str:
    """Upper case, width-normalized (OCR returns full-width brackets), with every space removed."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).upper()


def _is_header(word: Word, pattern: "re.Pattern[str]") -> bool:
    text = _compact(word[4])
    return bool(pattern.search(text)) and "INDEX" in text


def _rows(words: list[Word]) -> list[Word]:
    return sorted(words, key=lambda w: (w[1], w[0]))


def read_indices(words: list[Word]) -> dict[str, float]:
    """Each index's close: the line directly under its heading, "... to close at 245.34"."""
    out: dict[str, float] = {}
    rows = _rows(words)
    for key, pattern in _HEADERS.items():
        head = next((w for w in rows if _is_header(w, pattern)), None)
        if head is None:
            continue
        height = max(head[3] - head[1], 1.0)
        below = [w for w in rows if head[3] - height * 0.5 <= w[1] <= head[3] + height * 2.5
                 and abs(w[0] - head[0]) <= height * 3 and w is not head]
        for w in below:
            m = _CLOSE.search(_compact(w[4]))
            if m:
                out[key] = float(m.group(1).replace(",", ""))
                break
    return out


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def read_stats(words: list[Word]) -> dict[str, float]:
    """Market capitalisation, shares traded and equity turnover: the "Today" figure under each label."""
    rows = _rows(words)
    labels = {
        "market_cap_bn": lambda t: "CAPITALI" in t,
        "shares_traded": lambda t: "OFSHAR" in t,
        "equity_turnover": lambda t: "EQUITYTURN" in t,
    }
    out: dict[str, float] = {}
    for key, is_label in labels.items():
        label = next((w for w in rows if is_label(_compact(w[4]))), None)
        if label is None:
            continue
        height = max(label[3] - label[1], 1.0)
        figures = [w for w in rows if w[1] > label[1] + height * 0.5 and w[1] < label[3] + height * 5
                   and w[0] >= label[0] - height * 2 and _FIGURE.match(w[4].replace(" ", ""))]
        if len(figures) < 2:
            continue
        top = min(f[1] for f in figures)
        pair = sorted((f for f in figures if abs(f[1] - top) <= height * 0.6), key=lambda f: f[0])
        if len(pair) != 2:
            continue
        today = pair[0][4].replace(" ", "")   # "Today" is printed left of "Previous"
        if key == "market_cap_bn":
            m = re.fullmatch(r"(\d{1,3})[,.](\d{3})[,.](\d{3})", today)   # 4,117.371
            if m:
                out[key] = float(f"{m.group(1)}{m.group(2)}.{m.group(3)}")
        elif re.fullmatch(r"\d{1,3}(?:[,.]\d{3})+", today):
            out[key] = float(_digits(today))
    return out


def read_list_date(words: list[Word]) -> Optional[date]:
    for w in _rows(words):
        m = _HEADER_DATE.search(unicodedata.normalize("NFKC", w[4]))
        if m:
            try:
                return datetime.strptime(f"{m.group(2)} {m.group(1)} {m.group(3)}", "%d %B %Y").date()
            except ValueError:
                continue
    return None


def _box_bounds(words: list[Word], width: int, height: int) -> Optional[tuple[int, int, int, int]]:
    heads = [w for w in words if any(_is_header(w, p) for p in _HEADERS.values())]
    if not heads:
        return None
    line = max(max(h[3] - h[1] for h in heads), 1.0)
    top = max(int(min(h[1] for h in heads) - line * 2), 0)
    bottom = min(int(max(h[3] for h in heads) + line * 6), height)
    return 0, top, width, bottom


# ---------------------------------------------------------------------------
# The engine and the two readings
# ---------------------------------------------------------------------------

_ENGINE: Optional[Engine] = None


def rapidocr_engine() -> Engine:
    """RapidOCR, created once.  ImportError (naming the package) if it is not installed."""
    global _ENGINE
    if _ENGINE is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise ImportError("reading the NSE price list needs the 'rapidocr-onnxruntime' package "
                              "(pip install -e . in backend/ installs it)") from exc
        ocr = RapidOCR()

        def run(image: Any) -> list[Word]:
            result, _ = ocr(image)
            out: list[Word] = []
            for box, text, _score in result or []:
                xs, ys = [p[0] for p in box], [p[1] for p in box]
                out.append((min(xs), min(ys), max(xs), max(ys), text))
            return out

        _ENGINE = run
    return _ENGINE


def _page_images(pdf_bytes: bytes) -> list[Any]:
    import numpy as np
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return [np.array(page.to_image(resolution=DPI).original.convert("RGB"))[:, :, ::-1].copy() for page in pdf.pages]


def _enlarge(image: Any, scale: float) -> Any:
    if scale == 1.0:
        return image
    import cv2

    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)


def read_index_box(pdf_bytes: bytes, engine: Optional[Engine] = None,
                   render: Callable[[bytes], list[Any]] = _page_images) -> IndexBox:
    """The price list's date and index box, each figure kept only if two readings of the box agree."""
    engine = engine or rapidocr_engine()
    pages = render(pdf_bytes)
    if not pages:
        raise PriceListError("the price list PDF has no pages")
    first = pages[0]
    box = IndexBox(read_list_date(engine(first[: max(first.shape[0] // 6, 1)])))
    if box.list_date is None:
        box.problems.append("the date at the top of the list could not be read")
    for page in pages:
        words = engine(page)
        bounds = _box_bounds(words, page.shape[1], page.shape[0])
        if bounds is None:
            continue
        left, top, right, bottom = bounds
        crop = page[top:bottom, left:right]
        readings = []
        for scale in SCALES:
            read = engine(_enlarge(crop, scale))
            readings.append({**read_indices(read), **read_stats(read)})
        for key in (*INDEX_KEYS, *STAT_KEYS):
            seen = [r.get(key) for r in readings]
            if all(v is None for v in seen):
                box.problems.append(f"{key}: not found in the index box")
            elif any(v != seen[0] for v in seen):
                box.problems.append(f"{key}: two OCR readings disagree ({', '.join(str(v) for v in seen)}); left out")
            else:
                box.values[key] = seen[0]
        return box
    raise PriceListError("no index box (NSE ALL SHARE INDEX ...) was found on any page of the price list")


def read_index_box_cached(pdf_bytes: bytes, cache_dir: Optional[Path], engine: Optional[Engine] = None) -> IndexBox:
    """``read_index_box``, remembered per PDF (by its SHA-256): a reading takes about half a minute."""
    if cache_dir is None:
        return read_index_box(pdf_bytes, engine)
    path = Path(cache_dir) / f"{hashlib.sha256(pdf_bytes).hexdigest()}.json"
    if path.is_file():
        return IndexBox.from_dict(json.loads(path.read_text(encoding="utf-8")))
    box = read_index_box(pdf_bytes, engine)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(box.to_dict(), indent=1), encoding="utf-8")
    return box
