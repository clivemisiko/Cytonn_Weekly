"""Equities: afx parsing against real saved pages, the review run on fake edges, the stubs."""

from pathlib import Path

import httpx
import pytest

from cytonn_weekly.common.review import CLAIM, UNAVAILABLE_PART
from cytonn_weekly.digital_payments.coordinator_review import CLEAN, FLAGGED, NOT_AUTO_VERIFIED, TABLE_ROW
from cytonn_weekly.equities import fetcher, stubs
from cytonn_weekly.equities.review_run import BRIEFS, SECTION, build_equities_review
from tests.section_helpers import TODAY, FakeNarrativeProvider, equities_review, market, share

SOURCES = Path(__file__).parent / "fixtures" / "sources"
INDEX_HTML = (SOURCES / "afx_nse_2026-10-02.html").read_text(encoding="utf-8")
SCOM_HTML = (SOURCES / "afx_scom_2026-10-02.html").read_text(encoding="utf-8")


# --- parsing the real afx pages ---------------------------------------------------

def test_parse_indices_reads_the_real_paragraph():
    rows = {r["index"]: r for r in fetcher.parse_indices(INDEX_HTML)}
    assert (rows["NASI"]["close"], rows["NASI"]["wow_pct"], rows["NASI"]["ytd_pct"]) == (246.82, -0.66, 32.29)
    assert (rows["NSE10"]["wow_pct"], rows["NSE10"]["ytd_pct"]) == (-0.84, 39.43)
    assert (rows["BANKING"]["wow_pct"], rows["BANKING"]["ytd_pct"]) == (-1.4, 41.99)
    assert all(r["error"] is None for r in rows.values())


def test_parse_indices_reports_rather_than_guesses_when_the_paragraph_changes():
    rows = fetcher.parse_indices("<p>The NSE had a quiet day.</p>")
    assert all(r["error"] and r["wow_pct"] is None for r in rows)


def test_parse_price_list_and_ordinary_share_filter():
    listing = fetcher.parse_price_list(INDEX_HTML)
    by = {r["ticker"]: r for r in listing}
    assert len(listing) == 71 and by["KCB"] == {"ticker": "KCB", "slug": "kcb", "company": "KCB Group", "price": 92.25}
    shares = {r["ticker"] for r in fetcher.ordinary_shares(listing)}
    assert "SCOM" in shares and not shares & {"KPLC-P4", "GLD", "ALP", "LAPR", "TRFC", "SMWF"}


def test_parse_ticker_perf_ignores_the_css_and_reads_the_table():
    assert fetcher.parse_ticker_perf(SCOM_HTML) == {"wow_pct": 0.14, "ytd_pct": 28.4}
    assert fetcher.parse_ticker_perf("<html>no table</html>") == {"wow_pct": None, "ytd_pct": None}


def test_fetch_market_performance_isolates_a_failed_ticker():
    def get(url):
        if url == fetcher.BASE:
            return INDEX_HTML.encode()
        if url.endswith("/kcb.html"):
            raise TimeoutError("slow")
        return SCOM_HTML.encode()

    m = fetcher.fetch_market_performance(get=get, pause=0)
    kcb = next(s for s in m["shares"] if s["ticker"] == "KCB")
    assert kcb["error"] == "TimeoutError: slow"
    assert m["as_of"] == "2026-10-02T09:41:01+00:00" and len(m["indices"]) == 5
    assert all(s["wow_pct"] == 0.14 for s in m["shares"] if not s["error"])


def test_fetch_market_performance_gives_up_when_afx_goes_dark():
    """Seen live: the listing loaded, then every afx address refused connections; without this the
    run waited out ~60 per-ticker timeouts (about an hour) holding the API's one draft slot."""
    calls = []

    def get(url):
        calls.append(url)
        if url == fetcher.BASE:
            return INDEX_HTML.encode()
        if len(calls) <= 3:
            return SCOM_HTML.encode()
        raise httpx.ConnectTimeout("timed out")

    with pytest.raises(fetcher.SourceUnreachable, match=r"after 2 of the ticker pages: 3 in a row.*ConnectTimeout"):
        fetcher.fetch_market_performance(get=get, pause=0)
    assert len(calls) == 1 + 2 + fetcher.MAX_CONSECUTIVE_NETWORK_FAILURES  # stopped, did not try the other ~55


def test_answered_failures_do_not_count_toward_giving_up():
    """A 404 or an unparseable page means afx answered: isolated per row, and it resets the run of failures."""
    n = [0]

    def get(url):
        if url == fetcher.BASE:
            return INDEX_HTML.encode()
        n[0] += 1
        if n[0] % 3 == 0:
            raise ValueError("odd page")  # an answer, just not a usable one
        raise httpx.ConnectError("refused")

    m = fetcher.fetch_market_performance(get=get, pause=0)
    assert all(s["error"] for s in m["shares"]) and len(m["shares"]) > 3


