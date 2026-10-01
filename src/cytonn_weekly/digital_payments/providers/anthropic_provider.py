"""Anthropic drafting provider (production default).

Claude with the native web search tool finds news from the current report week
about one company and drafts its highlight.  The company's own investor
relations site is searched first (``allowed_domains``), then the open web only
if that returned no story.  The outlook paragraph is a separate, search-free
call.

Each highlight records, for every span of text the search tool cited, the exact
source URL, title and cited text (``claims``) - what the checking layer verifies
against.  Inline hyperlinks in the paragraph are only kept if the URL was
actually returned by the search tool.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional, Sequence

import anthropic

from cytonn_weekly.digital_payments.providers.base import (
    BODY_WORDS,
    GENUINE_ANNOUNCEMENT,
    LINK_RE as _LINK_RE,
    NO_STORY,
    NOT_GENUINE,
    OPENER,
    OUTLOOK_SYSTEM,
    SCOPE_IR,
    SCOPE_WEB,
    DraftingProvider,
    HighlightResult,
    OutlookResult,
    is_about_company,
    outlook_user_message,
    strip_links as _strip_links,
    word_count as _word_count,
)

MODEL = "claude-sonnet-5-5"
DRAFTED_BY = "anthropic:claude-sonnet-5"
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
MAX_TOKENS = 6000
MAX_CONTINUATIONS = 3  # server-side search turns can pause; resume a bounded number of times

_HIGHLIGHTS_SYSTEM = f"""\
You draft one "Weekly Highlights" item for the Digital Payments section of a \
weekly investment research report (formal, data-forward, third person).

Scope: news about the single company named in the user message ONLY. Never \
write about any other company, and no general industry news.

