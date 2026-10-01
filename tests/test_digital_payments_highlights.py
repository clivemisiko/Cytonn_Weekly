"""Unit tests for cytonn_weekly.digital_payments.highlights with the Anthropic provider.

The Anthropic client is faked and handed to AnthropicProvider; no network access.
"""

from datetime import date
from types import SimpleNamespace as NS

import pytest

from cytonn_weekly.digital_payments import highlights as dh
from cytonn_weekly.digital_payments.providers import anthropic_provider as ap
from cytonn_weekly.digital_payments.providers.anthropic_provider import AnthropicProvider

TODAY = date(2026, 9, 29)

IR = {
    "Visa": "investor.visa.com",
    "Mastercard": "investor.mastercard.com",
    "American Express": "ir.americanexpress.com",
    "PayPal": "investor.pypl.com",
    "Circle": "investor.circle.com",
}
PRIORITY = ["Visa", "Mastercard", "American Express", "PayPal", "Circle"]


def cite(url, title="T", text="cited"):
    return NS(type="web_search_result_location", url=url, title=title, cited_text=text)


def text(t, citations=None):
    return NS(type="text", text=t, citations=citations)


def search_result(*urls):
    return NS(
        type="web_search_tool_result",
        content=[NS(url=u, title="t", page_age="1 day ago") for u in urls],
    )


def resp(blocks, stop_reason="end_turn"):
    return NS(content=blocks, stop_reason=stop_reason)


def words(n, start="During the week, Visa did things"):
    filler = start.split()
    return " ".join(filler + ["word"] * (n - len(filler)))


def story(company, url, headline=None, body_words=140, subject=None):
    """Response blocks for one story about `company` (or `subject` if given)."""
    subject = subject or company
    body = words(body_words, f"During the week, {subject} announced a [new product]({url}) with 5.0% growth;")
    return [
        search_result(url),
        text(f"### {headline or subject + ' Launches Product'}\n\n"),
        text(body, [cite(url, f"Title {subject}", f"cited {subject}")]),
        text(" This reflects a broader trend.\n\n"),
    ]


NO_STORY = [text("NO_STORY")]


class NewsClient:
    """Fake Anthropic client answering per company and per search scope.

    news maps company -> {"ir": blocks, "web": blocks}; anything missing is NO_STORY.
    Every call is logged in .calls as (company, scope, kwargs).
    """

    def __init__(self, news):
        self.news = news
        self.calls = []
        self.messages = NS(create=self._create)

    def _create(self, **kwargs):
        prompt = kwargs["messages"][0]["content"]
        company = prompt.split("Company: ")[1].split(".\n")[0]
        scope = "ir" if "allowed_domains" in kwargs["tools"][0] else "web"
        self.calls.append((company, scope, kwargs))
        return resp(self.news.get(company, {}).get(scope, NO_STORY))

    def scopes(self):
        return [(c, s) for c, s, _ in self.calls]


def all_ir_news(companies=PRIORITY, extra=None):
    news = {c: {"ir": story(c, f"https://{IR[c]}/news")} for c in companies}
    news.update(extra or {})
    return news


def full_draft():
    return dh.draft_highlights(provider=AnthropicProvider(client=NewsClient(all_ir_news())), today=TODAY)


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
    client = NewsClient(all_ir_news())
    d = dh.draft_highlights(provider=AnthropicProvider(client=client), today=TODAY)
    assert [h["company"] for h in d["highlights"]] == PRIORITY[:4]  # Circle is left out
    assert d["shortfall"] == 0
    assert ("Circle", "ir") not in client.scopes()  # lowest priority never even searched
    assert any("Circle: not searched" in w for w in d["warnings"])


def test_lower_priority_company_fills_in_when_a_higher_one_has_no_news():
    news = all_ir_news(companies=["Visa", "American Express", "PayPal", "Circle"])
    d = dh.draft_highlights(provider=AnthropicProvider(client=NewsClient(news)), today=TODAY)
    assert [h["company"] for h in d["highlights"]] == ["Visa", "American Express", "PayPal", "Circle"]
    assert d["shortfall"] == 0
    assert any("Mastercard: no story found" in w for w in d["warnings"])


