import ast
import inspect
from datetime import date
from types import SimpleNamespace as NS

import pytest

from cytonn_weekly.common import http
from cytonn_weekly.common import sources as src
from cytonn_weekly.common.checks import check_sourced_claim, normalise_quote
from cytonn_weekly.common.review import _claim_context as block_claim_context
from cytonn_weekly.digital_payments.coordinator_review import SOURCE_KEYS
from cytonn_weekly.digital_payments.coordinator_review import _claim_context as dp_claim_context
from cytonn_weekly.narrative import bedrock_provider as bp
from cytonn_weekly.narrative.base import NarrativeBrief
from tests.section_helpers import TODAY, FakeNarrativeProvider, real_estate_review

SOURCE = ("The Central Bank of Kenya said private sector credit grew by 8.75% in the year to September 2026, "
          "compared with 6.1% a year earlier.\n\nThe “mortgage” book rose 4.2% – the fastest pace in two years. "
          "Loans of KSh 1,250 million were approved.")
TEXTS = {"s1": SOURCE}
URL = "https://www.centralbank.go.ke/press/x"
BRIEF = NarrativeBrief(id="lending", section="Real Estate", label="Mortgage lending", focus="loans",
                       preferred_domains=("centralbank.go.ke",), words=(1, 400))
START = date(2026, 9, 26)
QUOTE = "private sector credit grew by 8.75% in the year to September 2026"


# --- the checker ---------------------------------------------------------------------------------------------------------

def why(text, quote, sid="s1"):
    return check_sourced_claim(text, quote, sid, TEXTS)


def test_a_claim_quoted_word_for_word_with_its_figures_in_the_quote_holds():
    assert why("Private sector credit grew 8.75% in the year to September 2026.", QUOTE) is None


def test_the_quote_may_differ_only_in_whitespace_quote_marks_dashes_and_non_breaking_spaces():
    assert normalise_quote("a  b\n\tc ‘x’ “y” – — − ‑") == "a b c 'x' \"y\" - - - -"
    assert why("The mortgage book rose 4.2%.", 'The "mortgage"   book rose 4.2% - the fastest pace') is None
    assert why("The mortgage book rose 4.2%.", "The “mortgage” book rose 4.2% – the fastest pace") is None
    assert why("Loans of 1,250 million were approved.", "Loans of KSh 1,250 million were approved") is None
    assert why("Credit grew 8.75%.", "private  sector\ncredit grew by 8.75%") is None


@pytest.mark.parametrize("quote", [
    "private sector credit grew by 8.7% in the year to September 2026",        # a figure changed
    "private sector credit rose by 8.75% in the year to September 2026",       # one word changed
    "Private sector credit grew by 8.75% in the year to September 2026",       # case is not folded
    "private sector credit grew by 8.75 in the year to September 2026",        # a character dropped
    "private sector credit grew by 8.75%, in the year to September 2026",      # punctuation added
    "private sector credit grew by 8.75% in the year to Sept 2026",            # a word shortened
    "credit grew by 8.75% in the year to September 2026 and 6.1% a year earlier, up",  # joined from the page and beyond
    "grew by 8.75% ... September 2026",                                         # an ellipsis is not a quote
])
def test_a_near_miss_quote_fails(quote):
    assert "is not in the saved text of source s1 word for word" in why("Credit grew 8.75%.", quote)


def test_a_quote_may_not_be_joined_from_two_places_in_the_source():
    joined = 'grew by 8.75% in the year to September 2026, compared with 6.1% a year earlier. The "mortgage" book rose 4.2%'
    assert why("Credit grew 8.75%.", joined) is None          # one run of the text, even across a paragraph break
    skipping = "compared with 6.1% a year earlier. Loans of KSh 1,250 million were approved"
    assert "word for word" in why("Loans rose.", skipping)    # skips the sentence between them


def test_a_claim_that_names_no_source_or_an_unsupplied_one_fails():
    assert why("Credit grew.", QUOTE, "") == "it names no source"
    assert why("Credit grew.", QUOTE, "  ") == "it names no source"
    assert why("Credit grew.", QUOTE, "zz") == "source zz is not one of the supplied sources"


def test_a_claim_with_no_quote_fails():
    assert why("Credit grew.", "") == "it gives no quote"
    assert why("Credit grew.", " \n ") == "it gives no quote"
    assert why("Credit grew.", None) == "it gives no quote"


