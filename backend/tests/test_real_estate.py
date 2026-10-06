"""Real Estate: the Ibuka PDF parser against a real weekly summary, the review run, the stubs."""

from datetime import date
from pathlib import Path

import pytest

from cytonn_weekly.common.http import NotFound
from cytonn_weekly.common.review import CLAIM
from cytonn_weekly.digital_payments.coordinator_review import CLEAN, NOT_AUTO_VERIFIED, TABLE_ROW
from cytonn_weekly.real_estate import fetcher, stubs
from cytonn_weekly.real_estate.review_run import BRIEFS, SECTION, build_real_estate_review
from tests.section_helpers import TODAY, FakeNarrativeProvider, real_estate_review, reits

IBUKA_PDF = (Path(__file__).parent / "fixtures" / "sources" / "ibuka_2026-09-25.pdf").read_bytes()

# The REIT rows exactly as pdfplumber extracted them from the 25 Sept 2026 summary (digits kerned apart).
REAL_TABLE = [[
    ["ACORN D-REIT", "Real Estate", "2 9.65", "2 9.59", "2 9.65", "-", "-", "292,576,849", "8 ,674,903,573"],
    ["ACORN I-REIT", "Real Estate", "2 4.44", "2 3.75", "2 4.44", "-", "-", "405,022,492", "9 ,898,749,704"],
    ["ILAM FAHARI-I REIT", "Real Estate", "13.80", "11.00", "13.80", "-", "-", "180,972,300", "2 ,497,417,740"],
    ["BATIAN INCOME PROPERTY FUND", "Real Estate", "1 00.00", "100.00", "100.00", "-", "-", "29,933,476", "2 ,993,347,600"],
]]


def test_ibuka_url_follows_nse_naming():
    assert fetcher.ibuka_url(date(2026, 9, 25)).endswith("Unquoted-Securities-Platform-Ibuka-Weekly-Summary_25-09-2026.pdf")


def test_parse_tables_repairs_kerned_digits_and_ignores_other_funds():
    got = fetcher.parse_tables(REAL_TABLE)
    assert got == {
        "ACORN D-REIT": {"price": 29.65, "market_cap": 8674903573.0},
        "ACORN I-REIT": {"price": 24.44, "market_cap": 9898749704.0},
        "ILAM FAHARI-I REIT": {"price": 13.8, "market_cap": 2497417740.0},
    }


def test_parse_pdf_reads_the_real_summary():
    parsed = fetcher.parse_pdf(IBUKA_PDF)
    assert parsed["as_of"] == "2026-09-25"
    assert parsed["reits"] == fetcher.parse_tables(REAL_TABLE)


def _getter(files):
    def get(url):
        if url in files:
            return files[url]
        raise NotFound(url)
    return get


def test_fetch_reits_walks_back_to_the_latest_summary_and_computes_changes():
    files = {fetcher.ibuka_url(date(2026, 9, 25)): IBUKA_PDF, fetcher.ibuka_url(date(2026, 9, 18)): IBUKA_PDF,
             fetcher.ibuka_url(date(2025, 12, 26)): IBUKA_PDF}
    out = fetcher.fetch_reits(TODAY, get=_getter(files))
    d = {r["reit"]: r for r in out["rows"]}
    assert out["as_of"] == "2026-09-25" and out["warnings"] == []
    assert d["ACORN_D"]["price"] == 29.65 and d["ACORN_D"]["inception_gain_pct"] == 48.5
    assert d["ACORN_D"]["wow_pct"] == 0.0 and d["ACORN_D"]["ytd_pct"] == 0.0  # still carried, not drafted
    assert d["FAHARI"]["market_cap_kes_bn"] == pytest.approx(2.49741774)


def test_fetch_reits_leaves_changes_empty_rather_than_guessing():
    out = fetcher.fetch_reits(TODAY, get=_getter({fetcher.ibuka_url(date(2026, 9, 25)): IBUKA_PDF}))
    assert all(r["wow_pct"] is None and r["ytd_pct"] is None for r in out["rows"])
    assert len(out["warnings"]) == 2


