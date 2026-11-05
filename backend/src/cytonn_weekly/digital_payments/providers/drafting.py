from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Optional, Sequence

from cytonn_weekly.digital_payments.providers.base import (
    BODY_WORDS,
    GENUINE_ANNOUNCEMENT,
    LINK_RE,
    NOT_GENUINE,
    OPENER,
    HighlightResult,
    is_about_company,
    strip_links,
    word_count,
)

if TYPE_CHECKING:
    from cytonn_weekly.narrative.base import NarrativeBrief

CONTEXT_CHARS_PER_RESULT = 3000  # enough text per result to draft from

HIGHLIGHT_SYSTEM = f"""\
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

RESPONSE_SCHEMA = {
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


def results_message(subject: str, results: list[dict[str, Any]], heading: str = "Search results") -> str:
    """The user message: each source as a numbered block.  The text of each is cut at CONTEXT_CHARS_PER_RESULT."""
    blocks = []
    for i, r in enumerate(results, 1):
        text = " ".join((r.get("text") or "").split())[:CONTEXT_CHARS_PER_RESULT]
        blocks.append(
            f"[Result {i}]\nTitle: {r.get('title') or '(no title)'}\n"
            f"URL: {r.get('url')}\nPublished: {r.get('publishedDate') or 'n/a'}\nText: {text}"
        )
    return f"Company: {subject}\n\n{heading}:\n\n" + "\n\n".join(blocks)


def narrative_system(brief: NarrativeBrief) -> str:
    opener = f'begins exactly with "{brief.opener}"' if brief.opener else "is formal prose"
    extra = f"\n\n{brief.context}" if brief.context else ""
    head = "a short headline and " if brief.headed else (
        "body paragraphs only, with no heading of any kind (set the headline to the subject, and put no line starting "
        "with # in the paragraph): ")
    return f"""\
You help draft one item for the {brief.section} section of a {brief.report} investment research report \
on Kenya (formal, data-forward, third person) from search results.

Subject: {brief.label}. What qualifies: {brief.focus}{extra}

Step 1 - judge the material. Decide whether the search results contain material that genuinely \
qualifies. Analysis, opinion pieces or unrelated material do not. Do not force a draft.

Step 2 - only if it qualifies: write {head}prose of {brief.words[0]} to \
{brief.words[1]} words that {opener}. Use ONLY facts stated in the search results; never add \
figures, dates, names or claims from memory. Embed sources as inline markdown hyperlinks, using \
only URLs given in the results.

Step 3 - list every factual claim in your text with the exact URL of the result that supports it.

If nothing qualifies, set is_genuine_announcement to false, explain briefly in reasoning, and leave \
headline and paragraph empty and claims an empty list.

Reply with JSON only."""


def highlight_from_reply(
    raw: str, company: str, ir_domain: str, scope: str, aliases: Sequence[str],
    results: list[dict[str, Any]], warnings: list[str], *, who: str, label: str, drafted_by: str,
) -> Optional[HighlightResult]:
    """A Digital Payments highlight from the model's JSON reply, kept only where it cites the given results."""
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        warnings.append(f"{company}: {who} returned invalid JSON for the {scope} results; discarded")
        return None
    if not out.get("is_genuine_announcement"):
        reason = " ".join((out.get("reasoning") or "").split())
        warnings.append(f"{company}: {who} judged the {scope} results not a genuine announcement ({reason})")
        return None
    paragraph_md = (out.get("paragraph") or "").strip()
    headline = (out.get("headline") or "").strip().strip("*").strip()
    if not paragraph_md or not headline:
        warnings.append(f"{company}: {who} said genuine but returned no headline/paragraph; discarded")
        return None

    by_url = {r.get("url"): r for r in results if r.get("url")}
    hl_warnings: list[str] = []

    # Keep only links whose URL was among the results.
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
        hl_warnings.append(f"{label}: claims carry no cited_text (model-mapped URLs only, not provider-cited spans)")
    for link in links:
        published = by_url[link["url"]].get("publishedDate")
        if published:
            link["page_age"] = published

    return HighlightResult(
        company=company, search_scope=scope, ir_domain=ir_domain, drafted_by=drafted_by,
        headline=headline, paragraph=body, paragraph_md=body_md, word_count=n,
        links=links, claims=claims, citations=citations, warnings=hl_warnings,
    )


def piece_from_reply(
    raw: str, brief: NarrativeBrief, scope: str, results: list[dict[str, Any]], warnings: list[str],
    *, who: str, label: str, drafted_by: str,
) -> Optional[HighlightResult]:
    """A narrative piece from the model's JSON reply, kept only where it cites the given results."""
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        warnings.append(f"{brief.label}: {who} returned invalid JSON; discarded")
        return None
    if not out.get("is_genuine_announcement"):
        warnings.append(f"{brief.label}: {who} judged the {scope} results not qualifying "
                        f"({' '.join((out.get('reasoning') or '').split())})")
        return None
    headline = (out.get("headline") or "").strip().strip("*").strip() if brief.headed else brief.label
    paragraph_md = (out.get("paragraph") or "").strip()
    if not brief.headed:   # a heading line never cuts a Focus section; it is dropped
        lines = paragraph_md.splitlines()
        paragraph_md = "\n".join(ln for ln in lines if not ln.lstrip().startswith("#")).strip()
        if len(paragraph_md.splitlines()) < len(lines):
            warnings.append(f"{brief.label}: removed heading line(s) the {who} added to the section")
    if not headline or not paragraph_md:
        warnings.append(f"{brief.label}: {who} returned no headline/paragraph; discarded")
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
        hl.append(f"{label}: claims carry no cited_text (model-mapped URLs only)")
    else:
        hl.append("no cited claims recorded for this piece")
    return HighlightResult(
        company=brief.label, search_scope=scope, ir_domain=", ".join(brief.preferred_domains),
        drafted_by=drafted_by, headline=headline, paragraph=body, paragraph_md=body_md,
        word_count=n, links=links, claims=claims, citations=citations, warnings=hl,
    )
