"""Every report type's sections as the review screen sees them: which can be drafted, and how.

Each section is still its own independently drafted, independently approved
CoordinatorReview.  A review's key is (report type, period, section slug), so the same
slug in two report types (the weekly "fixed_income" and the Q3'2026 "fixed_income") is
two different reviews.  This registry only says, per report type and slug: the display
title, whether a draft can run today (and if not, what blocks it), whether the
coordinator must supply a topic or text, the steps a run takes, the real report's own
subsection headings and charts, and the function that builds the review.

Orders are the real reports' own (CLAUDE.md, "Report types", records where each was read):

* weekly: Fixed Income, Equities, Digital Payments, Real Estate, Focus of the Week
  (unchanged; ``SECTIONS`` and ``BY_SLUG`` are this list).
* quarterly and half_year: Executive Summary, Company Updates, Global Markets Review,
  Sub-Saharan Africa Region Review, Kenya Macro Economic Review, Fixed Income, Equities,
  Real Estate, Digital Payments.
* annual: the same without Digital Payments, which first ran in May 2026, after FY'2025.
* companion: one per verified kind, each section of it a stub (periodic/companion.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Optional, Union

from cytonn_weekly import sections
from cytonn_weekly.common.run_events import Observer
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview
from cytonn_weekly.report_types import ANNUAL, COMPANION, HALF_YEAR, QUARTERLY, WEEKLY


@dataclass(frozen=True)
class DraftContext:
    """What one draft run is for: the report and period, and anything the coordinator supplied."""

    report_type: str = WEEKLY
    period: str = ""
    topic: Optional[str] = None     # Focus of the Week
    text: Optional[str] = None      # Company Updates
    db_path: Optional[Union[Path, str]] = None  # Executive Summary reads the approved sections from here
    today: Optional[date] = None
    # Told each real step of the run (common/run_events.py).  None, the default, is a plain draft.
    on_event: Optional[Observer] = None


@dataclass(frozen=True)
class SectionSpec:
    slug: str
    title: str
    available: bool
    steps: tuple[tuple[str, str], ...] = ()
    needs_topic: bool = False
    reason: str = ""            # unavailable only: what blocks a draft
    unblock: str = ""           # unavailable only: what would unblock it
    built_parts: tuple[str, ...] = field(default_factory=tuple)  # unavailable only: what already exists
    build: Optional[Callable[[DraftContext], CoordinatorReview]] = None
    needs_text: bool = False         # Company Updates: the coordinator pastes the text
    requires_approved: bool = False  # Executive Summary: composed from the other sections once approved
    subsections: tuple[str, ...] = ()  # the real issue's own headings for this section, verbatim
    charts: tuple[str, ...] = ()       # the real issue's charts, which the tool does not draw


# ---------------------------------------------------------------------------
# Weekly
# ---------------------------------------------------------------------------

def _observer(ctx: DraftContext) -> dict[str, Any]:
    """``on_event`` as a keyword argument, only when the run has an observer: an unobserved draft
    calls its builder exactly as it always did."""
    return {} if ctx.on_event is None else {"on_event": ctx.on_event}


def _digital_payments(ctx: DraftContext) -> CoordinatorReview:
    from cytonn_weekly.digital_payments.review_run import build_digital_payments_review

    return build_digital_payments_review(**_observer(ctx))


def _equities(ctx: DraftContext) -> CoordinatorReview:
    from cytonn_weekly.equities.review_run import build_equities_review

    return build_equities_review(**_observer(ctx))


def _real_estate(ctx: DraftContext) -> CoordinatorReview:
    from cytonn_weekly.real_estate.review_run import build_real_estate_review

    return build_real_estate_review(**_observer(ctx))


def _focus(ctx: DraftContext) -> CoordinatorReview:
    from cytonn_weekly.focus.review_run import build_focus_review

    return build_focus_review(ctx.topic or "", **_observer(ctx))


_YOUR_REVIEW = ("Your review", "You resolve each item, then approve or reject the whole section.")

SECTIONS: tuple[SectionSpec, ...] = (
    SectionSpec(
        slug="fixed_income", title="Fixed Income", available=False,
        reason=("The weekly section is drafted from KCB's daily email, and none of the 20 requested sample "
                "emails has arrived, so its extraction cannot be written without guessing the format."),
        unblock="The 20 KCB daily email samples, then an inbox or forwarding rule for the live feed.",
        built_parts=(
            "CBK T-bill primary auction results fetcher (91/182/364-day)",
            "CBK T-bond primary auction results fetcher",
            "Money market fund yields ranking and formatting (its Business Daily fetch is a stub: no public source found)",
        ),
    ),
    SectionSpec(
        slug="equities", title="Equities", available=True, build=_equities,
        steps=(
            ("Fetch the market", "NASI, NSE 25/20/10 and banking index changes, plus every share's weekly move, from afx.kwayisi.org."),
            ("Draft highlights", "Up to three NSE company, banking and regulatory stories from the week, each with its source."),
            ("Check", "Every table figure exact-matched to its source; every claim's figures matched to its cited text."),
            _YOUR_REVIEW,
        ),
    ),
    SectionSpec(
        slug="digital_payments", title="Digital Payments", available=True, build=_digital_payments,
        steps=(
            ("Fetch prices", "Share prices for the seven tracked companies, from Yahoo Finance."),
            ("Draft highlights", "Four highlights from company investor pages, each with its source."),
            ("Exact-match check", "Every table figure compared with its source. No tolerance band."),
            _YOUR_REVIEW,
        ),
    ),
    SectionSpec(
        slug="real_estate", title="Real Estate", available=True, build=_real_estate,
        steps=(
            ("Draft subsections", "Up to four of this week's housing, mortgage, hospitality, infrastructure and other stories."),
            ("Fetch REITs", "Acorn D-REIT, Acorn I-REIT and ILAM Fahari prices from the NSE Ibuka weekly PDF."),
            ("Check", "REIT figures exact-matched to the PDF; every claim's figures matched to its cited text."),
            _YOUR_REVIEW,
        ),
    ),
    SectionSpec(
        slug="focus", title="Focus of the Week", available=True, needs_topic=True, build=_focus,
        steps=(
            ("Your topic", "You choose this week's theme; the tool never picks it."),
            ("Research and draft", "One long-form piece written only from what the search returned, every claim cited."),
            ("Check", "Each claim's figures matched to the text it cites."),
            _YOUR_REVIEW,
        ),
    ),
)

BY_SLUG = {s.slug: s for s in SECTIONS}

# ---------------------------------------------------------------------------
# Markets Reviews (quarterly, half-year, annual)
# ---------------------------------------------------------------------------


def _periodic(module: str, function: str) -> Callable[[DraftContext], CoordinatorReview]:
    """A build that imports its periodic module only when a draft runs (tests replace the function)."""

    def build(ctx: DraftContext) -> CoordinatorReview:
        import importlib

        from cytonn_weekly.periodic.common import PeriodContext

        mod = importlib.import_module(f"cytonn_weekly.periodic.{module}")
        pctx = PeriodContext.of(ctx.report_type, ctx.period, today=ctx.today, text=ctx.text, db_path=ctx.db_path)
        return getattr(mod, function)(pctx, **_observer(ctx))

    return build


_CHECK = ("Check", "Every table figure exact-matched to its source; every drafted figure matched to the text it cites.")
_STUBS_STEP = ("Mark what is missing", "Each part of the real section the tool cannot produce is listed for you to acknowledge, "
               "with why and what would unblock it.")

# The real issues' own headings, verbatim (curly apostrophes as printed), per type.
_SUBSECTIONS: dict[str, dict[str, tuple[str, ...]]] = {
    QUARTERLY: {
        "executive_summary": ("Global Markets Review:", "Sub-Saharan Africa Regional Review:", "Kenya Macroeconomic Review:",
                              "Fixed Income:", "Equities:", "Real Estate:", "Digital Payments:"),
        "company_updates": ("Investment Updates:", "Hospitality Updates:"),
        "global_markets": ("Global Economic Growth:", "Global Commodities Market Performance:",
                           "Global Equities Market Performance:"),
        "ssa": ("Currency Performance:", "African Eurobonds:", "Equities Market Performance:",
                "Global Markets and Sub-Saharan Africa Performance Summary and Outlook"),
        "kenya_macro": ("(GDP, with the Kenya 2026 Growth Projections table)",
                        "Stanbic Bank’s August 2026 Purchasing Manager’s Index (PMI)", "Inflation:",
                        "September 2026 Inflation", "The Kenyan Shilling:", "Monetary Policy:", "Fiscal Policy:"),
        "fixed_income": ("(T-bills over the quarter and the week)", "Primary T-Bond Auctions in H1’2026 [sic, the table is Q3]",
                         "Secondary Bond Market Activity:", "Bond Turnover:", "Yield Curve:", "Money Market Performance",
                         "Liquidity:", "Kenya Eurobonds:", "Weekly Highlights", "Q3’2026 Notable Highlights:"),
        "equities": ("Market Performance:", "Universe of Coverage:", "Kenyan Q3’2026 Equities Outlook",
                     "Notable Highlights in Q3’2026 include:"),
        "real_estate": ("(GDP contribution, initiatives, construction financing)", "Sectoral Market Performance",
                        "Industry Report", "July Leading Economic Indicators (LEI)", "Residential Sector",
                        "Detached Units Performance", "Apartments Performance", "Commercial Office Sector",
                        "Retail Sector", "Hospitality Sector", "Land Sector", "Infrastructure Sector",
                        "Real Estate Investments Trusts (REITs)", "Real Estate Performance Summary and Outlook"),
        "digital_payments": ("I to IV: the week's highlights (Visa, Mastercard, American Express, PayPal)",
                             "Digital Payments Stock Performance",
                             "Other notable digital payments sector highlights during the month of September 2026"),
    },
    HALF_YEAR: {
        "executive_summary": ("Global Markets Review:", "Sub-Saharan Africa Regional Review:", "Kenya Macroeconomic Review:",
                              "Fixed Income:", "Equities:", "Real Estate:", "Digital Payments:"),
        "company_updates": ("Investment Updates:", "Hospitality Updates:"),
        "global_markets": ("Global Economic Growth:", "Global Commodities Market Performance:",
                           "Global Equities Market Performance:"),
        "ssa": ("Currency Performance:", "African Eurobonds:", "Equities Market Performance:",
                "Global Markets and Sub-Saharan Africa Performance Summary and Outlook"),
        "kenya_macro": ("Kenya Macro Economic Review (GDP, with the Kenya 2026 Growth Projections table)",
                        "Stanbic Bank’s May 2026 Purchasing Manager’s Index (PMI)", "Inflation:",
                        "June 2026 Inflation", "The Kenyan Shilling:", "Monetary Policy:", "Fiscal Policy:"),
        "fixed_income": ("(T-bills over the half and the week)", "Primary T-Bond Auctions in H1’2026",
                         "Secondary Bond Market Activity:", "Bond Turnover:", "Yield Curve:", "Money Market Performance",
                         "Liquidity:", "Kenya Eurobonds:", "Q2’2026 Notable Highlights:"),
        "equities": ("Market Performance:", "Universe of Coverage:", "Weekly Highlights",
                     "Kenyan Q3’2026 Equities Outlook", "Q2’2026 Notable Highlights:"),
        "real_estate": ("(GDP contribution, initiatives, construction financing)", "Sectoral Market Performance",
                        "Industry Report", "Residential Sector", "Detached Units Performance", "Apartments Performance",
                        "Commercial Office Sector", "Retail Sector", "Hospitality Sector", "Land Sector",
                        "Infrastructure Sector", "Real Estate Investments Trusts (REITs)",
                        "Real Estate Performance Summary and Outlook"),
        "digital_payments": ("The week's highlights", "Digital Payments Stock Performance",
                             "Other notable digital payments sector highlights during H1’2026 Include:"),
    },
    ANNUAL: {
        "executive_summary": ("Global Markets Review:", "Sub-Saharan Africa Regional Review:", "Kenya Macro Economic Review:",
                              "Fixed Income:", "Equities:", "Real Estate:"),
        "company_updates": ("Investment Updates:", "Hospitality Updates:"),
        "global_markets": ("Global Economic Growth:", "Global Commodities Market Performance:",
                           "Global Equities Market Performance:"),
        "ssa": ("Currency Performance", "African Eurobonds:", "Equities Market Performance:"),
        "kenya_macro": ("Economic Growth:", "Kenyan Shilling:", "Inflation:", "December 2025 Inflation",
                        "Monetary Policy:", "2025 Key Highlights:", "FY’2025/2026 National Budget",
                        "Credit Facilities Extended to Kenya", "FY’2024/2025 KRA Revenue Performance",
                        "Balance of Payments", "Current account", "Credit Ratings",
                        "2025 Returns by Various Asset Classes:", "Macro-Economic & Business Environment Outlook (table)"),
        "fixed_income": ("T-Bills & T-Bonds Primary Auction:", "Primary T-Bond Auctions in FY’2025",
                         "Secondary Bond Market Activity:", "Money Market Performance:", "Liquidity:", "Kenya Eurobonds:"),
        "equities": ("Market Performance", "2025 Key Highlights", "I. Banking Sector Earnings",
                     "II. Insurance Sector Earnings", "Other Key Results", "III. Listings and Suspensions",
                     "IV. Liquidations", "V. Legislation and 0ther Developments [sic]",
                     "VI. Share Purchase and Consolidation", "Universe of coverage:"),
        "real_estate": ("(GDP contribution, initiatives, rental yields summary)", "Sectoral Market Performance",
                        "I. Residential Sector (A. Detached Units Performance, B. Apartments Performance)",
                        "II. Commercial Office Sector", "III. Retail Sector", "IV. Hospitality Sector",
                        "V. Mixed-Use Developments (MUDs)", "VI. Land Sector", "VII. Infrastructure Sector",
                        "VIII. Industrial Sector", "IX. Real Estate Investments Trusts (REITs)",
                        "Real Estate Performance Summary and Outlook"),
    },
}

_SSA_TITLE = {QUARTERLY: "Sub-Saharan Africa Region Review", HALF_YEAR: "Sub-Saharan Africa Region Review",
              ANNUAL: "Sub-Saharan Africa Regional Review"}


def _charts(module: str, report_type: str) -> tuple[str, ...]:
    import importlib

    return tuple(getattr(importlib.import_module(f"cytonn_weekly.periodic.{module}"), "CHARTS", {}).get(report_type, ()))


def _periodic_sections(report_type: str) -> tuple[SectionSpec, ...]:
    subs = _SUBSECTIONS[report_type]
    span = {QUARTERLY: "quarter", HALF_YEAR: "half-year", ANNUAL: "year"}[report_type]

    def spec(slug: str, title: str, module: str, function: str, steps: tuple[tuple[str, str], ...], **kw) -> SectionSpec:
        return SectionSpec(slug=slug, title=title, available=True, build=_periodic(module, function),
                           steps=steps + (_YOUR_REVIEW,), subsections=subs[slug], charts=_charts(module, report_type),
                           **kw)

    out = [
        spec("executive_summary", "Executive Summary", "executive_summary", "build_executive_summary_review", (
            ("Wait for approvals", "Every other drafted section of this report and period must be approved first."),
            ("Compose", "Each approved section's lead piece, carried verbatim with its sources. Nothing new is written."),
            ("Check", "The carried figures are matched to their cited text again."),
        ), requires_approved=True),
        spec("company_updates", "Company Updates", "company_updates", "build_company_updates_review", (
            ("Your text", "Paste the Investment Updates and Hospitality Updates. The tool never drafts Cytonn's own copy."),
        ), needs_text=True),
        spec("global_markets", "Global Markets Review", "global_markets", "build_global_markets_review", (
            ("Draft", f"Global growth (World Bank, IMF), commodities and equities over the {span}, every claim cited."),
            _CHECK,
        )),
        spec("ssa", _SSA_TITLE[report_type], "ssa", "build_ssa_review", (
            ("Draft", "The region's growth outlook and the period's Eurobond issues, every claim cited."),
            _STUBS_STEP, _CHECK,
        )),
        spec("kenya_macro", "Kenya Macro Economic Review", "kenya_macro", "build_kenya_macro_review", (
            ("Fetch", "KNBS's CPI release for the period's last month: the Major Inflation Changes table."),
            ("Draft", "GDP, inflation, the shilling, monetary and fiscal policy, every claim cited (KNBS, CBK, Treasury first)."),
            _STUBS_STEP, _CHECK,
        )),
        spec("fixed_income", "Fixed Income", "fixed_income", "build_fixed_income_review", (
            ("Fetch", f"Every CBK T-bond auction result of the {span} and of the same {span} a year earlier: the Bond Issuances table."),
            ("Draft", "The period's notable highlights (MPC, government borrowing), every claim cited."),
            _STUBS_STEP, _CHECK,
        )),
        spec("equities", "Equities", "equities", "build_equities_review", (
            ("Fetch", "NSE index levels with the week's and the year's moves, from afx.kwayisi.org."),
            ("Draft", f"Up to three of the {span}'s listed-company, banking and regulatory highlights, every claim cited."),
            _STUBS_STEP, _CHECK,
        )),
        spec("real_estate", "Real Estate", "real_estate", "build_real_estate_review", (
            ("Draft", f"The sector overview and up to four sectors' developments over the {span}, every claim cited."),
            ("Fetch REITs", "Acorn D-REIT, Acorn I-REIT and ILAM Fahari from the latest NSE Ibuka weekly PDF."),
            _STUBS_STEP, _CHECK,
        )),
    ]
    if report_type != ANNUAL:
        out.append(spec("digital_payments", "Digital Payments", "digital_payments", "build_digital_payments_review", (
            ("Draft the week", "The week's four highlights, as in the weekly report, from company investor pages."),
            ("Fetch prices", f"The seven companies' prices, including the {span}'s start and end, from Yahoo Finance."),
            ("Draft the month", "Other notable digital payments sector highlights, every claim cited."),
            _CHECK,
        )))
    return tuple(out)


# ---------------------------------------------------------------------------
# Companion research reports
# ---------------------------------------------------------------------------


def _companion_sections(kind: str) -> tuple[SectionSpec, ...]:
    from cytonn_weekly.periodic import companion

    k = companion.BY_KIND[kind]
    return tuple(
        SectionSpec(slug=f"{kind}.section_{n + 1}", title=title, available=False, reason=companion.BLOCKED_REASON,
                    unblock=companion.UNBLOCK, built_parts=companion.BUILT_PARTS)
        for n, title in enumerate(k.sections)
    )


def companion_kinds() -> list[dict[str, Any]]:
    from cytonn_weekly.periodic import companion

    return [{"slug": k.slug, "title": k.title, "issue": k.issue, "published": k.published} for k in companion.KINDS]


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, tuple[SectionSpec, ...]] = {WEEKLY: SECTIONS}


def sections_for(report_type: str, kind: Optional[str] = None) -> tuple[SectionSpec, ...]:
    """The report type's sections in report order (a companion report's: that kind's).  KeyError if unknown."""
    if report_type == COMPANION:
        if not kind:
            return ()
        return _companion_sections(kind)
    if report_type not in _REGISTRY:
        if report_type not in (QUARTERLY, HALF_YEAR, ANNUAL):
            raise KeyError(f"unknown report type {report_type!r}")
        _REGISTRY[report_type] = _periodic_sections(report_type)
    return _REGISTRY[report_type]


