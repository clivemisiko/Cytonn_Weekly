"""The local providers' development-only speed settings (httpx mocked; no Ollama, no network).

fixtures/local_provider_requests_before.json holds the Exa and Ollama requests the two local
providers built before the settings existed, captured from that code, with the inputs that
produced them.  With no variable set the providers must still build exactly those requests.
"""

import json
import logging
import re
from datetime import date
from pathlib import Path

import httpx
import pytest

from cytonn_weekly.digital_payments.providers import local_provider as lp
from cytonn_weekly.narrative.base import NarrativeBrief
from cytonn_weekly.narrative.local_provider import LocalNarrativeProvider

BEFORE = json.loads((Path(__file__).parent / "fixtures" / "local_provider_requests_before.json").read_text("ascii"))
INPUTS = BEFORE["inputs"]
START, TODAY = date.fromisoformat(INPUTS["start"]), date.fromisoformat(INPUTS["today"])
BRIEF = NarrativeBrief(**{**INPUTS["brief"], "words": tuple(INPUTS["brief"]["words"]),
                          "preferred_domains": tuple(INPUTS["brief"]["preferred_domains"])})
NO = {"is_genuine_announcement": False, "reasoning": "none", "headline": "", "paragraph": "", "claims": []}
LOGGER = lp.logger.name

MAX_RESULTS = "CYTONN_LOCAL_MAX_SEARCH_RESULTS"
RESULT_CHARS = "CYTONN_LOCAL_RESULT_CHARS"
NUM_THREAD = "CYTONN_LOCAL_NUM_THREAD"
NUM_PREDICT = "CYTONN_LOCAL_NUM_PREDICT"
PRESET = {MAX_RESULTS: "2", RESULT_CHARS: "1500", NUM_THREAD: "8", NUM_PREDICT: "1400"}

# variable, settings field, today's default, a valid value, one below the minimum, one above the maximum
CASES = [
    (MAX_RESULTS, "max_search_results", 5, 2, 0, 6),
    (RESULT_CHARS, "result_chars", None, 1500, 499, 3001),
    (NUM_THREAD, "num_thread", None, 8, 0, 17),
    (NUM_PREDICT, "num_predict", 2048, 1400, 1023, 4097),
]


class Backend:
    """Fake Exa + Ollama: every search returns ``results``; ``llm`` is the model's replies in order."""

    def __init__(self, results=None, llm=()):
        self.results = INPUTS["results"] if results is None else results
        self.llm = list(llm)
        self.exa, self.chat = [], []

    def __call__(self, request):
        url = str(request.url)
        if url.endswith("/api/tags"):
            return httpx.Response(200, json={"models": [{"name": "phi4-mini:latest"}]})
        body = json.loads(request.content)
        if "exa.ai" in url:
            self.exa.append(body)
            return httpx.Response(200, json={"results": self.results})
        self.chat.append(body)
        reply = self.llm.pop(0) if self.llm else (NO if "format" in body else "Outlook text.")
        return httpx.Response(200, json={"message": {"content": reply if isinstance(reply, str) else json.dumps(reply)}})


def make(cls, backend, **kw):
    return cls(exa_api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(backend)), **kw)


def run_digital_payments(**kw):
    b = Backend()
    p = make(lp.LocalProvider, b, **kw)
    p.find_highlight(INPUTS["company"], INPUTS["ir_domain"], start=START, end=TODAY, today=TODAY)
    p.draft_outlook(INPUTS["table_stats"], INPUTS["highlights"])
    return b


def run_narrative(**kw):
    b = Backend()
    make(LocalNarrativeProvider, b, **kw).draft_piece(BRIEF, start=START, end=TODAY, today=TODAY)
    return b


def result_blocks(chat):
    """The search results one chat request shows the model, as (title, url, text)."""
    return re.findall(r"\[Result \d+\]\nTitle: (.*)\nURL: (.*)\nPublished: .*\nText: (.*)", chat["messages"][1]["content"])


# --- reading the four variables -------------------------------------------------------

def test_no_variable_set_gives_todays_values():
    s = lp.read_local_settings({})
    assert s == lp.LocalSettings() == lp.LocalSettings(5, None, None, 2048)
    assert (lp.NUM_RESULTS, lp.CONTEXT_CHARS_PER_RESULT, lp.NUM_PREDICT) == (5, 3000, 2048)


@pytest.mark.parametrize("var,field,default,valid,low,high", CASES)
def test_unset_gives_the_default(var, field, default, valid, low, high, monkeypatch, caplog):
    monkeypatch.delenv(var, raising=False)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert getattr(lp.read_local_settings(), field) == default
    assert caplog.records == []


