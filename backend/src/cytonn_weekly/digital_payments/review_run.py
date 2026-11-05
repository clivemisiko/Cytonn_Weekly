"""Runs the Digital Payments pipeline end to end up to the coordinator's review.

    fetch table -> draft highlights -> draft outlook -> compose -> check -> review

This is the one place that wires the existing pieces together; each step is the
existing function, unchanged.  The checker compares the display-formatted rows
(format_table_rows) against the fetched source rows, the same pairing the
live-proven table check uses.

Live use calls Yahoo Finance and the drafting provider (CYTONN_LLM_PROVIDER):
the default Anthropic provider spends real API budget, the local one is a
dev-only mode.  Callers load the environment first (cytonn_weekly.env.load_env).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Optional

from cytonn_weekly.checkers.digital_payments import TABLE_TITLE, check_digital_payments
from cytonn_weekly.common.run_events import PIECE_FINISHED, Observer, emit, fetch_source, report_failed_rows
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview, build_coordinator_review
from cytonn_weekly.digital_payments.fetcher import fetch_digital_payments, format_table_rows
from cytonn_weekly.digital_payments.highlights import compose_section, draft_highlights, draft_outlook
from cytonn_weekly.digital_payments.provider_factory import get_provider
from cytonn_weekly.digital_payments.providers.base import DraftingProvider
from cytonn_weekly.digital_payments.workbook import read_dp_workbook, year_open_warnings
from cytonn_weekly.weekly.workbook import Workbook

SOURCE_NAME = "Yahoo Finance"


def build_digital_payments_review(
    provider: Optional[DraftingProvider] = None,
    today: Optional[date] = None,
    fetch_table: Callable[[Optional[date]], list[dict[str, Any]]] = fetch_digital_payments,
    on_event: Optional[Observer] = None,
    workbook: Optional[Workbook] = None,
) -> CoordinatorReview:
    """Draft this week's Digital Payments section, check it, and return the review.

    ``provider`` defaults to the one CYTONN_LLM_PROVIDER selects.  Provider and
    fetch errors propagate to the caller.  ``on_event`` (common/run_events.py) is
    told each step as it happens; with None the run is exactly what it always was.
    ``workbook`` (the uploaded Digital Payments workbook, optional) adds reviewer warnings: a P/E or Average the
    workbook shows that is not the figure worked out by company name, a Year Open that is not the first trading
    day's close, and quarters its P/E formulas add while blank.  It changes no printed figure.
    """
    provider = provider or get_provider()
    draft = draft_highlights(provider=provider, today=today, on_event=on_event)
    table = fetch_source(on_event, SOURCE_NAME, fetch_table, today)
    report_failed_rows(on_event, table, lambda r: f"{SOURCE_NAME}: {r.get('company') or r['ticker']} ({r['ticker']})")
    outlook = draft_outlook(draft, table, provider=provider, on_event=on_event)
    section = compose_section(draft, table, outlook)
    if workbook is not None:
        book = read_dp_workbook(workbook)
        section["warnings"] += book.warnings + year_open_warnings(book, table)
        if book.blank_quarters:
            section["warnings"].append(
                f"The workbook's P/E formulas add blank cells ({', '.join(book.blank_quarters)}) as 0, so those P/Es cover fewer than four quarters"
            )
    emit(on_event, PIECE_FINISHED, TABLE_TITLE)
    report = check_digital_payments(
        source_rows=table,
        drafted_rows=format_table_rows(table),
        drafted_outlook_stats=outlook["stats"],
        highlights=draft["highlights"],
        on_event=on_event,
    )
    return build_coordinator_review(section, report)
