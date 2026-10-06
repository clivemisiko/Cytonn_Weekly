"""The Focus topic length limit: one number (focus.review_run.MAX_TOPIC_CHARS), one judge (clean_topic).

The API used to carry its own limit (500) beside clean_topic's (200), so a topic the API
took could be refused by the pipeline.  Both draft routes now refuse or clean a topic
through clean_topic itself, before a draft is started.
"""

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly.focus import review_run as focus_run
from cytonn_weekly.focus.review_run import MAX_TOPIC_CHARS, clean_topic
from tests import section_helpers as sh

WORDS_300 = ("  Kenya's   public debt \n and the Eurobond buyback  " * 12)[:300]   # untidy whitespace, 300 characters


def words(n):
    """A topic of exactly ``n`` characters that is already clean (single spaces, no edge whitespace)."""
    return ("budget " * n)[:n - 1] + "x"


@pytest.fixture
def seen():
    return []


@pytest.fixture
def client(tmp_path, monkeypatch, seen):
    def build(topic, on_event=None):
        seen.append(topic)                       # the topic exactly as the API handed it to the builder
        return sh.focus_review(topic=topic, on_event=on_event)

    monkeypatch.setattr(focus_run, "build_focus_review", build)
    return TestClient(create_app(db_path=tmp_path / "app.db", load_dotenv=False))


def draft(client, topic):
    return client.post("/api/sections/focus/draft", json={"topic": topic})


def test_the_limit_is_500():
    assert MAX_TOPIC_CHARS == 500


def test_a_300_character_topic_is_accepted_by_both_and_cleaned_the_same(client, seen):
    assert len(WORDS_300) == 300
    cleaned = clean_topic(WORDS_300)
    assert cleaned == " ".join(WORDS_300.split()) and 200 < len(cleaned) < 300
    r = draft(client, WORDS_300)
    assert r.status_code == 200, r.text
    assert seen == [cleaned] and r.json()["section"]["topic"] == cleaned


def test_exactly_500_characters_is_accepted_by_both(client, seen):
    topic = words(500)
    assert len(topic) == 500 and clean_topic(topic) == topic
    r = draft(client, topic)
    assert r.status_code == 200, r.text
    assert seen == [topic] and r.json()["section"]["topic"] == topic


def test_501_characters_is_refused_by_both_in_the_same_words(client, seen):
    topic = words(501)
    with pytest.raises(ValueError) as exc:
        clean_topic(topic)
    assert str(exc.value) == "the topic is 501 characters; keep it under 500"
    r = draft(client, topic)
    assert r.status_code == 422 and r.json()["detail"] == str(exc.value)
    run = client.post("/api/runs", json={"section": "focus", "topic": topic})
    assert run.status_code == 422 and run.json()["detail"] == str(exc.value)
    assert seen == []                            # refused before any draft was started
    assert client.get("/api/sections").json()["drafting"] is None


def test_length_is_counted_after_whitespace_is_normalized_in_both(client, seen):
    padded = "  " + words(500).replace(" ", "   ") + "  "       # far over 500 raw, exactly 500 cleaned
    assert len(padded) > 600 and clean_topic(padded) == words(500)
    assert draft(client, padded).status_code == 200
    assert seen == [words(500)]


def test_a_200_character_topic_is_what_it_was_before(client, seen):
    topic = words(200)
    assert len(topic) == 200 and clean_topic(topic) == topic    # 200 was the old limit, and was accepted
    assert clean_topic("  " + topic.replace(" ", "  ") + " ") == topic
    r = draft(client, topic)
    assert r.status_code == 200 and seen == [topic] and r.json()["section"]["topic"] == topic


def test_blank_and_missing_topics_are_refused_as_before(client, seen):
    with pytest.raises(ValueError, match="needs a topic"):
        clean_topic("   ")
    for body in ({"topic": "   "}, {"topic": ""}, {}):
        r = client.post("/api/sections/focus/draft", json=body)
        assert r.status_code == 422 and r.json()["detail"] == "Focus of the Week needs a topic to draft"
    assert seen == []


def test_the_run_route_hands_the_builder_the_same_cleaned_topic(client, seen):
    import time

    run_id = client.post("/api/runs", json={"section": "focus", "topic": WORDS_300}).json()["run_id"]
    deadline = time.monotonic() + 20
    while client.get(f"/api/runs/{run_id}").json()["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "finished"
    assert seen == [clean_topic(WORDS_300)]
