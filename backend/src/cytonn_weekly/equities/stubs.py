"""Equities parts that depend on access this project does not have yet.

Each is a real interface that fails loudly, so the section visibly cannot draft
these parts rather than guessing at them.  The review run turns each into an
``unavailable`` block, which the coordinator must explicitly acknowledge.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

UNIVERSE_TITLE = "Universe of Coverage"
UNIVERSE_REASON = (
    "Target prices and buy/hold/sell recommendations for the ~20 covered companies are Cytonn's own "
    "proprietary research, not public market data, so the tool cannot derive them."
)
UNIVERSE_UNBLOCK = (
    "Cytonn's research team sharing the coverage sheet (company, target price, recommendation) each week, "
    "in a fixed format the tool can read."
)

MARKET_ACTIVITY_TITLE = "Market activity and valuation"
MARKET_ACTIVITY_REASON = (
    "Weekly and YTD equities turnover, foreign investor net buying/selling, and the market P/E, dividend "
    "yield and PEG against their historical averages are not published anywhere machine-readable: NSE's "
    "daily price list is an image-only PDF (checked 2026-10-02) and afx.kwayisi.org shows one day's "
    "turnover only."
)
MARKET_ACTIVITY_UNBLOCK = (
    "The KCB daily email samples (which carry these figures) or an NSE data feed; alternatively OCR on "
    "NSE's daily PDF, which would need its own checking."
)


@dataclass
class CoverageRow:
    """One Universe of Coverage row as the report prints it."""

    company: str
    price: float
    target_price: float
    upside_pct: float
    recommendation: str  # e.g. "Buy", "Hold", "Sell"


def fetch_universe_of_coverage(week_end: Optional[date] = None) -> list[CoverageRow]:
    # TODO: needs Cytonn's own target prices and recommendations (proprietary research), see UNIVERSE_UNBLOCK.
    raise NotImplementedError(UNIVERSE_REASON)


@dataclass
class MarketActivity:
    """The Market Performance figures afx does not carry."""

    weekly_turnover_kes_mn: float
    ytd_turnover_kes_bn: float
    foreign_net_kes_mn: float      # positive = net buying
    market_pe: float
    market_pe_hist_avg: float
    dividend_yield_pct: float
    dividend_yield_hist_avg_pct: float
    peg: float


def fetch_market_activity(week_end: Optional[date] = None) -> MarketActivity:
    # TODO: no machine-readable public source (NSE daily PDF is image-only); see MARKET_ACTIVITY_UNBLOCK.
    raise NotImplementedError(MARKET_ACTIVITY_REASON)
