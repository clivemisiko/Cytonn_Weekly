"""Unit tests for cytonn_weekly.digital_payments.highlights with a fake DraftingProvider.

The company order, the four-highlight target, shortfall bookkeeping, outlook statistics and composition live
in highlights.py and need no model; how a real provider reads its reply is tested in test_bedrock_provider.py
and test_digital_payments_providers.py.  No network access.
"""

from datetime import date

from cytonn_weekly.digital_payments import highlights as dh
from cytonn_weekly.drafting.highlight_contract import DraftingProvider
from cytonn_weekly.drafting.results import HighlightResult, OutlookResult

TODAY = date(2026, 9, 29)

IR = {
    "Visa": "investor.visa.com",
    "Mastercard": "investor.mastercard.com",
    "American Express": "ir.americanexpress.com",
    "PayPal": "investor.pypl.com",
    "Circle": "investor.circle.com",
}
PRIORITY = ["Visa", "Mastercard", "American Express", "PayPal", "Circle"]


def words(n, start="During the week, Visa did things"):
    filler = start.split()
    return " ".join(filler + ["word"] * (n - len(filler)))


def story(company, url=None):
    url = url or f"https://{IR[company]}/news"
    body = words(140, f"During the week, {company} announced a new product with 5.0% growth;")
    return HighlightResult(
        company=company, search_scope="investor_relations", ir_domain=IR[company], drafted_by="test:fake",
        headline=f"{company} Launches Product", paragraph=body, paragraph_md=body.replace("a new product", f"[a new product]({url})"),
        word_count=140, links=[{"anchor": "a new product", "url": url, "page_age": ""}],
        claims=[{"text": body, "url": url, "title": "T", "cited_text": f"cited {company}"}],
    )


class FakeProvider(DraftingProvider):
    """Answers per company: a story, or no story for any company not in `news`. Every request is logged."""

    drafted_by = "test:fake"

    def __init__(self, news, outlook=None):
        self.news = news
        self.outlook = outlook if outlook is not None else words(100, "The sector outlook")
        self.asked = []
        self.outlook_calls = []

    def find_highlight(self, company, ir_domain, *, start, end, today, aliases=None, style_examples=""):
        self.asked.append((company, ir_domain, start, end, style_examples))
        if company in self.news:
            return self.news[company]
        return HighlightResult(company=company, search_scope=None, ir_domain=ir_domain, drafted_by="test:fake", no_story=True)

    def draft_outlook(self, table_stats, highlights):
        self.outlook_calls.append((table_stats, highlights))
        return OutlookResult(text=self.outlook, stats=table_stats, drafted_by="test:fake")


def news_for(companies=PRIORITY):
    return {c: story(c) for c in companies}


def full_draft():
    return dh.draft_highlights(provider=FakeProvider(news_for()), today=TODAY)


def asked(provider):
    return [a[0] for a in provider.asked]


# ---------------------------------------------------------------------------
# Company scope and priority
# ---------------------------------------------------------------------------

def test_candidate_list_is_exactly_the_five_in_priority_order():
    assert [c["name"] for c in dh.HIGHLIGHT_COMPANIES] == PRIORITY
    names = " ".join(c["name"] for c in dh.HIGHLIGHT_COMPANIES)
    assert "Block" not in names and "Global Payments" not in names


def test_ir_domains_are_configured_per_company():
    assert {c["name"]: c["ir_domain"] for c in dh.HIGHLIGHT_COMPANIES} == IR


def test_priority_order_honored_when_all_five_have_news():
    p = FakeProvider(news_for())
    d = dh.draft_highlights(provider=p, today=TODAY)
    assert [h["company"] for h in d["highlights"]] == PRIORITY[:4]  # Circle is left out
    assert d["shortfall"] == 0
    assert "Circle" not in asked(p)  # lowest priority never even searched
    assert any("Circle: not searched" in w for w in d["warnings"])


def test_lower_priority_company_fills_in_when_a_higher_one_has_no_news():
    d = dh.draft_highlights(provider=FakeProvider(news_for(["Visa", "American Express", "PayPal", "Circle"])), today=TODAY)
    assert [h["company"] for h in d["highlights"]] == ["Visa", "American Express", "PayPal", "Circle"]
    assert d["shortfall"] == 0
    assert any("Mastercard: no story found" in w for w in d["warnings"])