def test_block_and_global_payments_are_never_searched_or_used():
    news = all_ir_news(companies=["Visa"])
    # Even if the model volunteers Block / Global Payments news, it must never surface.
    news["Mastercard"] = {"ir": story("Mastercard", "https://x.com/1", subject="Block")}
    news["American Express"] = {"web": story("American Express", "https://x.com/2", subject="Global Payments")}
    client = NewsClient(news)
    d = dh.draft_highlights(provider=AnthropicProvider(client=client), today=TODAY)
    assert [h["company"] for h in d["highlights"]] == ["Visa"]
    searched = {c for c, _ in client.scopes()}
    assert searched == set(PRIORITY)  # Block / Global Payments never requested
    assert all("Block" not in h["body"] and "Global Payments" not in h["body"] for h in d["highlights"])
    assert any("not about the company" in w and "Mastercard" in w for w in d["warnings"])


def test_shortfall_is_flagged_and_never_filled_from_block_or_gpn():
    d = dh.draft_highlights(provider=AnthropicProvider(client=NewsClient(all_ir_news(companies=["Visa", "PayPal"]))), today=TODAY)
    assert [h["company"] for h in d["highlights"]] == ["Visa", "PayPal"]
    assert d["shortfall"] == 2
    assert any("only 2 of 4" in w for w in d["warnings"])


def test_zero_stories_is_full_shortfall():
    d = dh.draft_highlights(provider=AnthropicProvider(client=NewsClient({})), today=TODAY)
    assert d["highlights"] == [] and d["shortfall"] == 4


# ---------------------------------------------------------------------------
# Investor-relations-first search, with fallback
# ---------------------------------------------------------------------------

def test_ir_search_is_restricted_to_the_companys_own_domain():
    client = NewsClient(all_ir_news())
    dh.draft_highlights(provider=AnthropicProvider(client=client), today=TODAY)
    for company, scope, kwargs in client.calls:
        assert scope == "ir"
        tool = kwargs["tools"][0]
        assert tool["type"].startswith("web_search_")
        assert tool["allowed_domains"] == [IR[company]]
        assert IR[company] in kwargs["messages"][0]["content"]


def test_ir_story_is_used_and_no_general_search_runs():
    client = NewsClient(all_ir_news())
    d = dh.draft_highlights(provider=AnthropicProvider(client=client), today=TODAY)
    assert all(h["search_scope"] == "investor_relations" for h in d["highlights"])
    assert all(s == "ir" for _, s in client.scopes())


def test_falls_back_to_general_web_search_only_when_ir_has_no_story():
    news = all_ir_news()
    news["Visa"] = {"web": story("Visa", "https://news.example.com/visa")}  # IR: NO_STORY
    client = NewsClient(news)
    d = dh.draft_highlights(provider=AnthropicProvider(client=client), today=TODAY)

    visa = d["highlights"][0]
    assert visa["company"] == "Visa" and visa["search_scope"] == "web_fallback"
    assert visa["links"][0]["url"] == "https://news.example.com/visa"
    # IR was tried first, then general search, for Visa only.
    assert client.scopes()[:2] == [("Visa", "ir"), ("Visa", "web")]
    web_calls = [(c, s) for c, s in client.scopes() if s == "web"]
    assert web_calls == [("Visa", "web")]
    fallback_kwargs = client.calls[1][2]
    assert "allowed_domains" not in fallback_kwargs["tools"][0]
    assert "had no story" in fallback_kwargs["messages"][0]["content"]


def test_no_story_anywhere_tries_ir_then_web_then_moves_on():
    client = NewsClient(all_ir_news(companies=["Mastercard", "American Express", "PayPal", "Circle"]))
    d = dh.draft_highlights(provider=AnthropicProvider(client=client), today=TODAY)
    assert client.scopes()[:2] == [("Visa", "ir"), ("Visa", "web")]
    assert [h["company"] for h in d["highlights"]] == ["Mastercard", "American Express", "PayPal", "Circle"]
    assert any("Visa: no story found" in w for w in d["warnings"])


