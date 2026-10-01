"""Unit tests for the provider factory and LocalProvider (httpx mocked; no network).

AnthropicProvider's behaviour is covered through test_digital_payments_highlights.py.
"""

import json
from datetime import date

import httpx
import pytest

from cytonn_weekly.digital_payments import highlights as dh
from cytonn_weekly.digital_payments import provider_factory
from cytonn_weekly.digital_payments.providers.anthropic_provider import AnthropicProvider
from cytonn_weekly.digital_payments.providers.base import DraftingProvider
from cytonn_weekly.digital_payments.providers.local_provider import LocalProvider

TODAY = date(2026, 9, 29)
START, END = date(2026, 9, 23), TODAY
VISA_URL = "https://investor.visa.com/news"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def test_factory_defaults_to_anthropic(monkeypatch, capsys):
    monkeypatch.delenv("CYTONN_LLM_PROVIDER", raising=False)
    p = provider_factory.get_provider()
    assert isinstance(p, AnthropicProvider) and p.drafted_by == "anthropic:claude-sonnet-5"
    assert capsys.readouterr().out == ""


def test_factory_local_prints_warning_every_time(monkeypatch, capsys):
    monkeypatch.setenv("CYTONN_LLM_PROVIDER", "local")
    for _ in range(2):
        p = provider_factory.get_provider()
        assert isinstance(p, LocalProvider) and p.drafted_by == "local:phi4-mini"
    out = capsys.readouterr().out
    assert out.count("DEV MODE: drafting with local phi4-mini") == 2
    assert out.count("NOT FOR PUBLICATION") == 2


def test_factory_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("CYTONN_LLM_PROVIDER", "gpt")
    with pytest.raises(ValueError, match="CYTONN_LLM_PROVIDER"):
        provider_factory.get_provider()


def test_both_providers_implement_the_interface():
    assert issubclass(AnthropicProvider, DraftingProvider)
    assert issubclass(LocalProvider, DraftingProvider)


# ---------------------------------------------------------------------------
# LocalProvider, with Exa and Ollama faked through an httpx mock transport
# ---------------------------------------------------------------------------

def paragraph(n=140, company="Visa", url=VISA_URL):
    filler = f"During the week, {company} announced a [new product]({url}) with 5.0% growth;".split()
    return " ".join(filler + ["word"] * (n - len(filler)))


class Backend:
    """Fake Exa + Ollama.  exa maps scope ('ir'/'web') -> results; llm is the model's JSON replies in order."""

    def __init__(self, exa, llm, models=("phi4-mini:latest",)):
        self.exa, self.llm, self.models = exa, list(llm), models
        self.exa_calls, self.chat_calls = [], []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/api/tags"):
            return httpx.Response(200, json={"models": [{"name": m} for m in self.models]})
        body = json.loads(request.content)
        if "exa.ai" in url:
            scope = "ir" if "includeDomains" in body else "web"
            self.exa_calls.append((scope, body))
            return httpx.Response(200, json={"results": self.exa.get(scope, [])})
        self.chat_calls.append(body)
        reply = self.llm.pop(0)
        return httpx.Response(200, json={"message": {"content": reply if isinstance(reply, str) else json.dumps(reply)}})


def provider(backend):
    return LocalProvider(exa_api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(backend)))


def exa_result(url=VISA_URL, title="Visa news"):
    return {"url": url, "title": title, "publishedDate": "2026-09-25", "text": "Visa announced things."}


def genuine(body=None, claims=None, headline="Visa Launches Product"):
    return {
        "is_genuine_announcement": True,
        "reasoning": "company press release",
        "headline": headline,
        "paragraph": body if body is not None else paragraph(),
        "claims": claims if claims is not None else [{"claim": "Visa announced a new product", "url": VISA_URL}],
    }


NOT_GENUINE = {"is_genuine_announcement": False, "reasoning": "stock analysis piece",
               "headline": "", "paragraph": "", "claims": []}


def find(p, company="Visa", ir="investor.visa.com"):
    return p.find_highlight(company, ir, start=START, end=END, today=TODAY, aliases=[company])


def test_local_ir_result_is_drafted_and_validated():
    b = Backend({"ir": [exa_result()]}, [genuine()])
    res = find(provider(b))
    assert not res.no_story and res.search_scope == "investor_relations"
    assert res.drafted_by == "local:phi4-mini" and res.company == "Visa" and res.ir_domain == "investor.visa.com"
    assert res.paragraph.startswith("During the week, Visa announced a new product")
    assert "](" not in res.paragraph and f"[new product]({VISA_URL})" in res.paragraph_md
    assert res.word_count == 140
    assert res.links == [{"anchor": "new product", "url": VISA_URL, "page_age": "2026-09-25"}]
    assert res.claims == [{"text": "Visa announced a new product", "url": VISA_URL, "title": "Visa news", "cited_text": ""}]
    assert not any("words, outside" in w or "does not open" in w for w in res.warnings)
    assert any("no cited_text" in w for w in res.warnings)
    # The Exa IR search is restricted to the company's domain and starts at the report week.
    scope, body = b.exa_calls[0]
    assert body["includeDomains"] == ["investor.visa.com"] and body["startPublishedDate"].startswith("2026-09-23")
    # Ollama call: deterministic, structured, and told the real word range.
    chat = b.chat_calls[0]
    assert chat["model"] == "phi4-mini" and chat["options"]["temperature"] == 0 and "format" in chat
    assert "100 to 180 words" in chat["messages"][0]["content"]