def test_three_priority_stories_plus_one_filler():
    p = FakeProvider(news_for(["Visa", "Mastercard", "PayPal", "Circle"]))
    d = dh.draft_highlights(provider=p, today=TODAY)
    assert set(asked(p)) >= set(PRIORITY[:4])   # all four priority companies were searched
    assert [h["company"] for h in d["highlights"]] == ["Visa", "Mastercard", "PayPal", "Circle"] and d["shortfall"] == 0
    assert not any("only" in w and "of 4" in w for w in d["warnings"])


def test_every_priority_company_that_released_appears():
    for released in (["Visa"], ["Mastercard", "PayPal"], ["Visa", "Mastercard", "American Express", "PayPal"]):
        d = dh.draft_highlights(provider=FakeProvider(news_for(released)), today=TODAY)
        assert [h["company"] for h in d["highlights"]] == released


def test_a_priority_search_that_found_but_discarded_a_result_cannot_be_confirmed():
    class Discarding(FakeProvider):
        def find_highlight(self, company, ir_domain, **kw):
            return HighlightResult(company=company, search_scope=None, ir_domain=ir_domain, drafted_by="test",
                                   no_story=True, draft_warnings=[f"{company}: a story was discarded as not about the company"])

    d = dh.draft_highlights(provider=Discarding({}), today=TODAY)
    assert d["highlights"] == []
    for name in PRIORITY[:4]:
        assert any(f"{name}: a result was found but discarded" in w and "check its releases by hand" in w for w in d["warnings"])
    assert not any("Circle: a result was found but discarded" in w for w in d["warnings"])


def test_block_and_global_payments_are_never_asked_for():
    p = FakeProvider(news_for(["Visa"]))
    d = dh.draft_highlights(provider=p, today=TODAY)
    assert [h["company"] for h in d["highlights"]] == ["Visa"]
    assert set(asked(p)) == set(PRIORITY)  # Block / Global Payments never requested


def test_shortfall_is_flagged_and_never_filled_from_block_or_gpn():
    d = dh.draft_highlights(provider=FakeProvider(news_for(["Visa", "PayPal"])), today=TODAY)
    assert [h["company"] for h in d["highlights"]] == ["Visa", "PayPal"]
    assert d["shortfall"] == 2
    assert any("only 2 of 4" in w for w in d["warnings"])


def test_zero_stories_is_full_shortfall():
    d = dh.draft_highlights(provider=FakeProvider({}), today=TODAY)
    assert d["highlights"] == [] and d["shortfall"] == 4


def test_each_company_is_asked_with_its_ir_domain_and_the_report_week():
    p = FakeProvider(news_for())
    dh.draft_highlights(provider=p, today=TODAY)
    assert [(c, ir) for c, ir, *_ in p.asked] == [(c, IR[c]) for c in PRIORITY[:4]]
    assert {(s, e) for *_, s, e, _ in p.asked} == {(date(2026, 9, 23), TODAY)}


def test_style_examples_override():
    p = FakeProvider(news_for())
    dh.draft_highlights(provider=p, today=TODAY, style_examples="EXAMPLE-STYLE-TEXT")
    assert {a[4] for a in p.asked} == {"EXAMPLE-STYLE-TEXT"}


def test_a_provider_error_propagates():
    class Boom(FakeProvider):
        def find_highlight(self, *a, **kw):
            raise RuntimeError("boom")

    import pytest

    with pytest.raises(RuntimeError):
        dh.draft_highlights(provider=Boom({}), today=TODAY)


# ---------------------------------------------------------------------------
# What a highlight carries
# ---------------------------------------------------------------------------

def test_highlight_formatting_and_metadata():
    h = full_draft()["highlights"][0]
    assert h["company"] == "Visa" and h["ir_domain"] == "investor.visa.com"
    assert h["headline"] == "Visa Launches Product"
    assert h["headline_md"] == "**Visa Launches Product**"
    assert h["body"].startswith("During the week, Visa announced a new product with")
    assert "[a new product](https://investor.visa.com/news)" in h["body_md"]
    assert h["links"][0]["url"] == "https://investor.visa.com/news"
    assert h["search_scope"] == "investor_relations" and h["drafted_by"] == "test:fake"


def test_each_claim_carries_its_own_citation_and_none_leak_across_highlights():
    for h in full_draft()["highlights"]:
        assert [c["url"] for c in h["claims"]] == [f"https://{IR[h['company']]}/news"]
        assert h["claims"][0]["cited_text"] == f"cited {h['company']}"


# ---------------------------------------------------------------------------
# Outlook + composition
# ---------------------------------------------------------------------------