def test_top_movers_rank_and_skip_failures():
    gainers, losers = fetcher.top_movers(market()["shares"], n=2)
    assert [g["ticker"] for g in gainers] == ["UMME", "OCH"]
    assert [l["ticker"] for l in losers] == ["NMG", "XPRS"]


@pytest.mark.parametrize("as_of,warns", [
    ("2026-10-02T09:41:01+00:00", True),    # 12:41 EAT, Friday: mid-session
    ("2026-10-02T13:00:00+00:00", False),   # 16:00 EAT: after the close
    ("2026-10-03T09:00:00+00:00", False),   # Saturday
    (None, True),
])
def test_intraday_warning(as_of, warns):
    assert bool(fetcher.intraday_warning(as_of)) is warns


# --- review run ------------------------------------------------------------------

def test_review_follows_the_report_order_and_checks_clean():
    review = equities_review()
    blocks = review.section["blocks"]
    assert review.section["section"] == SECTION
    assert [b["id"] for b in blocks] == ["indices", "gainers", "losers", "market_activity", "universe_of_coverage",
                                         "highlight_earnings", "highlight_banking", "highlight_market_regulation"]
    assert [b["numeral"] for b in blocks][:3] == ["I", "II", "III"]
    rows = [i for i in review.review_items if i.kind == TABLE_ROW]
    assert len(rows) == 5 + 3 + 2 and all(i.status == CLEAN for i in rows)
    assert blocks[0]["rows"][0] == {"index": "NASI", "name": "NASI", "close": "246.8", "wow_pct": "(0.7%)", "ytd_pct": "32.3%"}


def test_stub_parts_and_claims_need_explicit_resolution():
    review = equities_review()
    stubs_items = [i for i in review.review_items if i.kind == UNAVAILABLE_PART]
    assert [i.ref for i in stubs_items] == ["Market activity and valuation (not available yet)",
                                            "Universe of Coverage (not available yet)"]
    assert all(i.status == FLAGGED for i in stubs_items)
    assert all(i.status == NOT_AUTO_VERIFIED for i in review.review_items if i.kind == CLAIM)
    review.accept_all_clean()
    assert not review.is_approvable


def test_highlights_stop_at_three_and_skipped_briefs_are_reported():
    provider = FakeNarrativeProvider(no_story={"corporate_actions"})
    review = build_equities_review(provider=provider, today=TODAY, fetch_market=market)
    assert provider.calls == [b.id for b in BRIEFS]  # corporate_actions had nothing, so the 4th was needed
    assert review.section["pieces_found"] == 3 and review.section["shortfall"] == 0
    assert any("Corporate actions and deals: nothing qualifying" in w for w in review.section["warnings"])
    assert any("1 share page(s) failed" in w for w in review.section["warnings"])


def test_bad_claim_figure_is_flagged():
    review = equities_review(FakeNarrativeProvider(bad_figure=True))
    flagged = [i for i in review.review_items if i.kind == CLAIM and i.status == FLAGGED]
    assert flagged and all("99.9" in i.detail[0].message for i in flagged)


def test_tampered_index_figure_is_flagged():
    from cytonn_weekly.common.review import build_review, check_section
    from cytonn_weekly.equities.review_run import compose
    from cytonn_weekly.narrative.drafter import draft_pieces

    content = compose(market(), draft_pieces(BRIEFS, 3, provider=FakeNarrativeProvider(), today=TODAY))
    content["blocks"][0]["rows"][0]["ytd_pct"] = "32.2%"
    review = build_review(content, check_section(content))
    flagged = [i for i in review.review_items if i.status == FLAGGED and i.kind == TABLE_ROW]
    assert [i.ref for i in flagged] == ["Market Performance: NSE indices: NASI"]


def test_market_with_no_movers_still_builds():
    review = build_equities_review(provider=FakeNarrativeProvider(), today=TODAY,
                                   fetch_market=lambda: market(shares=[share("A", "A Ltd", 1.0, 0.0)]))
    assert [b["rows"] for b in review.section["blocks"] if b["id"] in ("gainers", "losers")] == [[], []]


# --- stubs -----------------------------------------------------------------------

def test_stubs_fail_loudly_with_their_reason():
    with pytest.raises(NotImplementedError, match="proprietary"):
        stubs.fetch_universe_of_coverage()
    with pytest.raises(NotImplementedError, match="image-only"):
        stubs.fetch_market_activity()