@pytest.mark.parametrize("var,field,default,valid,low,high", CASES)
def test_a_valid_value_is_used(var, field, default, valid, low, high, monkeypatch, caplog):
    monkeypatch.setenv(var, f" {valid} ")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        s = lp.read_local_settings()
    assert getattr(s, field) == valid and caplog.records == []
    others = {c[1]: c[2] for c in CASES if c[0] != var}
    assert {name: getattr(s, name) for name in others} == others


@pytest.mark.parametrize("blank", ["", " ", " \t "])
@pytest.mark.parametrize("var,field,default,valid,low,high", CASES)
def test_empty_or_blank_gives_the_default_without_a_warning(var, field, default, valid, low, high, blank,
                                                             monkeypatch, caplog):
    monkeypatch.setenv(var, blank)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert getattr(lp.read_local_settings(), field) == default
    assert caplog.records == []


@pytest.mark.parametrize("bad", ["fast", "2.5", "1e3", "8 threads"])
@pytest.mark.parametrize("var,field,default,valid,low,high", CASES)
def test_a_non_integer_gives_the_default_and_one_warning(var, field, default, valid, low, high, bad,
                                                         monkeypatch, caplog):
    monkeypatch.setenv(var, bad)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert getattr(lp.read_local_settings(), field) == default
    assert len(caplog.records) == 1 and var in caplog.text


@pytest.mark.parametrize("which", ["low", "high", "negative"])
@pytest.mark.parametrize("var,field,default,valid,low,high", CASES)
def test_out_of_range_gives_the_default_and_one_warning_naming_the_range(var, field, default, valid, low, high,
                                                                         which, monkeypatch, caplog):
    monkeypatch.setenv(var, str({"low": low, "high": high, "negative": -1}[which]))
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert getattr(lp.read_local_settings(), field) == default  # the default, not the nearest limit
    assert len(caplog.records) == 1
    assert var in caplog.text and f"from {low + 1} to {high - 1}" in caplog.text


def test_the_limits_are_in_one_table_and_num_ctx_is_not_among_them():
    assert [(var, low, high) for _, var, low, high, _ in lp._SETTING_LIMITS] == [
        (MAX_RESULTS, 1, 5), (RESULT_CHARS, 500, 3000), (NUM_THREAD, 1, 16), (NUM_PREDICT, 1024, 4096)]


def test_num_predict_700_is_rejected(monkeypatch, caplog):
    # 700 truncates Markets Review briefs (replies reached 949 tokens), so it is out of reach.
    monkeypatch.setenv(NUM_PREDICT, "700")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        b = run_narrative()
    assert [c["options"]["num_predict"] for c in b.chat] == [2048, 2048]
    assert sum(NUM_PREDICT in r.getMessage() for r in caplog.records) == 1


def test_one_invalid_value_does_not_disturb_the_others(monkeypatch, caplog):
    for var, value in {**PRESET, NUM_THREAD: "many"}.items():
        monkeypatch.setenv(var, value)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert lp.read_local_settings() == lp.LocalSettings(2, 1500, None, 1400)
    assert len(caplog.records) == 1


# --- the requests with nothing set are the requests from before --------------------------

def test_digital_payments_requests_are_identical_to_before_the_settings():
    b = run_digital_payments()
    assert len(b.chat) == 3  # IR results, web results, outlook
    assert {"exa": b.exa, "chat": b.chat} == BEFORE["digital_payments"]


def test_narrative_requests_are_identical_to_before_the_settings():
    b = run_narrative()
    assert len(b.chat) == 2
    assert {"exa": b.exa, "chat": b.chat} == BEFORE["narrative"]


@pytest.mark.parametrize("blank", ["", "  "])
def test_requests_are_identical_when_every_variable_is_empty(blank, monkeypatch):
    for var in PRESET:  # what docker-compose.yml passes for a variable that is not set
        monkeypatch.setenv(var, blank)
    b, n = run_digital_payments(), run_narrative()
    assert {"exa": b.exa, "chat": b.chat} == BEFORE["digital_payments"]
    assert {"exa": n.exa, "chat": n.chat} == BEFORE["narrative"]


def test_before_requests_carry_no_thread_or_keep_alive_setting():
    for chat in BEFORE["digital_payments"]["chat"] + BEFORE["narrative"]["chat"]:
        assert chat["options"] == {"temperature": 0, "num_ctx": 8192, "num_predict": 2048}
        assert "keep_alive" not in chat


# --- the settings in the request --------------------------------------------------------

