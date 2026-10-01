"""Local drafting provider (DEVELOPMENT ONLY - not for publication).

Drafts with a small local model (Phi-4-mini via Ollama's HTTP API) and searches
with Exa, so the pipeline can be exercised end to end for free.  The search
step is the same IR-domain-first, general-fallback logic proved out in
scripts/check_exa_ir_sourcing.py, ported here so nothing in src/ depends on
scripts/.

The model first judges whether the search results contain a genuine company
announcement or only analysis/opinion; only a genuine one is drafted.  It then
drafts a paragraph in the house format and maps each factual claim to the
search-result URL that supports it.  Everything it returns is validated against
the search results (links and claim URLs must be results Exa returned), but a
small model's output is not a substitute for the production provider.  Its
claims carry no ``cited_text`` (Exa returns page text, not cited spans), so the
citation checker has less to verify against; each highlight says so.

Needs: Ollama running with the model pulled (``ollama pull phi4-mini``) and
EXA_API_KEY in the environment.  Uses httpx (already installed with anthropic).
"""

from __future__ import annotations

import json
import os
from datetime import date
from typing import Any, Optional, Sequence

import httpx

from cytonn_weekly.digital_payments.providers.base import (
    BODY_WORDS,
    LINK_RE,
    OPENER,
    OUTLOOK_SYSTEM,
    SCOPE_IR,
    SCOPE_WEB,
    GENUINE_ANNOUNCEMENT,
    NOT_GENUINE,
    DraftingProvider,
    HighlightResult,
    OutlookResult,
    is_about_company,
    outlook_user_message,
    strip_links,
    word_count,
)

MODEL = "phi4-mini"
DRAFTED_BY = f"local:{MODEL}"
OLLAMA_URL = "http://localhost:11434"
EXA_URL = "https://api.exa.ai/search"
NUM_RESULTS = 5
CONTEXT_CHARS_PER_RESULT = 3000  # enough text per result to draft from
NUM_CTX = 8192
OLLAMA_TIMEOUT = 600  # small local models on CPU can be slow

_HIGHLIGHT_SYSTEM = f"""\
You help draft one "Weekly Highlights" item for the Digital Payments section of a \
weekly investment research report (formal, data-forward, third person) from search results.

Step 1 - judge the material. Decide whether the search results contain a GENUINE \
COMPANY ANNOUNCEMENT by {{company}} ({GENUINE_ANNOUNCEMENT}). If the results \
are only {NOT_GENUINE}, that is NOT a genuine \
announcement. Do not force a draft in that case.

Step 2 - only if genuine: write a short headline and ONE paragraph of {BODY_WORDS[0]} to \
{BODY_WORDS[1]} words (no fewer than {BODY_WORDS[0]}, no more than {BODY_WORDS[1]}) that begins \
exactly with "{OPENER} {{company}}". Describe the announcement with concrete stats or \
quotes from the results, then end with 1-2 sentences of relevance or industry implications \
that contain no new figures. Use ONLY facts stated in the search results; never add \
figures, dates, names or claims from your own memory. Embed the source as an inline \
markdown hyperlink on a natural word or short phrase inside the paragraph, e.g. \
"released [new research](https://...)", using only URLs given in the results.

Step 3 - claim mapping: list every factual claim in your paragraph together with the \
exact URL of the single search result that supports it. Use URLs exactly as given. Do \
not invent URLs.

If the material is not a genuine announcement, set is_genuine_announcement to false, \
explain briefly in reasoning, and leave headline and paragraph as empty strings and \
claims as an empty list.

Reply with JSON only."""

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_genuine_announcement": {"type": "boolean"},
        "reasoning": {"type": "string"},
        "headline": {"type": "string"},
        "paragraph": {"type": "string"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"claim": {"type": "string"}, "url": {"type": "string"}},
                "required": ["claim", "url"],
            },
        },
    },
    "required": ["is_genuine_announcement", "reasoning", "headline", "paragraph", "claims"],
}


