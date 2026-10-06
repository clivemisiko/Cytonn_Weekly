"""The narrative providers (Anthropic and local) and their factory; LLM and network always faked."""

import json
from datetime import date
from types import SimpleNamespace as NS

import httpx
import pytest

from cytonn_weekly.digital_payments.providers.base import SCOPE_WEB
from cytonn_weekly.narrative import factory
from cytonn_weekly.narrative.anthropic_provider import SCOPE_PREFERRED, AnthropicNarrativeProvider
from cytonn_weekly.narrative.base import NarrativeBrief
from cytonn_weekly.narrative.drafter import draft_pieces
from cytonn_weekly.narrative.local_provider import LocalNarrativeProvider

TODAY = date(2026, 10, 2)
START = date(2026, 9, 26)
URL = "https://www.centralbank.go.ke/mortgage"
BRIEF = NarrativeBrief(id="residential", section="Real Estate", label="Mortgage lending",
                       focus="mortgage data in Kenya", words=(10, 60), preferred_domains=("centralbank.go.ke",))
FREE = NarrativeBrief(id="focus", section="Focus", label="SSA Eurobonds", focus="Eurobond yields", words=(10, 60),
                      opener=None)


def cite(url, text):
    return NS(type="web_search_result_location", url=url, title="CBK", cited_text=text)


def piece_blocks(url=URL, opener="During the week,"):
    return [
        NS(type="web_search_tool_result", content=[NS(url=url, title="CBK", page_age="2 days ago")]),
        NS(type="text", text="### Mortgage Loans Rise\n\n", citations=None),
        NS(type="text", text=f"{opener} [mortgage loans]({url}) rose 10% to Sh307.2 billion,",
           citations=[cite(url, "loans rose 10 percent to Sh307.2 billion")]),
        NS(type="text", text=" with more lenders active [elsewhere](https://not-returned.example) this year, "
                             "which reflects deeper housing finance demand across the market.", citations=None),
    ]


class Client:
    """Fake Anthropic client: ``preferred`` / ``web`` are the blocks for each pass (NO_STORY if None)."""

    def __init__(self, preferred=None, web=None):
        self.replies = {"preferred": preferred, "web": web}
        self.calls = []
        self.messages = NS(create=self._create)

    def _create(self, **kw):
        scope = "preferred" if "allowed_domains" in kw["tools"][0] else "web"
        self.calls.append((scope, kw))
        blocks = self.replies[scope] or [NS(type="text", text="NO_STORY", citations=None)]
        return NS(content=blocks, stop_reason="end_turn")


def test_anthropic_drafts_from_preferred_sources_with_cited_claims():
    client = Client(preferred=piece_blocks())
    res = AnthropicNarrativeProvider(client=client).draft_piece(BRIEF, start=START, end=TODAY, today=TODAY)
    assert not res.no_story and res.search_scope == SCOPE_PREFERRED and res.headline == "Mortgage Loans Rise"
    assert res.claims == [{"text": "During the week, mortgage loans rose 10% to Sh307.2 billion,", "url": URL,
                           "title": "CBK", "cited_text": "loans rose 10 percent to Sh307.2 billion"}]
    assert "not-returned.example" not in res.paragraph_md  # only URLs the search returned stay linked
    assert any("not in the search results" in w for w in res.warnings)
    tool = client.calls[0][1]["tools"][0]
    assert tool["allowed_domains"] == ["centralbank.go.ke"] and tool["max_uses"] == BRIEF.max_searches
    assert "Mortgage lending" in client.calls[0][1]["system"]


def test_anthropic_falls_back_to_the_web_then_reports_no_story():
    client = Client(web=piece_blocks())
    res = AnthropicNarrativeProvider(client=client).draft_piece(BRIEF, start=START, end=TODAY, today=TODAY)
    assert res.search_scope == SCOPE_WEB and [c[0] for c in client.calls] == ["preferred", "web"]
    empty = Client()
    res = AnthropicNarrativeProvider(client=empty).draft_piece(BRIEF, start=START, end=TODAY, today=TODAY)
    assert res.no_story and len(empty.calls) == 2


