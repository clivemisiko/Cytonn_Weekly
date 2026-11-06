from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly.common import sources as src
from cytonn_weekly.digital_payments import review_run
from cytonn_weekly.source_pieces import pieces_for
from tests.review_helpers import ROWS, TODAY, FakeProvider
from tests.test_runs_api import REAL_DP, Clock, GatedProvider, finished, start
from tests.test_sources import PARAGRAPH, PUBLIC, Getter, article, reply

PERIOD = "Week ending 2026-10-02"
FRIDAY = date(2026, 10, 2)
REAL_ESTATE = pieces_for("weekly", PERIOD, "real_estate")
SUBJECT = REAL_ESTATE[0].subject
PASTED = {"section": "real_estate", "subject": SUBJECT, "period": PERIOD, "url": "https://www.centralbank.go.ke/press/x",
          "date": "2026-09-30", "text": PARAGRAPH * 2, "title": "CBK statement"}


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def fetched():
    """What the fake fetch was asked: it runs the real fetch_page over a fake http_get, so no site is reached."""
    return Getter(reply(article()))


@pytest.fixture
def client(tmp_path, clock, fetched):
    def fake_fetch(url, subject, end, root=None):
        return src.fetch_page(url, subject, end, http_get=fetched, resolve=lambda host: PUBLIC, root=root)

    return TestClient(create_app(db_path=tmp_path / "app.db", load_dotenv=False, clock=clock, fetch_source=fake_fetch))


def post(client, **over):
    return client.post("/api/sources", json={**PASTED, **over})


def listing(client, **params):
    return client.get("/api/sources", params={"section": "real_estate", "period": PERIOD, **params})


# --- the listing -----------------------------------------------------------------------------------------------------------

def test_the_listing_names_each_piece_with_its_day_and_week_and_no_sources_yet(client):
    body = listing(client).json()
    assert body["section"] == "real_estate" and body["uses_sources"] is True and body["title"] == "Real Estate"
    assert [p["subject"] for p in body["pieces"]] == [p.subject for p in REAL_ESTATE] and len(REAL_ESTATE) >= 3
    assert all(p["sources"] == [] and p["end"] == "2026-10-02" and p["week_end"] == "2026-10-02" for p in body["pieces"])
    assert body["approved_sites"] == list(src.APPROVED_SITES)


def test_the_listing_of_a_section_that_is_not_written_from_sources_says_so(client):
    body = client.get("/api/sources", params={"section": "company_updates"}).json()
    assert body["uses_sources"] is False and body["pieces"] == [] and body["approved_sites"] == list(src.APPROVED_SITES)


def test_an_unknown_section_is_404_and_a_period_that_does_not_fit_is_422(client):
    assert client.get("/api/sources", params={"section": "nope"}).status_code == 404
    bad = client.get("/api/sources", params={"section": "equities", "report_type": "quarterly", "period": "Q2'2026"})
    assert bad.status_code == 422 and "Q2" in bad.json()["detail"]


def test_a_markets_review_lists_its_own_pieces_filed_under_the_period_end(client):
    body = client.get("/api/sources", params={"section": "kenya_macro", "report_type": "quarterly", "period": "Q3'2026"}).json()
    assert body["pieces"] and {p["end"] for p in body["pieces"]} == {"2026-09-30"}
    assert {p["week_end"] for p in body["pieces"]} == {"2026-09-25"}     # the Friday on or before the quarter's last day


@pytest.fixture
def another_day(monkeypatch):
    """The route's own 'today' is a Monday that is none of the Fridays asked for, so a period that was dropped would show."""
    class Monday(date):
        @classmethod
        def today(cls):
            return date(2026, 11, 9)

    monkeypatch.setattr("api.main.date", Monday)


@pytest.mark.parametrize("subject", [None, SUBJECT])
def test_a_weekly_listing_keeps_the_period_it_was_asked_for(client, another_day, subject):
    extra = {"subject": subject} if subject else {}
    pieces = listing(client, **extra).json()["pieces"]
    assert [p["subject"] for p in pieces] == ([SUBJECT] if subject else [p.subject for p in REAL_ESTATE])
    assert {(p["end"], p["week_end"]) for p in pieces} == {("2026-10-02", "2026-10-02")}


@pytest.mark.parametrize("subject", [None, "Inflation"])
def test_a_quarterly_listing_keeps_the_period_it_was_asked_for(client, another_day, subject):
    extra = {"subject": subject} if subject else {}
    res = client.get("/api/sources", params={"section": "kenya_macro", "report_type": "quarterly", "period": "Q3'2026", **extra})
    assert res.status_code == 200
    pieces = res.json()["pieces"]
    assert [p["subject"] for p in pieces] == (["Inflation"] if subject else [p["subject"] for p in pieces]) and len(pieces) >= 1
    assert {(p["end"], p["week_end"]) for p in pieces} == {("2026-09-30", "2026-09-25")}