def row(ticker, wow, ytd, pe=None, error=None):
    r = {"company": ticker, "ticker": ticker, "wow_pct": wow, "ytd_pct": ytd, "error": error}
    if pe is not None:
        r["forward_pe"] = pe
    return r


TABLE = [row("V", 1.0, 10.0), row("MA", -3.0, 2.0), row("AXP", 5.0, -4.0), row("GPN", None, None, error="x")]


def test_table_stats_exclude_failed_rows_and_omit_pe_if_absent():
    s = dh.table_stats(TABLE)
    assert s["companies_included"] == 3 and s["companies_failed"] == 1
    assert s["avg_wow_pct"] == 1.0 and s["avg_ytd_pct"] == 2.7
    assert s["advancers"] == 2 and s["decliners"] == 1
    assert "avg_forward_pe" not in s


def test_table_stats_average_forward_pe_when_present():
    s = dh.table_stats([row("V", 1, 1, pe=20.0), row("MA", 1, 1, pe=30.0)])
    assert s["avg_forward_pe"] == 25.0


def test_outlook_is_bold_italic_uncited_and_uses_stats_without_search():
    d = full_draft()
    p = FakeProvider({})
    o = dh.draft_outlook(d, TABLE, provider=p)
    assert o["text_md"] == f"***{o['text']}***"
    stats, highlights = p.outlook_calls[0]
    assert stats["avg_wow_pct"] == 1.0
    assert [h["headline"] for h in highlights] == [h["headline"] for h in d["highlights"]]
    assert any("forward P/E not available" in w for w in o["warnings"])
    assert any("1 table row(s) failed" in w for w in o["warnings"])
    assert not any("words, outside" in w for w in o["warnings"])


def test_outlook_word_count_warning():
    o = dh.draft_outlook(full_draft(), TABLE, provider=FakeProvider({}, outlook="Too short."))
    assert any("outside 80-120" in w for w in o["warnings"])


def test_compose_section_numbers_highlights_table_then_outlook():
    d = full_draft()
    o = dh.draft_outlook(d, TABLE, provider=FakeProvider({}, outlook=words(100)))
    sec = dh.compose_section(d, TABLE, o)
    assert [i["numeral"] for i in sec["items"]] == ["I", "II", "III", "IV", "V"]
    assert [i["kind"] for i in sec["items"]] == ["highlight"] * 4 + ["stock_table"]
    assert sec["items"][4]["rows"] is TABLE
    assert sec["outlook"] is o


def test_compose_section_with_shortfall_renumbers_table_and_carries_warnings():
    d = dh.draft_highlights(provider=FakeProvider(news_for(["Visa"])), today=TODAY)
    o = dh.draft_outlook(d, TABLE, provider=FakeProvider({}, outlook=words(100)))
    sec = dh.compose_section(d, TABLE, o)
    assert [i["numeral"] for i in sec["items"]] == ["I", "II"]
    assert sec["items"][1]["kind"] == "stock_table"
    assert sec["shortfall"] == 3
    assert any("only 1 of 4" in w for w in sec["warnings"])


def test_stats_averages_round_half_up_to_one_decimal():
    # 2.25 -> 2.3 (Python's round() would give 2.2); 24.95 -> 25.0 (round() gives 24.9)
    s = dh.table_stats([row("V", 2.25, 0.05, pe=24.9), row("MA", 2.25, 0.05, pe=25.0)])
    assert s["avg_wow_pct"] == 2.3
    assert s["avg_ytd_pct"] == 0.1
    assert s["avg_forward_pe"] == 25.0  # mean 24.95


def test_stats_advancer_decliner_counts_stay_whole_numbers():
    s = dh.table_stats(TABLE)
    assert isinstance(s["advancers"], int) and isinstance(s["decliners"], int)


def test_stats_average_pe_equals_the_fetchers_table_average():
    from cytonn_weekly.digital_payments.fetcher import average_forward_pe

    rows = [row("V", 1, 1, pe=24.5), row("MA", 1, 1, pe=24.6), row("AXP", 1, 1, pe=15.15)]
    assert dh.table_stats(rows)["avg_forward_pe"] == average_forward_pe(rows)


def test_stats_average_that_rounds_to_zero_is_not_negative_zero():
    s = dh.table_stats([row("V", -0.02, -0.04, pe=1.0), row("MA", 0.0, 0.0, pe=1.0)])
    assert s["avg_wow_pct"] == 0.0 and str(s["avg_wow_pct"]) == "0.0"
    assert str(s["avg_ytd_pct"]) == "0.0"