@pytest.mark.parametrize("run", [run_digital_payments, run_narrative])
def test_the_preset_reaches_the_model_request_and_not_the_search(run, monkeypatch):
    for var, value in PRESET.items():
        monkeypatch.setenv(var, value)
    b = run()
    for chat in b.chat:
        assert chat["options"] == {"temperature": 0, "num_ctx": 8192, "num_predict": 1400, "num_thread": 8}
        assert "keep_alive" not in chat
    for chat in (c for c in b.chat if "format" in c):
        assert len(result_blocks(chat)) == 2
    # The search itself is unchanged, so the Exa cache is the same whatever the settings.
    assert b.exa == BEFORE["digital_payments" if run is run_digital_payments else "narrative"]["exa"]


@pytest.mark.parametrize("run", [run_digital_payments, run_narrative])
@pytest.mark.parametrize("env", [{}, PRESET, {"CYTONN_LOCAL_NUM_CTX": "4096", "CYTONN_NUM_CTX": "4096",
                                              "OLLAMA_NUM_CTX": "4096", "OLLAMA_CONTEXT_LENGTH": "4096",
                                              "NUM_CTX": "4096"}])
def test_num_ctx_is_8192_whatever_the_environment(run, env, monkeypatch):
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    b = run()
    assert b.chat and all(chat["options"]["num_ctx"] == 8192 for chat in b.chat)
    assert not any("ctx" in var.lower() for _, var, *_ in lp._SETTING_LIMITS)


def test_a_per_model_override_still_wins_over_num_predict(monkeypatch):
    monkeypatch.setenv(NUM_PREDICT, "1400")
    b = Backend()
    b_models = httpx.MockTransport(lambda r: httpx.Response(200, json={"models": [{"name": "openbmb/minicpm5-2b"}]})
                                   if str(r.url).endswith("/api/tags") else b(r))
    p = lp.LocalProvider(model="openbmb/minicpm5-2b", exa_api_key="k", http_client=httpx.Client(transport=b_models))
    p.draft_outlook(INPUTS["table_stats"], INPUTS["highlights"])
    assert b.chat[0]["options"]["num_predict"] == 4096


def test_settings_are_read_when_the_provider_is_created(monkeypatch):
    monkeypatch.setenv(NUM_THREAD, "8")
    b = Backend()
    p = make(lp.LocalProvider, b)
    monkeypatch.setenv(NUM_THREAD, "2")
    p.draft_outlook(INPUTS["table_stats"], INPUTS["highlights"])
    assert b.chat[0]["options"]["num_thread"] == 8


# --- trimming the search results -------------------------------------------------------

def provider_with(monkeypatch, **env):
    for var, value in env.items():
        monkeypatch.setenv(var, str(value))
    return make(lp.LocalProvider, Backend())


def test_trimming_does_nothing_when_no_setting_is_set(monkeypatch):
    p = provider_with(monkeypatch)
    results = INPUTS["results"]
    assert p._trim_results(results) is results
    long = [{"url": "u", "title": "t", "text": "word " * 5000}] * 9  # more and longer than Exa returns today
    assert p._trim_results(long) is long


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5])
def test_trimming_never_returns_more_results_than_the_setting(n, monkeypatch):
    p = provider_with(monkeypatch, **{MAX_RESULTS: n})
    kept = p._trim_results(INPUTS["results"])
    assert kept == INPUTS["results"][:n]  # the first n, in order, text untouched
    assert len(p._trim_results(INPUTS["results"][:1])) == 1


def test_trimming_keeps_title_url_and_date_and_leaves_the_input_alone(monkeypatch):
    p = provider_with(monkeypatch, **{RESULT_CHARS: 500})
    results = json.loads(json.dumps(INPUTS["results"]))
    kept = p._trim_results(results)
    assert results == INPUTS["results"]
    assert len(kept) == 5
    for before, after in zip(results, kept):
        assert {k: v for k, v in after.items() if k != "text"} == {k: v for k, v in before.items() if k != "text"}
        assert 0 < len(after["text"]) <= 500
        assert " ".join(before["text"].split()).startswith(after["text"])