def test_every_number_in_the_claim_must_be_in_the_quote():
    assert "figure(s) 9.5 are in the claim but not in its quote" in why("Credit grew 9.5% to September 2026.", QUOTE)
    assert "figure(s)" in why("Credit grew 8.75% in 2027.", "private sector credit grew by 8.75%")
    assert why("Credit grew 8.75%.", "private sector credit grew by 8.75%") is None


def test_a_number_matches_by_value_so_thousands_commas_do_not_matter_but_a_changed_digit_does():
    assert why("Loans of 1250 million were approved.", "Loans of KSh 1,250 million were approved") is None
    assert "figure(s)" in why("Loans of 1,520 million were approved.", "Loans of KSh 1,250 million were approved")


def test_a_claim_with_no_number_needs_no_number_in_its_quote():
    assert why("The mortgage book grew at its fastest pace.", "the fastest pace in two years") is None


# --- the provider, with the real store and a fake client ------------------------------------------------------------------

@pytest.fixture
def aws(monkeypatch):
    monkeypatch.setenv("CYTONN_LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "not a real key id")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "not a real secret")
    for name in ("BEDROCK_MODEL_ID", "AWS_DEFAULT_REGION", "AWS_SESSION_TOKEN", "AWS_BEARER_TOKEN_BEDROCK", "EXA_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(bp, "boto3_installed", lambda: True)


class Client:
    """``client.messages.create`` answering with the given claims; remembers each call."""

    def __init__(self, claims, paragraph="Private sector credit grew 8.75% in the year to September 2026, as the CBK said.",
                 genuine=True):
        self.calls, self.messages = [], self
        self.reply = {"is_genuine_announcement": genuine, "reasoning": "x", "headline": "Credit growth",
                      "paragraph": paragraph, "claims": claims}

    def create(self, **kw):
        self.calls.append(kw)
        return NS(stop_reason="tool_use", content=[NS(type="tool_use", input=self.reply)])


@pytest.fixture
def saved(tmp_path):
    """The one pasted page for Mortgage lending in the week of TODAY, in the real store (conftest points it at tmp_path)."""
    return src.from_paste(URL, "2026-09-30", SOURCE, "Mortgage lending", TODAY, title="CBK statement")


def draft(client, brief=BRIEF):
    return bp.BedrockNarrativeProvider(client=client).draft_piece(brief, start=START, end=TODAY, today=TODAY)


def claim(sid, text="Private sector credit grew 8.75%.", quote=QUOTE):
    return {"text": text, "quote": quote, "source_id": sid}


def test_the_seam_reads_the_saved_sources_by_subject_and_week(saved):
    found = bp.sources_for("Mortgage lending", TODAY)
    assert [(r["id"], r["url"], r["title"], r["publishedDate"], r["origin"], r["sha256"], r["host"]) for r in found] == [
        (saved.id, URL, "CBK statement", "2026-09-30", "pasted", saved.sha256, "www.centralbank.go.ke")]
    assert found[0]["text"] == SOURCE
    assert bp.sources_for("Affordable housing", TODAY) == [] and bp.sources_for("Mortgage lending", date(2026, 10, 9)) == []


def test_a_verified_claim_keeps_its_quote_as_cited_text_with_the_source_facts(aws, saved):
    res = draft(Client([claim(saved.id)]))
    assert not res.no_story
    assert res.claims == [{"text": "Private sector credit grew 8.75%.", "url": URL, "title": "CBK statement",
                           "cited_text": QUOTE, "source_id": saved.id, "sha256": saved.sha256,
                           "fetched_at": saved.fetched_at, "host": "www.centralbank.go.ke", "published_date": "2026-09-30",
                           "origin": "pasted", "source_flags": []}]


def test_a_quote_is_stored_as_the_model_gave_it_after_whitespace_is_collapsed_and_is_checked_against_the_saved_text(aws, saved):
    res = draft(Client([claim(saved.id, text="The mortgage book rose 4.2%.", quote='The  "mortgage"\nbook rose 4.2% - the fastest')]))
    assert res.claims[0]["cited_text"] == 'The "mortgage" book rose 4.2% - the fastest'


@pytest.mark.parametrize("bad,reason", [
    (claim("{sid}", quote=QUOTE.replace("8.75", "8.7")), "its quote is not in the saved text of source {sid} word for word"),
    (claim("{sid}", text="Private sector credit grew 9.9%."), "figure(s) 9.9 are in the claim but not in its quote"),
    (claim("{sid}", quote=""), "it gives no quote"),
    (claim("", ), "it names no source"),
    (claim("deadbeef"), "source deadbeef is not one of the supplied sources"),
])
def test_a_claim_that_fails_is_dropped_with_a_warning_that_names_the_reason(aws, saved, bad, reason):
    bad = {k: v.format(sid=saved.id) if isinstance(v, str) else v for k, v in bad.items()}
    res = draft(Client([claim(saved.id), bad]))
    assert len(res.claims) == 1 and res.claims[0]["text"] == "Private sector credit grew 8.75%."
    warning = next(w for w in res.warnings if w.startswith("claim dropped, "))
    assert reason.format(sid=saved.id) in warning and bad["text"][:90] in warning
    assert "made up" not in warning and "invented" not in warning.lower()


def test_a_source_id_is_read_without_brackets_or_case(aws, saved):
    res = draft(Client([claim(f"[{saved.id.upper()}]")]))
    assert [c["source_id"] for c in res.claims] == [saved.id]


def test_a_piece_with_no_surviving_claim_is_unavailable_with_a_plain_sentence(aws, saved):
    res = draft(Client([claim(saved.id, quote="nothing like the page"), claim("deadbeef")]))
    assert res.no_story and res.reason == bp.NO_VERIFIED_CLAIMS and not res.claims and not res.paragraph_md
    joined = " ".join(res.draft_warnings)
    assert bp.NO_VERIFIED_CLAIMS in joined and joined.count("claim dropped, ") == 2
    assert "word for word" in joined and "not one of the supplied sources" in joined


def test_a_reply_with_no_claims_at_all_is_unavailable_too(aws, saved):
    res = draft(Client([]))
    assert res.no_story and res.reason == bp.NO_VERIFIED_CLAIMS


def test_a_draft_with_no_saved_source_makes_no_model_call_and_says_so(aws):
    client = Client([claim("x")])
    res = draft(client)
    assert res.no_story and res.reason == bp.NO_SOURCES and client.calls == []


def test_the_model_is_shown_the_numbered_saved_text_and_the_source_id_and_nothing_else_to_read(aws, saved):
    client = Client([claim(saved.id)])
    draft(client)
    call = client.calls[0]
    message = call["messages"][0]["content"]
    assert "[Source 1]" in message and f"Source id: {saved.id}" in message and SOURCE.split("\n")[0] in message
    assert "[Source 2]" not in message and call["tool_choice"]["name"] == "submit_draft"
    assert [t["name"] for t in call["tools"]] == ["submit_draft"]
    assert "word for word" in call["system"] and "exact URL" not in call["system"]
    assert "search results" not in call["system"]


def test_a_long_source_is_cut_for_the_model_with_a_warning_but_quotes_are_checked_against_the_whole_text(aws, tmp_path):
    tail = "The ratio of reserves to deposits fell to 31.4% by the end of the month."
    long_text = "Filler sentence about nothing in particular. " * 600 + tail
    one = src.from_paste(URL, "2026-09-30", long_text, "Mortgage lending", TODAY)
    client = Client([claim(one.id, text="Reserves to deposits fell to 31.4%.", quote="The ratio of reserves to deposits fell to 31.4% by the end of the month")])
    res = draft(client)
    assert any(f"only the first {bp.SOURCE_CHARS:,} characters of www.centralbank.go.ke were shown" in w
               for w in res.draft_warnings)
    assert len(client.calls[0]["messages"][0]["content"]) < len(long_text)
    assert [c["text"] for c in res.claims] == ["Reserves to deposits fell to 31.4%."]


def test_a_source_pasted_from_a_host_off_the_list_carries_its_flag_onto_the_claim(aws, tmp_path):
    one = src.from_paste("https://blog.example.com/post", "2026-09-30", SOURCE, "Mortgage lending", TODAY)
    res = draft(Client([claim(one.id)]))
    assert res.claims[0]["source_flags"] == ["host not on the approved list"] and res.claims[0]["host"] == "blog.example.com"


def test_two_sources_are_numbered_and_a_claim_may_cite_either(aws, saved):
    other = src.from_paste("https://www.knbs.or.ke/cpi", "2026-10-01", "Inflation was 4.6% in September 2026, KNBS said in a statement.",
                           "Mortgage lending", TODAY)
    client = Client([claim(saved.id), claim(other.id, text="Inflation was 4.6%.", quote="Inflation was 4.6% in September 2026")])
    res = draft(client)
    message = client.calls[0]["messages"][0]["content"]
    assert "[Source 1]" in message and "[Source 2]" in message
    assert {c["host"] for c in res.claims} == {"www.centralbank.go.ke", "www.knbs.or.ke"}


def test_a_claim_cannot_quote_a_source_saved_for_another_piece(aws, saved):
    elsewhere = src.from_paste("https://www.knbs.or.ke/cpi", "2026-10-01", "Inflation was 4.6% in September 2026, KNBS said in a statement.",
                               "Affordable housing", TODAY)
    res = draft(Client([claim(saved.id), claim(elsewhere.id, text="Inflation was 4.6%.", quote="Inflation was 4.6% in September 2026")]))
    assert len(res.claims) == 1 and any(f"source {elsewhere.id} is not one of the supplied sources" in w for w in res.warnings)


# --- the review ------------------------------------------------------------------------------------------------------------

def test_the_source_facts_are_in_a_claim_context_in_both_review_shapes_and_only_when_the_claim_has_them():
    plain = {"text": "t", "url": "u", "title": "T", "cited_text": "c", "ignored": 1}
    sourced = {**plain, "source_id": "s1", "sha256": "ab" * 32, "fetched_at": "2026-11-06T09:00:00+00:00",
               "host": "h.example", "published_date": "2026-09-30", "origin": "pasted", "source_flags": ["host not on the approved list"]}
    for fn in (block_claim_context, dp_claim_context):
        assert fn(plain) == {"text": "t", "url": "u", "title": "T", "cited_text": "c"}
        assert fn(sourced) == {k: sourced[k] for k in ("text", "url", "title", "cited_text") + SOURCE_KEYS}
    assert set(SOURCE_KEYS) == {"source_id", "sha256", "fetched_at", "host", "published_date", "origin", "source_flags"}


class SourcedProvider(FakeNarrativeProvider):
    """The fake provider, but each claim carries what a claim quoted from a supplied source carries."""

    def draft_piece(self, brief, *, start, end, today):
        res = super().draft_piece(brief, start=start, end=end, today=today)
        for c in res.claims:
            c.update(source_id="a1b2c3d4", sha256="f" * 64, fetched_at="2026-11-06T09:00:00+00:00", host="www.nse.co.ke",
                     published_date="2026-09-30", origin="pasted", source_flags=["host not on the approved list"])
        return res


def test_a_review_item_for_a_sourced_claim_shows_its_source_quote_host_date_hash_and_flag():
    review = real_estate_review(SourcedProvider())
    claim_items = [i for i in review.review_items if i.kind == "claim"]
    assert claim_items
    for item in claim_items:
        ctx = item.context
        assert (ctx["source_id"], ctx["host"], ctx["published_date"], ctx["origin"], ctx["sha256"]) == (
            "a1b2c3d4", "www.nse.co.ke", "2026-09-30", "pasted", "f" * 64)
        assert ctx["fetched_at"] == "2026-11-06T09:00:00+00:00" and ctx["source_flags"] == ["host not on the approved list"]
        assert ctx["cited_text"]                           # the verified quote is what check_claim compared the figures to


def test_a_claim_without_source_facts_has_none_in_its_review_item():
    review = real_estate_review(FakeNarrativeProvider())
    for item in (i for i in review.review_items if i.kind == "claim"):
        assert not set(SOURCE_KEYS) & set(item.context)


# --- nothing on the Bedrock path reaches out -----------------------------------------------------------------------------------

def test_a_bedrock_draft_makes_no_http_request_of_its_own(aws, saved, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the Bedrock path made an HTTP request")

    monkeypatch.setattr(http, "http_get_once", refuse)
    monkeypatch.setattr(http, "http_get", refuse)
    monkeypatch.setattr(http, "http_get_pdf", refuse)
    monkeypatch.setattr(src, "fetch_page", refuse)
    res = draft(Client([claim(saved.id)]))
    assert len(res.claims) == 1


def test_the_bedrock_module_does_not_import_the_fetcher_or_an_http_client():
    tree = ast.parse(inspect.getsource(bp))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update([node.module or ""] + [f"{node.module}.{a.name}" for a in node.names])
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
    assert not [n for n in names if {"http", "httpx", "httpx2", "requests", "urllib"} & set(n.split("."))], names
    assert "fetch_page" not in inspect.getsource(bp) and "http_get" not in inspect.getsource(bp)
    assert "cytonn_weekly.common.sources" in names
