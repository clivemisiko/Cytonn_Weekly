"""Digital Payments "Weekly Highlights" drafter.

Uses Claude with the native web search tool to find news from the current
report week about the 7 tracked companies, and drafts exactly four highlight
write-ups (fewer, with a flagged shortfall, if fewer genuinely qualify).
A separate, search-free call drafts the closing outlook paragraph from the
drafted highlights plus the stock table.

Each highlight records, for every span of text the search tool cited, the exact
source URL, title and cited text (``claims``) - what the task 6 checking layer
verifies against.  Inline hyperlinks in the paragraph are only kept if the URL
was actually returned by the search tool.

Typical usage
-------------
    from cytonn_weekly.drafters.digital_payments_highlights import (
        draft_highlights, draft_outlook, compose_section,
    )
    from cytonn_weekly.fetchers.digital_payments import fetch_digital_payments

    draft = draft_highlights()
    table = fetch_digital_payments()
    section = compose_section(draft, table, draft_outlook(draft, table))
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Optional

import anthropic

MODEL = "claude-sonnet-5-5"
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
MAX_TOKENS = 6000
MAX_CONTINUATIONS = 3  # server-side search turns can pause; resume a bounded number of times

N_HIGHLIGHTS = 4
BODY_WORDS = (100, 180)
OUTLOOK_WORDS = (80, 120)
OPENER = "During the week,"
ROMAN = ["I", "II", "III", "IV", "V", "VI"]

# Companies eligible for a highlight, in selection priority order (highest first).
# Block and Global Payments are in the stock table but never get a highlight.
# "aliases" are used to confirm a drafted story is actually about the company.
HIGHLIGHT_COMPANIES: list[dict[str, Any]] = [
    {"name": "Visa", "aliases": ["Visa"], "ir_domain": "investor.visa.com"},
    {"name": "Mastercard", "aliases": ["Mastercard"], "ir_domain": "investor.mastercard.com"},
    {"name": "American Express", "aliases": ["American Express", "Amex"], "ir_domain": "ir.americanexpress.com"},
    {"name": "PayPal", "aliases": ["PayPal"], "ir_domain": "investor.pypl.com"},
    {"name": "Circle", "aliases": ["Circle"], "ir_domain": "investor.circle.com"},
]

# Real "Weekly Highlights" write-ups from a published Cytonn Weekly report, used
# as style reference (headline, then one paragraph).  Pass style_examples= to
# override.
STYLE_EXAMPLES: str = """\
### Visa Research Highlights the Rise of the Couch Economy and Home-Centered Consumption

During the week, Visa Inc. released new research from Visa Business and Economic Insights (VBEI) examining the couch economy, which reveals that consumers are increasingly shopping, streaming, dining, and managing everyday activities from home, driving domestic digital commerce volumes up to 58.0% in the U.S. (from 48.0% in 2019) and driving streaming subscriptions onto a larger share of cards than traditional cinema and concert spending across all markets studied; This structural shift toward convenience reflects changing consumer expectations where digital channels, subscription models, and delivery platforms dominate everyday spending habits. The expansion of home-centered consumption provides new avenues for merchants and financial institutions to capture recurring customer relationships, particularly as services like food delivery transition from early adopters to mainstream consumer staples.

### Mastercard Partners with Alchemy to Introduce Agentic Payments for AI Shopping Assistants

During the week, Mastercard announced a partnership with startup Alchemy to roll out an agentic payment option equipped with one-time-use virtual card credentials and stablecoin wallets, allowing AI agents to independently discover, compare, and purchase goods on behalf of users within set parameters; This capability addresses the evolving need to adapt traditional risk rules and anti-fraud frameworks to safely permit bots to transact online, marking a significant departure from legacy risk models built solely to block unauthorized automated traffic. While this innovation promises to streamline e-commerce and checkout experiences by letting users authorize agents ahead of time, it also brings industry-wide scrutiny regarding security safeguards, risk management standards, and the broader implications of autonomous agent capabilities across the financial ecosystem.

### PayPal Debit Card Earns Best in Class Honors in Javelin's 2026 GPR Card Scorecard