def spec_for(report_type: str, slug: str, kind: Optional[str] = None) -> Optional[SectionSpec]:
    if report_type == COMPANION and not kind and "." in slug:
        kind = slug.split(".", 1)[0]
    return next((s for s in sections_for(report_type, kind) if s.slug == slug), None)


def latest_runs(db_path: Optional[Union[Path, str]] = None, report_type: str = WEEKLY,
                period: str = "") -> dict[str, dict[str, Any]]:
    """{slug: {run_id, run_date, decision, decided_at}}: each section's newest review of this report and period.

    The defaults (weekly, no period label) are the reviews saved before report types existed.
    """
    sections.init_db(db_path)
    conn = sections._connect(db_path)
    try:
        rows = conn.execute(
            "SELECT r.section, r.run_id, r.run_date, r.decision, r.decided_at FROM coordinator_reviews r "
            "JOIN (SELECT section, MAX(run_id) AS run_id FROM coordinator_reviews "
            "      WHERE report_type = ? AND period = ? GROUP BY section) m "
            "ON r.run_id = m.run_id",
            (report_type, period),
        ).fetchall()
    finally:
        conn.close()
    return {r["section"]: {k: r[k] for k in ("run_id", "run_date", "decision", "decided_at")} for r in rows}


def is_this_week(run_date: str, today: Optional[date] = None) -> bool:
    """A run from the last seven days counts as this week's (the report goes out weekly)."""
    today = today or date.today()
    return date.fromisoformat(run_date) > today - timedelta(days=7)


def is_current(report_type: str, period: str, run_date: str, today: Optional[date] = None) -> bool:
    """Whether a section's newest run is the one to resume.

    An unlabelled weekly run is current while it is this week's; a run labelled with a
    period (any type) is that period's by definition, since lookups are per period.
    """
    if report_type == WEEKLY and not period:
        return is_this_week(run_date, today)
    return True


def section_slug(review: CoordinatorReview) -> str:
    """The slug a review's content belongs to; Digital Payments content predates the slug field."""
    return review.section.get("section") or "digital_payments"
