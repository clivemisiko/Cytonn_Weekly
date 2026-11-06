"""Local narrative provider (DEVELOPMENT ONLY - not for publication).

A subclass of the Digital Payments ``LocalProvider``, reusing its Ollama check,
Exa search and chat call unchanged; the brief-shaped prompt and validation are
shared (``digital_payments/providers/drafting.py``) with the Bedrock provider.  The same caveats apply: claims carry no
``cited_text`` (Exa returns page text, not cited spans), so the claim figure
check can never pass a local draft, only report it as unchecked.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from cytonn_weekly.digital_payments.providers import local_provider as dp_local
from cytonn_weekly.digital_payments.providers.base import SCOPE_WEB, HighlightResult
from cytonn_weekly.digital_payments.providers.drafting import (
    RESPONSE_SCHEMA,
    narrative_system,
    piece_from_reply,
    results_message,
)
from cytonn_weekly.narrative.anthropic_provider import SCOPE_PREFERRED
from cytonn_weekly.narrative.base import NarrativeBrief, NarrativeProvider


class LocalNarrativeProvider(dp_local.LocalProvider, NarrativeProvider):
    """Ollama model + Exa search, brief-driven."""

    def _brief_search(self, brief: NarrativeBrief, preferred: bool, start: date) -> list[dict[str, Any]]:
        query = f"Kenya {brief.label}: {brief.focus}"
        if preferred:
            return self._exa_search(query, start, list(brief.preferred_domains))
        return self._exa_search(query, start, exclude_domains=list(brief.blocked_domains) or None)

    def _draft(self, brief: NarrativeBrief, scope: str, results: list[dict[str, Any]],
               warnings: list[str]) -> HighlightResult | None:
        raw = self._chat(
            [{"role": "system", "content": narrative_system(brief)},
             {"role": "user", "content": results_message(brief.label, results)}],
            RESPONSE_SCHEMA,
            brief.max_tokens,
        )
        return piece_from_reply(raw, brief, scope, results, warnings,
                                who=self.WHO, label=self.LABEL, drafted_by=self.drafted_by)

    def draft_piece(self, brief: NarrativeBrief, *, start: date, end: date, today: date) -> HighlightResult:
        self._ensure_model()
        warnings: list[str] = []
        passes = [True, False] if brief.preferred_domains else [False]
        for preferred in passes:
            results = self._brief_search(brief, preferred, start)
            if not results:
                continue
            results = self._trim_results(results)
            res = self._draft(brief, SCOPE_PREFERRED if preferred else SCOPE_WEB, results, warnings)
            if res:
                res.draft_warnings = warnings
                return res
        return HighlightResult(company=brief.label, search_scope=None, ir_domain=", ".join(brief.preferred_domains),
                               drafted_by=self.drafted_by, no_story=True, draft_warnings=warnings)

    def complete(self, system: str, prompt: str, *, max_tokens: int) -> str:
        self._ensure_model()
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        return self._chat(messages, max_tokens=max_tokens).strip()