During the week, the PayPal Debit Card secured Best in Class recognition in Javelin Strategy & Research's 2026 General-Purpose Reloadable (GPR) Card Scorecard, while Cash App Card and Wisely Direct were named Overall Leaders; The scorecard underscores how peer-to-peer (P2P) linked cards are leading market momentum by successfully pairing low costs and broad acceptance with added benefits and consumer rewards. This evolution highlights a broader market trend where digital wallets are deeply embedding prepaid functionality into consumers' everyday financial lives, turning stored balances into practical, low-cost tools for daily spending.
"""

NO_STORY = "NO_STORY"

_HIGHLIGHTS_SYSTEM = f"""\
You draft one "Weekly Highlights" item for the Digital Payments section of a \
weekly investment research report (formal, data-forward, third person).

Scope: news about the single company named in the user message ONLY. Never \
write about any other company, and no general industry news.

Rules:
- Use web search to find a story about that company published during the \
report week given in the user message. Do not use stale news.
- If no story about that company genuinely qualifies, reply with exactly \
"{NO_STORY}" and nothing else. Never pad with off-topic or older news.
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

_OUTLOOK_SYSTEM = f"""\
You write the closing sector-outlook paragraph of the Digital Payments section \
of a weekly investment research report (formal, third person, forward-looking).

Write ONE paragraph of {OUTLOOK_WORDS[0]}-{OUTLOOK_WORDS[1]} words that synthesizes \
the week's highlights together with the stock-table statistics provided. Use \
only the highlights text and the statistics given - introduce no new external \
facts or figures, and quote statistics exactly as given. No headings, no links, \
no formatting marks.
"""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def _strip_links(text: str) -> str:
    return _LINK_RE.sub(r"\1", text)


def _word_count(text: str) -> int:
    return len(text.split())


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
# Highlights
# ---------------------------------------------------------------------------

def _week_window(today: date) -> tuple[date, date]:
    return today - timedelta(days=6), today


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
    if scope == "investor_relations":
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
        _search_tool(company["ir_domain"] if scope == "investor_relations" else None),
    )
    found = _parse_highlights(content)
    if not found:
        return None
    if len(found) > 1:
        warnings.append(f"{company['name']}: model returned {len(found)} stories; kept the first")
    h = found[0]
    lead = h["body"][:150].lower()
    if not any(a.lower() in lead for a in company["aliases"]):
        warnings.append(
            f"{company['name']}: discarded a story that is not about the company "
            f"({h['headline']!r})"
        )
        return None
    h.update(company=company["name"], search_scope=scope, ir_domain=company["ir_domain"])
    return h


