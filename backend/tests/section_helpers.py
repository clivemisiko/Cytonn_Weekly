"""Shared builders for the Equities / Real Estate / Focus tests: real pipelines on fake edges.

Same idea as review_helpers.py: the real fetch-parse, compose, check and review
code runs; only the network and the LLM are replaced.  Source data is the real
shape (and, where noted, real values) observed from afx.kwayisi.org, the NSE
Ibuka PDF and CBK's results PDFs on 2026-10-02.
"""

from datetime import date

from cytonn_weekly.digital_payments.providers.base import SCOPE_WEB, HighlightResult
from cytonn_weekly.equities.review_run import build_equities_review
from cytonn_weekly.focus.review_run import build_focus_review
from cytonn_weekly.narrative.base import NarrativeProvider
from cytonn_weekly.real_estate.review_run import build_real_estate_review

TODAY = date(2026, 10, 2)


class FakeNarrativeProvider(NarrativeProvider):
    """Drafts one piece per brief, except the briefs named in ``no_story``.

    Each piece has two claims whose figures appear verbatim in the cited text,
    unless ``bad_figure`` is set, in which case the second claim quotes a figure
    its cited text does not contain.
    """

    drafted_by = "fake:test"

    def __init__(self, no_story=(), bad_figure=False, cited=True):
        self.no_story = set(no_story)
        self.bad_figure = bad_figure
        self.cited = cited
        self.calls = []

    def draft_piece(self, brief, *, start, end, today):
        self.calls.append(brief.id)
        if brief.id in self.no_story:
            return HighlightResult(company=brief.label, search_scope=None, ir_domain="", drafted_by=self.drafted_by,
                                   no_story=True)
        url = f"https://example.org/{brief.id}"
        second = "Lending rose to Sh99.9 billion." if self.bad_figure else "Lending rose to Sh30.1 billion."
        claims = [
            {"text": f"During the week, {brief.label} grew 8.75% in 2026.", "url": url, "title": brief.label,
             "cited_text": f"{brief.label} grew by 8.75 percent in 2026." if self.cited else ""},
            {"text": second, "url": url, "title": brief.label,
             "cited_text": "Lending rose to Sh30.1bn this quarter." if self.cited else ""},
        ]
        body = " ".join(c["text"] for c in claims)
        return HighlightResult(
            company=brief.label, search_scope=SCOPE_WEB, ir_domain="", drafted_by=self.drafted_by,
            headline=f"{brief.label}: a development", paragraph=body,
            paragraph_md=body.replace("grew", f"[grew]({url})", 1), claims=claims,
        )


class LocalFakeNarrativeProvider(FakeNarrativeProvider):
    drafted_by = "local:phi4-mini"


# --- Equities -------------------------------------------------------------------

def index_rows():
    """The real afx index figures of 1 Oct 2026."""
    return [
        {"index": "NASI", "name": "NASI", "close": 246.82, "wow_pct": -0.66, "ytd_pct": 32.29, "error": None},
        {"index": "NSE25", "name": "NSE 25", "close": None, "wow_pct": -0.91, "ytd_pct": 37.08, "error": None},
        {"index": "NSE20", "name": "NSE 20", "close": None, "wow_pct": -0.95, "ytd_pct": 37.57, "error": None},
        {"index": "NSE10", "name": "NSE 10", "close": None, "wow_pct": -0.84, "ytd_pct": 39.43, "error": None},
        {"index": "BANKING", "name": "NSE Banking Sector Index", "close": None, "wow_pct": -1.4, "ytd_pct": 41.99,
         "error": None},
    ]


def share(ticker, company, price, wow, error=None):
    return {"ticker": ticker, "company": company, "price": price, "wow_pct": wow, "ytd_pct": 10.0, "error": error}


def market(shares=None, as_of="2026-10-02T13:00:00+00:00"):
    shares = shares if shares is not None else [
        share("UMME", "Umeme Ltd", 6.2, 8.01), share("OCH", "Olympia Capital Holdings Ltd", 8.0, 5.54),
        share("SCOM", "Safaricom Plc", 36.4, 0.14), share("NMG", "Nation Media Group", 14.2, -7.79),
        share("XPRS", "Express Kenya Ltd", 7.0, -7.65), share("KCB", "KCB Group", 92.25, None, error="timeout"),
    ]
    return {"as_of": as_of, "source_url": "https://afx.kwayisi.org/nse/", "indices": index_rows(), "shares": shares}


# --- Real Estate -----------------------------------------------------------------

def reits(warnings=()):
    """The real Ibuka figures of 25 Sept 2026 (prices unchanged from the 18 Sept summary)."""
    rows = [
        {"reit": "ACORN_D", "name": "Acorn D-REIT", "price": 29.65, "inception_gain_pct": 48.5, "prior_price": 29.65,
         "ytd_base_price": 25.0, "wow_pct": 0.0, "ytd_pct": 18.6, "market_cap_kes_bn": 8.674903573, "error": None},
        {"reit": "ACORN_I", "name": "Acorn I-REIT", "price": 24.44, "inception_gain_pct": 22.0, "prior_price": 23.75,
         "ytd_base_price": 22.0, "wow_pct": 2.905263157894737, "ytd_pct": 11.09, "market_cap_kes_bn": 9.898749704,
         "error": None},
        {"reit": "FAHARI", "name": "ILAM Fahari I-REIT", "price": 13.8, "inception_gain_pct": -31.0, "prior_price": 13.8,
         "ytd_base_price": 11.0, "wow_pct": 0.0, "ytd_pct": 25.45, "market_cap_kes_bn": 2.49741774, "error": None},
    ]
    return {"as_of": "2026-09-25", "source_url": "https://www.nse.co.ke/x.pdf", "prior_url": None, "ytd_url": None,
            "rows": rows, "warnings": list(warnings)}


# --- Ready-made reviews ----------------------------------------------------------
# (builders imported at module level, so a test that monkeypatches the section module's
# builder still gets the real pipeline from these)

# (``on_event`` is the optional run observer, common/run_events.py; None is a plain draft)

def equities_review(provider=None, on_event=None):
    return build_equities_review(provider=provider or FakeNarrativeProvider(no_story={"corporate_actions"}),
                                 today=TODAY, fetch_market=market, on_event=on_event)


def real_estate_review(provider=None, on_event=None):
    return build_real_estate_review(provider=provider or FakeNarrativeProvider(no_story={"hospitality"}),
                                    today=TODAY, fetch_reits=lambda _today: reits(), on_event=on_event)


def focus_review(provider=None, topic="SSA Eurobonds performance", on_event=None):
    return build_focus_review(topic, provider=provider or FakeNarrativeProvider(), today=TODAY, on_event=on_event)
