"""Real Estate structured sources not yet built, with why.

Neither is a weekly table; both are for the quarterly, half-year and annual
reviews.  The publication names are from the investments team, 2026-10-30:
CBK's mortgage figures (loans outstanding, number of loans, average rate, NPLs)
are in the CBK Bank Supervision Report, with the table still to be named, and the
house price index is the KNBS Residential Property Price Index, not a KBA one.
Their table layouts were not inspected in this pass, so no parser is written
against a guessed layout.  In the meantime the Real Estate "Residential and
mortgage lending" brief searches centralbank.go.ke, kba.co.ke and knbs.or.ke among
its sources first, so a release that lands in the report week reaches the draft
as cited claims, whose figures are exact-matched against the cited text like any
other claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

MORTGAGE_UNBLOCK = (
    "For the quarterly, half-year and annual reviews: name the table in the CBK Bank Supervision Report that holds "
    "the mortgage figures (publication named by the investments team, 2026-10-30), then parse it from a real sample."
)
HPI_UNBLOCK = (
    "For the quarterly, half-year and annual reviews: one real release of the KNBS Residential Property Price Index "
    "(named by the investments team, 2026-10-30) as the reference sample, then parse its changes."
)


@dataclass
class MortgageStats:
    year: int
    loans_outstanding_kes_bn: float
    number_of_loans: int
    average_rate_pct: float
    npl_ratio_pct: float
    source_url: str


def fetch_cbk_mortgage_stats(year: Optional[int] = None) -> MortgageStats:
    # TODO: annual CBK PDF, layout not yet inspected; see MORTGAGE_UNBLOCK.
    raise NotImplementedError("CBK mortgage statistics parser not built: " + MORTGAGE_UNBLOCK)


@dataclass
class HousePriceIndex:
    quarter: str            # e.g. "2025Q4"
    qoq_change_pct: float
    yoy_change_pct: float
    source_url: str


def fetch_residential_price_index(quarter: Optional[str] = None) -> HousePriceIndex:
    # TODO: KNBS Residential Property Price Index release, layout not yet inspected; see HPI_UNBLOCK.
    raise NotImplementedError("Residential price index parser not built: " + HPI_UNBLOCK)
