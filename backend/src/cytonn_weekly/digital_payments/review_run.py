"""Runs the Digital Payments pipeline end to end up to the analyst's review.

    fetch table -> draft highlights -> draft outlook -> compose -> check -> review

This is the one place that wires the existing pieces together; each step is the
existing function, unchanged.  The checker compares the display-formatted rows
(format_table_rows) against the fetched source rows, the same pairing the
live-proven table check uses.

Live use calls Yahoo Finance and the drafting provider (CYTONN_LLM_PROVIDER):
the Anthropic and Bedrock providers spend real model budget, the local one is a
dev-only mode.  Callers load the environment first (cytonn_weekly.env.load_env).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Optional

from cytonn_weekly.digital_payments.checks import TABLE_TITLE, check_digital_payments
from cytonn_weekly.common.run_events import PIECE_FINISHED, Observer, emit, fetch_source, report_failed_rows
from cytonn_weekly.review.figures import NOT_IMPLEMENTED, CheckReport, Flag
from cytonn_weekly.review.model import (
    ACCEPT, CLEAN, FLAGGED, HIGHLIGHT_CLAIM, NOT_AUTO_VERIFIED, NOT_AUTO_VERIFIED_NOTE, OUTLOOK_STAT, SOURCE_KEYS, TABLE_ROW,
    WORKBOOK_QUARTER, CoordinatorReview, ReviewItem,
)
from cytonn_weekly.digital_payments.fetcher import fetch_digital_payments, format_table_rows
from cytonn_weekly.digital_payments.highlights import compose_section, draft_highlights, draft_outlook
from cytonn_weekly.drafting.factory import get_provider
from cytonn_weekly.drafting.highlight_contract import DraftingProvider
from cytonn_weekly.digital_payments.workbook import (
    Fill, Search, exa_search, fill_blanks, pe_table, read_dp_workbook, year_open_warnings,
)
from cytonn_weekly.weekly.workbook import Workbook

SOURCE_NAME = "Yahoo Finance"

_REF_CLAIM_CHARS = 80


def _item(kind: str, ref: str, flags: list[Flag]) -> ReviewItem:
    if flags:
        return ReviewItem(kind=kind, ref=ref, status=FLAGGED, detail=flags)
    return ReviewItem(kind=kind, ref=ref, status=CLEAN)


def _claim_ref(numeral: str, h: dict[str, Any], text: str) -> str:
    text = " ".join(text.split())
    if len(text) > _REF_CLAIM_CHARS:
        text = text[: _REF_CLAIM_CHARS - 1].rstrip() + "…"
    who = h.get("company") or h.get("headline", "")
    return f"Highlight {numeral} ({who}): {text}" if text else f"Highlight {numeral} ({who})"


def _claim_context(claim: dict[str, Any]) -> dict[str, Any]:
    context = {k: claim.get(k, "") for k in ("text", "url", "title", "cited_text")}
    context.update({k: claim[k] for k in SOURCE_KEYS if k in claim})
    return context


def _unverified(ref: str, claim: dict[str, Any]) -> ReviewItem:
    return ReviewItem(
        kind=HIGHLIGHT_CLAIM, ref=ref, status=NOT_AUTO_VERIFIED,
        detail=NOT_AUTO_VERIFIED_NOTE, context=_claim_context(claim),
    )


def build_coordinator_review(compose_result: dict[str, Any], check_report: CheckReport) -> CoordinatorReview:
    """Build the analyst's review items from compose_section() and its CheckReport.

    CheckReport holds only flags and a count of figures compared; it records
    nothing about what passed.  "Clean" is therefore derived: every unit that
    compose_section() contains and that no flag points at.  Every flag the
    checker raised (other than the NOT_IMPLEMENTED placeholder, which the
    ``not_auto_verified`` highlight items stand in for) ends up on some item,
    even if it points at something compose_section() does not contain, so none
    can go missing.

    Raises ValueError if the report compared nothing at all while the section
    has things to check, since every item would then read "clean" without
    anything having been checked.
    """
    flags = [f for f in check_report.flags if f.kind != NOT_IMPLEMENTED]
    table_flags: dict[str, list[Flag]] = {}
    outlook_flags: dict[str, list[Flag]] = {}
    highlight_flags: dict[str, list[Flag]] = {}
    for f in flags:
        if f.scope == "table":
            table_flags.setdefault(f.subject, []).append(f)
        elif f.scope == "outlook":
            outlook_flags.setdefault(f.field or "outlook", []).append(f)
        elif f.scope == "highlight":
            highlight_flags.setdefault(f.subject, []).append(f)
        else:
            raise ValueError(f"flag with unrecognised scope {f.scope!r}: {f.message}")

    items: list[dict[str, Any]] = compose_result.get("items", [])
    outlook = compose_result.get("outlook") or {}
    stats: dict[str, Any] = outlook.get("stats") or {}
    table_rows = [r for it in items if it.get("kind") == "stock_table" for r in it.get("rows", [])]

    if check_report.checked == 0 and not flags and (table_rows or stats):
        raise ValueError(
            "check_report compared no figures, so nothing would be checked; "
            "run check_digital_payments() with the drafted table rows and outlook stats first"
        )

    review: list[ReviewItem] = []

    # Table rows: one per source row, then any flagged ticker compose does not contain.
    seen: set[str] = set()
    for r in table_rows:
        ticker = r["ticker"]
        seen.add(ticker)
        review.append(_item(TABLE_ROW, f"{r.get('company', ticker)} ({ticker})", table_flags.get(ticker, [])))
    for ticker, fl in table_flags.items():
        if ticker not in seen:
            review.append(_item(TABLE_ROW, ticker, fl))

    # Outlook stats: one per drafted stat, then any flagged stat that was not drafted (e.g. missing).
    stat_keys = list(stats) + [k for k in outlook_flags if k not in stats]
    for key in stat_keys:
        review.append(_item(OUTLOOK_STAT, f"Outlook: {key}", outlook_flags.get(key, [])))

    # Highlight claims: always not_auto_verified until 6b; a highlight flag (6b's, once it
    # exists) marks every claim of that highlight as flagged rather than being dropped.
    matched: set[str] = set()
    for it in items:
        if it.get("kind") != "highlight":
            continue
        numeral = it.get("numeral", "")
        headline = it.get("headline", "")
        own = highlight_flags.get(headline, [])
        if own:
            matched.add(headline)
        claims = it.get("claims") or [{"text": ""}]  # no claims: still list the highlight itself
        for c in claims:
            ref = _claim_ref(numeral, it, c.get("text", ""))
            if own:
                review.append(ReviewItem(
                    kind=HIGHLIGHT_CLAIM, ref=ref, status=FLAGGED, detail=list(own),
                    context=_claim_context(c),
                ))
            else:
                review.append(_unverified(ref, c))
    for headline, fl in highlight_flags.items():
        if headline not in matched:
            review.append(ReviewItem(kind=HIGHLIGHT_CLAIM, ref=headline, status=FLAGGED, detail=fl))

    return CoordinatorReview(section=compose_result, review_items=review)



def build_digital_payments_review(
    provider: Optional[DraftingProvider] = None,
    today: Optional[date] = None,
    fetch_table: Callable[[Optional[date]], list[dict[str, Any]]] = fetch_digital_payments,
    on_event: Optional[Observer] = None,
    workbook: Optional[Workbook] = None,
    search: Search = exa_search,
    as_at: Optional[date] = None,
) -> CoordinatorReview:
    """Draft this week's Digital Payments section, check it, and return the review.

    ``as_at`` is the table's date when the week's Friday was a market holiday (the stock table is
    fetched as at the last trading day, and a Friday 1 January would have no bar of its year).

    ``provider`` defaults to the one CYTONN_LLM_PROVIDER selects.  Provider and
    fetch errors propagate to the caller.  ``on_event`` (common/run_events.py) is
    told each step as it happens; with None the run is exactly what it always was.
    ``workbook`` (the uploaded Digital Payments workbook, optional) adds reviewer warnings: a P/E or Average the
    workbook shows that is not the figure worked out by company name, a Year Open that is not the first trading
    day's close, and quarters its TTM P/E reads while blank (never counted as zero: found on the Financial Results
    sheet or by ``search``, each as a review item to accept, see ``workbook_pe``).  It changes no printed figure.
    """
    provider = provider or get_provider()
    draft = draft_highlights(provider=provider, today=today, on_event=on_event)
    table = fetch_source(on_event, SOURCE_NAME, fetch_table, as_at or today)
    report_failed_rows(on_event, table, lambda r: f"{SOURCE_NAME}: {r.get('company') or r['ticker']} ({r['ticker']})")
    outlook = draft_outlook(draft, table, provider=provider, on_event=on_event)
    section = compose_section(draft, table, outlook)
    if workbook is not None:
        fills, reasons = fill_blanks(workbook, today or date.today(), search)
        book = read_dp_workbook(workbook, fills, reasons)
        section["warnings"] += book.warnings + year_open_warnings(book, table)
        section["workbook_pe"] = [r.as_dict() for r in book.rows]
    emit(on_event, PIECE_FINISHED, TABLE_TITLE)
    report = check_digital_payments(
        source_rows=table,
        drafted_rows=format_table_rows(table),
        drafted_outlook_stats=outlook["stats"],
        highlights=draft["highlights"],
        on_event=on_event,
    )
    review = build_coordinator_review(section, report)
    if workbook is not None:
        review.review_items += [_quarter_item(f) for f in fills]
    return review


def _quarter_item(f: Fill) -> ReviewItem:
    q = f.quarter
    return ReviewItem(
        WORKBOOK_QUARTER, f"{q.company} {q.label} net income ({q.ref})", NOT_AUTO_VERIFIED,
        f"{q.ref} is blank. USD {f.value} bn was found in {f.source} on {f.fetched}: \"{f.quoted}\" "
        f"{q.company}'s TTM P/E stays unavailable until you accept this.",
        context={"company": q.company, "cell": q.ref, "quarter": q.label, "value": str(f.value), "source": f.source,
                 "fetched": f.fetched, "quoted": f.quoted},
    )


def workbook_pe(review: CoordinatorReview) -> dict[str, Any]:
    """The workbook's TTM P/Es and their Average, a filled quarter counting only once its review item is accepted."""
    accepted = {i.context["cell"] for i in review.review_items if i.kind == WORKBOOK_QUARTER and i.resolution == ACCEPT}
    return pe_table(review.section.get("workbook_pe", []), accepted)
