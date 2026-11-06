from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional, Sequence

from cytonn_weekly.report_types import ANNUAL, HALF_YEAR, QUARTERLY, WEEKLY, normalize_period, week_ending_of
from cytonn_weekly.weekly.week import latest_friday


@dataclass(frozen=True)
class Piece:
    """One piece of a section a source can be supplied for.

    ``subject`` is exactly what the provider is asked about: a brief's label or a company name. ``end`` is the last day of
    the window the draft gives the provider; the piece's sources are filed under the Friday on or before it
    (common/sources.py), which for a weekly report is its own Friday.
    """

    subject: str
    end: date
    start: Optional[date] = None        # first day of the piece's window; None is the six days up to ``end`` (a weekly piece)
    domains: tuple[str, ...] = field(default=(), compare=False)       # the brief's preferred domains, which the gather step tries first
    market: bool = field(default=True, compare=False)                 # False for a global company: the gather step adds no market name to its query

    @property
    def window(self) -> tuple[date, date]:
        return self.start or self.end - timedelta(days=6), self.end


# A section's periodic module, by slug; each has briefs(ctx) with the labels the draft will ask about.
_PERIODIC = {"global_markets": "global_markets", "ssa": "ssa", "kenya_macro": "kenya_macro",
             "fixed_income": "fixed_income", "equities": "equities", "real_estate": "real_estate"}


def pieces_for(report_type: str, period: str, slug: str, *, sections: Sequence[str] = (),
               today: Optional[date] = None) -> Optional[list[Piece]]:
    """The pieces a section's draft will ask the provider about, with the day each is asked as of.

    None: the section calls no provider (Company Updates, the Executive Summary) or is not drafted yet. An empty list: the
    section has pieces but none can be named yet (a Focus with no typed section titles). ``sections`` is the Focus's typed
    titles, as a draft takes them. Read from the same briefs and company list the builders use, and the dates they pass:
    the weekly sections' Friday (weekly Fixed Income and Equities pass the week ending; Real Estate, Digital Payments and
    Focus are given the Friday as their ``today``), and a Markets Review's window end (its Digital Payments companies
    are asked as of the day of the draft, as that builder does, so ``today`` is when this is called).
    """
    today = today or date.today()
    if report_type == WEEKLY:
        friday = week_ending_of(period) or latest_friday(today)
        if slug == "fixed_income":
            from cytonn_weekly.fixed_income.weekly import BRIEFS
            return [Piece(b.label, friday, domains=tuple(b.preferred_domains)) for b in BRIEFS]
        if slug == "equities":
            from cytonn_weekly.equities.review_run import BRIEFS
            return [Piece(b.label, friday, domains=tuple(b.preferred_domains)) for b in BRIEFS]
        if slug == "real_estate":
            from cytonn_weekly.real_estate.review_run import BRIEFS
            return [Piece(b.label, friday, domains=tuple(b.preferred_domains)) for b in BRIEFS]
        if slug == "digital_payments":
            from cytonn_weekly.digital_payments.highlights import HIGHLIGHT_COMPANIES
            return [Piece(c["name"], friday, domains=(c["ir_domain"],), market=False) for c in HIGHLIGHT_COMPANIES]
        if slug == "focus":
            from cytonn_weekly.focus.review_run import clean_title, is_closing
            titles = [clean_title(t) for t in sections]
            return [Piece(t, friday) for i, t in enumerate(titles) if not (i == len(titles) - 1 and is_closing(t))]
        return None
    if report_type not in (QUARTERLY, HALF_YEAR, ANNUAL):
        return None
    from cytonn_weekly.periodic.common import PeriodContext

    ctx = PeriodContext.of(report_type, normalize_period(report_type, period), today=today)
    if slug == "digital_payments":
        from cytonn_weekly.digital_payments.highlights import HIGHLIGHT_COMPANIES
        from cytonn_weekly.periodic.digital_payments import other_highlights_brief

        brief, window = other_highlights_brief(ctx)
        return ([Piece(c["name"], ctx.today, domains=(c["ir_domain"],), market=False) for c in HIGHLIGHT_COMPANIES]
                + [Piece(brief.label, window[1], window[0], tuple(brief.preferred_domains), market=False)])
    if slug in _PERIODIC:
        import importlib

        module = importlib.import_module(f"cytonn_weekly.periodic.{_PERIODIC[slug]}")
        return [Piece(b.label, ctx.end, ctx.start, tuple(b.preferred_domains)) for b in module.briefs(ctx)]
    return None
