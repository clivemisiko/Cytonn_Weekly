"""The narrative providers (Bedrock factory and local) and draft_pieces; LLM and network always faked."""

import json
from datetime import date

import httpx
import pytest

from cytonn_weekly.digital_payments.providers.base import SCOPE_PREFERRED
from cytonn_weekly.narrative import factory
from cytonn_weekly.narrative.base import NarrativeBrief
from cytonn_weekly.narrative.bedrock_provider import BedrockNarrativeProvider
from cytonn_weekly.narrative.drafter import draft_pieces
from cytonn_weekly.narrative.local_provider import LocalNarrativeProvider
from tests.section_helpers import FakeNarrativeProvider

TODAY = date(2026, 10, 2)
START = date(2026, 9, 26)
URL = "https://www.centralbank.go.ke/mortgage"
BRIEF = NarrativeBrief(id="residential", section="Real Estate", label="Mortgage lending",
                       focus="mortgage data in Kenya", words=(10, 60), preferred_domains=("centralbank.go.ke",))
FREE = NarrativeBrief(id="focus", section="Focus", label="SSA Eurobonds", focus="Eurobond yields", words=(10, 60),
                      opener=None)


def test_draft_pieces_orders_skips_and_counts_shortfall():
    briefs = [BRIEF, NarrativeBrief(id="b", section="Real Estate", label="Quiet", focus="x"), FREE]
    out = draft_pieces(briefs, 2, provider=FakeNarrativeProvider(no_story={"b", "focus"}), today=TODAY)
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

def test_factory_builds_bedrock_when_asked_for_it(monkeypatch):
    monkeypatch.setenv("CYTONN_LLM_PROVIDER", "bedrock")
    assert isinstance(factory.get_narrative_provider(), BedrockNarrativeProvider)


def test_factory_refuses_the_removed_anthropic_provider(monkeypatch):
    monkeypatch.setenv("CYTONN_LLM_PROVIDER", "anthropic")
    with pytest.raises(ValueError, match="was removed"):
        factory.get_narrative_provider()


def test_factory_local_prints_the_dev_banner(monkeypatch, capsys):
    monkeypatch.setenv("CYTONN_LLM_PROVIDER", "local")
    p = factory.get_narrative_provider()
    assert isinstance(p, LocalNarrativeProvider) and "NOT FOR PUBLICATION" in capsys.readouterr().out


def test_factory_rejects_unknown(monkeypatch):
    monkeypatch.setenv("CYTONN_LLM_PROVIDER", "gpt")
    with pytest.raises(ValueError, match="Unknown"):
        factory.get_narrative_provider()
