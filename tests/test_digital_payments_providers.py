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


# ---------------------------------------------------------------------------
# Selectable local model (A/B testing): drafted_by and the Ollama request follow the model
# ---------------------------------------------------------------------------

GEMMA = "gemma4:26b-a4b-it-qat"


def test_model_label_shortens_ollama_tags():
    from cytonn_weekly.digital_payments.providers.local_provider import model_label

    assert model_label("phi4-mini") == "phi4-mini"
    assert model_label("phi4-mini:latest") == "phi4-mini"
    assert model_label(GEMMA) == "gemma4-26b-a4b"
    # Derived from the string passed in, not tied to the 26B variant; "latest" is shown as the E4B it resolves to.
    assert model_label("gemma4:latest") == "gemma4-e4b" and model_label("gemma4") == "gemma4-e4b"
    assert model_label("gemma4:e4b") == "gemma4-e4b" and model_label("gemma4:e2b-it-qat") == "gemma4-e2b"
    assert model_label("llama3:latest") == "llama3"
    # Namespaced registry names (user/model) are labelled by the model name alone.
    assert model_label("openbmb/minicpm5-2b") == "minicpm5-2b"
    assert model_label("openbmb/minicpm5-2b:q8_0") == "minicpm5-2b-q8_0"
    assert LocalProvider(model="openbmb/minicpm5-2b", exa_api_key="k").drafted_by == "local:minicpm5-2b"


@pytest.mark.parametrize("model,label", [("phi4-mini", "local:phi4-mini"), (GEMMA, "local:gemma4-26b-a4b")])
def test_drafted_by_and_ollama_requests_reflect_the_model_that_ran(model, label):
    b = Backend({"ir": [exa_result()]}, [genuine(), "outlook " * 100], models=(model,))
    p = LocalProvider(model=model, exa_api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(b)))
    assert p.drafted_by == label
    res = find(p)
    assert res.drafted_by == label
    assert p.draft_outlook({"avg_wow_pct": 1.0}, []).drafted_by == label
    # Both the highlight and outlook calls go to the selected model, with the same structured-output request.
    assert [c["model"] for c in b.chat_calls] == [model, model]
    assert b.chat_calls[0]["format"]["required"][:2] == ["is_genuine_announcement", "reasoning"]
    assert b.chat_calls[0]["options"] == {"temperature": 0, "num_ctx": 8192, "num_predict": 2048}
    assert b.chat_calls[1]["options"]["num_predict"] == 2048  # the outlook call is capped too


def test_default_model_is_phi4_mini():
    assert LocalProvider(exa_api_key="k").drafted_by == "local:phi4-mini"


def test_missing_selected_model_names_that_model_in_the_pull_instruction():
    with pytest.raises(RuntimeError, match=f"ollama pull {GEMMA}"):
        find(provider_for(GEMMA, Backend({}, [], models=("phi4-mini:latest",))))


def provider_for(model, backend, **kw):
    return LocalProvider(model=model, exa_api_key="k",
                         http_client=httpx.Client(transport=httpx.MockTransport(backend)), **kw)


def test_factory_local_model_env_override(monkeypatch, capsys):
    monkeypatch.setenv("CYTONN_LLM_PROVIDER", "local")
    monkeypatch.setenv("CYTONN_LOCAL_MODEL", GEMMA)
    p = provider_factory.get_provider()
    assert p.model == GEMMA and p.drafted_by == "local:gemma4-26b-a4b"
    out = capsys.readouterr().out
    assert f"DEV MODE: drafting with local {GEMMA}" in out and "NOT FOR PUBLICATION" in out


