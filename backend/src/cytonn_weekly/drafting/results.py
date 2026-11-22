from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

NO_STORY = "NO_STORY"

SCOPE_IR = "investor_relations"
SCOPE_WEB = "web_fallback"
SCOPE_PREFERRED = "preferred_sources"

# A snip is linked as snip:<id> (common/sources.from_snip); it is matched so its markdown never stays in the text.
LINK_RE = re.compile(r"\[([^\]]+)\]\(((?:https?://|snip:)[^)\s]+)\)")
SNIP = "snip:"


def strip_links(text: str) -> str:
    return LINK_RE.sub(r"\1", text)


def word_count(text: str) -> int:
    return len(text.split())


def is_about_company(body: str, aliases: Sequence[str]) -> bool:
    """True if the paragraph's opening names the company (or one of its aliases)."""
    lead = body[:150].lower()
    return any(a.lower() in lead for a in aliases)


@dataclass
class HighlightResult:
    """One company's highlight, or NO_STORY (``no_story`` True, empty paragraph).

    ``paragraph`` is plain text; ``paragraph_md`` is the same text with inline
    source hyperlinks.  ``claims`` is a list of {text, url, title, cited_text},
    the exact source each claim is checked against by the checking layer.
    ``warnings`` belong to this highlight; ``draft_warnings`` are provider-level
    notes (e.g. a discarded off-topic story) that go to the section's warnings.
    ``drafted_by`` identifies provider + model, e.g. "anthropic:claude-sonnet-5-5".
    ``reason`` is why there is no story when the provider knows a plainer reason than "nothing qualifying" (Bedrock with
    no sources supplied); empty otherwise, and a caller shows it in place of the generic sentence.
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
    reason: str = ""


@dataclass
class OutlookResult:
    """The outlook paragraph (plain text, unformatted) plus the stats it was given."""

    text: str
    stats: dict[str, Any]
    drafted_by: str
