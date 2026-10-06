"""REIT unit prices from the NSE Unquoted Securities Platform (Ibuka) weekly summary PDF.

NSE publishes one PDF per week, on Fridays, at a predictable address with no
listing page (confirmed 2026-10-02: the 4, 11, 18 and 25 Sept 2026 files exist,
dates in between 404):

    https://www.nse.co.ke/wp-content/uploads/Unquoted-Securities-Platform-Ibuka-Weekly-Summary_DD-MM-YYYY.pdf

so the fetcher constructs the filename and walks back day by day to the latest
one.  The PDF has a text layer; pdfplumber extracts the securities table, but
kerns digits apart ("2 9.65", "8 ,674,903,573"), which common.formatting's
clean_pdf_number repairs.

The report-facing table shows what the report shows: the unit price and the
gain (or loss) from the Kshs 20.0 inception price (see COLUMNS).  Week-on-week
and YTD changes, the previous week's price and market cap are still carried in
the raw rows for reference, but are not drafted into the table: the report
prints none of them.  A summary that cannot be found leaves that change empty
and says why; nothing is interpolated.
"""

from __future__ import annotations

import io
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Callable, Optional

import pdfplumber

from cytonn_weekly.common.formatting import PCT, PRICE, TEXT, clean_pdf_number, pct_change, round_half_up
from cytonn_weekly.common.http import NotFound, http_get_pdf

URL_PATTERN = "https://www.nse.co.ke/wp-content/uploads/Unquoted-Securities-Platform-Ibuka-Weekly-Summary_{:%d-%m-%Y}.pdf"
SOURCE_NAME = "NSE USP (Ibuka) weekly summary"
MAX_LOOKBACK_DAYS = 14

# (row key, name in the report, name as printed in the PDF)
REITS: list[tuple[str, str, str]] = [
    ("ACORN_D", "Acorn D-REIT", "ACORN D-REIT"),
    ("ACORN_I", "Acorn I-REIT", "ACORN I-REIT"),
    ("FAHARI", "ILAM Fahari I-REIT", "ILAM FAHARI-I REIT"),
]

# Content and precision follow Cytonn Weekly #38.2026 (published 2026-09-27, still the
# newest issue on 2026-10-02), whose REITs paragraph reads: "Acorn D-REIT and I-REIT traded
# at Kshs 29.7 and Kshs 24.4 per unit, respectively ... The performance represented a 48.5%
# and 22.0% gain for the D-REIT and I-REIT, respectively, from the Kshs 20.0 inception
# price", and "ILAM Fahari I-REIT traded at Kshs 13.8 per share ... representing a 31.0 %
# loss from the Kshs 20.0 inception price".
#   price, 1 dp: Ibuka's 29.65 and 24.44 print as 29.7 and 24.4 (round-half-up, not half-to-even).
#   gain, 1 dp, from the PRINTED price: the report used the 18 Sept 2026 summary, whose raw
#     prices were 29.65 and 24.44 (checked against NSE's PDF).  From those, the gains would be
#     48.3% and 22.2%; the report's 48.5% and 22.0% are (29.7 - 20) / 20 and (24.4 - 20) / 20.
#     So the gain is computed from the price rounded to its display precision, then rounded.
INCEPTION_PRICE = Decimal("20.0")
PRICE_DECIMALS = 1
COLUMNS = [
    {"key": "name", "label": "REIT", "fmt": TEXT},
    {"key": "price", "label": "Unit price (KES)", "fmt": PRICE, "decimals": PRICE_DECIMALS},
    {"key": "inception_gain_pct", "label": "Gain from KES 20.0 inception price", "fmt": PCT, "decimals": 1},
]

Getter = Callable[[str], bytes]


def ibuka_url(d: date) -> str:
    return URL_PATTERN.format(d)


def inception_gain_pct(price: Optional[float]) -> Optional[float]:
    """% gain (negative: loss) from the Kshs 20.0 inception price, on the price as printed (see COLUMNS)."""
    if price is None:
        return None
    return float((round_half_up(price, PRICE_DECIMALS) - INCEPTION_PRICE) / INCEPTION_PRICE * 100)


