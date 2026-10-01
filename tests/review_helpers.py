"""Shared builders for the review tests: a real pipeline run on fake edges.

``make_review`` runs the real draft/compose/check/review code with a fake
drafting provider and fixed price rows, so tests get a genuine CoordinatorReview
(real Flag objects, real compose_section() output) without network or LLM.
"""

from datetime import date

from cytonn_weekly.checkers.digital_payments import check_digital_payments
from cytonn_weekly.digital_payments import coordinator_review as cr
from cytonn_weekly.digital_payments.fetcher import format_table_rows
from cytonn_weekly.digital_payments.highlights import compose_section, draft_highlights, draft_outlook
from cytonn_weekly.digital_payments.providers.base import (
    SCOPE_IR, DraftingProvider, HighlightResult, OutlookResult,
)

TODAY = date(2026, 9, 30)


def src_row(ticker, company, wow=2.0, pe=20.0):
    return {"company": company, "ticker": ticker, "error": None, "current_price": 100.0,
            "prior_close": 98.0, "ytd_open": 90.0, "wow_pct": wow, "ytd_pct": 10.0, "forward_pe": pe}


ROWS = [src_row("V", "Visa"), src_row("MA", "Mastercard", wow=-1.5), src_row("AXP", "American Express", pe=18.0)]


class FakeProvider(DraftingProvider):
    drafted_by = "fake:test"

    def find_highlight(self, company, ir_domain, *, start, end, today, aliases=None, style_examples=""):
        text = f"During the week, {company} paid $5 million for a thing."
        return HighlightResult(
            company=company, search_scope=SCOPE_IR, ir_domain=ir_domain, drafted_by=self.drafted_by,
            headline=f"{company} announces a thing", paragraph=text, paragraph_md=text,
            claims=[{"text": text, "url": f"https://{ir_domain}/news", "title": f"{company} news",
                     "cited_text": f"{company} said it paid $5 million."}],
        )

    def draft_outlook(self, table_stats, highlights):
        return OutlookResult(text="Outlook: the sector gained $2 billion.", stats=table_stats,
                             drafted_by=self.drafted_by)


class LocalFakeProvider(FakeProvider):
    drafted_by = "local:phi4-mini"


def make_review(provider=None, tamper=False):
    """The real pipeline pieces on fake edges.  ``tamper`` plants a wrong price (MA) and drops AXP."""
    provider = provider or FakeProvider()
    draft = draft_highlights(provider=provider, today=TODAY)
    outlook = draft_outlook(draft, ROWS, provider=provider)
    section = compose_section(draft, ROWS, outlook)
    drafted = format_table_rows(ROWS)
    if tamper:
        drafted = [r for r in drafted if r["ticker"] != "AXP"]
        next(r for r in drafted if r["ticker"] == "MA")["current_price"] = "101.0"
    report = check_digital_payments(
        ROWS, drafted_rows=drafted, drafted_outlook_stats=outlook["stats"], highlights=draft["highlights"],
    )
    return cr.build_coordinator_review(section, report)
