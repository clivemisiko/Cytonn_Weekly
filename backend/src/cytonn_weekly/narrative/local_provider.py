"""Local narrative provider (DEVELOPMENT ONLY - not for publication).

A subclass of the Digital Payments ``LocalProvider``, reusing its Ollama check,
Exa search, chat call and search-results prompt unchanged; only the brief-shaped
prompt and validation are new.  The same caveats apply: claims carry no
``cited_text`` (Exa returns page text, not cited spans), so the claim figure
check can never pass a local draft, only report it as unchecked.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from cytonn_weekly.digital_payments.providers import local_provider as dp_local
from cytonn_weekly.digital_payments.providers.base import (
    LINK_RE,
    SCOPE_WEB,
    HighlightResult,
    strip_links,
    word_count,
)
from cytonn_weekly.narrative.anthropic_provider import SCOPE_PREFERRED
from cytonn_weekly.narrative.base import NarrativeBrief, NarrativeProvider


def _system(brief: NarrativeBrief) -> str:
    opener = f'begins exactly with "{brief.opener}"' if brief.opener else "is formal prose"
    return f"""\
You help draft one item for the {brief.section} section of a {brief.report} investment research report \
on Kenya (formal, data-forward, third person) from search results.

Subject: {brief.label}. What qualifies: {brief.focus}

Step 1 - judge the material. Decide whether the search results contain material that genuinely \
qualifies. Analysis, opinion pieces or unrelated material do not. Do not force a draft.

Step 2 - only if it qualifies: write a short headline and prose of {brief.words[0]} to \
{brief.words[1]} words that {opener}. Use ONLY facts stated in the search results; never add \
figures, dates, names or claims from memory. Embed sources as inline markdown hyperlinks, using \
only URLs given in the results.

Step 3 - list every factual claim in your text with the exact URL of the result that supports it.

If nothing qualifies, set is_genuine_announcement to false, explain briefly in reasoning, and leave \
headline and paragraph empty and claims an empty list.

Reply with JSON only."""


class LocalNarrativeProvider(dp_local.LocalProvider, NarrativeProvider):
    """Ollama model + Exa search, brief-driven."""

    def _brief_search(self, brief: NarrativeBrief, preferred: bool, start: date) -> list[dict[str, Any]]:
        query = f"Kenya {brief.label}: {brief.focus}"
        return self._exa_search(query, start, list(brief.preferred_domains) if preferred else None)

    def _draft(self, brief: NarrativeBrief, scope: str, results: list[dict[str, Any]],
               warnings: list[str]) -> HighlightResult | None:
        raw = self._chat(
            [{"role": "system", "content": _system(brief)},
             {"role": "user", "content": self._results_message(brief.label, results)}],
            dp_local._RESPONSE_SCHEMA,
        )
        try:
            out = json.loads(raw)
        except json.JSONDecodeError:
            warnings.append(f"{brief.label}: local model returned invalid JSON; discarded")
            return None
        if not out.get("is_genuine_announcement"):
            warnings.append(f"{brief.label}: local model judged the {scope} results not qualifying "
                            f"({' '.join((out.get('reasoning') or '').split())})")
            return None
        headline = (out.get("headline") or "").strip().strip("*").strip()
        paragraph_md = (out.get("paragraph") or "").strip()
        if not headline or not paragraph_md:
            warnings.append(f"{brief.label}: local model returned no headline/paragraph; discarded")
            return None
        by_url = {r.get("url"): r for r in results if r.get("url")}
        hl: list[str] = []
        links: list[dict[str, str]] = []

        def keep(m) -> str:
            if m.group(2) in by_url:
                links.append({"anchor": m.group(1), "url": m.group(2)})
                return m.group(0)
            hl.append(f"link to {m.group(2)} was not in the search results; unlinked")
            return m.group(1)

        body_md = LINK_RE.sub(keep, paragraph_md)
        body = strip_links(body_md)
        claims, citations = [], []
        for c in out.get("claims") or []:
            url, text = (c.get("url") or "").strip(), strip_links((c.get("claim") or "").strip())
            if url not in by_url:
                hl.append(f"claim cited a URL not in the search results; dropped: {url or '(empty)'}")
                continue
            if text:
                cite = {"url": url, "title": by_url[url].get("title") or "", "cited_text": ""}
                claims.append({"text": text, **cite})
                if cite not in citations:
                    citations.append(cite)
        n = word_count(body)
        if not brief.words[0] <= n <= brief.words[1]:
            hl.append(f"body is {n} words, outside {brief.words[0]}-{brief.words[1]}")
        if brief.opener and not body.startswith(brief.opener):
            hl.append(f'body does not open with "{brief.opener}"')
        if claims:
            hl.append("local provider: claims carry no cited_text (model-mapped URLs only)")
        else:
            hl.append("no cited claims recorded for this piece")
        return HighlightResult(
            company=brief.label, search_scope=scope, ir_domain=", ".join(brief.preferred_domains),
            drafted_by=self.drafted_by, headline=headline, paragraph=body, paragraph_md=body_md,
            word_count=n, links=links, claims=claims, citations=citations, warnings=hl,
        )

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