def test_digital_payments_lists_its_five_companies(client):
    body = client.get("/api/sources", params={"section": "digital_payments", "period": PERIOD}).json()
    assert [p["subject"] for p in body["pieces"]] == ["Visa", "Mastercard", "American Express", "PayPal", "Circle"]


def test_a_focus_is_listed_by_its_typed_titles_without_the_closing_part(client):
    titles = "Overview of the topic\nMarket performance\nRecommendations and Conclusion"
    body = client.get("/api/sources", params={"section": "focus", "period": PERIOD, "sections": titles}).json()
    assert [p["subject"] for p in body["pieces"]] == ["Overview of the topic", "Market performance"]
    assert client.get("/api/sources", params={"section": "focus", "period": PERIOD}).json()["pieces"] == []


# --- adding a source -------------------------------------------------------------------------------------------------------

def test_a_pasted_source_is_kept_listed_and_its_text_is_served_exactly(client):
    r = post(client)
    assert r.status_code == 200, r.text
    body = r.json()
    one = body["source"]
    assert (one["origin"], one["host"], one["published_date"], one["title"], one["flags"]) == (
        "pasted", "www.centralbank.go.ke", "2026-09-30", "CBK statement", [])
    assert "text" not in one and one["chars"] == len(PARAGRAPH * 2) and len(one["sha256"]) == 64
    assert body["subject"] == SUBJECT and body["week_end"] == "2026-10-02"
    assert [s["id"] for s in body["sources"]] == [one["id"]]
    again = listing(client, subject=SUBJECT).json()
    assert [p["subject"] for p in again["pieces"]] == [SUBJECT] and again["pieces"][0]["sources"][0]["id"] == one["id"]
    others = [p for p in listing(client).json()["pieces"] if p["subject"] != SUBJECT]
    assert others and all(p["sources"] == [] for p in others)
    text = client.get(f"/api/sources/{one['id']}/text")
    assert text.status_code == 200 and text.text == PARAGRAPH * 2
    assert text.headers["content-type"].startswith("text/plain") and text.headers["cache-control"] == "no-store"
    assert text.headers["x-content-type-options"] == "nosniff"


def test_a_pasted_source_from_a_host_off_the_list_carries_the_flag(client):
    one = post(client, url="https://blog.example.com/p").json()["source"]
    assert one["flags"] == ["host not on the approved list"]


@pytest.mark.parametrize("over,word", [
    ({"date": None}, "date of the page"), ({"date": "2026-9-30x"}, "not a date"),
    ({"url": "https://x.com/a/status/1"}, "social media"), ({"url": "centralbank.go.ke/x"}, "not a web address"),
    ({"text": "  ", "date": "2026-09-30", "url": "https://www.centralbank.go.ke/x"}, None),
])
def test_a_paste_that_breaks_a_rule_is_422_with_a_plain_sentence_and_keeps_nothing(client, over, word):
    r = post(client, **over)
    if word is None:       # blank text and a date is read as a paste with no text, never as a fetch
        assert r.status_code == 422 and "Paste the text" in r.json()["detail"]
    else:
        assert r.status_code == 422 and word in r.json()["detail"]
    assert "Traceback" not in r.text and all(p["sources"] == [] for p in listing(client).json()["pieces"])


def test_a_url_alone_is_fetched_and_kept_as_fetched(client, fetched):
    r = post(client, url="https://www.centralbank.go.ke/press/2026-10-01", date=None, text=None, title=None)
    assert r.status_code == 200, r.text
    one = r.json()["source"]
    assert one["origin"] == "fetched" and one["host"] == "www.centralbank.go.ke" and one["title"] == "Credit report"
    assert fetched.asked == ["https://www.centralbank.go.ke/press/2026-10-01"]
    assert client.get(f"/api/sources/{one['id']}/text").text == src.get(one["id"]).text


@pytest.mark.parametrize("url,word", [("https://blog.example.com/post", "not on the approved list"),
                                      ("https://x.com/CBK/status/1", "social media"),
                                      ("http://www.centralbank.go.ke/x", "Only https")])
def test_a_refused_fetch_is_422_with_the_sentence_and_nothing_was_asked(client, fetched, url, word):
    r = post(client, url=url, date=None, text=None)
    assert r.status_code == 422 and word in r.json()["detail"] and fetched.asked == []


def test_a_fetch_that_fails_shows_the_sentence_and_keeps_nothing(client, fetched):
    fetched.replies = [reply(status=404)]
    r = post(client, url="https://www.centralbank.go.ke/gone", date=None, text=None)
    assert r.status_code == 422 and "No page was found" in r.json()["detail"]
    assert all(p["sources"] == [] for p in listing(client).json()["pieces"])


def test_a_subject_that_is_not_a_piece_of_the_section_is_422_naming_the_pieces(client):
    r = post(client, subject="Cryptocurrency")
    assert r.status_code == 422 and "is not a piece of Real Estate" in r.json()["detail"] and SUBJECT in r.json()["detail"]


