"""Companion research reports: registered, every kind an explicit stub.

What they are (read 2026-10-05 on cytonnreport.com): each is the weekly issue's own Focus
of the Week, not a separate document.  The issue is titled after it ("Kenya's Listed Banks
H1'2026 Report, & Cytonn Weekly #37.2026"), the report is the "Focus of the Week" section
of that issue (cytonnreport.com/api/series/1/research-reports/<id>, section "Focus of the
Week", whose ``title`` is the report's name), and the downloadable PDF is the whole weekly
("kenyas-listed-banks-h12026-report-cytonn-weekly-372026vf.pdf").  The Listed Banks report
also links eleven per-bank earnings notes as separate PDFs.

Each is structured in numbered sections of Cytonn's own analysis (below, verbatim), which
the tool does not have, so none is drafted.  The weekly Focus of the Week section can still
draft a cited piece on the same topic from a topic the coordinator types; it does not
follow these structures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

BLOCKED_REASON = (
    "Every section of this report is Cytonn's own analysis (its rankings, valuations, market surveys, "
    "recommendations and outlook), which the tool does not have; drafting to this structure would mean "
    "guessing Cytonn's data and views."
)
UNBLOCK = (
    "Cytonn's research team supplying the analysis inputs for the report (e.g. the bank ranking scores, REIT "
    "valuation inputs or residential survey data). Until then, draft the issue's Focus of the Week, which writes "
    "a cited piece on a topic you supply."
)
BUILT_PARTS = (
    "The weekly Focus of the Week section drafts one cited long-form piece on a topic you supply (not to this structure)",
)


@dataclass(frozen=True)
class CompanionKind:
    slug: str
    title: str          # the Focus of the Week title, verbatim
    issue: str          # the weekly issue it rode with
    published: str
    sections: tuple[str, ...]  # its numbered sections, verbatim


KINDS: tuple[CompanionKind, ...] = (
    CompanionKind(
        "ssa_eurobonds", "Sub-Saharan Africa (SSA) Eurobonds Performance in 2026", "Weekly #38.2026", "27 Sept 2026",
        ("Section I: Background of Eurobonds Issued in Sub-Saharan Africa",
         "Section II: Analysis of Existing Eurobond Issues in Sub-Saharan Africa",
         "Section III: Debt Sustainability in the Sub-Saharan Africa Region",
         "Section IV: Outlook on SSA Eurobonds Performance"),
    ),
    CompanionKind(
        "listed_banks", "Kenya Listed Banks H1’2026 Report", "Weekly #37.2026", "20 Sept 2026",
        ("Section I: Key Themes That Shaped the Banking Sector Performance in H1’2026",
         "Section II: Summary of the Performance of the Listed Banking Sector in H1’2026",
         "Section III: The Focus Areas of the Banking Sector Players Going Forward",
         "Section IV: Brief Summary and Ranking of the Listed Banks"),
    ),
    CompanionKind(
        "reits", "Kenya’s Real Estate Investment Trusts (REITs) H1’2026 Report", "Weekly #33.2026", "23 Aug 2026",
        ("Section I: Overview of the REITs Sector in Kenya",
         "Section II: Themes that Shaped the REIT Sector in H1’2026",
         "Section III: Summary Performance of the REITs in H1’2026",
         "Section IV: Conclusion, Recommendations, and Outlook for the REITs Sector"),
    ),
    CompanionKind(
        "nma_residential", "Nairobi Metropolitan Area Residential Report 2026", "Weekly #23.2026", "14 June 2026",
        ("Section I: Overview of the Residential Sector",
         "Section II: Recent Developments in the Sector",
         "Section III: Residential Market Performance",
         "Section IV: Conclusion, Market Outlook, and Investment Opportunity"),
    ),
)
BY_KIND = {k.slug: k for k in KINDS}


def build_companion_report(kind: str) -> Any:
    # TODO: needs Cytonn's own analysis inputs for the report (UNBLOCK).
    if kind not in BY_KIND:
        raise KeyError(f"unknown companion report kind {kind!r}")
    raise NotImplementedError(BLOCKED_REASON)