def test_factory_local_defaults_and_cache_settings(monkeypatch):
    monkeypatch.setenv("CYTONN_LLM_PROVIDER", "local")
    monkeypatch.delenv("CYTONN_LOCAL_MODEL", raising=False)
    monkeypatch.delenv("CYTONN_EXA_REFRESH", raising=False)
    p = provider_factory.get_provider()
    assert p.model == "phi4-mini" and p._cache_dir == provider_factory.EXA_CACHE_DIR and not p._refresh_cache
    monkeypatch.setenv("CYTONN_LOCAL_MODEL", "  ")  # blank means unset
    monkeypatch.setenv("CYTONN_EXA_REFRESH", "1")
    p = provider_factory.get_provider()
    assert p.model == "phi4-mini" and p._refresh_cache


def test_local_model_env_is_ignored_for_anthropic(monkeypatch):
    monkeypatch.setenv("CYTONN_LOCAL_MODEL", GEMMA)
    for value in (None, "anthropic"):
        if value is None:
            monkeypatch.delenv("CYTONN_LLM_PROVIDER", raising=False)
        else:
            monkeypatch.setenv("CYTONN_LLM_PROVIDER", value)
        p = provider_factory.get_provider()
        assert isinstance(p, AnthropicProvider) and p.drafted_by == "anthropic:claude-sonnet-5"


# ---------------------------------------------------------------------------
# Exa result cache: a second model sees identical search results
# ---------------------------------------------------------------------------

def test_cache_is_off_by_default_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    b = Backend({"ir": [exa_result()]}, [genuine(), genuine()])
    p = provider(b)
    find(p), find(p)
    assert len(b.exa_calls) == 2 and list(tmp_path.iterdir()) == []


def test_second_model_reuses_cached_exa_results_instead_of_querying(tmp_path):
    first = Backend({"ir": [exa_result()]}, [genuine()])
    find(provider_for("phi4-mini", first, cache_dir=tmp_path))
    assert len(first.exa_calls) == 1
    files = list(tmp_path.glob("*.json"))
    assert [f.name for f in files] == ["visa_2026-09-29.json"]
    saved = json.loads(files[0].read_text(encoding="utf-8"))
    assert saved["company"] == "Visa" and saved["scopes"]["investor_relations"][0]["url"] == VISA_URL

    # Exa now "returns" something else; the cached results must win, and Exa must not be called.
    second = Backend({"ir": [exa_result("https://other.example.com", "Changed")]}, [genuine()], models=(GEMMA,))
    res = find(provider_for(GEMMA, second, cache_dir=tmp_path))
    assert second.exa_calls == []
    assert res.drafted_by == "local:gemma4-26b-a4b" and res.claims[0]["url"] == VISA_URL
    # Both models were shown the same search-result text.
    assert second.chat_calls[0]["messages"][1] == first.chat_calls[0]["messages"][1]


def test_cache_records_empty_ir_results_and_the_fallback_scope(tmp_path):
    b = Backend({"ir": [], "web": [exa_result()]}, [genuine()])
    res = find(provider_for("phi4-mini", b, cache_dir=tmp_path))
    assert res.search_scope == "web_fallback" and not any("not in the cache" in w for w in res.draft_warnings)
    scopes = json.loads((tmp_path / "visa_2026-09-29.json").read_text(encoding="utf-8"))["scopes"]
    assert scopes["investor_relations"] == [] and len(scopes["web_fallback"]) == 1

    again = Backend({}, [genuine()])
    res = find(provider_for("phi4-mini", again, cache_dir=tmp_path))
    assert again.exa_calls == [] and res.search_scope == "web_fallback"


def test_scope_missing_from_cache_is_fetched_fresh_and_flagged(tmp_path):
    find(provider_for("phi4-mini", Backend({"ir": [exa_result()]}, [genuine()]), cache_dir=tmp_path))
    # A different model rejects the IR results, so it needs the web scope the first run never fetched.
    b = Backend({"web": [exa_result("https://news.example.com/v")]},
                [NOT_GENUINE, genuine(paragraph(url="https://news.example.com/v"),
                                      [{"claim": "x", "url": "https://news.example.com/v"}])], models=(GEMMA,))
    res = find(provider_for(GEMMA, b, cache_dir=tmp_path))
    assert [s for s, _ in b.exa_calls] == ["web"]
    assert any("web_fallback search results were not in the cache" in w for w in res.draft_warnings)
    assert "web_fallback" in json.loads((tmp_path / "visa_2026-09-29.json").read_text(encoding="utf-8"))["scopes"]


