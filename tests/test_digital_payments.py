"""Unit tests for cytonn_weekly.fetchers.digital_payments.

yfinance is mocked; no network access.
"""

from datetime import date

import pandas as pd
import pytest

from cytonn_weekly.fetchers import digital_payments as dp

TODAY = date(2026, 9, 29)


def _hist(rows):
    """rows: list of (iso_date, open, close)."""
    idx = pd.DatetimeIndex([r[0] for r in rows], tz="America/New_York")
    return pd.DataFrame(
        {"Open": [r[1] for r in rows], "Close": [r[2] for r in rows]}, index=idx
    )


GOOD = _hist(
    [
        ("2026-01-02", 100.0, 101.0),
        ("2026-09-21", 110.0, 120.0),
        ("2026-09-22", 120.0, 125.0),  # 7 days before 09-29
        ("2026-09-29", 125.0, 130.0),
    ]
)


class FakeTicker:
    def __init__(self, symbol, histories):
        self.symbol = symbol
        self.histories = histories

    def history(self, **kwargs):
        h = self.histories[self.symbol]
        if isinstance(h, Exception):
            raise h
        return h


@pytest.fixture
def patch_yf(monkeypatch):
    def _apply(histories):
        monkeypatch.setattr(
            dp.yf, "Ticker", lambda symbol: FakeTicker(symbol, histories)
        )

    return _apply


def test_computes_prices_and_changes(patch_yf):
    patch_yf({t: GOOD for _, t in dp.COMPANIES})
    rows = dp.fetch_digital_payments(today=TODAY)
    assert len(rows) == 7
    r = rows[0]
    assert (r["company"], r["ticker"]) == ("Visa", "V")
    assert r["current_price"] == 130.0
    assert r["prior_close"] == 125.0
    assert r["prior_close_date"] == "2026-09-22"
    assert r["ytd_open"] == 100.0
    assert r["wow_pct"] == pytest.approx(4.0)
    assert r["ytd_pct"] == pytest.approx(30.0)
    assert r["error"] is None


def test_prior_close_uses_last_trading_day_on_or_before_target(patch_yf):
    h = _hist(
        [
            ("2026-01-02", 100.0, 100.0),
            ("2026-09-18", 110.0, 115.0),  # no bars between 09-19 and 09-27
            ("2026-09-28", 120.0, 130.0),
        ]
    )
    patch_yf({t: h for _, t in dp.COMPANIES})
    r = dp.fetch_digital_payments(today=date(2026, 9, 28))[0]
    # latest 09-28, target 09-21 -> last bar on/before is 09-18
    assert r["prior_close_date"] == "2026-09-18"
    assert r["wow_pct"] == pytest.approx((130 - 115) / 115 * 100)


def test_single_ticker_failure_does_not_crash_batch(patch_yf):
    hs = {t: GOOD for _, t in dp.COMPANIES}
    hs["GPN"] = RuntimeError("network down")
    hs["PYPL"] = pd.DataFrame()
    patch_yf(hs)
    rows = {r["ticker"]: r for r in dp.fetch_digital_payments(today=TODAY)}
    assert len(rows) == 7
    assert "network down" in rows["GPN"]["error"]
    assert rows["GPN"]["current_price"] is None
    assert "no price history" in rows["PYPL"]["error"]
    assert rows["V"]["error"] is None


def test_insufficient_history_is_flagged(patch_yf):
    h = _hist([("2026-09-28", 100.0, 101.0), ("2026-09-29", 101.0, 102.0)])
    patch_yf({t: h for _, t in dp.COMPANIES})
    r = dp.fetch_digital_payments(today=TODAY)[0]
    assert r["error"] and "no close on or before" in r["error"]


def test_history_not_starting_this_year_is_flagged(patch_yf):
    h = _hist([("2025-12-31", 90.0, 95.0), ("2026-09-29", 100.0, 101.0)])
    patch_yf({t: h for _, t in dp.COMPANIES})
    r = dp.fetch_digital_payments(today=TODAY)[0]
    assert r["error"]


def test_tracked_companies_are_the_seven_report_tickers():
    tickers = dict(dp.COMPANIES)
    assert sorted(tickers.values()) == sorted(
        ["AXP", "V", "MA", "CRCL", "XYZ", "PYPL", "GPN"]
    )
    assert tickers["Block Inc."] == "XYZ"
    assert "SQ" not in tickers.values()