# ---------------------------------------------------------------------------
# Formatting and citations (per highlight)
# ---------------------------------------------------------------------------

def test_highlight_formatting_and_metadata():
    h = full_draft()["highlights"][0]
    assert h["company"] == "Visa" and h["ir_domain"] == "investor.visa.com"
    assert h["headline"] == "Visa Launches Product"
    assert h["headline_md"] == "**Visa Launches Product**"
    assert h["body"].startswith("During the week, Visa announced a new product with")
    assert "[new product](https://investor.visa.com/news)" in h["body_md"]
    assert "](" not in h["body"]
    assert h["links"][0]["anchor"] == "new product"
    assert h["links"][0]["url"] == "https://investor.visa.com/news"
    assert h["links"][0]["page_age"] == "1 day ago"
    assert h["warnings"] == []


def test_each_claim_carries_its_own_citation_and_none_leak_across_highlights():
    for h in full_draft()["highlights"]:
        assert [c["url"] for c in h["claims"]] == [f"https://{IR[h['company']]}/news"]
        assert h["claims"][0]["cited_text"] == f"cited {h['company']}"
        assert "](" not in h["claims"][0]["text"] and "###" not in h["claims"][0]["text"]
        assert h["claims"][0]["text"].startswith(f"During the week, {h['company']}")


def test_uncited_closing_sentence_has_no_claim():
    h = full_draft()["highlights"][0]
    assert "This reflects a broader trend." in h["body"]
    assert all("broader trend" not in c["text"] for c in h["claims"])


def test_link_to_url_not_in_search_results_is_unlinked_and_flagged():
    body = words(140, "During the week, Visa announced a [made up](https://evil.com/x) launch;")
    blocks = [search_result("https://investor.visa.com/n"), text("### Visa Thing\n\n"),
              text(body, [cite("https://investor.visa.com/n")])]
    d = dh.draft_highlights(provider=AnthropicProvider(client=NewsClient({"Visa": {"ir": blocks}})), today=TODAY)
    h = d["highlights"][0]
    assert h["links"] == []
    assert "made up" in h["body"] and "evil.com" not in h["body_md"]
    assert any("evil.com" in w for w in h["warnings"])
    assert any("no inline source hyperlink" in w for w in h["warnings"])


def test_word_count_and_opener_warnings():
    blocks = [
        search_result("https://investor.visa.com/n"),
        text("### Visa Thing\n\n"),
        text("Visa did a short thing [here](https://investor.visa.com/n).", [cite("https://investor.visa.com/n")]),
    ]
    h = dh.draft_highlights(provider=AnthropicProvider(client=NewsClient({"Visa": {"ir": blocks}})), today=TODAY)["highlights"][0]
    assert any("words, outside 100-180" in w for w in h["warnings"])
    assert any("does not open with" in w for w in h["warnings"])


def test_uncited_highlight_is_flagged():
    blocks = [text("### Visa Thing\n\n" + words(140))]
    h = dh.draft_highlights(provider=AnthropicProvider(client=NewsClient({"Visa": {"ir": blocks}})), today=TODAY)["highlights"][0]
    assert any("no cited claims" in w for w in h["warnings"])


def test_multiple_stories_in_one_company_call_keeps_first_with_warning():
    blocks = story("Visa", "https://investor.visa.com/1") + story("Visa", "https://investor.visa.com/2", headline="Second")
    d = dh.draft_highlights(provider=AnthropicProvider(client=NewsClient({"Visa": {"ir": blocks}})), today=TODAY)
    assert d["highlights"][0]["headline"] == "Visa Launches Product"
    assert any("Visa: model returned 2 stories" in w for w in d["warnings"])


# ---------------------------------------------------------------------------
# Request shape, continuation, errors
# ---------------------------------------------------------------------------