def test_fetch_reits_with_no_summary_at_all_raises():
    with pytest.raises(LookupError, match="no Ibuka weekly summary"):
        fetcher.fetch_reits(TODAY, get=_getter({}))


def test_review_closes_with_reits_and_checks_clean():
    review = real_estate_review()
    blocks = review.section["blocks"]
    assert review.section["section"] == SECTION
    assert [b["id"] for b in blocks] == ["subsection_residential", "subsection_affordable_housing",
                                         "subsection_infrastructure", "subsection_commercial", "reits"]
    assert blocks[-1]["numeral"] == "V"
    assert blocks[-1]["rows"][1] == {"reit": "ACORN_I", "name": "Acorn I-REIT", "price": "24.4", "inception_gain_pct": "22.0%"}
    rows = [i for i in review.review_items if i.kind == TABLE_ROW]
    assert len(rows) == 3 and all(i.status == CLEAN for i in rows)
    assert all(i.status == NOT_AUTO_VERIFIED for i in review.review_items if i.kind == CLAIM)


def test_reit_prices_print_as_cytonn_weekly_38_2026_did():
    """Same Ibuka prices, same strings as the real report: "traded at Kshs 29.7 and Kshs 24.4 per unit",
    "ILAM Fahari I-REIT traded at Kshs 13.8".  29.65 -> 29.7 also pins round-half-up."""
    prices = [r["price"] for r in real_estate_review().section["blocks"][-1]["rows"]]
    assert prices == ["29.7", "24.4", "13.8"]


def test_reit_gains_are_from_the_inception_price_as_cytonn_weekly_38_2026_printed_them():
    """Regression: #38.2026 printed "a 48.5% and 22.0% gain for the D-REIT and I-REIT, respectively, from the Kshs 20.0
    inception price" and Fahari's "31.0 % loss from the Kshs 20.0 inception price", from the 18 Sept 2026 Ibuka prices
    29.65 / 24.44 / 13.80.  Gains on the raw prices would be 48.3% and 22.2%; the report's are on the printed prices
    (29.7, 24.4), so the gain is taken from the 1 dp price.  Not w/w, not YTD."""
    files = {fetcher.ibuka_url(date(2026, 9, 18)): IBUKA_PDF}  # same REIT prices as the 18 Sept summary (checked)
    out = fetcher.fetch_reits(date(2026, 9, 18), get=_getter(files))
    assert [r["price"] for r in out["rows"]] == [29.65, 24.44, 13.8]
    assert [r["inception_gain_pct"] for r in out["rows"]] == [48.5, 22.0, -31.0]
    assert [c["key"] for c in fetcher.COLUMNS] == ["name", "price", "inception_gain_pct"]
    shown = [r["inception_gain_pct"] for r in real_estate_review().section["blocks"][-1]["rows"]]
    assert shown == ["48.5%", "22.0%", "(31.0%)"]
    assert fetcher.inception_gain_pct(None) is None


def test_rotating_subsections_skip_a_quiet_theme_and_stop_at_four():
    provider = FakeNarrativeProvider(no_story={"hospitality"})
    review = build_real_estate_review(provider=provider, today=TODAY, fetch_reits=lambda _t: reits())
    assert provider.calls == [b.id for b in BRIEFS[:5]]
    assert any("Land: not searched" in w for w in review.section["warnings"])


def test_source_warnings_reach_the_section():
    review = build_real_estate_review(provider=FakeNarrativeProvider(), today=TODAY,
                                      fetch_reits=lambda _t: reits(warnings=["YTD change left empty"]))
    assert "YTD change left empty" in review.section["warnings"]


def test_structured_stubs_fail_loudly():
    with pytest.raises(NotImplementedError, match="CBK mortgage"):
        stubs.fetch_cbk_mortgage_stats(2025)
    with pytest.raises(NotImplementedError, match="price index"):
        stubs.fetch_residential_price_index("2025Q4")
