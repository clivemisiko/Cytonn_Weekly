import ast
import inspect
import json
import logging
import os
import re
from datetime import date
from types import SimpleNamespace as NS

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient

from api.cms_publish import local_pieces, publish_report
from api.main import create_app, failure_message, provider_problem
from api.serialize import is_dev_draft
from cytonn_weekly import env
from cytonn_weekly.digital_payments.delivery import is_dev_mode_review
from cytonn_weekly.digital_payments.provider_factory import get_provider
from cytonn_weekly.digital_payments.providers import drafting
from cytonn_weekly.digital_payments.providers.anthropic_provider import AnthropicProvider
from cytonn_weekly.digital_payments.providers.base import DraftingProvider
from cytonn_weekly.digital_payments.providers.local_provider import EXA_KEY_MISSING, LocalProvider
from cytonn_weekly.narrative import bedrock_provider as bp
from cytonn_weekly.narrative.anthropic_provider import AnthropicNarrativeProvider
from cytonn_weekly.narrative.base import NarrativeBrief, NarrativeProvider
from cytonn_weekly.narrative.drafter import draft_pieces
from cytonn_weekly.narrative.factory import get_narrative_provider
from cytonn_weekly.narrative.local_provider import LocalNarrativeProvider
from tests.review_helpers import make_review
from tests.section_helpers import TODAY, focus_review

URL = "https://investor.example.com/news"
UNSEEN = "https://unseen.example/page"
MODEL = "us.anthropic.claude-sonnet-4-6"
START = date(2026, 9, 26)
BRIEF = NarrativeBrief(id="lending", section="Real Estate", label="Mortgage lending", focus="loans",
                       preferred_domains=("centralbank.go.ke",))
# Values have spaces on purpose: they can never be mistaken for, or be, a real credential.
SECRETS = {"AWS_ACCESS_KEY_ID": "not a real key id", "AWS_SECRET_ACCESS_KEY": "not a real secret",
           "AWS_SESSION_TOKEN": "not a real session token", "AWS_BEARER_TOKEN_BEDROCK": "not a real bearer token"}
PAGE = {"url": URL, "title": "Release", "text": "Visa paid $5 million for a thing. Loans rose 8.75% in 2026.",
        "publishedDate": "2026-09-29"}
SEAM_AS_SHIPPED = bp.sources_for   # before any test replaces it


