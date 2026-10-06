"""Digital Payments share-price fetcher (Yahoo Finance via yfinance).

For each tracked company, pulls the latest close, the close 7 calendar days
before it, and the close of this calendar year's first trading day (the report's
"Year Open"), then derives w/w and YTD percentage change from them.  No checking or drafting logic lives here.

Prices are unadjusted (auto_adjust=False) so they match the quoted price
rather than a dividend-adjusted series.  All tracked tickers are US-listed and
USD-quoted.  If a non-USD name is ever added, note that LSE tickers (".L") are
quoted in pence, so current_price would be in pence, not pounds.

Typical usage
-------------
    from cytonn_weekly.digital_payments.fetcher import fetch_digital_payments

    for row in fetch_digital_payments():
        if row["error"]:
            ...
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

import yfinance as yf

COMPANIES: list[tuple[str, str]] = [
    ("Visa", "V"),
    ("Mastercard", "MA"),
    ("American Express", "AXP"),
    ("Circle Internet Group", "CRCL"),
    ("Block Inc.", "XYZ"),  # formerly SQ
    ("PayPal Holdings", "PYPL"),
    ("Global Payments", "GPN"),
]

_PE_FIELDS = ("forward_pe", "forward_eps", "forward_pe_source", "forward_pe_note")

_NUMERIC_FIELDS = (
    "current_price",
    "current_price_date",
    "prior_close",
    "prior_close_date",
    "ytd_open",
    "ytd_open_date",
    "wow_pct",
    "ytd_pct",
)


def _positive_number(value: Any) -> Optional[float]:
    """value as a finite float > 0, else None (Yahoo may return None or 'Infinity')."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return float(value)


def get_forward_pe(ticker: str, price: float) -> dict[str, Any]:
    """Forward P/E on the conventional consensus-estimate basis.

    Prefers Yahoo's own info["forwardPE"] (price / forward consensus EPS).  If
    that is missing or not a positive number, falls back to the supplied price
    divided by info["forwardEps"].  Pulled fresh every run: consensus estimates
    are revised over time, so nothing here is cached.

    Returns {"forward_pe", "forward_eps", "forward_pe_source", "forward_pe_note"};
    forward_pe is None (with a note) if neither route yields a positive figure.
    Raises if the info call itself fails.
    """
    info = yf.Ticker(ticker).info or {}
    eps = _positive_number(info.get("forwardEps"))
    pe = _positive_number(info.get("forwardPE"))
    if pe is not None:
        return {
            "forward_pe": pe,
            "forward_eps": eps,
            "forward_pe_source": "yahoo_forwardPE",
            "forward_pe_note": None,
        }
    if eps is not None:
        return {
            "forward_pe": price / eps,
            "forward_eps": eps,
            "forward_pe_source": "price/forwardEps",
            "forward_pe_note": "forwardPE missing; computed from price / forwardEps",
        }
    return {
        "forward_pe": None,
        "forward_eps": None,
        "forward_pe_source": None,
        "forward_pe_note": "no positive forwardPE or forwardEps from Yahoo",
    }


# The report table shows every price, % change and P/E at one decimal.
DISPLAY_DECIMALS = 1

_PRICE_FIELDS = ("current_price", "prior_close", "ytd_open")
_PCT_FIELDS = ("wow_pct", "ytd_pct")