def parse_tables(tables: list[list[list[Optional[str]]]]) -> dict[str, dict[str, Optional[float]]]:
    """{PDF security name: {"price", "market_cap"}} for every REIT row in pdfplumber's tables."""
    wanted = {pdf_name for _, _, pdf_name in REITS}
    found: dict[str, dict[str, Optional[float]]] = {}
    for table in tables:
        for row in table:
            if not row or not row[0]:
                continue
            name = " ".join(str(row[0]).split()).upper()
            if name in wanted and len(row) >= 9:
                # Security | Segment | High | Low | Closing unit price | Volume | Turnover | Issued units | Market cap
                found[name] = {"price": clean_pdf_number(row[4]), "market_cap": clean_pdf_number(row[8])}
    return found


def parse_as_of(text: str) -> Optional[str]:
    m = re.search(r"WEEKLY SUMMARY AS AT (\d{2})/(\d{2})/(\d{4})", text or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def parse_pdf(pdf_bytes: bytes) -> dict[str, Any]:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        tables = [t for p in pdf.pages for t in p.extract_tables()]
        text = pdf.pages[0].extract_text() if pdf.pages else ""
    return {"as_of": parse_as_of(text), "reits": parse_tables(tables)}


def latest_summary(on_or_before: date, get: Getter = http_get_pdf,
                   lookback: int = MAX_LOOKBACK_DAYS) -> Optional[tuple[date, str, dict[str, Any]]]:
    """(date, url, parsed) of the newest weekly summary on or before the date, or None within ``lookback`` days."""
    for k in range(lookback + 1):
        d = on_or_before - timedelta(days=k)
        url = ibuka_url(d)
        try:
            body = get(url)
        except NotFound:
            continue
        return d, url, parse_pdf(body)
    return None


def fetch_reits(today: Optional[date] = None, get: Getter = http_get_pdf) -> dict[str, Any]:
    """REIT rows for the week ending on or before ``today``.

    Returns {"as_of", "source_url", "prior_url", "ytd_url", "rows", "warnings"}.
    Raises LookupError if no summary at all is found for the current week.
    """
    today = today or date.today()
    current = latest_summary(today, get)
    if current is None:
        raise LookupError(f"no Ibuka weekly summary found in the {MAX_LOOKBACK_DAYS} days to {today.isoformat()}")
    cur_date, cur_url, cur = current
    warnings: list[str] = []
    prior = latest_summary(cur_date - timedelta(days=7), get)
    base = latest_summary(date(cur_date.year - 1, 12, 31), get)
    if prior is None:
        warnings.append("previous week's Ibuka summary not found; w/w change (not in the report table) left empty")
    if base is None:
        warnings.append(f"no Ibuka summary found for the end of {cur_date.year - 1}; "
                        "YTD change (not in the report table) left empty")

    rows = []
    for key, name, pdf_name in REITS:
        now = cur["reits"].get(pdf_name)
        row: dict[str, Any] = {"reit": key, "name": name, "price": None, "inception_gain_pct": None,
                               "prior_price": None, "ytd_base_price": None, "wow_pct": None, "ytd_pct": None,
                               "market_cap_kes_bn": None, "error": None}
        if not now or now["price"] is None:
            row["error"] = f"{pdf_name} not found in the {cur_date.isoformat()} summary"
            rows.append(row)
            continue
        row["price"] = now["price"]
        row["inception_gain_pct"] = inception_gain_pct(now["price"])
        if now["market_cap"] is not None:
            row["market_cap_kes_bn"] = now["market_cap"] / 1e9
        if prior:
            row["prior_price"] = (prior[2]["reits"].get(pdf_name) or {}).get("price")
            row["wow_pct"] = pct_change(row["price"], row["prior_price"])
        if base:
            row["ytd_base_price"] = (base[2]["reits"].get(pdf_name) or {}).get("price")
            row["ytd_pct"] = pct_change(row["price"], row["ytd_base_price"])
        rows.append(row)
    return {
        "as_of": cur["as_of"] or cur_date.isoformat(), "source_url": cur_url,
        "prior_url": prior[1] if prior else None, "ytd_url": base[1] if base else None,
        "rows": rows, "warnings": warnings,
    }
