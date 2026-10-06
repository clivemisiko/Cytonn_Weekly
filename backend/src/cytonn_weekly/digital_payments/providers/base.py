"""The drafting-provider contract for the Digital Payments highlights drafter.

A provider does the two LLM-judgment jobs: finding and drafting one company's
highlight (IR site first, then a general search), and drafting the closing
outlook paragraph.  Everything provider-independent - company priority order,
the four-highlight target, shortfall/warning bookkeeping, outlook statistics,
section composition - stays in ``digital_payments.highlights``.

This module also holds the format contract every provider must draft to (word
ranges, opener, NO_STORY) and the small helpers that validate against it, so the
providers cannot drift apart on what a valid highlight looks like.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional, Sequence

NO_STORY = "NO_STORY"
BODY_WORDS = (100, 180)
OUTLOOK_WORDS = (80, 120)
OPENER = "During the week,"

# What counts as a highlight-worthy story, worded once so every provider applies the
# same test (and so falls back from the IR site to the open web in the same cases).
GENUINE_ANNOUNCEMENT = (
    "a product launch, partnership, earnings or business update, research release, "
    "or similar thing the company itself announced"
)
NOT_GENUINE = (
    "analysis, commentary, opinion, investor-advice or market-chatter pieces about "
    "the company or its stock, or are about something else entirely"
)

SCOPE_IR = "investor_relations"
SCOPE_WEB = "web_fallback"

OUTLOOK_SYSTEM = f"""\
You write the closing sector-outlook paragraph of the Digital Payments section \
of a weekly investment research report (formal, third person, forward-looking).

Write ONE paragraph of {OUTLOOK_WORDS[0]}-{OUTLOOK_WORDS[1]} words that synthesizes \
the week's highlights together with the stock-table statistics provided. Use \
only the highlights text and the statistics given - introduce no new external \
facts or figures, and quote statistics exactly as given. No headings, no links, \
no formatting marks.
"""

LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def strip_links(text: str) -> str:
    return LINK_RE.sub(r"\1", text)


def word_count(text: str) -> int:
    return len(text.split())


def is_about_company(body: str, aliases: Sequence[str]) -> bool:
    """True if the paragraph's opening names the company (or one of its aliases)."""
    lead = body[:150].lower()
    return any(a.lower() in lead for a in aliases)


def outlook_user_message(stats: dict[str, Any], highlights: list[dict[str, Any]]) -> str:
    """The outlook prompt body, shared so every provider sees identical inputs."""
    hl = "\n\n".join(f"{h['headline']}\n{h['body']}" for h in highlights) or "(none)"
    stat_lines = "\n".join(f"- {k}: {v}" for k, v in stats.items())
    return (
        f"Highlights:\n{hl}\n\nStock table statistics "
        f"(average across companies, week-over-week / year-to-date % price change):\n{stat_lines}"
    )


@dataclass
class HighlightResult:
    """One company's highlight, or NO_STORY (``no_story`` True, empty paragraph).

    ``paragraph`` is plain text; ``paragraph_md`` is the same text with inline
    source hyperlinks.  ``claims`` is a list of {text, url, title, cited_text},
    the exact source each claim is checked against by the checking layer.
    ``warnings`` belong to this highlight; ``draft_warnings`` are provider-level
    notes (e.g. a discarded off-topic story) that go to the section's warnings.
    ``drafted_by`` identifies provider + model, e.g. "anthropic:claude-sonnet-5-5".
    """

    company: str
    search_scope: Optional[str]
    ir_domain: str
    drafted_by: str
    no_story: bool = False
    headline: str = ""
    paragraph: str = ""
    paragraph_md: str = ""
    word_count: int = 0
    links: list[dict[str, str]] = field(default_factory=list)
    claims: list[dict[str, str]] = field(default_factory=list)
    citations: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    draft_warnings: list[str] = field(default_factory=list)


@dataclass
class OutlookResult:
    """The outlook paragraph (plain text, unformatted) plus the stats it was given."""

    text: str
    stats: dict[str, Any]
    drafted_by: str


class DraftingProvider(ABC):
    """Swappable backend for the Weekly Highlights drafter."""

    @abstractmethod
    def find_highlight(
        self,
        company: str,
        ir_domain: str,
        *,
        start: date,
        end: date,
        today: date,
        aliases: Optional[Sequence[str]] = None,
        style_examples: str = "",
    ) -> HighlightResult:
        """Find and draft one highlight for ``company`` from report week start..end.

        Searches the company's IR domain first and falls back to a general
        search only if that yields no usable story; the scope that produced the
        story is recorded in ``search_scope``.  Returns a result with
        ``no_story`` True if neither does.  ``aliases`` (default: just the
        company name) confirm a story is actually about the company.
        """

    @abstractmethod
    def draft_outlook(
        self, table_stats: dict[str, Any], highlights: list[dict[str, Any]]
    ) -> OutlookResult:
        """Draft the closing outlook paragraph from the week's highlights and table stats.

        ``highlights`` are highlight dicts with at least ``headline`` and ``body``.
        No web search is used and no new facts may be introduced.
        """