def test_request_scopes_to_one_company_and_states_week():
    client = NewsClient(all_ir_news())
    dh.draft_highlights(provider=AnthropicProvider(client=client), today=TODAY)
    company, _, kwargs = client.calls[0]
    assert company == "Visa"
    assert "2026-09-23 to 2026-09-29" in kwargs["messages"][0]["content"]
    assert "single company" in kwargs["system"] and "NO_STORY" in kwargs["system"]


def test_style_examples_override():
    client = NewsClient(all_ir_news())
    dh.draft_highlights(provider=AnthropicProvider(client=client), today=TODAY, style_examples="EXAMPLE-STYLE-TEXT")
    assert "EXAMPLE-STYLE-TEXT" in client.calls[0][2]["messages"][0]["content"]


def test_pause_turn_is_resumed_and_bounded():
    class Paused:
        def __init__(self, n_pauses):
            self.n, self.calls = n_pauses, []
            self.messages = NS(create=self._create)

        def _create(self, **kw):
            self.calls.append(kw)
            if len(self.calls) <= self.n:
                return resp([text("Searching.\n\n")], stop_reason="pause_turn")
            return resp(story("Visa", "https://investor.visa.com/n")[1:])

    c = Paused(1)
    h = ap._draft_for_company(c, ap.MODEL, dh.HIGHLIGHT_COMPANIES[0], "investor_relations",
                              date(2026, 9, 23), TODAY, TODAY, "", [])
    assert len(c.calls) == 2 and c.calls[1]["messages"][-1]["role"] == "assistant"
    assert h is not None

    c = Paused(99)
    ap._run_search(c, ap.MODEL, "Company: Visa.\nx", {"type": "web_search_20250305", "name": "web_search"})
    assert len(c.calls) == ap.MAX_CONTINUATIONS + 1


def test_api_error_propagates():
    client = NewsClient({})
    client.messages = NS(create=lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        dh.draft_highlights(provider=AnthropicProvider(client=client), today=TODAY)


class SimpleClient:
    """Fake client returning queued responses (used for the outlook call)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.messages = NS(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


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
    client = SimpleClient([resp([text(words(100, "The sector outlook"))])])
    o = dh.draft_outlook(d, TABLE, provider=AnthropicProvider(client=client))
    assert o["text_md"] == f"***{o['text']}***"
    call = client.calls[0]
    assert "tools" not in call
    prompt = call["messages"][0]["content"]
    assert "avg_wow_pct: 1.0" in prompt
    assert d["highlights"][0]["headline"] in prompt
    assert any("forward P/E not available" in w for w in o["warnings"])
    assert any("1 table row(s) failed" in w for w in o["warnings"])
    assert not any("words, outside" in w for w in o["warnings"])


def test_outlook_word_count_warning():
    d = full_draft()
    o = dh.draft_outlook(d, TABLE, provider=AnthropicProvider(client=SimpleClient([resp([text("Too short.")])])))
    assert any("outside 80-120" in w for w in o["warnings"])


def test_compose_section_numbers_highlights_table_then_outlook():
    d = full_draft()
    o = dh.draft_outlook(d, TABLE, provider=AnthropicProvider(client=SimpleClient([resp([text(words(100))])])))
    sec = dh.compose_section(d, TABLE, o)
    assert [i["numeral"] for i in sec["items"]] == ["I", "II", "III", "IV", "V"]
    assert [i["kind"] for i in sec["items"]] == ["highlight"] * 4 + ["stock_table"]
    assert sec["items"][4]["rows"] is TABLE
    assert sec["outlook"] is o


def test_compose_section_with_shortfall_renumbers_table_and_carries_warnings():
    d = dh.draft_highlights(provider=AnthropicProvider(client=NewsClient(all_ir_news(companies=["Visa"]))), today=TODAY)
    o = dh.draft_outlook(d, TABLE, provider=AnthropicProvider(client=SimpleClient([resp([text(words(100))])])))
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
