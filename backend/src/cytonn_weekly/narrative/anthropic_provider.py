"""Anthropic narrative provider (production): Claude + the native web search tool.

Same mechanism as the Digital Payments highlights provider, reusing its
``_collect`` (which gathers text blocks, their citations and every search-result
URL): the preferred domains are searched first through ``allowed_domains``, then
the open web if they produced nothing.  Inline links survive only if the search
tool actually returned that URL, and every cited span becomes a claim with the
exact URL, title and cited text the checking layer compares figures against.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional

import anthropic

from cytonn_weekly.digital_payments.providers import anthropic_provider as dp
from cytonn_weekly.digital_payments.providers.base import (
    LINK_RE,
    NO_STORY,
    SCOPE_WEB,
    HighlightResult,
    strip_links,
    word_count,
)
from cytonn_weekly.narrative.base import NarrativeBrief, NarrativeProvider

SCOPE_PREFERRED = "preferred_sources"
MAX_TOKENS = 8000


def _span(brief: NarrativeBrief) -> str:
    """The last word of the search window's name: "week" for the weekly report, "period" otherwise."""
    return brief.window.split()[-1]


def system_prompt(brief: NarrativeBrief) -> str:
    opener = (f'The paragraph opens with "{brief.opener}" and ' if brief.opener else "The piece ")
    that = "that week" if _span(brief) == "week" else f"in that {_span(brief)}"
    return f"""\
You draft one item for the {brief.section} section of a {brief.report} investment research report \
on Kenya (formal, data-forward, third person).

Subject: {brief.label}. What qualifies: {brief.focus}

Rules:
- Use web search to find material published during the {brief.window} given in the user \
message. Do not use stale news.
- If nothing published {that} genuinely qualifies, reply with exactly "{NO_STORY}" and \
nothing else. Never pad with off-topic or older material.
- Every factual claim (figure, quote, name, date, specific detail) must come from the search \
results you retrieved. Never rely on memory.
- Output format, exactly: a line "### <headline>" followed by prose of \
{brief.words[0]}-{brief.words[1]} words. No introduction, closing remarks or other headings.
- {opener}ends with 1-2 sentences of implications that contain no new figures or factual claims.
- Embed sources as inline markdown hyperlinks on natural anchor text, using only URLs that \
appeared in your search results. No footnotes or reference lists.
"""


def _prompt(brief: NarrativeBrief, preferred: bool, start: date, end: date, today: date) -> str:
    if preferred:
        where = f"Search ONLY these sources: {', '.join(brief.preferred_domains)}."
    elif brief.preferred_domains:
        where = (f"The preferred sources had nothing for this {_span(brief)}, so search the web generally, "
                 "preferring primary sources.")
    else:
        where = "Search the web, preferring primary sources and reputable Kenyan and international outlets."
    return (f"{where}\nThe {brief.window} is {start.isoformat()} to {end.isoformat()} "
            f"(today is {today.isoformat()}). Draft the item.")


def _run(client, model: str, system: str, prompt: str, tool: dict[str, Any]) -> list[Any]:
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    content: list[Any] = []
    for _ in range(dp.MAX_CONTINUATIONS + 1):
        resp = client.messages.create(model=model, max_tokens=MAX_TOKENS, system=system, tools=[tool],
                                      messages=messages)
        content.extend(resp.content)
        if resp.stop_reason != "pause_turn":
            break
        messages = [messages[0], {"role": "assistant", "content": list(content)}]
    return content


def parse_piece(content: list[Any], brief: NarrativeBrief) -> Optional[dict[str, Any]]:
    """The first "### headline" piece in the reply, with its links and cited claims, or None."""
    full, spans, result_urls = dp._collect(content)
    seen = set(result_urls) | {c["url"] for _, _, cs in spans for c in cs}
    heads = list(re.finditer(r"^###[ \t]+(.+?)[ \t]*$", full, flags=re.MULTILINE))
    if not heads:
        return None
    m = heads[0]
    end = heads[1].start() if len(heads) > 1 else len(full)
    headline = m.group(1).strip().strip("*").strip()
    warnings: list[str] = []
    if len(heads) > 1:
        warnings.append(f"model returned {len(heads)} pieces; kept the first")
    links: list[dict[str, str]] = []

    def keep(match: re.Match) -> str:
        if match.group(2) in seen:
            links.append({"anchor": match.group(1), "url": match.group(2)})
            return match.group(0)
        warnings.append(f"link to {match.group(2)} was not in the search results; unlinked")
        return match.group(1)

    body_md = LINK_RE.sub(keep, full[m.end():end].strip())
    body = strip_links(body_md)
    claims: list[dict[str, str]] = []
    citations: list[dict[str, str]] = []
    for end_pos, block_text, cites in spans:
        if cites and m.end() <= end_pos - 1 < end:
            text = dp._claim_text(block_text)
            for c in cites:
                claims.append({"text": text, **c})
                if c not in citations:
                    citations.append(c)
    n = word_count(body)
    if not brief.words[0] <= n <= brief.words[1]:
        warnings.append(f"body is {n} words, outside {brief.words[0]}-{brief.words[1]}")
    if brief.opener and not body.startswith(brief.opener):
        warnings.append(f'body does not open with "{brief.opener}"')
    if not links:
        warnings.append("no inline source hyperlink in the body")
    if not claims:
        warnings.append("no cited claims recorded for this piece")
    return {"headline": headline, "body": body, "body_md": body_md, "links": links,
            "claims": claims, "citations": citations, "warnings": warnings}


class AnthropicNarrativeProvider(NarrativeProvider):
    """Claude + native web search.  ``client`` is injectable for tests."""

    def __init__(self, client: Optional[anthropic.Anthropic] = None, model: str = dp.MODEL):
        self._client = client
        self.model = model
        self.drafted_by = f"anthropic:{model}"

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def draft_piece(self, brief: NarrativeBrief, *, start: date, end: date, today: date) -> HighlightResult:
        system = system_prompt(brief)
        passes = [True, False] if brief.preferred_domains else [False]
        for preferred in passes:
            tool = {**dp.WEB_SEARCH_TOOL, "max_uses": brief.max_searches}
            if preferred:
                tool["allowed_domains"] = list(brief.preferred_domains)
            piece = parse_piece(_run(self.client, self.model, system, _prompt(brief, preferred, start, end, today), tool), brief)
            if piece:
                return HighlightResult(
                    company=brief.label, search_scope=SCOPE_PREFERRED if preferred else SCOPE_WEB,
                    ir_domain=", ".join(brief.preferred_domains), drafted_by=self.drafted_by,
                    headline=piece["headline"], paragraph=piece["body"], paragraph_md=piece["body_md"],
                    word_count=word_count(piece["body"]), links=piece["links"], claims=piece["claims"],
                    citations=piece["citations"], warnings=piece["warnings"],
                )
        return HighlightResult(company=brief.label, search_scope=None, ir_domain=", ".join(brief.preferred_domains),
                               drafted_by=self.drafted_by, no_story=True)
