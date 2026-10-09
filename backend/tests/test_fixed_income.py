"""Fixed Income: CBK auction-result parsers against real PDFs, and the MMF ranking."""

from pathlib import Path

import pytest

from cytonn_weekly.common.formatting import format_rows
from cytonn_weekly.fixed_income import cbk_auctions as cbk
from cytonn_weekly.fixed_income import mmf

SOURCES = Path(__file__).parent / "fixtures" / "sources"
TBILL_PDF = (SOURCES / "cbk_tbill_2026-09-28.pdf").read_bytes()
TBOND_PDF = (SOURCES / "cbk_tbond_2026-09-21.pdf").read_bytes()
BOND_LISTING = (SOURCES / "cbk_tbond_listing_excerpt.html").read_text(encoding="utf-8")


def test_tbill_results_match_the_real_pdf():
    tables, text = cbk._tables_and_text(TBILL_PDF)
    out = cbk.parse_tbill_results(tables, text)
    assert out["auction_date"] == "2026-09-28"
    r91, r182, r364 = out["rows"]
    # CBK prints KES m (8,000.00 / 17,739.93 / 16,546.14); stored in KES bn, the report's unit.
    assert r91 == {"tenor": "91-day", "offered_kes_bn": 8.0, "bids_kes_bn": 17.73993,
                   "subscription_pct": pytest.approx(17739.93 / 8000 * 100), "accepted_kes_bn": 16.54614,
                   "avg_rate_pct": 8.7781, "prior_avg_rate_pct": 8.7837, "error": None}
    assert (r182["avg_rate_pct"], r364["avg_rate_pct"]) == (8.8949, 9.0431)


def test_tbill_display_rows_print_as_cytonn_weekly_38_2026_did():
    """#38.2026 reported this auction: "bids of Kshs 17.7 bn against the offered Kshs 8.0 bn, translating to a
    subscription rate of 221.7%"; "182-day ... to 8.89% from 8.91%"; "364-day ... to 9.04% from 9.06%"; "the 182-day
    paper increased to 127.6%"; "the 364-day paper increased to 112.3%"."""
    tables, text = cbk._tables_and_text(TBILL_PDF)
    r91, r182, r364 = format_rows(cbk.parse_tbill_results(tables, text)["rows"], cbk.TBILL_COLUMNS)
    assert r91 == {"tenor": "91-day", "offered_kes_bn": "8.0", "bids_kes_bn": "17.7", "subscription_pct": "221.7%",
                   "accepted_kes_bn": "16.5", "avg_rate_pct": "8.78%", "prior_avg_rate_pct": "8.78%"}
    assert (r182["avg_rate_pct"], r182["prior_avg_rate_pct"], r182["subscription_pct"]) == ("8.89%", "8.91%", "127.6%")
    assert (r364["avg_rate_pct"], r364["prior_avg_rate_pct"], r364["subscription_pct"]) == ("9.04%", "9.06%", "112.3%")


def test_subscription_is_derived_unrounded_not_from_cbks_rounded_rate():
    """Regression: CBK prints the 91-day performance rate as 221.75 (already rounded); re-rounding that half-up gives
    221.8%, but the report printed 221.7%, which is 17,739.93 / 8,000.00 = 221.749% rounded once."""
    tables, text = cbk._tables_and_text(TBILL_PDF)
    assert cbk._labelled_rows(tables)["performancerate"][0] == "221.75"
    r91 = cbk.parse_tbill_results(tables, text)["rows"][0]
    assert format_rows([r91], cbk.TBILL_COLUMNS)[0]["subscription_pct"] == "221.7%"


def test_tbond_results_match_the_real_pdf():
    tables, text = cbk._tables_and_text(TBOND_PDF)
    out = cbk.parse_tbond_results(tables, text)
    assert out["total_offered_kes_bn"] == 60.0
    assert out["total_subscription_pct"] == pytest.approx(81405.30 / 60000 * 100)
    a, b = out["rows"]
    assert a["issue"] == "FXD1/2019/020" and a["tenor"] == "Twenty (12.6 years to maturity)"
    assert (a["bids_kes_bn"], a["accepted_kes_bn"], a["avg_rate_pct"], a["coupon_pct"]) == (43.80382, 33.45674, 13.6105, 12.873)
    assert a["subscription_pct"] == pytest.approx(43803.82 / 60000 * 100)
    assert (b["issue"], b["avg_rate_pct"], b["coupon_pct"]) == ("FXD1/2026/030", 14.2355, 12.5)


