"""Real Estate structured sources not yet built, with why.

Neither is a weekly table: CBK's mortgage figures (loans outstanding, number of
loans, average rate, NPLs) come once a year in the Bank Supervision Annual
Report, and the KBA Housing Price Index is a quarterly PDF (kba.co.ke/housing-price-index/).
Their table layouts were not inspected in this pass, so no parser is written
against a guessed layout.  In the meantime the Real Estate "Residential and
mortgage lending" brief searches centralbank.go.ke and kba.co.ke first, so a
release that lands in the report week reaches the draft as cited claims, whose
figures are exact-matched against the cited text like any other claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

MORTGAGE_UNBLOCK = (
    "Confirm which CBK publication and table the report takes its mortgage figures from (Bank Supervision "
    "Annual Report or the Mortgage Finance survey), then parse that table from a real sample."
)
HPI_UNBLOCK = "Pick one real KBA HPI PDF as the reference sample and parse its quarterly and annual change table."


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
    # TODO: quarterly KBA HPI PDF, layout not yet inspected; see HPI_UNBLOCK.
    raise NotImplementedError("Residential price index parser not built: " + HPI_UNBLOCK)
