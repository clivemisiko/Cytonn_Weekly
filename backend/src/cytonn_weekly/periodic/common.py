"""What every Markets Review section shares: its period, its stubs, its briefs, its content shape."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, Union

from cytonn_weekly.common.review import numbered, unavailable_block
from cytonn_weekly.common.run_events import Observer
from cytonn_weekly.narrative.base import NarrativeBrief, NarrativeProvider
from cytonn_weekly.narrative.drafter import draft_pieces
from cytonn_weekly.report_types import (
    ANNUAL,
    HALF_YEAR,
    PERIODIC,
    QUARTERLY,
    TYPES,
    normalize_period,
    period_window,
    prose_label,
    year_ago,
)

# How the drafting prompt names each report ("You draft one item for the X section of a
# <report> investment research report on Kenya").
REPORT_NAMES = {
    QUARTERLY: "quarterly markets review",
    HALF_YEAR: "half-year markets review",
    ANNUAL: "annual markets review",
}

# The issue each type's structure and chart lists were read from (2026-10-05).
REFERENCE_ISSUES = {
    QUARTERLY: "Cytonn Q3' 2026 Markets Review (4 Oct 2026)",
    HALF_YEAR: "Cytonn H1'2026 Markets Review (5 July 2026)",
    ANNUAL: "Cytonn Annual Markets Review - 2025 (4 Jan 2026)",
}


@dataclass(frozen=True)
class PeriodContext:
    """One Markets Review draft: which report, which period, and what the coordinator supplied."""

    report_type: str
    period: str
    start: date
    end: date
    today: date
    text: Optional[str] = None                       # Company Updates only: the coordinator's text
    db_path: Optional[Union[Path, str]] = None       # Executive Summary only: where the approved sections are

    @classmethod
    def of(cls, report_type: str, period: str, *, today: Optional[date] = None, text: Optional[str] = None,
           db_path: Optional[Union[Path, str]] = None) -> "PeriodContext":
        if report_type not in PERIODIC:
            raise ValueError(f"{report_type!r} is not a Markets Review type")
        period = normalize_period(report_type, period)
        start, end = period_window(report_type, period)
        return cls(report_type, period, start, end, today or date.today(), text, db_path)

    @property
    def prose(self) -> str:
        """The period as the report's prose writes it: "Q3’2026"."""
        return prose_label(self.period)

    @property
    def year_ago(self) -> str:
        return year_ago(self.period)

    @property
    def report_name(self) -> str:
        return REPORT_NAMES[self.report_type]

    @property
    def report_title(self) -> str:
        return TYPES[self.report_type].title

    @property
    def window(self) -> tuple[date, date]:
        return self.start, self.end


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Stub:
    """A real part of the report the tool cannot produce, with why and what would change that.

    ``fetch`` is the module's own function that raises NotImplementedError with the
    module's ``*_BLOCKED_REASON`` (the kcb_email.py pattern); ``block()`` is how the
    coordinator sees it: an ``unavailable`` block they must explicitly acknowledge.
    """

    id: str
    title: str
    blocked_reason: str
    unblock: str
    fetch: Callable[..., Any] = field(compare=False)

    def block(self) -> dict[str, Any]:
        return unavailable_block(self.id, self.title, self.blocked_reason, self.unblock)


# ---------------------------------------------------------------------------
# Narrative briefs over the period
# ---------------------------------------------------------------------------

def period_brief(ctx: PeriodContext, id: str, section: str, label: str, focus: str,
                 preferred_domains: tuple[str, ...] = (), words: tuple[int, int] = (120, 260),
                 opener: Optional[str] = None) -> NarrativeBrief:
    """A brief searched over the whole period rather than the week.

    No opener is imposed by default: the reviews open their subsections variously ("During
    Q3’2026, ...", "In Q3’2026, ...", "According to the World Bank ..."), so forcing one
    would invent a rule the report does not follow.
    """
    return NarrativeBrief(
        id=id, section=section, label=label, focus=f"{focus}, published during {ctx.prose} ({ctx.start:%d %b %Y} "
        f"to {ctx.end:%d %b %Y}) or the latest release covering it", words=words, opener=opener,
        preferred_domains=preferred_domains, report=ctx.report_name, window="report period",
    )


def draft_period(briefs: Sequence[NarrativeBrief], target: int, ctx: PeriodContext,
                 provider: Optional[NarrativeProvider] = None, on_event: Optional[Observer] = None) -> dict[str, Any]:
    """draft_pieces over the period's window instead of the report week."""
    return draft_pieces(briefs, target, provider=provider, today=ctx.today, window=ctx.window, on_event=on_event)


def no_draft() -> dict[str, Any]:
    """The draft_pieces shape for a section that drafts nothing (Company Updates, the summary)."""
    return {"pieces": [], "shortfall": 0, "warnings": []}


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------

def compose(slug: str, title: str, ctx: PeriodContext, blocks: list[dict[str, Any]], *,
            draft: Optional[dict[str, Any]] = None, expected: int = 0, warnings: Sequence[str] = (),
            charts: Optional[dict[str, tuple[str, ...]]] = None) -> dict[str, Any]:
    """The section content every Markets Review section stores (common/review.py's shape, plus the period).

    ``week_start``/``week_end`` carry the period too, so a screen written for the weekly
    report still shows a date range; ``period_start``/``period_end`` say what it is.
    """
    draft = draft or no_draft()
    chart_list = list((charts or {}).get(ctx.report_type, ()))
    return {
        "section": slug, "title": title, "report_type": ctx.report_type, "period": ctx.period,
        "period_start": ctx.start.isoformat(), "period_end": ctx.end.isoformat(),
        "week_start": ctx.start.isoformat(), "week_end": ctx.end.isoformat(),
        "blocks": numbered(blocks), "pieces_found": len(draft["pieces"]), "pieces_expected": expected,
        "shortfall": draft["shortfall"], "warnings": list(draft["warnings"]) + list(warnings),
        "chart_notes": chart_list,
        "chart_reference": REFERENCE_ISSUES[ctx.report_type] if chart_list else None,
    }
