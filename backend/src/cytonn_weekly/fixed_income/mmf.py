"""Money Market Fund yields table (~34 fund managers, effective annual rate, ranked).

The real report credits this table to Business Daily.  The ranking and display
are built and tested here; the FETCH is a stub, because no public, machine-readable
Business Daily page carrying the table was found (checked 2026-10-02):
businessdailyafrica.com's markets pages carry money-market coverage only as
articles, mostly behind its PRIME paywall, and the ranked table appears to be a
print / e-paper feature.  Scraping an article's prose for 34 figures would be a
guess at a format that is not published as data.

What unblocks it: the exact Business Daily URL or e-paper page Cytonn's analysts
copy the table from (and the access to it), so a parser can be written against
a real sample.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Optional

from cytonn_weekly.common.formatting import PCT, TEXT, format_rows

BLOCKED_REASON = (
    "No public, machine-readable Business Daily source for the money market fund yields table was found; "
    "it appears in the print/e-paper edition and paywalled articles."
)
UNBLOCK = "The exact Business Daily page (and access) the analysts take the table from."

# Header and precision follow Cytonn Weekly #38.2026 (published 2026-09-27):
# "Rank | Fund Manager | Effective Annual Rate", rates to 1 dp ("1 | Cytonn Money
# Market Fund ... | 11.0%", "34 | Stanbic Money Market Fund | 5.4%").
COLUMNS = [
    {"key": "rank", "label": "Rank", "fmt": TEXT},
    {"key": "fund", "label": "Fund Manager", "fmt": TEXT},
    {"key": "effective_annual_rate_pct", "label": "Effective Annual Rate", "fmt": PCT, "decimals": 1},
]


@dataclass
class MmfYield:
    fund: str
    effective_annual_rate_pct: float


def fetch_mmf_yields(week_end: Optional[date] = None) -> list[MmfYield]:
    # TODO: no public machine-readable source found; needs the exact Business Daily page, see UNBLOCK.
    raise NotImplementedError(BLOCKED_REASON)


def rank_mmf_yields(yields: list[MmfYield]) -> list[dict[str, Any]]:
    """Rank funds by effective annual rate, highest first; equal rates share a rank (1, 2, 2, 4)."""
    ordered = sorted(yields, key=lambda y: (-y.effective_annual_rate_pct, y.fund))
    rows, rank = [], 0
    for i, y in enumerate(ordered):
        if i == 0 or y.effective_annual_rate_pct != ordered[i - 1].effective_annual_rate_pct:
            rank = i + 1
        rows.append({"rank": str(rank), "fund": y.fund, **{k: v for k, v in asdict(y).items() if k != "fund"}})
    return rows


def format_mmf_table(yields: list[MmfYield]) -> list[dict[str, Any]]:
    return format_rows(rank_mmf_yields(yields), COLUMNS)
