"""Digital Payments share-price fetcher (Yahoo Finance via yfinance).

For each tracked company, pulls the latest close, the close 7 calendar days
before it, and this calendar year's opening price, then derives w/w and YTD
percentage change.  No checking or drafting logic lives here.

Prices are unadjusted (auto_adjust=False) so they match the quoted price
rather than a dividend-adjusted series.  All tracked tickers are US-listed and
USD-quoted.  If a non-USD name is ever added, note that LSE tickers (".L") are
quoted in pence, so current_price would be in pence, not pounds.

Typical usage
-------------
    from cytonn_weekly.fetchers.digital_payments import fetch_digital_payments

    for row in fetch_digital_payments():
        if row["error"]:
            ...
"""

from __future__ import annotations

from datetime import date, timedelta
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

    hist = hist.dropna(subset=["Close", "Open"])
    if hist.empty:
        raise ValueError("no usable price rows returned")

    dates = [ts.date() for ts in hist.index]
    if dates[0].year != today.year:
        raise ValueError(f"first row is {dates[0]}, not in {today.year}")

    latest_date = dates[-1]
    current = float(hist["Close"].iloc[-1])
    ytd_open = float(hist["Open"].iloc[0])

    # Last trading day on or before (latest_date - 7 days).
    target = latest_date - timedelta(days=7)
    prior_idx = [i for i, d in enumerate(dates) if d <= target]
    if not prior_idx:
        raise ValueError(f"no close on or before {target} in this year's history")
    prior_close = float(hist["Close"].iloc[prior_idx[-1]])
    prior_date = dates[prior_idx[-1]]

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
        "error": None,
    }


def fetch_digital_payments(today: Optional[date] = None) -> list[dict[str, Any]]:
    """Fetch price data for every tracked company.

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
            row.update({f: None for f in _NUMERIC_FIELDS})
            row["error"] = f"{type(exc).__name__}: {exc}"
            results.append(row)
    return results
