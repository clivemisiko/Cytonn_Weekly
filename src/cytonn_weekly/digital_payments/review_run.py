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

from cytonn_weekly.checkers.digital_payments import check_digital_payments
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview, build_coordinator_review
from cytonn_weekly.digital_payments.fetcher import fetch_digital_payments, format_table_rows
from cytonn_weekly.digital_payments.highlights import compose_section, draft_highlights, draft_outlook
from cytonn_weekly.digital_payments.provider_factory import get_provider
from cytonn_weekly.digital_payments.providers.base import DraftingProvider


def build_digital_payments_review(
    provider: Optional[DraftingProvider] = None,
    today: Optional[date] = None,
    fetch_table: Callable[[Optional[date]], list[dict[str, Any]]] = fetch_digital_payments,
) -> CoordinatorReview:
    """Draft this week's Digital Payments section, check it, and return the review.

    ``provider`` defaults to the one CYTONN_LLM_PROVIDER selects.  Provider and
    fetch errors propagate to the caller.
    """
    provider = provider or get_provider()
    draft = draft_highlights(provider=provider, today=today)
    table = fetch_table(today)
    outlook = draft_outlook(draft, table, provider=provider)
    section = compose_section(draft, table, outlook)
    report = check_digital_payments(
        source_rows=table,
        drafted_rows=format_table_rows(table),
        drafted_outlook_stats=outlook["stats"],
        highlights=draft["highlights"],
    )
    return build_coordinator_review(section, report)
