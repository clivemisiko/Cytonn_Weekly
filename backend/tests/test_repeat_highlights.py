from datetime import date

from cytonn_weekly.common import run_events as ev
from cytonn_weekly.drafting.results import HighlightResult
from cytonn_weekly.drafting.base import NarrativeBrief, NarrativeProvider
from cytonn_weekly.drafting.drafter import REPEAT, draft_pieces, repeated_url
from cytonn_weekly.weekly import previous_issue as pi

TODAY = date(2026, 11, 13)
BODY = (
    '<p><strong>Treasury bill yields eased at the weekly auction</strong></p>'
    '<p>Details at <a href="https://www.centralbank.go.ke/auction/?utm=1#top">CBK</a> and '
    '<a href="https://example.org/old/">a report</a>.</p>'
    '<p><b>Short</b></p>'
)


def issue():
    return pi.Issue(issue_id=1, published=date(2026, 11, 6), sections={"fixed-income": {"name": "Fixed Income", "body": BODY, "summary": ""}})


class Seeing(NarrativeProvider):
    """Gives each brief a piece citing the address named for it, and keeps the briefs it was given."""

    drafted_by = "fake:test"

    def __init__(self, urls):
        self.urls, self.briefs = urls, []

    def draft_piece(self, brief, *, start, end, today):
        self.briefs.append(brief)
        url = self.urls[brief.id]
        claim = {"text": "A claim.", "url": url, "title": "t", "cited_text": "q"}
        return HighlightResult(company=brief.label, search_scope="web", ir_domain="", drafted_by=self.drafted_by,
                               headline=f"H {brief.id}", paragraph="p", paragraph_md="p", claims=[claim])


def briefs(*ids):
    return [NarrativeBrief(id=i, section="Fixed Income", label=i.upper(), focus="f") for i in ids]


def test_norm_url_makes_two_mentions_of_one_page_agree():
    a = pi.norm_url("HTTPS://www.Example.org/a/b/#x")
    assert a == pi.norm_url("http://example.org/a/b") == "example.org/a/b"
    assert pi.norm_url("https://example.org/a?x=1") != pi.norm_url("https://example.org/a")
    assert pi.norm_url("") == "" and pi.norm_url("not a url") == ""


def test_digest_lists_the_headings_and_every_linked_page_of_the_section():
    d = pi.digest(issue(), "fixed-income")
    assert d["headings"] == ["Treasury bill yields eased at the weekly auction"]   # "Short" is too short to be a heading
    assert d["urls"] == {"centralbank.go.ke/auction?utm=1", "example.org/old"}
    assert pi.digest(issue(), "equities") is None and pi.digest(None, "fixed-income") is None


def test_repeated_url_finds_a_cited_page_the_section_already_linked():
    urls = pi.digest(issue(), "fixed-income")["urls"]
    assert repeated_url([{"url": "https://example.org/old"}], urls) == "https://example.org/old"
    assert repeated_url([{"url": "https://example.org/new"}, {"url": ""}], urls) is None


def test_a_piece_citing_an_already_linked_page_is_left_out_and_the_next_brief_fills_in():
    provider = Seeing({"a": "https://www.example.org/old/", "b": "https://example.org/fresh"})
    events = []
    out = draft_pieces(briefs("a", "b"), 1, provider=provider, today=TODAY, earlier=pi.digest(issue(), "fixed-income"),
                       on_event=lambda kind, label, detail=None, counts=None: events.append((kind, label, detail)))
    assert [p["brief_id"] for p in out["pieces"]] == ["b"] and out["skipped"] == {"a": REPEAT} and out["shortfall"] == 0
    assert any(w.startswith("A: left out, already reported in the previous issue") and "https://www.example.org/old/" in w
               for w in out["warnings"])
    skipped = [a for a in events if a[0] == ev.PART_SKIPPED]
    assert len(skipped) == 1 and skipped[0][1] == "A" and REPEAT in skipped[0][2]


def test_the_headings_go_into_every_brief_as_already_reported():
    provider = Seeing({"a": "https://example.org/fresh"})
    draft_pieces(briefs("a"), 1, provider=provider, today=TODAY, earlier=pi.digest(issue(), "fixed-income"))
    assert "Already reported in the previous issue, do not repeat: Treasury bill yields eased at the weekly auction." in provider.briefs[0].context


def test_with_no_earlier_section_nothing_changes():
    provider = Seeing({"a": "https://example.org/old"})
    out = draft_pieces(briefs("a"), 1, provider=provider, today=TODAY)
    assert [p["brief_id"] for p in out["pieces"]] == ["a"] and "skipped" not in out and provider.briefs[0].context == ""


def test_two_briefs_whose_pieces_cite_the_same_page_give_one_piece_and_the_next_brief_is_tried():
    seeing = Seeing({"a": "https://cma.or.ke/notice/1", "b": "https://cma.or.ke/notice/1#x", "c": "https://nse.co.ke/c"})
    events = []
    out = draft_pieces(briefs("a", "b", "c"), 2, provider=seeing, today=TODAY,
                       on_event=lambda kind, label, detail=None, counts=None: events.append((kind, label)))
    assert [p["brief_id"] for p in out["pieces"]] == ["a", "c"] and out["shortfall"] == 0
    assert out["skipped"] == {"b": "already drafted in this run under A"}
    assert (ev.PART_SKIPPED, "B") in events


def test_two_briefs_whose_pieces_cite_different_pages_give_two_pieces():
    seeing = Seeing({"a": "https://cma.or.ke/notice/1", "b": "https://nse.co.ke/notice/2"})
    out = draft_pieces(briefs("a", "b"), 2, provider=seeing, today=TODAY)
    assert [p["brief_id"] for p in out["pieces"]] == ["a", "b"] and "skipped" not in out
