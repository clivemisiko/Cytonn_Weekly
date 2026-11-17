import hashlib
import json
from datetime import date
from types import SimpleNamespace as NS

import pytest

from cytonn_weekly.drafting import prompts
from cytonn_weekly.drafting import bedrock as bp
from cytonn_weekly.drafting.base import NarrativeBrief

# The schemas are hand-written and sent to the model as they are. Any change to a key, its order or its wording changes
# the hash, so a move or a refactor cannot alter what the model is asked for without this test failing.
HASHES = {
    "RESPONSE_SCHEMA": "132d7ef5a9af4fa6e9b8da3eed44d8bec6576040b962dfa74eb1c57b76bfbafc",
    "SOURCED_SCHEMA": "c7b4beb77783aca2de369c2c1ed42ca4cc4ec3cc3e176b38370dea2ecacc7ad5",
    "PDF_SCHEMA": "5a3db88aee39d84f3a17f7534b484746fd654ccc8855e772fc135030cf74717c",
}
SCHEMAS = {"RESPONSE_SCHEMA": prompts.RESPONSE_SCHEMA, "SOURCED_SCHEMA": bp.SOURCED_SCHEMA, "PDF_SCHEMA": bp.PDF_SCHEMA}
PAGE = {"id": "a1b2c3d4", "url": "https://investor.example.com/news", "title": "Release", "text": "Visa paid $5 million.",
        "publishedDate": "2026-09-29", "sha256": "f" * 64, "fetched_at": "2026-11-06T10:00:00+00:00",
        "host": "investor.example.com", "origin": "pasted", "flags": []}
START, DAY = date(2026, 9, 26), date(2026, 10, 2)


def digest(schema) -> str:
    return hashlib.sha256(json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


class Recorder:
    """A Bedrock client that keeps each request and answers a forced tool call with an empty reply."""

    def __init__(self):
        self.calls, self.messages = [], self

    def create(self, **kw):
        self.calls.append(kw)
        reply = {"passages": []} if "passages" in json.dumps(kw["tools"][0]["input_schema"]) else \
            {"is_genuine_announcement": False, "reasoning": "x", "headline": "", "paragraph": "", "claims": []}
        return NS(stop_reason="tool_use", content=[NS(type="tool_use", input=reply)])


@pytest.mark.parametrize("name", HASHES)
def test_each_schema_has_the_pinned_bytes(name):
    assert digest(SCHEMAS[name]) == HASHES[name]


@pytest.fixture
def page(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(bp, "sources_for", lambda subject, week_end: [dict(PAGE)])


def sent(client) -> list[dict]:
    return [c["tools"][0]["input_schema"] for c in client.calls]


def test_the_digital_payments_call_sends_the_sourced_schema(page):
    client = Recorder()
    bp.BedrockProvider(client=client).find_highlight("Visa", "investor.visa.com", start=START, end=DAY, today=DAY)
    assert sent(client) == [bp.SOURCED_SCHEMA] and digest(sent(client)[0]) == HASHES["SOURCED_SCHEMA"]


def test_the_narrative_call_sends_the_sourced_schema(page):
    client = Recorder()
    brief = NarrativeBrief(id="x", section="Real Estate", label="Lending", focus="loans")
    bp.BedrockNarrativeProvider(client=client).draft_piece(brief, start=START, end=DAY, today=DAY)
    assert sent(client) == [bp.SOURCED_SCHEMA] and digest(sent(client)[0]) == HASHES["SOURCED_SCHEMA"]


def test_the_pdf_call_sends_the_pdf_schema(page):
    client = Recorder()
    assert bp.BedrockNarrativeProvider(client=client).read_pdf_passages("Land", "[Page 1] text") == []
    assert sent(client) == [bp.PDF_SCHEMA] and digest(sent(client)[0]) == HASHES["PDF_SCHEMA"]
