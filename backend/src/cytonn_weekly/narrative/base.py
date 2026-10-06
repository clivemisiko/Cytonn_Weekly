"""The drafting-provider contract for narrative pieces in any section.

Digital Payments' ``DraftingProvider`` (digital_payments/providers/base.py) is
company-shaped: one company, its investor relations domain, one highlight.  The
other sections draft from a *brief* instead - a theme to search for this week
(Real Estate: "mortgage lending"), or the coordinator's chosen topic (Focus).
``NarrativeProvider`` is that same contract with a brief in place of a company:

* it returns the existing ``HighlightResult`` unchanged (``company`` holds the
  brief's label, ``ir_domain`` its preferred domains), so claims, links,
  ``drafted_by`` and warnings mean exactly what they mean for Digital Payments;
* the search is preferred-domains-first, then the open web, the same two-pass
  shape as IR-first-then-web;
* ``NO_STORY`` is still a legitimate answer, and is never padded.

The concrete providers subclass the Digital Payments ones' building blocks
(anthropic_provider._collect, LocalProvider's Ollama/Exa calls) rather than
re-implementing them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from cytonn_weekly.digital_payments.providers.base import HighlightResult


@dataclass(frozen=True)
class NarrativeBrief:
    """What to search for and how to write it up.

    ``label``: short name shown to the coordinator ("Residential and mortgage lending").
    ``focus``: what qualifies, in a sentence the model is given verbatim.
    ``preferred_domains``: searched first; the open web only if they yield nothing.
    ``opener``: required first words of the paragraph (None for free-form, e.g. Focus).
    ``report``: the kind of report, as the prompt names it ("weekly", "quarterly markets
    review"); ``window``: what the search window is called ("report week", "report
    period").  The defaults are the weekly report's, word for word, so the weekly prompts
    are unchanged; the quarterly, half-year and annual reviews set both.
    """

    id: str
    section: str
    label: str
    focus: str
    words: tuple[int, int] = (100, 180)
    opener: Optional[str] = "During the week,"
    preferred_domains: tuple[str, ...] = field(default_factory=tuple)
    max_searches: int = 5
    report: str = "weekly"
    window: str = "report week"


class NarrativeProvider(ABC):
    """Swappable backend for brief-driven narrative drafting (Anthropic or local)."""

    drafted_by: str

    @abstractmethod
    def draft_piece(self, brief: NarrativeBrief, *, start: date, end: date, today: date) -> HighlightResult:
        """Find and draft one piece for ``brief`` from the report week ``start``..``end``.

        Returns ``no_story=True`` when nothing in the week qualifies.  Every factual
        claim must carry the URL (and, where the provider has one, the cited span)
        it was drafted from.
        """