def test_tbond_display_rows():
    """Coupon to 1 dp as #38.2026 printed it: "FXD1/2019/020 has a fixed coupon rate of 12.9%" (CBK: 12.8730)."""
    tables, text = cbk._tables_and_text(TBOND_PDF)
    a, b = format_rows(cbk.parse_tbond_results(tables, text)["rows"], cbk.TBOND_COLUMNS)
    assert a == {"issue": "FXD1/2019/020", "tenor": "Twenty (12.6 years to maturity)", "bids_kes_bn": "43.8",
                 "subscription_pct": "73.0%", "accepted_kes_bn": "33.5", "avg_rate_pct": "13.61%", "coupon_pct": "12.9%"}
    assert (b["avg_rate_pct"], b["coupon_pct"]) == ("14.24%", "12.5%")


def test_parsers_flag_rather_than_guess_on_an_unrecognised_layout():
    out = cbk.parse_tbill_results([[["Something else", "1", "2", "3"]]])
    assert all(r["error"] and r["avg_rate_pct"] is None for r in out["rows"])
    assert cbk.parse_tbond_results([[["Nothing", "here"]]])["rows"] == []


def test_listing_links_and_bond_fetch_skip_switch_results():
    links = cbk.latest_pdf_links(BOND_LISTING, "historical_treasury_bond_results")
    assert len(links) == 4 and links[0].startswith("https://www.centralbank.go.ke/uploads/")
    fetched = []

    def get(url):
        fetched.append(url)
        return BOND_LISTING.encode() if url == cbk.TBOND_LISTING else TBOND_PDF

    out = cbk.fetch_latest_tbond_results(get=get)
    assert "FXD3-2019-015" in out["source_url"] and "SWITCH" not in fetched[1]
    assert out["rows"][0]["issue"] == "FXD1/2019/020"


def test_tbill_fetch_uses_the_newest_listed_pdf():
    listing = ('<a href="/uploads/91_day_historical_treasury_bill_results/2_RESULTS 2701 DATED 05-10-2026.pdf">2702</a>'
               '<a href="/uploads/91_day_historical_treasury_bill_results/1_RESULTS 2700 DATED 28-09-2026.pdf">2701</a>')
    seen = []

    def get(url):
        seen.append(url)
        return listing.encode() if url == cbk.TBILL_LISTING else TBILL_PDF

    out = cbk.fetch_latest_tbill_results(get=get)
    assert "05-10-2026" in seen[1] and out["rows"][0]["avg_rate_pct"] == 8.7781


def test_fetch_raises_when_no_pdf_is_linked():
    with pytest.raises(LookupError):
        cbk.fetch_latest_tbill_results(get=lambda url: b"<html></html>")


def test_mmf_ranking_shares_ranks_on_ties():
    rows = mmf.format_mmf_table([mmf.MmfYield("B Fund", 12.5), mmf.MmfYield("A Fund", 13.0),
                                 mmf.MmfYield("C Fund", 12.5), mmf.MmfYield("D Fund", 9.875)])
    assert [(r["rank"], r["fund"], r["effective_annual_rate_pct"]) for r in rows] == [
        ("1", "A Fund", "13.0%"), ("2", "B Fund", "12.5%"), ("2", "C Fund", "12.5%"), ("4", "D Fund", "9.9%")]


def test_mmf_display_ties_still_rank_sequentially_as_cytonn_weekly_38_2026_did():
    """#38.2026 printed "1 | Cytonn Money Market Fund ... | 11.0%" and "2 | Nabo Africa Money Market Fund | 11.0%": tied
    as printed, ranked 1 and 2.  All nine display-tied groups in that table rank sequentially, ordered by something
    finer than the printed rate (Lofty-Corban above Arvocap, both 10.7%; not alphabetical).  Rates equal at display
    precision but not at source precision (the source values here are hypothetical) must never share a rank."""
    rows = mmf.format_mmf_table([mmf.MmfYield("Nabo Africa Money Market Fund", 10.96),
                                 mmf.MmfYield("Cytonn Money Market Fund", 11.04),
                                 mmf.MmfYield("Faulu Money Market Fund", 10.8),
                                 mmf.MmfYield("Arvocap Money Market Fund", 10.71),
                                 mmf.MmfYield("Lofty-Corban Money Market Fund", 10.74)])
    assert [(r["rank"], r["fund"], r["effective_annual_rate_pct"]) for r in rows] == [
        ("1", "Cytonn Money Market Fund", "11.0%"), ("2", "Nabo Africa Money Market Fund", "11.0%"),
        ("3", "Faulu Money Market Fund", "10.8%"), ("4", "Lofty-Corban Money Market Fund", "10.7%"),
        ("5", "Arvocap Money Market Fund", "10.7%")]


def test_unbuilt_sources_fail_loudly():
    with pytest.raises(NotImplementedError, match="Business Daily"):
        mmf.fetch_mmf_yields()


def test_the_kcb_email_stub_is_retired():
    """Its premise was wrong: KCB IB's reports cover NSE equities only, and the weekly section is built without them."""
    import importlib.util

    assert importlib.util.find_spec("cytonn_weekly.fixed_income.kcb_email") is None
    assert importlib.util.find_spec("cytonn_weekly.fixed_income.weekly") is not None