class LocalProvider(DraftingProvider):
    """Phi-4-mini (Ollama) + Exa.  ``http_client`` is injectable for tests."""

    def __init__(
        self,
        model: str = MODEL,
        ollama_url: str = OLLAMA_URL,
        exa_api_key: Optional[str] = None,
        http_client: Optional[httpx.Client] = None,
    ):
        self.model = model
        self.drafted_by = DRAFTED_BY if model == MODEL else f"local:{model}"
        self.ollama_url = ollama_url.rstrip("/")
        self._exa_api_key = exa_api_key
        self._http = http_client or httpx.Client(timeout=OLLAMA_TIMEOUT)
        self._model_checked = False

    # -- setup ---------------------------------------------------------------

    def _exa_key(self) -> str:
        key = self._exa_api_key or os.environ.get("EXA_API_KEY")
        if not key:
            raise RuntimeError("EXA_API_KEY is not set (the local provider searches with Exa).")
        return key

    def _ensure_model(self) -> None:
        """Fail with a one-line instruction if Ollama is down or the model is not pulled."""
        if self._model_checked:
            return
        try:
            resp = self._http.get(f"{self.ollama_url}/api/tags")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Cannot reach Ollama at {self.ollama_url} ({exc}). Start it with: ollama serve"
            ) from exc
        names = [m.get("name", "") for m in resp.json().get("models", [])]
        if not any(n == self.model or n.startswith(f"{self.model}:") for n in names):
            raise RuntimeError(f"Model '{self.model}' is not installed. Run: ollama pull {self.model}")
        self._model_checked = True

    # -- search (ported from scripts/check_exa_ir_sourcing.py) ---------------

    def _exa_search(self, query: str, start: date, include_domains: Optional[list[str]] = None):
        body: dict[str, Any] = {
            "query": query,
            "numResults": NUM_RESULTS,
            "startPublishedDate": f"{start.isoformat()}T00:00:00.000Z",
            "contents": {"text": {"maxCharacters": CONTEXT_CHARS_PER_RESULT}},
        }
        if include_domains:
            body["includeDomains"] = include_domains
        resp = self._http.post(
            EXA_URL, headers={"x-api-key": self._exa_key(), "Content-Type": "application/json"}, json=body
        )
        resp.raise_for_status()
        return resp.json().get("results", [])

    def _search(self, company: str, ir_domain: str, scope: str, start: date) -> list[dict[str, Any]]:
        if scope == SCOPE_IR:
            return self._exa_search(f"{company} news announcement", start, [ir_domain])
        return self._exa_search(f"{company} recent news", start)

    # -- drafting ------------------------------------------------------------

    def _chat(self, messages: list[dict[str, str]], schema: Optional[dict] = None) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "options": {"temperature": 0, "num_ctx": NUM_CTX},
            "messages": messages,
        }
        if schema:
            payload["format"] = schema
        resp = self._http.post(f"{self.ollama_url}/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    @staticmethod
    def _results_message(company: str, results: list[dict[str, Any]]) -> str:
        blocks = []
        for i, r in enumerate(results, 1):
            text = " ".join((r.get("text") or "").split())[:CONTEXT_CHARS_PER_RESULT]
            blocks.append(
                f"[Result {i}]\nTitle: {r.get('title') or '(no title)'}\n"
                f"URL: {r.get('url')}\nPublished: {r.get('publishedDate') or 'n/a'}\nText: {text}"
            )
        return f"Company: {company}\n\nSearch results:\n\n" + "\n\n".join(blocks)

    def _draft_from_results(
        self, company: str, ir_domain: str, scope: str, aliases: Sequence[str],
        results: list[dict[str, Any]], warnings: list[str],
    ) -> Optional[HighlightResult]:
        raw = self._chat(
            [
                {"role": "system", "content": _HIGHLIGHT_SYSTEM.replace("{company}", company)},
                {"role": "user", "content": self._results_message(company, results)},
            ],
            _RESPONSE_SCHEMA,
        )
        try:
            out = json.loads(raw)
        except json.JSONDecodeError:
            warnings.append(f"{company}: local model returned invalid JSON for the {scope} results; discarded")
            return None
        if not out.get("is_genuine_announcement"):
            reason = " ".join((out.get("reasoning") or "").split())
            warnings.append(
                f"{company}: local model judged the {scope} results not a genuine announcement ({reason})"
            )
            return None
        paragraph_md = (out.get("paragraph") or "").strip()
        headline = (out.get("headline") or "").strip().strip("*").strip()
        if not paragraph_md or not headline:
            warnings.append(f"{company}: local model said genuine but returned no headline/paragraph; discarded")
            return None

        by_url = {r.get("url"): r for r in results if r.get("url")}
        hl_warnings: list[str] = []

        # Keep only links whose URL Exa actually returned.
        links: list[dict[str, str]] = []

        def _keep(m) -> str:
            anchor, url = m.group(1), m.group(2)
            if url in by_url:
                links.append({"anchor": anchor, "url": url})
                return m.group(0)
            hl_warnings.append(f"link to {url} was not in the search results; unlinked")
            return anchor

        body_md = LINK_RE.sub(_keep, paragraph_md)
        body = strip_links(body_md)
        if not is_about_company(body, aliases):
            warnings.append(f"{company}: discarded a story that is not about the company ({headline!r})")
            return None

        claims: list[dict[str, str]] = []
        citations: list[dict[str, str]] = []
        for c in out.get("claims") or []:
            url, text = (c.get("url") or "").strip(), strip_links((c.get("claim") or "").strip())
            if url not in by_url:
                hl_warnings.append(f"claim cited a URL not in the search results; dropped: {url or '(empty)'}")
                continue
            if not text:
                continue
            cite = {"url": url, "title": by_url[url].get("title") or "", "cited_text": ""}
            claims.append({"text": text, **cite})
            if cite not in citations:
                citations.append(cite)

        n = word_count(body)
        if not BODY_WORDS[0] <= n <= BODY_WORDS[1]:
            hl_warnings.append(f"body is {n} words, outside {BODY_WORDS[0]}-{BODY_WORDS[1]}")
        if not body.startswith(OPENER):
            hl_warnings.append(f'body does not open with "{OPENER}"')
        if not links:
            hl_warnings.append("no inline source hyperlink in the body")
        if not claims:
            hl_warnings.append("no cited claims recorded for this highlight")
        else:
            hl_warnings.append(
                "local provider: claims carry no cited_text (model-mapped URLs only, not provider-cited spans)"
            )
        for link in links:
            published = by_url[link["url"]].get("publishedDate")
            if published:
                link["page_age"] = published

        return HighlightResult(
            company=company,
            search_scope=scope,
            ir_domain=ir_domain,
            drafted_by=self.drafted_by,
            headline=headline,
            paragraph=body,
            paragraph_md=body_md,
            word_count=n,
            links=links,
            claims=claims,
            citations=citations,
            warnings=hl_warnings,
        )

    def find_highlight(
        self,
        company: str,
        ir_domain: str,
        *,
        start: date,
        end: date,
        today: date,
        aliases: Optional[Sequence[str]] = None,
        style_examples: str = "",  # accepted for interface parity; the local prompt does not use it
    ) -> HighlightResult:
        self._ensure_model()
        aliases = list(aliases or [company])
        warnings: list[str] = []
        for scope in (SCOPE_IR, SCOPE_WEB):
            results = self._search(company, ir_domain, scope, start)
            if not results:
                continue
            res = self._draft_from_results(company, ir_domain, scope, aliases, results, warnings)
            if res:
                res.draft_warnings = warnings
                return res
        return HighlightResult(
            company=company, search_scope=None, ir_domain=ir_domain,
            drafted_by=self.drafted_by, no_story=True, draft_warnings=warnings,
        )

    def draft_outlook(
        self, table_stats: dict[str, Any], highlights: list[dict[str, Any]]
    ) -> OutlookResult:
        self._ensure_model()
        text = self._chat(
            [
                {"role": "system", "content": OUTLOOK_SYSTEM},
                {"role": "user", "content": outlook_user_message(table_stats, highlights)},
            ]
        ).strip()
        return OutlookResult(text=text, stats=table_stats, drafted_by=self.drafted_by)
