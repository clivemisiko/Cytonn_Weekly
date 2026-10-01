"""Unit tests for cytonn_weekly.digital_payments.fetcher.

yfinance is mocked; no network access.
"""

from datetime import date

import pandas as pd
import pytest

from cytonn_weekly.digital_payments import fetcher as dp

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


# Default Yahoo info: forwardPE 26.0 / forwardEps 5.0 for every ticker.
DEFAULT_INFO = {"forwardPE": 26.0, "forwardEps": 5.0}

INFO_CALLS: list[str] = []


class FakeTicker:
    def __init__(self, symbol, histories, infos):
        self.symbol = symbol
        self.histories = histories
        self.infos = infos

    def history(self, **kwargs):
        h = self.histories[self.symbol]
        if isinstance(h, Exception):
            raise h
        return h

    @property
    def info(self):
        INFO_CALLS.append(self.symbol)
        i = self.infos.get(self.symbol, DEFAULT_INFO)
        if isinstance(i, Exception):
            raise i
        return i


@pytest.fixture(autouse=True)
def reset_calls():
    INFO_CALLS.clear()


@pytest.fixture
def patch_yf(monkeypatch):
    def _apply(histories, infos=None):
        monkeypatch.setattr(
            dp.yf, "Ticker", lambda symbol: FakeTicker(symbol, histories, infos or {})
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


# ---------------------------------------------------------------------------
# Forward P/E (forward consensus basis, fetched fresh every run)
# ---------------------------------------------------------------------------

def _by_ticker(rows):
    return {r["ticker"]: r for r in rows}


def test_row_uses_yahoo_forward_pe_directly(patch_yf):
    patch_yf({t: GOOD for _, t in dp.COMPANIES}, {"V": {"forwardPE": 24.51, "forwardEps": 15.0}})
    r = dp.fetch_digital_payments(today=TODAY)[0]
    assert r["forward_pe"] == 24.51  # not price/eps (130/15 = 8.67)
    assert r["forward_eps"] == 15.0
    assert r["forward_pe_source"] == "yahoo_forwardPE"
    assert r["forward_pe_note"] is None


def test_falls_back_to_price_over_forward_eps_when_forward_pe_missing(patch_yf):
    patch_yf({t: GOOD for _, t in dp.COMPANIES}, {"V": {"forwardPE": None, "forwardEps": 5.0}})
    r = dp.fetch_digital_payments(today=TODAY)[0]
    assert r["forward_pe"] == pytest.approx(130.0 / 5.0)  # GOOD's latest close is 130
    assert r["forward_pe_source"] == "price/forwardEps"
    assert "forwardPE missing" in r["forward_pe_note"]


@pytest.mark.parametrize("bad", [None, "Infinity", float("inf"), float("nan"), 0, -5.0, True])
def test_unusable_forward_pe_values_trigger_fallback(patch_yf, bad):
    patch_yf({t: GOOD for _, t in dp.COMPANIES}, {"V": {"forwardPE": bad, "forwardEps": 10.0}})
    r = dp.fetch_digital_payments(today=TODAY)[0]
    assert r["forward_pe"] == pytest.approx(13.0)
    assert r["forward_pe_source"] == "price/forwardEps"


def test_no_forward_data_gives_none_with_note_and_price_row_survives(patch_yf):
    patch_yf({t: GOOD for _, t in dp.COMPANIES}, {"V": {"forwardPE": None, "forwardEps": None}})
    r = dp.fetch_digital_payments(today=TODAY)[0]
    assert r["error"] is None and r["current_price"] == 130.0
    assert r["forward_pe"] is None
    assert "no positive forwardPE or forwardEps" in r["forward_pe_note"]


def test_negative_forward_eps_with_no_forward_pe_gives_none(patch_yf):
    patch_yf({t: GOOD for _, t in dp.COMPANIES}, {"V": {"forwardPE": None, "forwardEps": -1.0}})
    assert dp.fetch_digital_payments(today=TODAY)[0]["forward_pe"] is None


def test_circle_gets_a_real_positive_forward_pe(patch_yf):
    # Trailing FY2025 EPS was a loss, but the consensus-forward figure is positive.
    patch_yf({t: GOOD for _, t in dp.COMPANIES}, {"CRCL": {"forwardPE": 56.28, "forwardEps": 1.53}})
    r = _by_ticker(dp.fetch_digital_payments(today=TODAY))["CRCL"]
    assert r["forward_pe"] == 56.28 and r["forward_pe"] > 0
    assert r["forward_pe_note"] is None


def test_info_failure_leaves_price_row_intact_with_note(patch_yf):
    patch_yf({t: GOOD for _, t in dp.COMPANIES}, {"V": RuntimeError("info down")})
    r = dp.fetch_digital_payments(today=TODAY)[0]
    assert r["error"] is None and r["current_price"] == 130.0
    assert r["forward_pe"] is None
    assert "info down" in r["forward_pe_note"]


def test_forward_pe_is_pulled_fresh_every_run_not_cached(patch_yf):
    patch_yf({t: GOOD for _, t in dp.COMPANIES})
    dp.fetch_digital_payments(today=TODAY)
    dp.fetch_digital_payments(today=TODAY)
    assert INFO_CALLS.count("V") == 2


def test_no_info_call_for_a_ticker_whose_price_fetch_failed(patch_yf):
    patch_yf({t: RuntimeError("down") for _, t in dp.COMPANIES})
    rows = dp.fetch_digital_payments(today=TODAY)
    assert INFO_CALLS == []
    assert all(r["error"] and r["forward_pe"] is None and r["forward_eps"] is None for r in rows)


def test_average_forward_pe_skips_failed_and_none_rows():
    rows = [
        {"forward_pe": 20.0, "error": None},
        {"forward_pe": 30.0, "error": None},
        {"forward_pe": None, "error": None},
        {"forward_pe": None, "error": "boom"},
    ]
    assert dp.average_forward_pe(rows) == 25.0
    assert dp.average_forward_pe([{"forward_pe": None}]) is None


def test_average_covers_all_seven_when_all_have_forward_pe(patch_yf):
    pes = {"V": 24.0, "MA": 24.0, "AXP": 15.0, "CRCL": 56.0, "XYZ": 14.0, "PYPL": 9.0, "GPN": 5.0}
    patch_yf({t: GOOD for _, t in dp.COMPANIES}, {t: {"forwardPE": v} for t, v in pes.items()})
    rows = dp.fetch_digital_payments(today=TODAY)
    assert dp.average_forward_pe(rows) == 21.0  # 147 / 7, at 1dp


def test_average_matches_what_the_outlook_stats_read(patch_yf):
    from cytonn_weekly.digital_payments.highlights import table_stats

    patch_yf({t: GOOD for _, t in dp.COMPANIES}, {"V": {"forwardPE": 24.0}, "MA": {"forwardPE": 25.0}})
    rows = dp.fetch_digital_payments(today=TODAY)
    assert table_stats(rows)["avg_forward_pe"] == dp.average_forward_pe(rows)


# ---------------------------------------------------------------------------
# Display formatting and 1dp average
# ---------------------------------------------------------------------------

def _row(**kw):
    base = {"company": "Visa", "ticker": "V", "current_price": 372.65, "prior_close": 388.31,
            "ytd_open": 350.6, "wow_pct": -4.0234, "ytd_pct": 6.3149, "forward_pe": 15.46}
    base.update(kw)
    return base


def test_format_uses_the_real_table_style():
    f = dp.format_table_rows([_row()])[0]
    assert f["company"] == "Visa" and f["ticker"] == "V"
    assert f["current_price"] == "372.7"   # no $, one decimal, half up
    assert f["prior_close"] == "388.3"
    assert f["ytd_open"] == "350.6"
    assert f["wow_pct"] == "(4.0%)"        # negative: parentheses, no minus
    assert f["ytd_pct"] == "6.3%"          # positive: no plus
    assert f["forward_pe"] == "15.5x"


def test_format_has_no_currency_symbol_plus_or_minus_signs():
    f = dp.format_table_rows([_row(wow_pct=1.26, ytd_pct=-12.5)])[0]
    assert "$" not in f["current_price"] and "+" not in f["wow_pct"]
    assert f["wow_pct"] == "1.3%" and f["ytd_pct"] == "(12.5%)"
    assert "-" not in f["ytd_pct"]


def test_format_zero_and_rounds_to_zero_have_no_sign_or_parentheses():
    f = dp.format_table_rows([_row(wow_pct=0.0, ytd_pct=-0.04)])[0]
    assert f["wow_pct"] == "0.0%" and f["ytd_pct"] == "0.0%"


def test_format_rounds_half_up_not_bankers():
    f = dp.format_table_rows([_row(current_price=2.25, wow_pct=-2.25, forward_pe=24.95)])[0]
    assert f["current_price"] == "2.3" and f["wow_pct"] == "(2.3%)" and f["forward_pe"] == "25.0x"


def test_format_missing_values_are_dashes():
    failed = {"company": "Circle", "ticker": "CRCL", "current_price": None, "prior_close": None,
              "ytd_open": None, "wow_pct": None, "ytd_pct": None, "forward_pe": None, "error": "x"}
    f = dp.format_table_rows([failed, _row(forward_pe=None)])
    assert all(f[0][k] == "-" for k in ("current_price", "prior_close", "ytd_open", "wow_pct", "ytd_pct", "forward_pe"))
    assert f[1]["forward_pe"] == "-"


def test_format_keeps_fetcher_field_names_and_row_order():
    rows = [_row(), _row(company="Mastercard", ticker="MA")]
    out = dp.format_table_rows(rows)
    assert [r["ticker"] for r in out] == ["V", "MA"]
    assert set(out[0]) == {"company", "ticker", "current_price", "prior_close", "ytd_open",
                           "wow_pct", "ytd_pct", "forward_pe"}


def test_average_forward_pe_is_one_decimal_half_up():
    assert dp.average_forward_pe([{"forward_pe": 24.9}, {"forward_pe": 25.0}]) == 25.0  # 24.95
    assert dp.average_forward_pe([{"forward_pe": 23.3}, {"forward_pe": 23.4}]) == 23.4  # 23.35
