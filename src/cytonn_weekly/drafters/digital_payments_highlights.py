"""Digital Payments "Weekly Highlights" drafter.

Asks Claude, with the native web search tool enabled, to find recent real
news in the digital payments industry and draft a short write-up for each
item.  Every highlight keeps the citations the search tool returned (URL,
title, cited text) so the checking layer can later verify claims against them.

No figure-vs-analysis separation happens here: sentences the model wrote
without needing a search simply carry no citation.

Typical usage
-------------
    from cytonn_weekly.drafters.digital_payments_highlights import (
        draft_weekly_highlights,
    )

    for h in draft_weekly_highlights():
        print(h["title"], len(h["citations"]))
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional

import anthropic

MODEL = "claude-sonnet-5-5"
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 10}
MAX_TOKENS = 4096
MAX_CONTINUATIONS = 3  # server-side search turns can pause; resume a bounded number of times

# Real "Weekly Highlights" write-ups from a published Cytonn Weekly report, used
# as style reference.  Headlines are shown without the roman-numeral prefix; the
# report assembly adds numbering.  Pass style_examples= to override.
STYLE_EXAMPLES: str = """## Visa Research Highlights the Rise of the Couch Economy and Home-Centered Consumption

During the week, Visa Inc. released new research from Visa Business and Economic Insights (VBEI) examining the couch economy, which reveals that consumers are increasingly shopping, streaming, dining, and managing everyday activities from home, driving domestic digital commerce volumes up to 58.0% in the U.S. (from 48.0% in 2019) and driving streaming subscriptions onto a larger share of cards than traditional cinema and concert spending across all markets studied; This structural shift toward convenience reflects changing consumer expectations where digital channels, subscription models, and delivery platforms dominate everyday spending habits. The expansion of home-centered consumption provides new avenues for merchants and financial institutions to capture recurring customer relationships, particularly as services like food delivery transition from early adopters to mainstream consumer staples.

## Mastercard Partners with Alchemy to Introduce Agentic Payments for AI Shopping Assistants

During the week, Mastercard announced a partnership with startup Alchemy to roll out an agentic payment option equipped with one-time-use virtual card credentials and stablecoin wallets, allowing AI agents to independently discover, compare, and purchase goods on behalf of users within set parameters; This capability addresses the evolving need to adapt traditional risk rules and anti-fraud frameworks to safely permit bots to transact online, marking a significant departure from legacy risk models built solely to block unauthorized automated traffic. While this innovation promises to streamline e-commerce and checkout experiences by letting users authorize agents ahead of time, it also brings industry-wide scrutiny regarding security safeguards, risk management standards, and the broader implications of autonomous agent capabilities across the financial ecosystem.

## PayPal Debit Card Earns Best in Class Honors in Javelin's 2026 GPR Card Scorecard

During the week, the PayPal Debit Card secured Best in Class recognition in Javelin Strategy & Research's 2026 General-Purpose Reloadable (GPR) Card Scorecard, while Cash App Card and Wisely Direct were named Overall Leaders; The scorecard underscores how peer-to-peer (P2P) linked cards are leading market momentum by successfully pairing low costs and broad acceptance with added benefits and consumer rewards. This evolution highlights a broader market trend where digital wallets are deeply embedding prepaid functionality into consumers' everyday financial lives, turning stored balances into practical, low-cost tools for daily spending.
"""

_SYSTEM_PROMPT = """\
You draft the "Weekly Highlights" part of the Digital Payments section of a \
weekly investment research report.

Rules:
- Use web search to find 4-5 recent (roughly the past 7-10 days), real, notable \
news items in the digital payments industry: product launches, partnerships, \
research releases, regulatory news.
- Every factual claim (names, dates, figures, quotes, what was announced) must \
come from the search results you retrieved. Never rely on memory. If you cannot \
find enough genuine items, return fewer rather than padding or inventing.
- Each write-up is a short paragraph or two. Brief interpretive commentary is \
fine, but keep it clearly separate from the facts.
- Output format, exactly: for each item, a line "## <headline>" followed by the \
write-up text. No introduction, no closing remarks, no other headings.
"""


def _build_user_prompt(today: date, style_examples: str) -> str:
    prompt = (
        f"Today is {today.isoformat()}. Find 4-5 recent digital payments news "
        "items and draft the Weekly Highlights."
    )
    if style_examples.strip():
        prompt += (
            "\n\nMatch the tone, length and structure of these real examples "
            "from previous reports (do not reuse their content):\n\n"
            + style_examples.strip()
        )
    return prompt


def _collect_text(content: list[Any]) -> tuple[str, list[tuple[int, list[dict[str, str]]]]]:
    """Concatenate text blocks; return the full text and (end_offset, citations) per block."""
    parts: list[str] = []
    spans: list[tuple[int, list[dict[str, str]]]] = []
    pos = 0
    for block in content:
        if getattr(block, "type", None) != "text":
            continue
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
        spans.append((pos, cites))
    return "".join(parts), spans


def _parse_highlights(content: list[Any]) -> list[dict[str, Any]]:
    full, spans = _collect_text(content)
    headings = list(re.finditer(r"^##[ \t]+(.+?)[ \t]*$", full, flags=re.MULTILINE))
    highlights: list[dict[str, Any]] = []
    for i, m in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(full)
        highlights.append(
            {
                "title": m.group(1).strip(),
                "body": full[m.end():end].strip(),
                "citations": [],
                "_start": m.end(),
                "_end": end,
            }
        )

    # Assign each block's citations to the highlight containing the block's last
    # character (citations sit at the end of the claim they support).
    for end_pos, cites in spans:
        anchor = end_pos - 1
        for h in highlights:
            if h["_start"] <= anchor < h["_end"]:
                for c in cites:
                    if c not in h["citations"]:
                        h["citations"].append(c)
                break

    for h in highlights:
        del h["_start"], h["_end"]
    return highlights


def draft_weekly_highlights(
    client: Optional[anthropic.Anthropic] = None,
    today: Optional[date] = None,
    style_examples: Optional[str] = None,
    model: str = MODEL,
) -> list[dict[str, Any]]:
    """Draft the Weekly Highlights.

    Returns a list of dicts, one per highlight: {"title", "body", "citations"},
    where citations is a list of {"url", "title", "cited_text"} from the web
    search tool.  API errors propagate to the caller.
    """
    client = client or anthropic.Anthropic()
    today = today or date.today()
    examples = STYLE_EXAMPLES if style_examples is None else style_examples

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": _build_user_prompt(today, examples)}
    ]
    all_content: list[Any] = []
    for _ in range(MAX_CONTINUATIONS + 1):
        resp = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            tools=[WEB_SEARCH_TOOL],
            messages=messages,
        )
        all_content.extend(resp.content)
        if resp.stop_reason != "pause_turn":
            break
        # Server-side tool loop hit its iteration cap: resume with the partial turn.
        messages = [
            messages[0],
            {"role": "assistant", "content": list(all_content)},
        ]

    return _parse_highlights(all_content)
