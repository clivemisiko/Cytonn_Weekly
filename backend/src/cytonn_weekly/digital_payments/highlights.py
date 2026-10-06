"""Digital Payments "Weekly Highlights" drafter.

Orchestrates four highlight write-ups (fewer, with a flagged shortfall, if fewer
genuinely qualify) and the closing outlook paragraph.  The LLM-judgment work -
finding and drafting one company's story, and drafting the outlook - is done by
an injected drafting provider (see ``digital_payments.providers``): Anthropic
(production default) or a local Ollama model (development).  Which one runs is
chosen by ``provider_factory.get_provider()`` unless a provider is passed in.

Each highlight records, for every span of text the provider cited, the exact
source URL, title and cited text (``claims``) - what the checking layer verifies
against - and ``drafted_by``, the provider + model that drafted it.

Typical usage
-------------
    from cytonn_weekly.digital_payments.fetcher import fetch_digital_payments
    from cytonn_weekly.digital_payments.highlights import (
        draft_highlights, draft_outlook, compose_section,
    )

    draft = draft_highlights()
    table = fetch_digital_payments()
    section = compose_section(draft, table, draft_outlook(draft, table))
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from cytonn_weekly.common.run_events import PART_SKIPPED, PIECE_FINISHED, PIECE_STARTED, Observer, emit
from cytonn_weekly.digital_payments.provider_factory import get_provider
from cytonn_weekly.digital_payments.providers.base import (
    OUTLOOK_WORDS,
    DraftingProvider,
    word_count as _word_count,
)

N_HIGHLIGHTS = 4
OUTLOOK_LABEL = "Outlook paragraph"  # what a run's events call the closing paragraph
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


# ---------------------------------------------------------------------------
# Highlights
# ---------------------------------------------------------------------------

def _week_window(today: date) -> tuple[date, date]:
    return today - timedelta(days=6), today


def _highlight_item(res) -> dict[str, Any]:
    """A provider HighlightResult as the highlight dict the rest of the pipeline consumes."""
    return {
        "headline": res.headline,
        "headline_md": f"**{res.headline}**",
        "body": res.paragraph,
        "body_md": res.paragraph_md,
        "links": res.links,
        "claims": res.claims,
        "citations": res.citations,
        "warnings": res.warnings,
        "company": res.company,
        "search_scope": res.search_scope,
        "ir_domain": res.ir_domain,
        "drafted_by": res.drafted_by,
    }


def draft_highlights(
    provider: Optional[DraftingProvider] = None,
    today: Optional[date] = None,
    style_examples: Optional[str] = None,
    on_event: Optional[Observer] = None,
) -> dict[str, Any]:
    """Draft the Weekly Highlights for the 7 days ending on ``today``.

    Only the 5 HIGHLIGHT_COMPANIES are considered, in priority order (Visa,
    Mastercard, American Express, PayPal, Circle); Block and Global Payments
    never get a highlight.  For each company the provider searches the
    company's own investor relations site first, and the open web only if that
    returned no story.  Companies are processed in priority order until 4
    highlights are found, so lower-priority companies are searched only when a
    higher-priority one has no news.

    ``provider`` defaults to ``get_provider()`` (CYTONN_LLM_PROVIDER, default
    Anthropic).

    Returns {"week_start", "week_end", "highlights", "shortfall", "warnings"}.
    Each highlight has company, search_scope ("investor_relations" or
    "web_fallback"), ir_domain, headline, headline_md, body (plain), body_md
    (with inline links), links, claims [{text, url, title, cited_text}],
    citations, warnings, drafted_by.  "shortfall" is how many highlights short
    of 4 the result is (0 if complete); it is never filled from outside the 5.
    Provider errors propagate to the caller.

    ``on_event`` (common/run_events.py) is told as each company's search and draft
    starts and ends; it changes nothing about the result.
    """
    provider = provider or get_provider()
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
        emit(on_event, PIECE_STARTED, company["name"])
        res = provider.find_highlight(
            company["name"],
            company["ir_domain"],
            start=start,
            end=end,
            today=today,
            aliases=company["aliases"],
            style_examples=examples,
        )
        warnings.extend(res.draft_warnings)
        if res.no_story:
            warnings.append(f"{company['name']}: no story found for the week (IR site or web)")
            emit(on_event, PART_SKIPPED, company["name"], detail="No story found for the week (IR site or web).")
        else:
            highlights.append(_highlight_item(res))
            emit(on_event, PIECE_FINISHED, company["name"], detail=res.headline)

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

STATS_DECIMALS = 1  # the table's display precision; the outlook reuses its averages verbatim


def _avg(values: list[float]) -> float:
    """Mean at display precision, rounded half up on the values' shortest string form."""
    ds = [Decimal(repr(v)) for v in values]
    mean = sum(ds) / len(ds)
    # + 0.0 turns a negative zero (a tiny negative mean rounded to 0.0) into plain 0.0
    return float(mean.quantize(Decimal(1).scaleb(-STATS_DECIMALS), rounding=ROUND_HALF_UP)) + 0.0


def table_stats(table_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summary statistics from digital_payments.py rows (failed rows excluded).

    Averages are rounded (half up) to the table's display precision, one decimal.
    Average forward P/E is included only if rows carry a numeric "forward_pe".
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
            avg_wow_pct=_avg(wow),
            avg_ytd_pct=_avg(ytd),
            advancers=sum(1 for v in wow if v > 0),
            decliners=sum(1 for v in wow if v < 0),
        )
    pes = [
        r["forward_pe"]
        for r in ok
        if isinstance(r.get("forward_pe"), (int, float)) and not isinstance(r.get("forward_pe"), bool)
    ]
    if pes:
        stats["avg_forward_pe"] = _avg(pes)
    return stats



def draft_outlook(
    draft: dict[str, Any],
    table_rows: list[dict[str, Any]],
    provider: Optional[DraftingProvider] = None,
    on_event: Optional[Observer] = None,
) -> dict[str, Any]:
    """Draft the closing outlook paragraph (bold italic, uncited synthesis).

    Returns {"text_md", "text", "stats", "warnings", "drafted_by"}.  No web
    search is used.
    """
    provider = provider or get_provider()
    stats = table_stats(table_rows)
    warnings: list[str] = []
    if not draft["highlights"]:
        warnings.append("no highlights to synthesize; outlook drafted from table only")
    if stats["companies_failed"]:
        warnings.append(f"{stats['companies_failed']} table row(s) failed and are excluded from the stats")
    if "avg_forward_pe" not in stats:
        warnings.append("forward P/E not available in table output; outlook has no P/E figure")

    emit(on_event, PIECE_STARTED, OUTLOOK_LABEL)
    result = provider.draft_outlook(stats, draft["highlights"])
    emit(on_event, PIECE_FINISHED, OUTLOOK_LABEL)
    text = result.text
    n = _word_count(text)
    if not OUTLOOK_WORDS[0] <= n <= OUTLOOK_WORDS[1]:
        warnings.append(f"outlook is {n} words, outside {OUTLOOK_WORDS[0]}-{OUTLOOK_WORDS[1]}")
    return {
        "text_md": f"***{text}***",
        "text": text,
        "stats": result.stats,
        "warnings": warnings,
        "drafted_by": result.drafted_by,
    }


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
