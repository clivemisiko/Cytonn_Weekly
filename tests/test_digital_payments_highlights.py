"""Unit tests for cytonn_weekly.drafters.digital_payments_highlights.

The Anthropic client is faked; no network access.
"""

from datetime import date
from types import SimpleNamespace as NS

import pytest

from cytonn_weekly.drafters import digital_payments_highlights as dh


def cite(url, title="T", text="cited"):
    return NS(type="web_search_result_location", url=url, title=title, cited_text=text)


def text(t, citations=None):
    return NS(type="text", text=t, citations=citations)


def resp(blocks, stop_reason="end_turn"):
    return NS(content=blocks, stop_reason=stop_reason)


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.messages = NS(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


TWO_HIGHLIGHTS = [
    NS(type="server_tool_use"),
    NS(type="web_search_tool_result"),
    text("## Visa launches X\n"),
    text("Visa announced X on Monday.", [cite("https://a.com/1", "A1", "Visa X")]),
    text(" This looks strategic.", None),  # interpretive, uncited
    text("\n\n## Mastercard partners with Y\n"),
    text(
        "Mastercard and Y signed a deal.",
        [cite("https://b.com/2", "B2", "deal"), cite("https://b.com/2", "B2", "deal")],
    ),
]


def test_returns_title_body_and_citations_per_highlight():
    out = dh.draft_weekly_highlights(client=FakeClient([resp(TWO_HIGHLIGHTS)]))
    assert [h["title"] for h in out] == ["Visa launches X", "Mastercard partners with Y"]
    assert out[0]["body"] == "Visa announced X on Monday. This looks strategic."
    assert out[0]["citations"] == [
        {"url": "https://a.com/1", "title": "A1", "cited_text": "Visa X"}
    ]
    # duplicate citation within a highlight is collapsed
    assert out[1]["citations"] == [
        {"url": "https://b.com/2", "title": "B2", "cited_text": "deal"}
    ]


def test_citations_are_not_leaked_across_highlights():
    out = dh.draft_weekly_highlights(client=FakeClient([resp(TWO_HIGHLIGHTS)]))
    assert all(c["url"] != "https://b.com/2" for c in out[0]["citations"])


def test_heading_split_across_text_blocks():
    blocks = [text("## Vi"), text("sa news\nBody.", [cite("https://a.com")])]
    out = dh.draft_weekly_highlights(client=FakeClient([resp(blocks)]))
    assert out[0]["title"] == "Visa news"
    assert out[0]["citations"][0]["url"] == "https://a.com"


def test_no_highlights_returns_empty_list():
    out = dh.draft_weekly_highlights(client=FakeClient([resp([text("Nothing found.")])]))
    assert out == []


def test_request_enables_web_search_and_states_date():
    client = FakeClient([resp(TWO_HIGHLIGHTS)])
    dh.draft_weekly_highlights(client=client, today=date(2026, 9, 29))
    call = client.calls[0]
    assert call["tools"][0]["type"].startswith("web_search_")
    assert "2026-09-29" in call["messages"][0]["content"]


def test_style_examples_included_in_prompt_when_given():
    client = FakeClient([resp(TWO_HIGHLIGHTS)])
    dh.draft_weekly_highlights(client=client, style_examples="EXAMPLE-STYLE-TEXT")
    assert "EXAMPLE-STYLE-TEXT" in client.calls[0]["messages"][0]["content"]


def test_pause_turn_is_resumed_and_content_merged():
    first = resp([text("## Visa launches X\n")], stop_reason="pause_turn")
    second = resp([text("Visa did X.", [cite("https://a.com")])])
    client = FakeClient([first, second])
    out = dh.draft_weekly_highlights(client=client)
    assert len(client.calls) == 2
    assert client.calls[1]["messages"][-1]["role"] == "assistant"
    assert out[0]["title"] == "Visa launches X"
    assert out[0]["citations"][0]["url"] == "https://a.com"


def test_pause_turn_loop_is_bounded():
    paused = [resp([text("x")], stop_reason="pause_turn") for _ in range(10)]
    client = FakeClient(paused)
    dh.draft_weekly_highlights(client=client)
    assert len(client.calls) == dh.MAX_CONTINUATIONS + 1


def test_api_error_propagates():
    client = FakeClient([])
    client.messages = NS(create=lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        dh.draft_weekly_highlights(client=client)