@pytest.fixture
def aws(monkeypatch):
    """A complete Bedrock set-up in the environment, with boto3 reported present (it is not installed in every venv)."""
    monkeypatch.setenv("CYTONN_LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", SECRETS["AWS_ACCESS_KEY_ID"])
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", SECRETS["AWS_SECRET_ACCESS_KEY"])
    for name in ("BEDROCK_MODEL_ID", "AWS_DEFAULT_REGION", "AWS_SESSION_TOKEN", "AWS_BEARER_TOKEN_BEDROCK", "EXA_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(bp, "boto3_installed", lambda: True)


@pytest.fixture(autouse=True)
def pages(monkeypatch):
    """One supplied page for every subject, standing in for step 2b; the tests of the empty seam put the real one back."""
    monkeypatch.setattr(bp, "sources_for", lambda subject, week_end: [dict(PAGE)])


TEXT = {"propose the section titles": "Overview of the topic\nMarket performance\nRisks\nRecommendations and Conclusion",
        "closing part": "The sections show steady demand. Investors may weigh these points against their own mandate.",
        "opening paragraph": "This report covers the market and its risks."}


class FakeBedrock:
    """What ``client.messages.create`` is: a forced-tool call gets a draft that cites one shown and one unseen URL."""

    def __init__(self, error=None, stop="tool_use"):
        self.calls, self.messages, self.error, self.stop = [], self, error, stop

    def create(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        if "tools" in kw:
            subject = kw["messages"][-1]["content"].split("\n", 1)[0].removeprefix("Company: ")
            paragraph = (f"During the week, [{subject}]({URL}) paid $5 million for a thing, and "
                         f"[more]({UNSEEN}) was said.")
            reply = {"is_genuine_announcement": True, "reasoning": "x", "headline": f"{subject} announces a thing",
                     "paragraph": paragraph,
                     "claims": [{"claim": f"{subject} paid $5 million", "url": URL}, {"claim": "unseen", "url": UNSEEN}]}
            return NS(stop_reason=self.stop, content=[NS(type="tool_use", input=reply)])
        said = next((v for k, v in TEXT.items() if k in kw.get("system", "")), "Outlook: the sector gained $2 billion.")
        return NS(stop_reason="end_turn", content=[NS(type="text", text=said)])


def narrative(client=None, **kw):
    return bp.BedrockNarrativeProvider(client=client or FakeBedrock(), **kw)


def api_error(cls, status, kind, message="RAW LIBRARY TEXT"):
    response = httpx2.Response(status, headers={"x-amzn-ErrorType": kind},
                               request=httpx2.Request("POST", "https://bedrock-runtime.us-east-1.amazonaws.com/x"))
    return cls(message, response=response, body=None)


# --- the switch -----------------------------------------------------------------------

def test_bedrock_is_chosen_by_the_switch_and_not_by_default(aws, monkeypatch):
    assert isinstance(get_narrative_provider(), bp.BedrockNarrativeProvider)
    assert isinstance(get_provider(), bp.BedrockProvider)
    monkeypatch.delenv("CYTONN_LLM_PROVIDER")
    assert isinstance(get_narrative_provider(), AnthropicNarrativeProvider)
    assert isinstance(get_provider(), AnthropicProvider)


def test_the_model_is_bedrock_model_id_with_the_sonnet_profile_as_default(aws, monkeypatch):
    assert narrative().model == MODEL and narrative().drafted_by == f"bedrock:{MODEL}"
    monkeypatch.setenv("BEDROCK_MODEL_ID", " us.anthropic.claude-haiku-4-5 ")
    assert narrative().drafted_by == "bedrock:us.anthropic.claude-haiku-4-5"


def test_the_ollama_speed_settings_have_no_say_over_a_bedrock_draft(aws, monkeypatch):
    monkeypatch.setenv("CYTONN_LOCAL_MAX_SEARCH_RESULTS", "1")
    monkeypatch.setenv("CYTONN_LOCAL_RESULT_CHARS", "500")
    monkeypatch.setattr(bp, "sources_for", lambda subject, week_end: [
        {"url": f"{URL}/{i}", "title": str(i), "text": "word " * 400, "publishedDate": ""} for i in range(3)])
    client = FakeBedrock()
    p = bp.BedrockNarrativeProvider(client=client)
    p.draft_piece(BRIEF, start=START, end=TODAY, today=TODAY)
    sent = client.calls[0]["messages"][-1]["content"]
    assert not hasattr(p, "settings") and sent.count("[Result") == 3 and len(sent) > 3 * 1900


# --- independent of the local providers and of Exa -------------------------------------------------

def _imports(module):
    names = set()
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
    return names


def test_the_bedrock_module_does_not_import_the_local_providers_and_does_not_mention_exa():
    for module in (bp, drafting):
        assert not [n for n in _imports(module) if "local_provider" in n], module.__name__
        assert not re.search(r"\bexa\b|EXA_|exa_", inspect.getsource(module), re.IGNORECASE), module.__name__


def test_the_bedrock_providers_do_not_subclass_either_local_provider():
    for cls, base in ((bp.BedrockProvider, DraftingProvider), (bp.BedrockNarrativeProvider, NarrativeProvider)):
        assert issubclass(cls, base)
        assert not issubclass(cls, (LocalProvider, LocalNarrativeProvider))
        assert not any(c.__module__.endswith("local_provider") for c in cls.__mro__)


# --- a draft ---------------------------------------------------------------------------

def test_a_narrative_piece_has_claims_links_and_flags_as_a_local_one_does_and_drops_what_it_was_not_shown(aws):
    client = FakeBedrock()
    p = bp.BedrockNarrativeProvider(client=client)
    res = p.draft_piece(BRIEF, start=START, end=TODAY, today=TODAY)
    assert res.drafted_by == f"bedrock:{MODEL}" and not res.no_story
    assert res.claims == [{"text": "Mortgage lending paid $5 million", "url": URL, "title": "Release", "cited_text": ""}]
    assert res.links == [{"anchor": "Mortgage lending", "url": URL}]
    assert UNSEEN not in res.paragraph_md and "more" in res.paragraph
    assert any("claim cited a URL not in the search results; dropped" in w for w in res.warnings)
    assert any("link to " + UNSEEN in w for w in res.warnings)
    assert "Bedrock provider: claims carry no cited_text" in " ".join(res.warnings)
    assert f"Written by Amazon Bedrock ({MODEL}) from the supplied sources." in res.warnings
    assert not any("Exa" in w for w in res.warnings) and res.search_scope == bp.SCOPE_SUPPLIED


def test_the_call_is_a_forced_client_side_function_with_no_server_tool_and_no_continuation(aws):
    client = FakeBedrock()
    narrative(client).draft_piece(BRIEF, start=START, end=TODAY, today=TODAY)
    call = client.calls[0]
    assert call["model"] == MODEL and call["max_tokens"] == bp.MAX_TOKENS == 4096
    assert call["tool_choice"] == {"type": "tool", "name": bp.DRAFT_TOOL}
    assert [t["name"] for t in call["tools"]] == [bp.DRAFT_TOOL] == ["submit_draft"] and "type" not in call["tools"][0]
    assert call["messages"][0]["role"] == "user" and "Supplied sources:" in call["messages"][0]["content"]
    assert "search results" not in call["system"] and "Search results" not in call["messages"][0]["content"]
    assert set(call) == {"model", "max_tokens", "messages", "system", "tools", "tool_choice"}   # no other tool or option
    assert "web_search" not in json.dumps(call) and len(client.calls) == 1


def test_a_reply_cut_off_at_the_token_limit_is_discarded_with_a_warning(aws):
    res = narrative(FakeBedrock(stop="max_tokens")).draft_piece(BRIEF, start=START, end=TODAY, today=TODAY)
    assert res.no_story and any("Bedrock model returned invalid JSON" in w for w in res.draft_warnings)


def test_a_digital_payments_review_is_a_production_draft_with_the_brief_caps(aws):
    client = FakeBedrock()
    provider = bp.BedrockProvider(client=client)
    review = make_review(provider)
    highlights = [i for i in review.section["items"] if i.get("kind") == "highlight"]
    assert highlights and {i["drafted_by"] for i in highlights} == {f"bedrock:{MODEL}"}
    assert review.section["outlook"]["drafted_by"] == f"bedrock:{MODEL}"
    assert not is_dev_draft(review) and not is_dev_mode_review(review) and not list(local_pieces(review.section))
    assert highlights[0]["search_scope"] == bp.SCOPE_SUPPLIED
    plain = [c for c in client.calls if "tools" not in c]
    assert [c["max_tokens"] for c in plain] == [800]                       # the outlook, as on the Anthropic path
    assert all(c["max_tokens"] == 4096 for c in client.calls if "tools" in c)


# --- the Focus structure ------------------------------------------------------------------

def test_the_focus_structure_runs_through_bedrock_with_the_caps_and_is_not_a_dev_draft(aws):
    client = FakeBedrock()
    provider = bp.BedrockNarrativeProvider(client=client)
    review = focus_review(provider)
    assert review.section["outline"]["source"] == "proposed"
    assert [c["max_tokens"] for c in client.calls] == [300, 2000, 2000, 2000, 2000, 600]   # outline, 3 sections, conclusion, lead
    assert review.section["api_requests"] == 6 and review.section["pieces_found"] == review.section["pieces_expected"]
    drafted = {b["drafted_by"] for b in review.section["blocks"] if b["kind"] == "narrative"}
    assert drafted == {f"bedrock:{MODEL}"}
    assert not is_dev_draft(review) and not is_dev_mode_review(review) and not list(local_pieces(review.section))
    with pytest.raises(Exception) as refused:                                # the CMS stub's guards: not approved, not dev
        publish_report(review.report_type, review.period, [review])
    assert "dev-mode" not in str(refused.value) and "not approved" in str(refused.value)


# --- the real client, against a mock transport ------------------------------------------------

def test_the_real_client_posts_to_the_inference_profile_with_the_bearer_token():
    seen = {}

    def handler(request):
        seen.update(url=str(request.url), auth=request.headers.get("authorization"), body=json.loads(request.content))
        return httpx2.Response(200, json={
            "id": "m", "type": "message", "role": "assistant", "model": MODEL, "stop_reason": "tool_use",
            "content": [{"type": "tool_use", "id": "t", "name": bp.DRAFT_TOOL, "input": {"a": 1}}],
            "usage": {"input_tokens": 1, "output_tokens": 1}})

    client = anthropic.AnthropicBedrock(aws_region="us-east-1", api_key="bearer not real", max_retries=0,
                                        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    p = bp.BedrockNarrativeProvider(client=client)
    assert p._chat([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}], {"type": "object"}, 77) == '{"a": 1}'
    assert seen["url"] == f"https://bedrock-runtime.us-east-1.amazonaws.com/model/{MODEL}/invoke"
    assert seen["auth"] == "Bearer bearer not real" and "model" not in seen["body"]
    assert seen["body"]["anthropic_version"] == "bedrock-2023-05-31" and seen["body"]["max_tokens"] == 77


def test_the_client_the_provider_builds_takes_the_region_and_the_bearer_token_from_the_environment(aws, monkeypatch):
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", SECRETS["AWS_BEARER_TOKEN_BEDROCK"])
    client = bp.BedrockNarrativeProvider().client
    assert isinstance(client, anthropic.AnthropicBedrock)
    assert client.aws_region == "us-east-1" and client.api_key == SECRETS["AWS_BEARER_TOKEN_BEDROCK"]
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK")
    monkeypatch.delenv("AWS_REGION")
    with pytest.raises(bp.BedrockError, match="needs an AWS region"):
        bp.BedrockNarrativeProvider().client


# --- before a draft starts ----------------------------------------------------------------------

def test_the_complete_set_up_has_no_problem_and_is_not_dev_mode(aws, tmp_path):
    assert provider_problem() is None
    cfg = TestClient(create_app(db_path=tmp_path / "a.db", load_dotenv=False)).get("/api/config").json()
    assert (cfg["provider"], cfg["provider_valid"], cfg["dev_mode"], cfg["spends_api_budget"], cfg["provider_problem"]) == (
        "bedrock", True, False, True, None)


@pytest.mark.parametrize("remove, says", [
    (["AWS_REGION"], bp.REGION_MISSING),
    (["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"], bp.CREDENTIALS_MISSING),
    (["AWS_SECRET_ACCESS_KEY"], bp.CREDENTIALS_MISSING),
])
def test_a_missing_part_is_a_plain_409_before_anything_is_fetched_and_a_bearer_token_stands_for_the_keys(
        aws, monkeypatch, tmp_path, remove, says):
    for name in remove:
        monkeypatch.delenv(name)
    client = TestClient(create_app(db_path=tmp_path / "a.db", load_dotenv=False))
    assert provider_problem() == says
    for r in (client.post("/api/sections/equities/draft"), client.post("/api/runs", json={"section": "equities"})):
        assert r.status_code == 409 and r.json()["detail"] == says
    assert client.get("/api/config").json()["provider_problem"] == says
    assert client.get("/api/sections").json()["drafting"] is None            # the slot was never taken
    if "AWS_ACCESS_KEY_ID" in remove:
        monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", SECRETS["AWS_BEARER_TOKEN_BEDROCK"])
        assert provider_problem() is None


def test_a_blank_value_is_as_missing_as_an_absent_one_and_the_region_may_be_the_default_one(aws, monkeypatch):
    monkeypatch.setenv("AWS_REGION", "  ")
    assert provider_problem() == bp.REGION_MISSING
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    assert provider_problem() is None


def test_access_keys_without_boto3_say_so_and_a_bearer_token_does_not_need_it(aws, monkeypatch):
    monkeypatch.setattr(bp, "boto3_installed", lambda: False)
    assert provider_problem() == bp.BOTO3_MISSING
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", SECRETS["AWS_BEARER_TOKEN_BEDROCK"])
    assert provider_problem() is None


def test_an_unknown_provider_names_all_three(monkeypatch):
    monkeypatch.setenv("CYTONN_LLM_PROVIDER", "gpt")
    assert provider_problem() == "Unknown CYTONN_LLM_PROVIDER value 'gpt'; expected 'anthropic', 'bedrock' or 'local'."


def test_startup_names_which_aws_variables_are_set_and_never_a_value(aws, monkeypatch, caplog, tmp_path):
    monkeypatch.setenv("AWS_SESSION_TOKEN", SECRETS["AWS_SESSION_TOKEN"])
    with caplog.at_level(logging.WARNING):
        create_app(db_path=tmp_path / "a.db", load_dotenv=False)
    lines = [r.getMessage() for r in caplog.records if "Amazon Bedrock" in r.getMessage()]
    assert len(lines) == 1
    assert ("AWS variables set: AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN; "
            "not set: AWS_DEFAULT_REGION, AWS_BEARER_TOKEN_BEDROCK.") in lines[0]
    assert "Exa" not in lines[0] and not any(v in caplog.text for v in SECRETS.values())
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", SECRETS["AWS_BEARER_TOKEN_BEDROCK"])
    assert "AWS_BEARER_TOKEN_BEDROCK is the one used" in bp.startup_line()


def test_no_warning_is_logged_for_another_provider(monkeypatch, caplog, tmp_path):
    monkeypatch.setenv("CYTONN_LLM_PROVIDER", "local")
    with caplog.at_level(logging.WARNING):
        create_app(db_path=tmp_path / "a.db", load_dotenv=False)
    assert "Amazon Bedrock" not in caplog.text


# --- no Exa for Bedrock; Exa still required locally -------------------------------------------------

def test_bedrock_variables_without_an_exa_key_are_no_problem(aws, tmp_path):
    assert "EXA_API_KEY" not in os.environ
    assert bp.env_problem() is None and provider_problem() is None
    cfg = TestClient(create_app(db_path=tmp_path / "a.db", load_dotenv=False)).get("/api/config").json()
    assert cfg["provider_problem"] is None


def test_a_bedrock_draft_is_not_refused_for_a_missing_exa_key_and_a_local_draft_still_is(aws, monkeypatch, tmp_path):
    client = TestClient(create_app(db_path=tmp_path / "a.db", load_dotenv=False))
    assert "EXA_API_KEY" not in os.environ and provider_problem() is None
    monkeypatch.setenv("CYTONN_LLM_PROVIDER", "local")
    assert provider_problem() == EXA_KEY_MISSING
    for r in (client.post("/api/sections/equities/draft"), client.post("/api/runs", json={"section": "equities"})):
        assert r.status_code == 409 and r.json()["detail"] == EXA_KEY_MISSING
    assert client.get("/api/sections").json()["drafting"] is None            # the slot was never taken


def test_an_exa_key_override_is_reported_for_the_local_provider_only(monkeypatch, tmp_path):
    dot_env = tmp_path / ".env"
    dot_env.write_text("EXA_API_KEY=file-key-0000000000000000\n", encoding="utf-8")
    monkeypatch.setenv("EXA_API_KEY", "shell-key-1111111111111111")
    for provider, reported in (("bedrock", False), ("anthropic", False), ("local", True)):
        monkeypatch.setenv("CYTONN_LLM_PROVIDER", provider)
        assert bool(env.key_override_warnings(dot_env)) is reported, provider


# --- the source seam ---------------------------------------------------------------------------------

def test_the_seam_as_shipped_returns_no_sources():
    assert SEAM_AS_SHIPPED("Mortgage lending", TODAY) == []


def test_with_no_sources_a_piece_is_unavailable_with_the_plain_sentence_and_nothing_is_called(aws, monkeypatch):
    monkeypatch.setattr(bp, "sources_for", SEAM_AS_SHIPPED)
    assert bp.NO_SOURCES == "No sources were supplied for this piece, so nothing was drafted. Supply the pages to read."
    client = FakeBedrock()
    res = narrative(client).draft_piece(BRIEF, start=START, end=TODAY, today=TODAY)
    assert res.no_story and res.paragraph == "" and res.draft_warnings == [f"{BRIEF.label}: {bp.NO_SOURCES}"]
    assert client.calls == []                                                # no Bedrock call, and no search of any kind
    hl = bp.BedrockProvider(client=client).find_highlight("Visa", "investor.visa.com", start=START, end=TODAY, today=TODAY)
    assert hl.no_story and hl.draft_warnings == [f"Visa: {bp.NO_SOURCES}"] and client.calls == []
    drafted = draft_pieces([BRIEF], 1, provider=narrative(client), today=TODAY)
    assert drafted["pieces"] == [] and drafted["shortfall"] == 1
    assert f"{BRIEF.label}: {bp.NO_SOURCES}" in drafted["warnings"] and client.calls == []


def test_the_seam_is_asked_for_the_subject_and_the_end_of_the_report_week(aws, monkeypatch):
    asked = []
    monkeypatch.setattr(bp, "sources_for", lambda subject, week_end: asked.append((subject, week_end)) or [dict(PAGE)])
    narrative().draft_piece(BRIEF, start=START, end=TODAY, today=TODAY)
    bp.BedrockProvider(client=FakeBedrock()).find_highlight("Visa", "investor.visa.com", start=START, end=TODAY, today=TODAY)
    assert asked == [("Mortgage lending", TODAY), ("Visa", TODAY)]


# --- when Bedrock fails --------------------------------------------------------------------------

REQUEST = httpx2.Request("POST", "https://bedrock-runtime.us-east-1.amazonaws.com/x")
FAILURES = [
    (api_error(anthropic.PermissionDeniedError, 403, "AccessDeniedException:http://internal"),
     ["AccessDeniedException", "model access is not enabled", "IAM policy", MODEL, "will not help"]),
    (api_error(anthropic.BadRequestError, 400, "ValidationException"),
     ["ValidationException", "BEDROCK_MODEL_ID is " + MODEL, "inference profile", "will not help"]),
    (api_error(anthropic.RateLimitError, 429, "ThrottlingException"), ["throttling", "Wait a few minutes"]),
    (api_error(anthropic.BadRequestError, 400, "ServiceQuotaExceededException"), ["service quota", "will not help"]),
    (api_error(anthropic.PermissionDeniedError, 403, "ExpiredTokenException", "The security token is expired"),
     ["have expired", "fresh credentials", "force-recreate"]),
    (api_error(anthropic.AuthenticationError, 401, "UnrecognizedClientException"), ["did not accept the AWS credentials"]),
    (api_error(anthropic.InternalServerError, 500, "InternalServerException"), ["could not serve", "draft again"]),
    (anthropic.APIConnectionError(request=REQUEST), ["could not reach Amazon Bedrock in us-east-1"]),
    (anthropic.APITimeoutError(request=REQUEST), ["could not reach Amazon Bedrock in us-east-1"]),
    (RuntimeError("could not resolve credentials from session"), ["needs AWS credentials"]),
    (ValueError("No AWS region was provided."), ["needs an AWS region"]),
    (ModuleNotFoundError("No module named 'boto3'"), ["boto3"]),
    (api_error(anthropic.APIStatusError, 418, "TeapotException"), ["does not recognise (TeapotException, HTTP 418)"]),
]


@pytest.mark.parametrize("error, words", FAILURES, ids=lambda v: type(v).__name__ if isinstance(v, BaseException) else "")
def test_each_failure_is_one_plain_sentence_with_no_library_text_and_no_secret(aws, monkeypatch, caplog, error, words):
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    with caplog.at_level(logging.DEBUG), pytest.raises(bp.BedrockError) as raised:
        narrative(FakeBedrock(error=error)).draft_piece(BRIEF, start=START, end=TODAY, today=TODAY)
    sentence = str(raised.value)
    assert all(w in sentence for w in words), sentence
    assert "RAW LIBRARY TEXT" not in sentence and "Traceback" not in sentence
    shown = failure_message(raised.value)                                   # what the run view shows
    assert shown == sentence
    for value in SECRETS.values():
        assert value not in sentence and value not in shown and value not in caplog.text


def test_a_failure_that_is_not_a_bedrock_error_is_not_swallowed_by_the_mapping(aws):
    class Oops(BaseException):
        pass
    with pytest.raises(Oops):
        narrative(FakeBedrock(error=Oops())).draft_piece(BRIEF, start=START, end=TODAY, today=TODAY)