def test_anthropic_brief_without_preferred_domains_searches_once_and_skips_the_opener_rule():
    client = Client(web=piece_blocks(opener="Sub-Saharan"))
    res = AnthropicNarrativeProvider(client=client).draft_piece(FREE, start=START, end=TODAY, today=TODAY)
    assert len(client.calls) == 1 and not any("does not open" in w for w in res.warnings)


def test_draft_pieces_orders_skips_and_counts_shortfall():
    briefs = [BRIEF, NarrativeBrief(id="b", section="Real Estate", label="Quiet", focus="x"), FREE]
    client = Client(preferred=piece_blocks(), web=None)
    out = draft_pieces(briefs, 2, provider=AnthropicNarrativeProvider(client=client), today=TODAY)
    assert [p["brief_id"] for p in out["pieces"]] == ["residential"]
    assert out["shortfall"] == 1 and out["week_start"] == "2026-09-26"
    assert any("Quiet: nothing qualifying" in w for w in out["warnings"])


# --- local --------------------------------------------------------------------------

class Backend:
    def __init__(self, exa, llm):
        self.exa, self.llm = exa, list(llm)
        self.exa_calls = []

    def __call__(self, request):
        url = str(request.url)
        if url.endswith("/api/tags"):
            return httpx.Response(200, json={"models": [{"name": "phi4-mini:latest"}]})
        body = json.loads(request.content)
        if "exa.ai" in url:
            scope = "preferred" if "includeDomains" in body else "web"
            self.exa_calls.append(scope)
            return httpx.Response(200, json={"results": self.exa.get(scope, [])})
        return httpx.Response(200, json={"message": {"content": json.dumps(self.llm.pop(0))}})


def local(backend):
    return LocalNarrativeProvider(exa_api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(backend)))


def test_local_drafts_and_never_has_a_cited_span():
    reply = {"is_genuine_announcement": True, "reasoning": "data", "headline": "Loans Rise",
             "paragraph": f"During the week, [loans]({URL}) rose 10% to Sh307.2 billion across many lenders.",
             "claims": [{"claim": "loans rose 10%", "url": URL}, {"claim": "made up", "url": "https://x.example"}]}
    backend = Backend({"preferred": [{"url": URL, "title": "CBK", "text": "loans rose"}]}, [reply])
    res = local(backend).draft_piece(BRIEF, start=START, end=TODAY, today=TODAY)
    assert res.search_scope == SCOPE_PREFERRED and res.drafted_by == "local:phi4-mini"
    assert res.claims == [{"text": "loans rose 10%", "url": URL, "title": "CBK", "cited_text": ""}]
    assert any("dropped" in w for w in res.warnings)


def test_local_judged_not_qualifying_falls_back_then_no_story():
    no = {"is_genuine_announcement": False, "reasoning": "opinion piece", "headline": "", "paragraph": "", "claims": []}
    backend = Backend({"preferred": [{"url": URL}], "web": [{"url": URL}]}, [no, no])
    res = local(backend).draft_piece(BRIEF, start=START, end=TODAY, today=TODAY)
    assert res.no_story and backend.exa_calls == ["preferred", "web"]
    assert any("opinion piece" in w for w in res.draft_warnings)


# --- factory ------------------------------------------------------------------------

def test_factory_defaults_to_anthropic(monkeypatch):
    monkeypatch.delenv("CYTONN_LLM_PROVIDER", raising=False)
    p = factory.get_narrative_provider()
    assert isinstance(p, AnthropicNarrativeProvider) and p.drafted_by == "anthropic:claude-sonnet-5-5"


def test_anthropic_label_names_the_model_actually_used():
    # The label was once a second hand-typed string ("claude-sonnet-5") that drifted from MODEL.
    for model in (AnthropicNarrativeProvider().model, "claude-opus-5-5"):
        assert AnthropicNarrativeProvider(model=model).drafted_by == f"anthropic:{model}"


def test_factory_local_prints_the_dev_banner(monkeypatch, capsys):
    monkeypatch.setenv("CYTONN_LLM_PROVIDER", "local")
    p = factory.get_narrative_provider()
    assert isinstance(p, LocalNarrativeProvider) and "NOT FOR PUBLICATION" in capsys.readouterr().out


def test_factory_rejects_unknown(monkeypatch):
    monkeypatch.setenv("CYTONN_LLM_PROVIDER", "gpt")
    with pytest.raises(ValueError, match="Unknown"):
        factory.get_narrative_provider()