def test_a_trimmed_result_still_validates_citations_and_a_dropped_one_does_not(monkeypatch):
    for var, value in PRESET.items():
        monkeypatch.setenv(var, value)
    shown, dropped = INPUTS["results"][0]["url"], INPUTS["results"][4]["url"]
    body = " ".join(f"During the week, PayPal said [volume]({shown}) rose and [more]({dropped}) came;".split()
                    + ["word"] * 100)
    reply = {"is_genuine_announcement": True, "reasoning": "release", "headline": "PayPal Volume Rises",
             "paragraph": body, "claims": [{"claim": "volume rose", "url": shown}, {"claim": "more", "url": dropped}]}
    b = Backend(llm=[reply])
    res = make(lp.LocalProvider, b).find_highlight("PayPal", "investor.pypl.com", start=START, end=TODAY, today=TODAY)
    assert [(title, url) for title, url, _ in result_blocks(b.chat[0])] == [
        (r["title"], r["url"]) for r in INPUTS["results"][:2]]
    assert res.claims == [{"text": "volume rose", "url": shown, "title": "PayPal release 1", "cited_text": ""}]
    assert res.links == [{"anchor": "volume", "url": shown, "page_age": "2026-09-21"}]
    assert dropped not in res.paragraph_md and any(dropped in w for w in res.warnings)


def test_truncate_cuts_at_a_word_boundary():
    text = "alpha beta gamma delta"
    assert lp.truncate_text(text, 12) == "alpha beta"  # not "alpha beta g"
    assert lp.truncate_text(text, 16) == "alpha beta gamma"
    assert lp.truncate_text(text, 100) == text
    assert lp.truncate_text("  alpha \n\n beta\tgamma ", 10) == "alpha beta"


def test_truncate_never_splits_a_number():
    assert lp.truncate_text("revenue rose to 1,234,567.8 in the year", 20) == "revenue rose to"
    assert lp.truncate_text("growth of 12.5% was recorded", 12) == "growth of"
    # A figure written with spaces is dropped whole, not kept in part.
    assert lp.truncate_text("with 1 200 000 merchants", 10) == "with"
    assert lp.truncate_text("with 1 200 000 merchants", 14) == "with 1 200 000"
    assert lp.truncate_text("paid KES 5 bn in 2026 12 times", 21) == "paid KES 5 bn in"
    assert lp.truncate_text("1 200 000", 5) == ""


@pytest.mark.parametrize("limit", range(500, 3001, 137))
def test_truncate_on_real_shaped_text_never_ends_inside_a_figure(limit):
    for r in INPUTS["results"]:
        full = " ".join(r["text"].split())
        out = lp.truncate_text(r["text"], limit)
        assert len(out) <= limit and full.startswith(out)
        if len(out) < len(full):
            assert full[len(out)] == " "  # cut between words
            assert not (out[-1].isdigit() and full[len(out) + 1].isdigit())  # and not inside "10 000"


# --- the one log line ------------------------------------------------------------------

def settings_lines(caplog):
    return [r for r in caplog.records if r.getMessage().startswith("local provider settings")]


@pytest.mark.parametrize("cls", [lp.LocalProvider, LocalNarrativeProvider])
def test_effective_settings_are_logged_once_per_provider_at_first_use(cls, monkeypatch, caplog):
    for var, value in PRESET.items():
        monkeypatch.setenv(var, value)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        p = make(cls, Backend())
        assert settings_lines(caplog) == []  # not at creation
        for _ in range(3):
            p.draft_outlook(INPUTS["table_stats"], INPUTS["highlights"])
        assert len(settings_lines(caplog)) == 1
        make(cls, Backend()).draft_outlook(INPUTS["table_stats"], INPUTS["highlights"])
        assert len(settings_lines(caplog)) == 2  # once per instance
    line = settings_lines(caplog)[0]
    assert line.levelno == logging.WARNING  # a run off the defaults says so without any logging setup
    for part in ("max_search_results=2", "result_chars=1500", "num_thread=8", "num_predict=1400", "num_ctx=8192"):
        assert part in line.getMessage()


def test_default_settings_are_logged_at_info_and_stay_out_of_the_draft(caplog):
    reply = {"is_genuine_announcement": True, "reasoning": "release", "headline": "PayPal Volume Rises",
             "paragraph": " ".join("During the week, PayPal said volume rose;".split() + ["word"] * 100),
             "claims": [{"claim": "volume rose", "url": INPUTS["results"][0]["url"]}]}
    b = Backend(llm=[reply])
    with caplog.at_level(logging.INFO, logger=LOGGER):
        p = make(lp.LocalProvider, b)
        res = p.find_highlight("PayPal", "investor.pypl.com", start=START, end=TODAY, today=TODAY)
        outlook = p.draft_outlook(INPUTS["table_stats"], INPUTS["highlights"])
    (line,) = settings_lines(caplog)
    assert line.levelno == logging.INFO
    for part in ("max_search_results=5", "result_chars=unchanged (3000)", "num_thread=Ollama default",
                 "num_predict=2048", "num_ctx=8192"):
        assert part in line.getMessage()
    content = json.dumps([res.__dict__, outlook.__dict__], default=str)
    assert "local provider settings" not in content and "num_predict" not in content
