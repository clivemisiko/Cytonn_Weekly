"""Display formatting in the real report's string conventions, for any section's tables.

The conventions are the ones confirmed for the Digital Payments table (see
digital_payments/fetcher.py format_table_rows): no currency symbol, no "+" on a
positive figure, accounting-style parentheses for a negative one ("(4.0%)"), and
"-" for a figure that is not available.  Rounding is round-half-up on the
value's shortest string form, never Python's round(), so it agrees with the
checking layer at exactly the boundary values real data hits.

Each table column declares its own ``fmt`` and ``decimals``; the checker reads
the same column definition, so display and check precision cannot drift.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

BLANK = "-"

# fmt values a column may declare
TEXT = "text"        # shown as given
NUMBER = "number"    # 1,234.5
PRICE = "price"      # 29.65 (no thousands separator, as the DP table prints prices)
PCT = "pct"          # 6.3% / (4.0%)
MULTIPLE = "multiple"  # 15.5x


def round_half_up(value: Any, decimals: int) -> Decimal:
    d = value if isinstance(value, Decimal) else Decimal(repr(value) if isinstance(value, float) else str(value))
    return d.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def fmt_value(value: Any, fmt: str, decimals: int = 1) -> str:
    """One figure as the report prints it; "-" when there is no value."""
    if fmt == TEXT:
        return BLANK if value in (None, "") else str(value)
    if value is None or not is_number(value):
        return BLANK
    d = round_half_up(value, decimals)
    if d == 0:
        d = abs(d)  # never print "(0.0%)" or "-0.0"
    if fmt == PRICE:
        body = f"{abs(d):.{decimals}f}"
    elif fmt == NUMBER:
        body = f"{abs(d):,.{decimals}f}"
    elif fmt == PCT:
        body = f"{abs(d):.{decimals}f}%"
    elif fmt == MULTIPLE:
        body = f"{abs(d):.{decimals}f}x"
    else:
        raise ValueError(f"unknown fmt {fmt!r}")
    return f"({body})" if d < 0 else body


def format_rows(rows: list[dict[str, Any]], columns: list[dict[str, Any]], keep: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """Raw source rows -> display rows, one string per declared column (same keys).

    ``keep`` names fields copied through unformatted, e.g. a table's row key when
    it is not itself a displayed column.
    """
    return [
        {**{k: r.get(k) for k in keep},
         **{c["key"]: fmt_value(r.get(c["key"]), c.get("fmt", TEXT), c.get("decimals", 1)) for c in columns}}
        for r in rows
    ]


def pct_change(new: Optional[float], old: Optional[float]) -> Optional[float]:
    if new is None or old is None or old == 0:
        return None
    return (new - old) / old * 100


def clean_pdf_number(text: Optional[str]) -> Optional[float]:
    """A figure as pdfplumber extracts it from NSE / CBK PDFs -> float, or None for "-"/blank.

    Those PDFs kern digits apart, so "29.65" comes out as "2 9.65" and "8,674,903,573"
    as "8 ,674,903,573".  Spaces and thousands commas are removed, a trailing "%" is
    dropped.  Anything still unreadable raises ValueError rather than guessing.
    """
    if text is None:
        return None
    s = str(text).replace(" ", "").replace(",", "").replace("\n", "").strip()
    if s.endswith("%"):
        s = s[:-1]
    if s in ("", "-", "–", "—"):
        return None
    return float(Decimal(s))