def test_refresh_cache_forces_a_fresh_exa_pull_and_overwrites(tmp_path):
    find(provider_for("phi4-mini", Backend({"ir": [exa_result()]}, [genuine()]), cache_dir=tmp_path))
    b = Backend({"ir": [exa_result("https://investor.visa.com/new", "New")]},
                [genuine(paragraph(url="https://investor.visa.com/new"),
                         [{"claim": "x", "url": "https://investor.visa.com/new"}])])
    res = find(provider_for("phi4-mini", b, cache_dir=tmp_path, refresh_cache=True))
    assert len(b.exa_calls) == 1 and res.claims[0]["url"] == "https://investor.visa.com/new"
    saved = json.loads((tmp_path / "visa_2026-09-29.json").read_text(encoding="utf-8"))
    assert saved["scopes"]["investor_relations"][0]["url"] == "https://investor.visa.com/new"


def test_corrupt_cache_file_is_treated_as_absent(tmp_path):
    (tmp_path / "visa_2026-09-29.json").write_text("{not json", encoding="utf-8")
    b = Backend({"ir": [exa_result()]}, [genuine()])
    assert not find(provider_for("phi4-mini", b, cache_dir=tmp_path)).no_story and len(b.exa_calls) == 1


def test_capped_runaway_reply_is_truncated_json_and_discarded_as_invalid():
    # What a model that never closes its JSON looks like after Ollama stops it at num_predict.
    truncated = '{"is_genuine_announcement": true, "reasoning": "' + "the company announced " * 300
    res = find(provider(Backend({"ir": [exa_result()]}, [truncated])))
    assert res.no_story and any("invalid JSON" in w for w in res.draft_warnings)


# ---------------------------------------------------------------------------
# Per-model request overrides: MiniCPM5-2B gets a higher output cap; thinking stays on
# ---------------------------------------------------------------------------

def _requests_for(model, models=None):
    b = Backend({"ir": [exa_result()]}, [genuine(), "outlook " * 100], models=(models or model,))
    p = LocalProvider(model=model, exa_api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(b)))
    find(p)
    p.draft_outlook({"avg_wow_pct": 1.0}, [])
    return b.chat_calls


@pytest.mark.parametrize("model", ["openbmb/minicpm5-2b", "openbmb/minicpm5-2b:latest", "minicpm5-2b:q8_0"])
def test_minicpm5_2b_gets_the_higher_cap_and_keeps_thinking_on(model):
    from cytonn_weekly.digital_payments.providers import local_provider as lp

    highlight, outlook = _requests_for(model)
    for call in (highlight, outlook):
        assert call["options"] == {"temperature": 0, "num_ctx": 8192, "num_predict": 4096}
        assert "think" not in call  # thinking is left at the model's default (on)
    assert highlight["format"] == lp._RESPONSE_SCHEMA


@pytest.mark.parametrize("model", ["phi4-mini", "phi4-mini:latest", GEMMA, "gemma4:latest", "openbmb/minicpm5"])
def test_other_models_requests_are_unchanged_at_the_default_cap(model):
    from cytonn_weekly.digital_payments.providers import local_provider as lp

    highlight, outlook = _requests_for(model)
    # Exactly the default request shape: no extra keys, the 2048 cap.
    options = {"temperature": 0, "num_ctx": 8192, "num_predict": 2048}
    assert highlight == {"model": model, "stream": False, "options": options, "format": lp._RESPONSE_SCHEMA,
                         "messages": highlight["messages"]}
    assert outlook == {"model": model, "stream": False, "options": options, "messages": outlook["messages"]}