def test_local_not_genuine_ir_results_fall_back_to_web_search():
    b = Backend({"ir": [exa_result()], "web": [exa_result("https://news.example.com/v")]},
                [NOT_GENUINE, genuine(paragraph(url="https://news.example.com/v"),
                                      [{"claim": "x", "url": "https://news.example.com/v"}])])
    res = find(provider(b))
    assert res.search_scope == "web_fallback" and [s for s, _ in b.exa_calls] == ["ir", "web"]
    assert any("not a genuine announcement" in w and "stock analysis piece" in w for w in res.draft_warnings)


def test_local_empty_ir_search_skips_the_model_and_goes_to_web():
    b = Backend({"ir": [], "web": [exa_result()]}, [genuine()])
    res = find(provider(b))
    assert res.search_scope == "web_fallback" and len(b.chat_calls) == 1


def test_local_no_story_when_nothing_found_or_nothing_genuine():
    assert find(provider(Backend({}, []))).no_story
    res = find(provider(Backend({"ir": [exa_result()], "web": [exa_result()]}, [NOT_GENUINE, NOT_GENUINE])))
    assert res.no_story and res.search_scope is None and res.paragraph == ""


def test_local_unlinks_and_drops_urls_not_in_the_search_results():
    body = paragraph(url="https://evil.com/x")
    res = find(provider(Backend({"ir": [exa_result()]},
                                [genuine(body, [{"claim": "made up", "url": "https://evil.com/x"}])])))
    assert res.links == [] and "evil.com" not in res.paragraph_md
    assert res.claims == []
    assert any("evil.com" in w and "unlinked" in w for w in res.warnings)
    assert any("claim cited a URL not in the search results" in w for w in res.warnings)
    assert any("no inline source hyperlink" in w for w in res.warnings)
    assert any("no cited claims" in w for w in res.warnings)


def test_local_flags_word_count_and_opener():
    res = find(provider(Backend({"ir": [exa_result()]}, [genuine("Visa did a short thing [here](%s)." % VISA_URL)])))
    assert any("words, outside 100-180" in w for w in res.warnings)
    assert any("does not open with" in w for w in res.warnings)


def test_local_discards_story_about_another_company():
    b = Backend({"ir": [exa_result()], "web": []}, [genuine(paragraph(company="Block"))])
    res = find(provider(b))
    assert res.no_story and any("not about the company" in w for w in res.draft_warnings)


def test_local_invalid_json_is_discarded_with_a_warning():
    res = find(provider(Backend({"ir": [exa_result()]}, ["not json"])))
    assert res.no_story and any("invalid JSON" in w for w in res.draft_warnings)


def test_local_missing_model_gives_one_line_pull_instruction():
    with pytest.raises(RuntimeError, match="ollama pull phi4-mini"):
        find(provider(Backend({}, [], models=("llama3:latest",))))


def test_local_requires_exa_key(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    p = LocalProvider(http_client=httpx.Client(transport=httpx.MockTransport(Backend({}, []))))
    with pytest.raises(RuntimeError, match="EXA_API_KEY"):
        find(p)


def test_local_outlook_uses_shared_inputs_and_is_labelled():
    b = Backend({}, [" " + " ".join(["outlook"] * 100) + " "])
    out = provider(b).draft_outlook({"avg_wow_pct": 1.0}, [{"headline": "H1", "body": "B1"}])
    assert out.drafted_by == "local:phi4-mini" and out.stats == {"avg_wow_pct": 1.0}
    assert len(out.text.split()) == 100
    chat = b.chat_calls[0]
    assert "format" not in chat
    assert "avg_wow_pct: 1.0" in chat["messages"][1]["content"] and "H1" in chat["messages"][1]["content"]


# ---------------------------------------------------------------------------
# Orchestration through the injected provider
# ---------------------------------------------------------------------------

def test_draft_highlights_and_outlook_carry_drafted_by_from_the_provider():
    # Every company's IR search returns the same Visa result and the model drafts a Visa story
    # each time, so only the Visa highlight passes the "about the company" check.
    b = Backend({"ir": [exa_result()]}, [genuine()] * 5 + ["outlook " * 100])
    p = provider(b)
    d = dh.draft_highlights(provider=p, today=TODAY)
    assert [h["company"] for h in d["highlights"]] == ["Visa"]
    assert d["highlights"][0]["drafted_by"] == "local:phi4-mini"
    assert d["shortfall"] == 3
    o = dh.draft_outlook(d, [], provider=p)
    assert o["drafted_by"] == "local:phi4-mini"


# ---------------------------------------------------------------------------
# Shared fallback semantics: both providers apply the same genuine-announcement test
# ---------------------------------------------------------------------------

def test_both_provider_prompts_use_the_same_genuine_announcement_test():
    from cytonn_weekly.digital_payments.providers import anthropic_provider as ap
    from cytonn_weekly.digital_payments.providers import local_provider as lp
    from cytonn_weekly.digital_payments.providers.base import GENUINE_ANNOUNCEMENT, NOT_GENUINE

    for prompt in (ap._HIGHLIGHTS_SYSTEM, lp._HIGHLIGHT_SYSTEM):
        assert GENUINE_ANNOUNCEMENT in prompt and NOT_GENUINE in prompt
        assert "NOT a genuine" in prompt
    # Anthropic signals "not genuine" the way it signals any non-story: NO_STORY, which triggers the web fallback.
    assert "NO_STORY" in ap._HIGHLIGHTS_SYSTEM