def test_the_subject_may_differ_in_case_and_spacing(client):
    r = post(client, subject=f"  {SUBJECT.upper()} ")
    assert r.status_code == 200 and r.json()["subject"] == SUBJECT


def test_a_section_that_calls_no_provider_or_does_not_exist_takes_no_sources(client):
    assert post(client, section="company_updates").status_code == 422
    assert "not written from sources" in post(client, section="company_updates").json()["detail"]
    assert post(client, section="nope").status_code == 404


def test_a_focus_source_is_for_a_typed_title_and_never_for_the_closing_part(client):
    titles = "Overview of the topic\nMarket performance\nRecommendations and Conclusion"
    ok = post(client, section="focus", subject="Market performance", sections=titles)
    assert ok.status_code == 200 and ok.json()["subject"] == "Market performance"
    closing = post(client, section="focus", subject="Recommendations and Conclusion", sections=titles)
    assert closing.status_code == 422 and "closing part" in closing.json()["detail"]
    other = post(client, section="focus", subject="Something else", sections=titles)
    assert other.status_code == 422 and "not a section title you typed" in other.json()["detail"]


def test_sources_of_two_pieces_stay_apart(client):
    first, second = REAL_ESTATE[0].subject, REAL_ESTATE[1].subject
    a = post(client, subject=first).json()["source"]
    b = post(client, subject=second, text=PARAGRAPH * 3).json()["source"]
    assert [s["id"] for s in listing(client, subject=first).json()["pieces"][0]["sources"]] == [a["id"]]
    assert [s["id"] for s in listing(client, subject=second).json()["pieces"][0]["sources"]] == [b["id"]]


# --- the text and removing -------------------------------------------------------------------------------------------------

def test_a_removed_source_is_gone_from_the_list_and_the_text_route_and_cannot_be_removed_twice(client):
    one = post(client).json()["source"]
    assert client.delete(f"/api/sources/{one['id']}").json() == {"removed": one["id"]}
    assert listing(client, subject=SUBJECT).json()["pieces"][0]["sources"] == []
    assert client.get(f"/api/sources/{one['id']}/text").status_code == 404
    assert client.delete(f"/api/sources/{one['id']}").status_code == 404


def test_the_text_of_an_unknown_source_is_404(client):
    r = client.get("/api/sources/deadbeef/text")
    assert r.status_code == 404 and "no saved source" in r.json()["detail"]


def test_a_saved_text_changed_on_disk_is_refused_with_a_plain_sentence_on_every_route(client, tmp_path):
    one = post(client).json()["source"]
    (tmp_path / "inputs" / "sources" / "2026-10-02" / f"{one['id']}.txt").write_bytes(b"edited")
    for r in (client.get(f"/api/sources/{one['id']}/text"), listing(client, subject=SUBJECT)):
        assert r.status_code == 409 and "no longer matches the fingerprint" in r.json()["detail"]


# --- no change while a draft runs -------------------------------------------------------------------------------------------

def test_sources_cannot_be_added_or_removed_while_a_draft_holds_the_slot(client, clock, monkeypatch):
    one = post(client).json()["source"]
    gated = GatedProvider()
    monkeypatch.setattr(review_run, "build_digital_payments_review", lambda on_event=None: REAL_DP(
        provider=gated, today=TODAY, fetch_table=lambda today: ROWS, on_event=on_event))
    run_id = start(client, section="digital_payments", report_type="weekly")
    assert gated.entered.wait(timeout=10)
    try:
        added = post(client)
        assert added.status_code == 409 and "is being drafted right now" in added.json()["detail"]
        assert "Digital Payments" in added.json()["detail"]
        assert client.delete(f"/api/sources/{one['id']}").status_code == 409
        assert listing(client, subject=SUBJECT).json()["pieces"][0]["sources"][0]["id"] == one["id"]   # reading is allowed
        assert client.get(f"/api/sources/{one['id']}/text").status_code == 200
        assert src.get(one["id"]) is not None                                                           # and nothing changed
        clock.t += 3601                                                                                # a stuck draft does not count
        assert post(client, text=PARAGRAPH * 3).status_code == 200
    finally:
        gated.release.set()
    assert finished(client, run_id)["status"] in ("finished", "failed")


def test_once_the_draft_has_ended_sources_can_be_changed_again(client, monkeypatch):
    monkeypatch.setattr(review_run, "build_digital_payments_review", lambda on_event=None: REAL_DP(
        provider=FakeProvider(), today=TODAY, fetch_table=lambda today: ROWS, on_event=on_event))
    finished(client, start(client, section="digital_payments", report_type="weekly"))
    one = post(client).json()["source"]
    assert client.delete(f"/api/sources/{one['id']}").status_code == 200


# --- the routes' protection ---------------------------------------------------------------------------------------------------

def test_the_source_routes_have_the_protection_the_other_api_routes_have_which_is_none(client):
    assert listing(client).status_code == 200 and post(client).status_code == 200
    assert client.get("/api/health").status_code == 200       # no sign-in on any /api route; nothing is added here