def draft_highlights(
    client: Optional[anthropic.Anthropic] = None,
    today: Optional[date] = None,
    style_examples: Optional[str] = None,
    model: str = MODEL,
) -> dict[str, Any]:
    """Draft the Weekly Highlights for the 7 days ending on ``today``.

    Only the 5 HIGHLIGHT_COMPANIES are considered, in priority order (Visa,
    Mastercard, American Express, PayPal, Circle); Block and Global Payments
    never get a highlight.  For each company the company's own investor
    relations site is searched first, and a general web search is used only if
    that returned no story.  Companies are processed in priority order until 4
    highlights are found, so lower-priority companies are searched only when a
    higher-priority one has no news.

    Returns {"week_start", "week_end", "highlights", "shortfall", "warnings"}.
    Each highlight has company, search_scope ("investor_relations" or
    "web_fallback"), ir_domain, headline, headline_md, body (plain), body_md
    (with inline links), links, claims [{text, url, title, cited_text}],
    citations, warnings.  "shortfall" is how many highlights short of 4 the
    result is (0 if complete); it is never filled from outside the 5.
    API errors propagate to the caller.
    """
    client = client or anthropic.Anthropic()
    today = today or date.today()
    start, end = _week_window(today)
    examples = STYLE_EXAMPLES if style_examples is None else style_examples

    highlights: list[dict[str, Any]] = []
    warnings: list[str] = []
    for company in HIGHLIGHT_COMPANIES:
        if len(highlights) == N_HIGHLIGHTS:
            warnings.append(
                f"{company['name']}: not searched ({N_HIGHLIGHTS} higher-priority highlights already found)"
            )
            continue
        h = None
        for scope in ("investor_relations", "web_fallback"):
            h = _draft_for_company(
                client, model, company, scope, start, end, today, examples, warnings
            )
            if h:
                break
        if h:
            highlights.append(h)
        else:
            warnings.append(f"{company['name']}: no story found for the week (IR site or web)")

    shortfall = N_HIGHLIGHTS - len(highlights)
    if shortfall:
        warnings.append(
            f"only {len(highlights)} of {N_HIGHLIGHTS} highlights found for "
            f"{start.isoformat()} to {end.isoformat()}"
        )
    return {
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "highlights": highlights,
        "shortfall": shortfall,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Outlook
# ---------------------------------------------------------------------------

def table_stats(table_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summary statistics from digital_payments.py rows (failed rows excluded).

    Average forward P/E is included only if rows carry a numeric "forward_pe"
    (the fetcher does not produce one yet).
    """
    ok = [r for r in table_rows if not r.get("error")]
    stats: dict[str, Any] = {
        "companies_included": len(ok),
        "companies_failed": len(table_rows) - len(ok),
    }
    if ok:
        wow = [r["wow_pct"] for r in ok]
        ytd = [r["ytd_pct"] for r in ok]
        stats.update(
            avg_wow_pct=round(sum(wow) / len(wow), 2),
            avg_ytd_pct=round(sum(ytd) / len(ytd), 2),
            advancers=sum(1 for v in wow if v > 0),
            decliners=sum(1 for v in wow if v < 0),
        )
    pes = [r["forward_pe"] for r in ok if isinstance(r.get("forward_pe"), (int, float))]
    if pes:
        stats["avg_forward_pe"] = round(sum(pes) / len(pes), 2)
    return stats


def draft_outlook(
    draft: dict[str, Any],
    table_rows: list[dict[str, Any]],
    client: Optional[anthropic.Anthropic] = None,
    model: str = MODEL,
) -> dict[str, Any]:
    """Draft the closing outlook paragraph (bold italic, uncited synthesis).

    Returns {"text_md", "text", "stats", "warnings"}.  No web search is used.
    """
    client = client or anthropic.Anthropic()
    stats = table_stats(table_rows)
    warnings: list[str] = []
    if not draft["highlights"]:
        warnings.append("no highlights to synthesize; outlook drafted from table only")
    if stats["companies_failed"]:
        warnings.append(f"{stats['companies_failed']} table row(s) failed and are excluded from the stats")
    if "avg_forward_pe" not in stats:
        warnings.append("forward P/E not available in table output; outlook has no P/E figure")

    hl = "\n\n".join(f"{h['headline']}\n{h['body']}" for h in draft["highlights"]) or "(none)"
    stat_lines = "\n".join(f"- {k}: {v}" for k, v in stats.items())
    resp = client.messages.create(
        model=model,
        max_tokens=800,
        system=_OUTLOOK_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": f"Highlights:\n{hl}\n\nStock table statistics "
                f"(average across companies, week-over-week / year-to-date % price change):\n{stat_lines}",
            }
        ],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    n = _word_count(text)
    if not OUTLOOK_WORDS[0] <= n <= OUTLOOK_WORDS[1]:
        warnings.append(f"outlook is {n} words, outside {OUTLOOK_WORDS[0]}-{OUTLOOK_WORDS[1]}")
    return {"text_md": f"***{text}***", "text": text, "stats": stats, "warnings": warnings}


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

def compose_section(
    draft: dict[str, Any],
    table_rows: list[dict[str, Any]],
    outlook: dict[str, Any],
) -> dict[str, Any]:
    """Compose the full Digital Payments section draft.

    Items are numbered in order: highlights I..n, then the stock table as the
    next numeral (V when all four highlights are found), then the outlook.
    """
    items: list[dict[str, Any]] = []
    for i, h in enumerate(draft["highlights"]):
        items.append({"numeral": ROMAN[i], "kind": "highlight", **h})
    items.append(
        {"numeral": ROMAN[len(draft["highlights"])], "kind": "stock_table", "rows": table_rows}
    )
    return {
        "week_start": draft["week_start"],
        "week_end": draft["week_end"],
        "items": items,
        "outlook": outlook,
        "shortfall": draft["shortfall"],
        "warnings": draft["warnings"] + outlook["warnings"],
    }
