from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Callable, Optional, Sequence

from cytonn_weekly.drafting.highlight_contract import BODY_WORDS, OPENER
from cytonn_weekly.drafting.reply_models import DraftReply, _decoded
from cytonn_weekly.drafting.results import LINK_RE, HighlightResult, is_about_company, strip_links, word_count

if TYPE_CHECKING:
    from cytonn_weekly.drafting.base import NarrativeBrief

TAKEOUT_NUMERALS = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii")
WHERE_SEARCHED = "search results"   # how a warning names the material the model was shown; Bedrock says "supplied sources"

# Turns one claim from the model's reply into the claim dict kept in the draft (url, title, cited_text and any extra
# keys), or None after adding its reason to the warning list.  Given the claim, the sources by URL and the warnings.
ClaimReader = Callable[[dict[str, Any], dict[str, dict[str, Any]], list[str]], Optional[dict[str, Any]]]

def _claims(claim_list: list[Any], by_url: dict[str, dict[str, Any]], hl: list[str], where: str,
            read_claim: Optional[ClaimReader]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """The reply's claims that cite a given source, and the distinct citations they make."""
    claims: list[dict[str, Any]] = []
    citations: list[dict[str, str]] = []
    for c in claim_list:
        if c is None:
            hl.append("a claim in the reply was not readable; dropped")
            continue
        if read_claim:
            claim = read_claim(c, by_url, hl)
        else:
            url, text = (c.get("url") or "").strip(), strip_links((c.get("claim") or "").strip())
            if url not in by_url:
                hl.append(f"claim cited a URL not in the {where}; dropped: {url or '(empty)'}")
                continue
            claim = {"text": text, "url": url, "title": by_url[url].get("title") or "", "cited_text": ""} if text else None
        if not claim:
            continue
        claims.append(claim)
        cite = {k: claim[k] for k in ("url", "title", "cited_text")}
        if cite not in citations:
            citations.append(cite)
    return claims, citations


def highlight_from_reply(
    raw: str, company: str, ir_domain: str, scope: str, aliases: Sequence[str],
    results: list[dict[str, Any]], warnings: list[str], *, who: str, label: str, drafted_by: str,
    where: str = WHERE_SEARCHED, read_claim: Optional[ClaimReader] = None,
) -> Optional[HighlightResult]:
    """A Digital Payments highlight from the model's JSON reply, kept only where it cites the given results.

    ``where`` names the material in warnings; ``read_claim`` replaces how a claim is read and checked (Bedrock's
    quote check) and, when given, the "no cited_text" warning is not made, because its claims carry one."""
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        warnings.append(f"{company}: {who} returned invalid JSON for the {scope} results; discarded")
        return None
    out = _decoded(out, dict)
    if out is not None:
        out = DraftReply.model_validate(out)
    if out is None:
        warnings.append(f"{company}: {who} returned a reply that is not a draft object for the {scope} results; discarded")
        return None
    if not out.is_genuine_announcement:
        reason = " ".join((out.reasoning or "").split())
        warnings.append(f"{company}: {who} judged the {scope} results not a genuine announcement ({reason})")
        return None
    paragraph_md = (out.paragraph or "").strip()
    headline = (out.headline or "").strip().strip("*").strip()
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
        hl_warnings.append(f"link to {url} was not in the {where}; unlinked")
        return anchor

    body_md = LINK_RE.sub(_keep, paragraph_md)
    body = strip_links(body_md)
    if not is_about_company(body, aliases):
        warnings.append(f"{company}: discarded a story that is not about the company ({headline!r})")
        return None

    claims, citations = _claims(out.claims, by_url, hl_warnings, where, read_claim)

    n = word_count(body)
    if not BODY_WORDS[0] <= n <= BODY_WORDS[1]:
        hl_warnings.append(f"body is {n} words, outside {BODY_WORDS[0]}-{BODY_WORDS[1]}")
    if not body.startswith(OPENER):
        hl_warnings.append(f'body does not open with "{OPENER}"')
    if not links:
        hl_warnings.append("no inline source hyperlink in the body")
    if not claims:
        hl_warnings.append("no cited claims recorded for this highlight")
    elif not read_claim:
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
    *, who: str, label: str, drafted_by: str, where: str = WHERE_SEARCHED, read_claim: Optional[ClaimReader] = None,
) -> Optional[HighlightResult]:
    """A narrative piece from the model's JSON reply, kept only where it cites the given results."""
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        warnings.append(f"{brief.label}: {who} returned invalid JSON; discarded")
        return None
    out = _decoded(out, dict)
    if out is not None:
        out = DraftReply.model_validate(out)
    if out is None:
        warnings.append(f"{brief.label}: {who} returned a reply that is not a draft object; discarded")
        return None
    if not out.is_genuine_announcement:
        warnings.append(f"{brief.label}: {who} judged the {scope} results not qualifying "
                        f"({' '.join((out.reasoning or '').split())})")
        return None
    if brief.findings:   # no paragraph is wanted or kept: the claims, each checked against its source, are the piece
        by_url = {r.get("url"): r for r in results if r.get("url")}
        hl: list[str] = []
        claims, citations = _claims(out.claims, by_url, hl, where, read_claim)
        if not claims:
            warnings.append(f"{brief.label}: {who} returned no findings; discarded")
            return None
        if not read_claim:
            hl.append(f"{label}: claims carry no cited_text (model-mapped URLs only)")
        return HighlightResult(
            company=brief.label, search_scope=scope, ir_domain=", ".join(brief.preferred_domains), drafted_by=drafted_by,
            headline=brief.label, paragraph="", paragraph_md="", word_count=0, links=[], claims=claims,
            citations=citations, warnings=hl)
    headline = (out.headline or "").strip().strip("*").strip() if brief.headed else brief.label
    paragraph_md = (out.paragraph or "").strip()
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
        hl.append(f"link to {m.group(2)} was not in the {where}; unlinked")
        return m.group(1)

    body_md = LINK_RE.sub(keep, paragraph_md)
    body = strip_links(body_md)
    claims, citations = _claims(out.claims, by_url, hl, where, read_claim)
    n = word_count(body)
    if not brief.words[0] <= n <= brief.words[1]:
        hl.append(f"body is {n} words, outside {brief.words[0]}-{brief.words[1]}")
    if brief.opener and not body.startswith(brief.opener):
        hl.append(f'body does not open with "{brief.opener}"')
    if brief.takeouts:
        parts = [p for p in paragraph_md.split("\n\n") if p.strip()][1:]
        if not parts or [p.split(".", 1)[0].strip() for p in parts] != list(TAKEOUT_NUMERALS[:len(parts)]):
            hl.append("the take-outs are not numbered i., ii., iii. in order, each as its own paragraph after the introduction")
    if not claims:
        hl.append("no cited claims recorded for this piece")
    elif not read_claim:
        hl.append(f"{label}: claims carry no cited_text (model-mapped URLs only)")
    return HighlightResult(
        company=brief.label, search_scope=scope, ir_domain=", ".join(brief.preferred_domains),
        drafted_by=drafted_by, headline=headline, paragraph=body, paragraph_md=body_md,
        word_count=n, links=links, claims=claims, citations=citations, warnings=hl,
    )