def _round_half_up(value: float, decimals: int = DISPLAY_DECIMALS) -> Decimal:
    """Round half up on the float's shortest string form (matches the checking layer)."""
    return Decimal(repr(value)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


def average_forward_pe(rows: list[dict[str, Any]]) -> Optional[float]:
    """Mean forward P/E over rows that have one, at display precision (1dp), or None.

    Failed rows and rows with no forward P/E are left out.  This is the table's
    Average row value, which the outlook paragraph reuses verbatim.
    """
    pes = [
        Decimal(repr(r["forward_pe"]))
        for r in rows
        if isinstance(r.get("forward_pe"), (int, float)) and not isinstance(r.get("forward_pe"), bool)
    ]
    if not pes:
        return None
    avg = sum(pes) / len(pes)
    return float(avg.quantize(Decimal(1).scaleb(-DISPLAY_DECIMALS), rounding=ROUND_HALF_UP))


def _fmt_number(value: Optional[float], kind: str) -> str:
    """One figure as the real report table prints it; "-" when there is no value."""
    if value is None:
        return "-"
    d = _round_half_up(value)
    if kind == "price":
        return f"{d:.{DISPLAY_DECIMALS}f}"  # 372.7 (no currency symbol)
    if kind == "pe":
        return f"{d:.{DISPLAY_DECIMALS}f}x"  # 15.5x
    body = f"{abs(d):.{DISPLAY_DECIMALS}f}%"
    return f"({body})" if d < 0 else body  # 6.3% / (4.0%); zero has no sign


def format_table_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn fetcher rows into drafted, display-formatted rows for the report table.

    Same field names as the fetcher's rows (company, ticker, current_price,
    prior_close, ytd_open, wow_pct, ytd_pct, forward_pe); the figures become
    strings in the real table's format: prices "372.7", positive % "6.3%",
    negative % "(4.0%)", forward P/E "15.5x".  Missing figures (failed rows,
    no forward P/E) are "-".
    """
    out = []
    for r in rows:
        f: dict[str, Any] = {"company": r["company"], "ticker": r["ticker"]}
        for name in _PRICE_FIELDS:
            f[name] = _fmt_number(r.get(name), "price")
        for name in _PCT_FIELDS:
            f[name] = _fmt_number(r.get(name), "pct")
        f["forward_pe"] = _fmt_number(r.get("forward_pe"), "pe")
        out.append(f)
    return out


def _pct_change(new: float, old: float) -> float:
    if old == 0:
        raise ValueError("cannot compute % change from a zero base price")
    return (new - old) / old * 100


def _fetch_one(name: str, ticker: str, today: date) -> dict[str, Any]:
    year_start = date(today.year, 1, 1)
    # end is exclusive in yfinance, so add a day to include today's bar.
    hist = yf.Ticker(ticker).history(
        start=year_start.isoformat(),
        end=(today + timedelta(days=1)).isoformat(),
        auto_adjust=False,
    )
    if hist is None or hist.empty:
        raise ValueError("no price history returned")

    hist = hist.dropna(subset=["Close"])
    if hist.empty:
        raise ValueError("no usable price rows returned")

    dates = [ts.date() for ts in hist.index]
    if dates[0].year != today.year:
        raise ValueError(f"first row is {dates[0]}, not in {today.year}")

    latest_date = dates[-1]
    current = float(hist["Close"].iloc[-1])
    # "Year Open" in the report is the CLOSE of the year's first trading day (the first row of
    # this year's data, never a hard-coded date).  Checked 2026-10-05 against the Year Open
    # column of 16 issues (cytonnreport.com ids 877 to 892, #38.2026 and the H1 and Q3 reviews included): the first day's close
    # reproduces 6 of 7 companies (AXP 372.7, V 346.5, MA 563.1, CRCL 83.5, XYZ 65.2, PYPL 58.1)
    # and their YTD column; the first day's open reproduces none.
    # KNOWN DIFFERENCE, not special-cased: Global Payments prints 77.0, but its 2 Jan 2026 close
    # is 75.5 (the 5 Jan close is 77.02), so its Year Open and YTD disagree with the issue.
    # See CLAUDE.md, Open items.  The field keeps its old name ``ytd_open``.
    ytd_open = float(hist["Close"].iloc[0])

    # Last trading day on or before (latest_date - 7 days).
    target = latest_date - timedelta(days=7)
    prior_idx = [i for i, d in enumerate(dates) if d <= target]
    if not prior_idx:
        raise ValueError(f"no close on or before {target} in this year's history")
    prior_close = float(hist["Close"].iloc[prior_idx[-1]])
    prior_date = dates[prior_idx[-1]]

    pe: dict[str, Any] = {f: None for f in _PE_FIELDS}
    try:
        pe.update(get_forward_pe(ticker, current))
    except Exception as exc:  # noqa: BLE001 - price data is still good; only P/E is unavailable
        pe["forward_pe_note"] = f"forward P/E unavailable: {type(exc).__name__}: {exc}"

    return {
        "company": name,
        "ticker": ticker,
        "current_price": current,
        "current_price_date": latest_date.isoformat(),
        "prior_close": prior_close,
        "prior_close_date": prior_date.isoformat(),
        "ytd_open": ytd_open,
        "ytd_open_date": dates[0].isoformat(),
        "wow_pct": _pct_change(current, prior_close),
        "ytd_pct": _pct_change(current, ytd_open),
        **pe,
        "error": None,
    }


def fetch_digital_payments(today: Optional[date] = None) -> list[dict[str, Any]]:
    """Fetch price data for every tracked company.

    Each row also carries forward_pe (forward consensus basis, see
    get_forward_pe), forward_eps, forward_pe_source and forward_pe_note.
    forward_pe is None when Yahoo has no usable figure; the note says why.
    Use average_forward_pe(rows) for the table's average.

    A failure on one ticker is recorded in that row's "error" field (numeric
    fields are None) and never stops the rest of the batch.
    """
    today = today or date.today()
    results: list[dict[str, Any]] = []
    for name, ticker in COMPANIES:
        try:
            results.append(_fetch_one(name, ticker, today))
        except Exception as exc:  # noqa: BLE001 - isolate any per-ticker failure
            row: dict[str, Any] = {"company": name, "ticker": ticker}
            row.update({f: None for f in _NUMERIC_FIELDS + _PE_FIELDS})
            row["error"] = f"{type(exc).__name__}: {exc}"
            results.append(row)
    return results