Rules:
- Use web search to find a story about that company published during the \
report week given in the user message. Do not use stale news.
- A story qualifies only if it is a GENUINE COMPANY ANNOUNCEMENT by the company \
({GENUINE_ANNOUNCEMENT}). If the search results are only {NOT_GENUINE}, that is \
NOT a genuine announcement: do not draft from it.
- If no story about that company genuinely qualifies, reply with exactly \
"{NO_STORY}" and nothing else. Never pad with off-topic or older news, and never \
force a draft from non-announcement content.
- Every factual claim (stat, quote, specific detail) must come from the search \
results you retrieved. Never rely on memory.
- Output format, exactly: a line "### <headline>" (a short headline describing \
the announcement) followed by ONE paragraph of {BODY_WORDS[0]}-{BODY_WORDS[1]} \
words. No introduction, closing remarks or other headings.
- The paragraph opens with "{OPENER} [Company] ...", blends the announcement \
with concrete stats/quotes from the source, and ends with 1-2 sentences of \
relevance or industry implications (e.g. "This reflects / underscores ..."). \
Keep that closing interpretation free of new figures or factual claims.
- Embed the source as an inline markdown hyperlink on a natural word or short \
phrase inside the paragraph, e.g. "released [new research](https://...)". Use \
only URLs that appeared in your search results. No footnotes or reference lists.
"""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _collect(content: list[Any]):
    """Return (full_text, block_spans, result_urls).

    block_spans: (end_offset, block_text, citations) per text block.
    result_urls: url -> {"title", "page_age"} for every search result returned.
    """
    parts: list[str] = []
    spans: list[tuple[int, str, list[dict[str, str]]]] = []
    result_urls: dict[str, dict[str, Any]] = {}
    pos = 0
    for block in content:
        btype = getattr(block, "type", None)
        if btype == "web_search_tool_result":
            results = getattr(block, "content", None)
            if isinstance(results, list):
                for r in results:
                    url = getattr(r, "url", None)
                    if url:
                        result_urls[url] = {
                            "title": getattr(r, "title", None) or "",
                            "page_age": getattr(r, "page_age", None),
                        }
        elif btype == "text":
            text = block.text or ""
            parts.append(text)
            pos += len(text)
            cites = []
            for c in getattr(block, "citations", None) or []:
                if getattr(c, "type", None) != "web_search_result_location":
                    continue
                cites.append(
                    {
                        "url": c.url,
                        "title": getattr(c, "title", None) or "",
                        "cited_text": getattr(c, "cited_text", None) or "",
                    }
                )
            spans.append((pos, text, cites))
    return "".join(parts), spans, result_urls


def _claim_text(block_text: str) -> str:
    lines = [ln for ln in block_text.splitlines() if not ln.lstrip().startswith("###")]
    return _strip_links(" ".join(lines)).strip()


def _parse_highlights(content: list[Any]) -> list[dict[str, Any]]:
    full, spans, result_urls = _collect(content)
    seen_urls = set(result_urls) | {c["url"] for _, _, cs in spans for c in cs}

    headings = list(re.finditer(r"^###[ \t]+(.+?)[ \t]*$", full, flags=re.MULTILINE))
    items: list[dict[str, Any]] = []
    for i, m in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(full)
        headline = m.group(1).strip().strip("*").strip()
        raw_body = full[m.end():end].strip()
        warnings: list[str] = []

        # Keep only links whose URL the search tool actually returned.
        links: list[dict[str, str]] = []

        def _keep(match: re.Match) -> str:
            anchor, url = match.group(1), match.group(2)
            if url in seen_urls:
                links.append({"anchor": anchor, "url": url})
                return match.group(0)
            warnings.append(f"link to {url} was not in the search results; unlinked")
            return anchor

        body_md = _LINK_RE.sub(_keep, raw_body)
        body = _strip_links(body_md)

        n = _word_count(body)
        if not BODY_WORDS[0] <= n <= BODY_WORDS[1]:
            warnings.append(f"body is {n} words, outside {BODY_WORDS[0]}-{BODY_WORDS[1]}")
        if not body.startswith(OPENER):
            warnings.append(f'body does not open with "{OPENER}"')
        if not links:
            warnings.append("no inline source hyperlink in the body")

        items.append(
            {
                "headline": headline,
                "headline_md": f"**{headline}**",
                "body": body,
                "body_md": body_md,
                "links": links,
                "claims": [],
                "citations": [],
                "warnings": warnings,
                "_start": m.end(),
                "_end": end,
            }
        )

    # Attach each cited block to the highlight containing its last character
    # (citations sit at the end of the claim they support).
    for end_pos, block_text, cites in spans:
        if not cites:
            continue
        anchor = end_pos - 1
        claim = _claim_text(block_text)
        for h in items:
            if h["_start"] <= anchor < h["_end"]:
                for c in cites:
                    h["claims"].append({"text": claim, **c})
                    if c not in h["citations"]:
                        h["citations"].append(c)
                break

    for h in items:
        del h["_start"], h["_end"]
        if not h["claims"]:
            h["warnings"].append("no cited claims recorded for this highlight")
        for link in h["links"]:
            info = result_urls.get(link["url"])
            if info and info["page_age"]:
                link["page_age"] = info["page_age"]
    return items


# ---------------------------------------------------------------------------
# Search and drafting (one company, one scope)
# ---------------------------------------------------------------------------

def _search_tool(ir_domain: Optional[str]) -> dict[str, Any]:
    """Web search tool config; restricted to one domain for the IR-first pass."""
    tool = dict(WEB_SEARCH_TOOL)
    if ir_domain:
        tool["allowed_domains"] = [ir_domain]
    return tool


def _run_search(client, model: str, prompt: str, tool: dict[str, Any]) -> list[Any]:
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    all_content: list[Any] = []
    for _ in range(MAX_CONTINUATIONS + 1):
        resp = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=_HIGHLIGHTS_SYSTEM,
            tools=[tool],
            messages=messages,
        )
        all_content.extend(resp.content)
        if resp.stop_reason != "pause_turn":
            break
        # Server-side tool loop hit its iteration cap: resume with the partial turn.
        messages = [messages[0], {"role": "assistant", "content": list(all_content)}]
    return all_content


def _company_prompt(company: dict[str, Any], scope: str, start: date, end: date,
                    today: date, examples: str) -> str:
    if scope == SCOPE_IR:
        where = f"Search ONLY {company['ir_domain']} (the company's own investor relations site)."
    else:
        where = (
            f"The investor relations site ({company['ir_domain']}) had no story for this "
            "week, so search the web generally, preferring the company's own "
            "announcements and reputable news outlets."
        )
    prompt = (
        f"Company: {company['name']}.\n{where}\n"
        f"The report week is {start.isoformat()} to {end.isoformat()} "
        f"(today is {today.isoformat()}). Find the most notable story about "
        f"{company['name']} from that week and draft the highlight."
    )
    if examples.strip():
        prompt += (
            "\n\nMatch the tone, length and structure of these real examples from "
            "previous reports (do not reuse their content; add inline hyperlinks as "
            "instructed):\n\n" + examples.strip()
        )
    return prompt


def _draft_for_company(client, model, company, scope, start, end, today, examples,
                       warnings: list[str]) -> Optional[dict[str, Any]]:
    content = _run_search(
        client, model, _company_prompt(company, scope, start, end, today, examples),
        _search_tool(company["ir_domain"] if scope == SCOPE_IR else None),
    )
    found = _parse_highlights(content)
    if not found:
        return None
    if len(found) > 1:
        warnings.append(f"{company['name']}: model returned {len(found)} stories; kept the first")
    h = found[0]
    if not is_about_company(h["body"], company["aliases"]):
        warnings.append(
            f"{company['name']}: discarded a story that is not about the company "
            f"({h['headline']!r})"
        )
        return None
    h.update(company=company["name"], search_scope=scope, ir_domain=company["ir_domain"])
    return h


class AnthropicProvider(DraftingProvider):
    """Claude Sonnet + native web search.  ``client`` is injectable for tests."""

    def __init__(self, client: Optional[anthropic.Anthropic] = None, model: str = MODEL):
        self._client = client
        self.model = model
        self.drafted_by = DRAFTED_BY if model == MODEL else f"anthropic:{model}"

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

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
        co = {"name": company, "aliases": list(aliases or [company]), "ir_domain": ir_domain}
        warnings: list[str] = []
        for scope in (SCOPE_IR, SCOPE_WEB):
            h = _draft_for_company(
                self.client, self.model, co, scope, start, end, today, style_examples, warnings
            )
            if h:
                return HighlightResult(
                    company=company,
                    search_scope=scope,
                    ir_domain=ir_domain,
                    drafted_by=self.drafted_by,
                    headline=h["headline"],
                    paragraph=h["body"],
                    paragraph_md=h["body_md"],
                    word_count=_word_count(h["body"]),
                    links=h["links"],
                    claims=h["claims"],
                    citations=h["citations"],
                    warnings=h["warnings"],
                    draft_warnings=warnings,
                )
        return HighlightResult(
            company=company, search_scope=None, ir_domain=ir_domain,
            drafted_by=self.drafted_by, no_story=True, draft_warnings=warnings,
        )

    def draft_outlook(
        self, table_stats: dict[str, Any], highlights: list[dict[str, Any]]
    ) -> OutlookResult:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=800,
            system=OUTLOOK_SYSTEM,
            messages=[{"role": "user", "content": outlook_user_message(table_stats, highlights)}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        return OutlookResult(text=text, stats=table_stats, drafted_by=self.drafted_by)
