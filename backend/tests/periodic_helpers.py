"""Builders for the Markets Review (quarterly, half-year, annual) tests: real pipelines on fake edges.

Same idea as section_helpers.py: the real fetch-parse, compose, check and review code
runs; only the network and the LLM are replaced.  Sources are the real documents
captured to tests/fixtures/sources/ on 2026-10-05: CBK's T-bond results PDFs for every
Q3'2026 auction with the treasury-bonds listing they were linked from, KNBS's September
2026 CPI release, and afx.kwayisi.org's NSE page.
"""

from datetime import date
from pathlib import Path

from cytonn_weekly.fixed_income import cbk_auctions
from cytonn_weekly.periodic import equities, kenya_macro
from cytonn_weekly.periodic.common import PeriodContext
# The builders themselves, bound at import, so a test that monkeypatches a section module's
# builder (to fake the API's draft) still gets the real pipeline from the helpers below.
from cytonn_weekly.periodic.company_updates import build_company_updates_review
from cytonn_weekly.periodic.digital_payments import build_digital_payments_review
from cytonn_weekly.periodic.equities import build_equities_review
from cytonn_weekly.periodic.fixed_income import build_fixed_income_review
from cytonn_weekly.periodic.global_markets import build_global_markets_review
from cytonn_weekly.periodic.kenya_macro import build_kenya_macro_review
from cytonn_weekly.periodic.real_estate import build_real_estate_review
from cytonn_weekly.periodic.ssa import build_ssa_review
from tests import section_helpers as sh
from tests.review_helpers import FakeProvider

SOURCES = Path(__file__).parent / "fixtures" / "sources"
TODAY = date(2026, 10, 4)
Q3 = "Q3'2026"

# Every Q3'2026 auction's results PDF, by the value date CBK puts in its file name.
TBOND_PDFS = {
    "2026-07-13": "cbk_tbond_2026-07-13.pdf",
    "2026-07-15": "cbk_tbond_2026-07-15_switch.pdf",
    "2026-07-27": "cbk_tbond_2026-07-27.pdf",
    "2026-08-17": "cbk_tbond_2026-08-17.pdf",
    "2026-08-26": "cbk_tbond_2026-08-26_switch.pdf",
    "2026-09-07": "cbk_tbond_2026-09-07.pdf",
    "2026-09-09": "cbk_tbond_2026-09-09_switch.pdf",
    "2026-09-21": "cbk_tbond_2026-09-21.pdf",
}
LISTING = SOURCES / "cbk_tbond_listing_2026-10-05_excerpt.html"
KNBS_CPI = SOURCES / "knbs_cpi_2026-09_first5pages.pdf"
AFX_NSE = SOURCES / "afx_nse_2026-10-02.html"


def ctx(report_type="quarterly", period=Q3, text=None, db_path=None, today=TODAY):
    return PeriodContext.of(report_type, period, today=today, text=text, db_path=db_path)


def cbk_get(url: str) -> bytes:
    """CBK as captured: the listing excerpt and the Q3'2026 PDFs; any other PDF (e.g. 2025's) is not captured."""
    if url == cbk_auctions.TBOND_LISTING:
        return LISTING.read_bytes()
    when = cbk_auctions.link_value_date(url)
    name = TBOND_PDFS.get(when.isoformat()) if when else None
    if name is None:
        raise FileNotFoundError(f"not captured: {url}")
    return (SOURCES / name).read_bytes()


def fetch_tbonds(start, end):
    return cbk_auctions.fetch_period_tbonds(start, end, get=cbk_get)


def fetch_cpi(month):
    return kenya_macro.fetch_cpi(month, get=lambda url: KNBS_CPI.read_bytes())


def fetch_indices():
    return equities.fetch_indices(get=lambda url: AFX_NSE.read_bytes())


def dp_rows(today=None):
    """The weekly fetcher's row shape, for every tracked company."""
    names = [("Visa", "V"), ("Mastercard", "MA"), ("American Express", "AXP"), ("Circle Internet Group", "CRCL"),
             ("Block Inc.", "XYZ"), ("PayPal Holdings", "PYPL"), ("Global Payments", "GPN")]
    return [{"company": c, "ticker": t, "error": None, "current_price": 100.0, "current_price_date": "2026-10-02",
             "prior_close": 98.0, "prior_close_date": "2026-09-25", "ytd_open": 90.0, "wow_pct": 100 / 98 * 100 - 100,
             "ytd_pct": 100 / 90 * 100 - 100, "forward_pe": 20.0} for c, t in names]


def dp_history(ticker, start, end):
    """Closes on the quarter's eve (30 June) and last day (30 Sept)."""
    return [(date(2026, 6, 29), 79.0), (date(2026, 6, 30), 80.0), (date(2026, 9, 30), 96.0)]


def narrative(**kw):
    return sh.FakeNarrativeProvider(**kw)


# (``on_event`` is the optional run observer, common/run_events.py; None is a plain draft)

def global_markets_review(c=None, provider=None, on_event=None):
    return build_global_markets_review(c or ctx(), provider=provider or narrative(), on_event=on_event)


def ssa_review(c=None, provider=None, on_event=None):
    return build_ssa_review(c or ctx(), provider=provider or narrative(), on_event=on_event)


def kenya_macro_review(c=None, provider=None, on_event=None, fetch_inflation=fetch_cpi):
    return build_kenya_macro_review(c or ctx(), provider=provider or narrative(), fetch_inflation=fetch_inflation,
                                    on_event=on_event)


def fixed_income_review(c=None, provider=None, on_event=None):
    return build_fixed_income_review(c or ctx(), provider=provider or narrative(), fetch_tbonds=fetch_tbonds,
                                     on_event=on_event)


def equities_review(c=None, provider=None, on_event=None):
    return build_equities_review(c or ctx(), provider=provider or narrative(), fetch=fetch_indices, on_event=on_event)


def real_estate_review(c=None, provider=None, on_event=None):
    return build_real_estate_review(c or ctx(), provider=provider or narrative(),
                                                fetch_reits=lambda today: sh.reits(), on_event=on_event)


def digital_payments_review(c=None, provider=None, narrative_provider=None, on_event=None):
    return build_digital_payments_review(
        c or ctx(), provider=provider or FakeProvider(), narrative_provider=narrative_provider or narrative(),
        fetch_table=dp_rows, history=dp_history, on_event=on_event)


def company_updates_review(c=None, text="Investment Updates: Weekly Rates: Demo text. Hospitality Updates: Demo text.",
                           on_event=None):
    return build_company_updates_review(c or ctx(text=text), on_event=on_event)


BUILDERS = {
    "global_markets": global_markets_review,
    "ssa": ssa_review,
    "kenya_macro": kenya_macro_review,
    "fixed_income": fixed_income_review,
    "equities": equities_review,
    "real_estate": real_estate_review,
    "digital_payments": digital_payments_review,
}
