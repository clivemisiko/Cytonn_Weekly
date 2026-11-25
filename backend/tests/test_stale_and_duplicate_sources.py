import functools
import time
from datetime import date
from pathlib import Path

import pytest

from cytonn_weekly.common import content_dates as cd
from cytonn_weekly.common import gather, http, site_read
from cytonn_weekly.common import run_events as ev
from cytonn_weekly.common import sources as src
from cytonn_weekly.drafting import bedrock as bp
from cytonn_weekly.drafting.base import NarrativeBrief, NarrativeProvider
from cytonn_weekly.drafting.drafter import draft_pieces, same_event
from cytonn_weekly.drafting.results import HighlightResult
from cytonn_weekly.equities import companies
from cytonn_weekly.source_pieces import Piece
from tests.test_sourced_claims import Client, aws  # noqa: F401 - the fake Bedrock client and its settings fixture

FRIDAY = date(2026, 11, 20)
WINDOW = (date(2026, 11, 14), FRIDAY)   # the report week of the 2026-11-20 weekly
FIX = Path(__file__).parent / "fixtures" / "sources"
FILLER = " The bank said its performance was supported by growth across its business lines and customer deposits." * 6
STALE_TITLE = "KCB Group Posts 69% Net Profit Growth in Q1 2024, Board Proposes Interim Dividend"   # what reached the draft
STALE_TEXT = ("KCB Group PLC has reported a 69% growth in net profit for the first quarter of 2024, and the board proposed "
              "an interim dividend." + FILLER)
CURRENT_TEXT = ("Press Release November 18, 2026\nKCB Group Q3 Profit After Tax Rises 24% to KShs. 58.6 Billion. KCB Group "
                "PLC has reported a profit after tax of KShs. 58.6 billion for the nine months ending September 30, 2026."
                + FILLER)   # the opening of KCB's real release, kcbgroup.com, 18 November 2026


def tiny_pdf(lines, created=""):
    """A one-page PDF holding ``lines`` and, when given, a CreationDate ("20261118151229+03'00'")."""
    content = "BT /F1 10 Tf 40 800 Td 12 TL " + " ".join(f"({line}) '" for line in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            f"<< /Length {len(content)} >>\nstream\n{content}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            f"<< /CreationDate (D:{created}) >>" if created else "<< >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info 6 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


FILLER_LINES = [FILLER[i:i + 90] for i in range(0, len(FILLER), 90)]


def serve(pages):
    """An http_get answering each address in ``pages`` (bytes, or (bytes, content type)); anything else is a 404."""
    def get(url, max_bytes):
        if url not in pages:
            return http.Reply(404, {}, b"")
        body, kind = pages[url] if isinstance(pages[url], tuple) else (pages[url], "")
        kind = kind or ("application/pdf" if body.startswith(b"%PDF") else "text/html")
        return http.Reply(200, {"content-type": kind}, body)
    return get


def fetcher(pages):
    return functools.partial(src.fetch_page, http_get=serve(pages), resolve=lambda host: ["93.184.216.34"])


def html_page(title, text, meta_day=""):
    meta = f'<meta property="article:published_time" content="{meta_day}T08:00:00Z">' if meta_day else ""
    paras = "".join(f"<p>{p}</p>" for p in text.split("\n"))
    return f"<html><head><title>{title}</title>{meta}</head><body><h1>{title}</h1>{paras}</body></html>".encode()


# --- reading a page's own date and the period it reports ---------------------------------------------------------------

def test_the_dateline_is_the_date_at_the_top_and_never_a_period_end():
    assert cd.dateline(CURRENT_TEXT) == date(2026, 11, 18)
    assert cd.dateline("Nairobi, 22nd May 2024 - KCB Group announced") == date(2024, 5, 22)
    assert cd.dateline("Results for the nine months ended 30 September 2026. Nairobi") is None
    assert cd.dateline("No date at all in this text") is None


@pytest.mark.parametrize("text,end", [
    ("Q1 2024", date(2024, 3, 31)), ("Q3’2026 results", date(2026, 9, 30)), ("2026 Q1 Financial Results", date(2026, 3, 31)),
    ("the third quarter of 2026", date(2026, 9, 30)), ("H1 2026", date(2026, 6, 30)), ("FY'2025", date(2025, 12, 31)),
    ("full year 2025", date(2025, 12, 31)), ("2025 Full Year Results", date(2025, 12, 31)),
    ("Unaudited Results Quarter 3 2026", date(2026, 9, 30)), ("/x/Investor_Presentation_Q3_2025.pdf", date(2025, 9, 30)),
    ("/x/DTB-Q3-2026-Investor-Presentation.pdf", date(2026, 9, 30)),
    ("for the period ended 30 September 2026", date(2026, 9, 30)),
    ("Q3 2026 against Q3 2025", date(2026, 9, 30)),   # the newest period named is the one the page reports
])
def test_the_newest_reporting_period_a_text_names(text, end):
    assert cd.latest_period(text)[1] == end


def test_a_period_too_old_for_the_week_is_stale_and_a_current_one_is_not():
    assert cd.stale_period(STALE_TITLE, WINDOW) == "Q1 2024 (ended 2024-03-31)"
    assert cd.stale_period("H1 2026 results", WINDOW)       # ended 30 June: its results came out by October
    assert cd.stale_period("FY 2025 Performance", WINDOW)
    assert cd.stale_period("KCB Group Press Release- Q3 2026 Financial Results", WINDOW) is None
    assert cd.stale_period("CMA approves the cross-listing of Africa Eats", WINDOW) is None   # no period: not judged


# --- problem 1: a source whose content is dated outside the window yields no item --------------------------------------

def test_the_stale_kcb_page_dated_inside_the_week_is_left_out_at_draft_time():
    stale = {"id": "s", "title": STALE_TITLE, "host": "kcbgroup.com", "publishedDate": "2026-11-18", "text": STALE_TEXT}
    kept, notes = bp.within_window([stale], "KCB Group", *WINDOW, dated_only=True)
    assert kept == [] and "Q1 2024 (ended 2024-03-31)" in notes[0] and "dated 2026-11-18" in notes[0]
    current = {"id": "c", "title": "KCB Q3 2026 results", "host": "kcbgroup.com", "publishedDate": "2026-11-18",
               "text": CURRENT_TEXT}
    assert bp.within_window([current], "KCB Group", *WINDOW, dated_only=True)[0] == [current]


def test_a_dateline_years_before_the_week_marks_the_page_old_whatever_its_stated_date():
    old = {"id": "o", "title": "KCB board proposes dividend", "host": "kcbgroup.com", "publishedDate": "2026-11-18",
           "text": "Nairobi, 22nd May 2024 - The board of KCB Group proposed an interim dividend." + FILLER}
    kept, notes = bp.within_window([old], "KCB Group", *WINDOW)
    assert kept == [] and "its text is dated 2024-05-22" in notes[0]
    recent = {**old, "text": "Nairobi, 12th November 2026 - The board of KCB Group proposed an interim dividend." + FILLER}
    assert bp.within_window([recent], "KCB Group", *WINDOW)[0] == [recent]   # a few days before the week is not old news


def test_the_whole_provider_path_makes_no_model_call_from_the_stale_kcb_page(aws):
    src.from_paste("https://ke.kcbgroup.com/news/q1-2024", "2026-11-18", STALE_TEXT, "KCB Group", FRIDAY, title=STALE_TITLE)
    client = Client([])
    brief = companies._brief(next(c for c in companies.load() if c.name == "KCB Group"))
    res = bp.BedrockNarrativeProvider(client=client).draft_piece(brief, start=WINDOW[0], end=WINDOW[1], today=FRIDAY)
    assert res.no_story and client.calls == [] and any("Q1 2024" in w for w in res.draft_warnings)


def test_a_page_whose_meta_date_is_in_the_week_but_whose_title_reports_q1_2024_is_not_saved(tmp_path):
    url = "https://kcbgroup.com/blog/q1-2024"
    fetch = fetcher({url: html_page(STALE_TITLE, STALE_TEXT, meta_day="2026-11-18")})
    with pytest.raises(src.OutOfWindow, match="Q1 2024"):
        fetch(url, "KCB Group", FRIDAY, root=tmp_path, origin="found", window=WINDOW)
    assert src.list_for("KCB Group", FRIDAY, tmp_path) == []


def found_by_search(tmp_path, pages, result):
    """One search result for a Fixed Income piece, its page read through the real fetch_page from ``pages``."""
    events = []
    piece = Piece("T-bills", FRIDAY, domains=("centralbank.go.ke",), section="fixed_income")
    saved = gather.gather_piece(piece, search=lambda q, start, domains: [result], fetch=fetcher(pages), root=tmp_path,
                                limits=gather.Limits(max_queries=1), deadline=time.monotonic() + 100,
                                on_event=lambda kind, label, detail=None, counts=None: events.append((kind, detail)))
    return saved, [d for k, d in events if k == ev.SOURCE_LEFT_OUT]


def test_the_search_services_date_never_dates_a_page_that_states_none(tmp_path):
    url = "https://www.centralbank.go.ke/old-notice"
    result = {"url": url, "title": "An undated notice", "publishedDate": "2026-11-18T00:00:00Z", "text": ""}
    saved, left = found_by_search(tmp_path, {url: html_page("An undated notice", "The bank issued a notice." + FILLER)}, result)
    assert saved == [] and "no date" in left[0]


def test_search_text_is_kept_only_with_its_own_dateline_inside_the_week(tmp_path):
    url = "https://www.centralbank.go.ke/unreadable"   # the page answers 404, so the search text is all there is
    undated = {"url": url, "title": "Notice", "publishedDate": "2026-11-18", "text": "The bank issued a notice." + FILLER}
    saved, left = found_by_search(tmp_path, {}, undated)
    assert saved == [] and "its text states no date" in left[0]
    dated = {**undated, "text": "Nairobi, 17th November 2026 - The bank issued a notice." + FILLER}
    saved, left = found_by_search(tmp_path, {}, dated)
    assert [s.published_date for s in saved] == ["2026-11-17"] and src.TEXT_FROM_SEARCH in saved[0].flags and left == []


# --- undated is not current ------------------------------------------------------------------------------------------

def test_an_undated_source_never_yields_a_company_item():
    brief = companies._brief(companies.load()[0])
    assert brief.dated_only
    kept, notes = bp.within_window([{"id": "u", "title": "Undated", "host": "kcbgroup.com", "text": CURRENT_TEXT}],
                                   brief.label, *WINDOW, brief.dated_only)
    assert kept == [] and "has no date" in notes[0]


def test_an_undated_page_is_never_saved_by_the_gather(tmp_path):
    url = "https://kcbgroup.com/press/undated"
    with pytest.raises(src.OutOfWindow, match="no date"):
        fetcher({url: html_page("Press note", "The bank issued a note." + FILLER)})(
            url, "KCB Group", FRIDAY, root=tmp_path, origin="found", window=WINDOW)


# --- PDFs date themselves ----------------------------------------------------------------------------------------------

def test_a_pdf_is_dated_by_its_dateline_else_by_its_creation_date(tmp_path):
    a, b, c = "https://x.example.com/a.pdf", "https://x.example.com/b.pdf", "https://x.example.com/c.pdf"
    fetch = fetcher({a: tiny_pdf(["Press Release November 18, 2026", *FILLER_LINES], "20261101000000Z"),
                     b: tiny_pdf(["Investor Presentation Q3 2026", *FILLER_LINES], "20261119144341+03'00'"),
                     c: tiny_pdf(["Investor Presentation Q3 2026", *FILLER_LINES])})
    assert fetch(a, "DTB", FRIDAY, root=tmp_path).published_date == "2026-11-18"
    assert fetch(b, "DTB", FRIDAY, root=tmp_path).published_date == "2026-11-19"
    assert fetch(c, "DTB", FRIDAY, root=tmp_path).published_date == ""
    with pytest.raises(src.OutOfWindow, match="no date"):
        fetch(c, "DTB", FRIDAY, root=tmp_path, window=WINDOW)


# --- problem 3: each bank's own page or document, from a fixture -------------------------------------------------------

def company(name):
    return next(c for c in companies.load() if c.name == name)


def read_bank(name, listings, documents, tmp_path):
    """read_site over captured listing excerpts (fixtures) and tiny documents; robots.txt answers 404 (nothing disallowed)."""
    c = company(name)
    piece = next(p for p in companies.pieces(FRIDAY) if p.subject == name)
    fetched = []

    def raw(url):
        if url.endswith("/robots.txt"):
            raise src.SourceError(src.NOT_FOUND.format(status=404))
        if url in listings:
            return url, (FIX / listings[url]).read_bytes(), "text/html"
        raise src.SourceError(src.NOT_FOUND.format(status=404))

    def fetch(url, *a, **kw):
        fetched.append(url)
        return fetcher(documents)(url, *a, **kw)

    got = site_read.read_site(c, piece, fetch=fetch, root=tmp_path, skip=set(), deadline=time.monotonic() + 60, raw=raw,
                              sleep=lambda s: None)
    return got, fetched


def test_kcb_q3_2026_release_is_read_first_from_its_undated_download_link(tmp_path):
    listing = "kcb_press_release_2026-11-25_excerpt.html"
    q3 = next(lk["url"] for lk in site_read.read_links((FIX / listing).read_bytes(), "https://kcbgroup.com/press-release")
              if "Q3 2026" in lk["text"])
    doc = tiny_pdf(["Press Release November 18, 2026", "KCB Group Q3 Profit After Tax Rises 24% to KShs. 58.6 Billion",
                    *FILLER_LINES], "20261118151229+03'00'")   # the real release's dateline and CreationDate
    got, fetched = read_bank("KCB Group", {"https://kcbgroup.com/investor-relations": listing,
                                           "https://kcbgroup.com/press-release": listing}, {q3: doc}, tmp_path)
    assert fetched[0] == q3                                                     # before the menus and older releases
    assert [s.published_date for s in got.saved] == ["2026-11-18"] and "58.6 Billion" in got.saved[0].text


def test_kcb_never_fetches_a_link_that_names_a_stale_period(tmp_path):
    listing = (FIX / "kcb_press_release_2026-11-25_excerpt.html").read_bytes()
    stale = [lk["url"] for lk in site_read.read_links(listing, "https://kcbgroup.com/press-release")
             if any(p in lk["text"] for p in ("2026 Q1", "FY 2025", "H1 2025"))]
    _, fetched = read_bank("KCB Group", {"https://kcbgroup.com/press-release": "kcb_press_release_2026-11-25_excerpt.html"},
                           {}, tmp_path)
    assert len(stale) == 3 and not set(stale) & set(fetched)


def test_dtb_q3_2026_presentation_pdf_is_read(tmp_path):
    url = ("https://dtbk.dtbafrica.com/storage/uploads/c4480c8c-cc2e-4064-9106-3e312fa2d027/"
           "DTB-Q3-2026-Investor-Presentation.pdf")
    doc = tiny_pdf(["Investor Presentation Q3 2026", *FILLER_LINES], "20261119144341+03'00'")   # the real file's CreationDate
    got, fetched = read_bank("Diamond Trust Bank Kenya", {"https://dtbk.dtbafrica.com/investor-presentation":
                                                          "dtb_investor_presentation_2026-11-25_excerpt.html"}, {url: doc}, tmp_path)
    assert fetched == [url] and [s.published_date for s in got.saved] == ["2026-11-19"]   # H1 2026, FY 2025, Q3 2025 never fetched


def test_stanbic_is_read_on_stanbicbank_co_ke_and_its_period_is_read_from_the_address(tmp_path):
    c = company("Stanbic Holdings")
    assert c.domain == "stanbicbank.co.ke" and c.start == ("https://www.stanbicbank.co.ke/kenya/personal/about-us/investor-relations",)
    url = ("https://www.stanbicbank.co.ke/static_file/Kenya/Downloadable files/Stanbic Bank Limited/Financials/2026/"
           "Stanbic-Bank-Kenya-Ltd-Q3-2026-Financial-Presentation.pdf")
    doc = tiny_pdf(["Stanbic Bank Kenya Q3 2026 Financial Presentation", *FILLER_LINES], "20261120090000+03'00'")
    got, fetched = read_bank("Stanbic Holdings", {c.start[0]: "stanbic_investor_relations_2026-11-25_excerpt.html"},
                             {url: doc}, tmp_path)
    assert fetched[0] == url and [s.published_date for s in got.saved] == ["2026-11-20"]
    assert not any("H1 2026" in u or "Q1-2026" in u or "2025" in u for u in fetched)


def test_standard_chartered_q3_2026_link_is_tried_and_its_file_refused_when_unreadable(tmp_path):
    url = "https://av.sc.com/ke/content/docs/ke-q3-unaudited-financial-results-2026.pdf"
    _, fetched = read_bank("Standard Chartered Bank Kenya", {"https://www.sc.com/ke/investor-relations/":
                                                             "sc_ke_investor_relations_2026-11-25_excerpt.html"}, {}, tmp_path)
    assert fetched[0] == url and not any("2025" in u for u in fetched)


def test_a_bot_wall_is_named_as_the_reason_a_site_was_not_read(tmp_path):
    wall = (b'<html><head><script src="/_Incapsula_Resource?SWJIYLWA=x"></script></head><body>Request unsuccessful. '
            b'Incapsula incident ID: 1</body></html>')   # what equitygroupholdings.com answered on 2026-11-25
    c = company("Equity Group Holdings")

    def raw(url):
        if url.endswith("/robots.txt"):
            raise src.SourceError(src.NOT_FOUND.format(status=404))
        return url, wall, "text/html"

    piece = next(p for p in companies.pieces(FRIDAY) if p.subject == c.name)
    got = site_read.read_site(c, piece, fetch=lambda *a, **k: None, root=tmp_path, skip=set(), deadline=time.monotonic() + 60,
                              raw=raw, sleep=lambda s: None)
    assert got.saved == [] and got.note == site_read.BOT_WALL


# --- problem 2: one event, one item --------------------------------------------------------------------------------------

CMA = "CMA Approves Cross-Listing of Africa Eats Ltd and New Dividend ETF on the NSE"


def piece(headline, url, text="The CMA approved it.", news=False):
    flags = [src.NEWS_SITE] if news else []
    return {"topic": headline, "headline": headline, "claims": [{"text": text, "url": url, "source_flags": flags}]}


def test_the_same_event_from_two_pages_is_one_and_different_stories_are_two():
    assert same_event(piece(CMA, "https://www.cma.or.ke/a"), piece(CMA, "https://www.businessdaily.example/b", news=True))
    assert not same_event(piece("KCB Group Q3 Profit After Tax Rises 24%", "https://kcbgroup.com/a", "Profit rose 24%."),
                          piece("KCB Signs Afreximbank Financing Deal", "https://kcbgroup.com/b", "A USD 100 mn deal."))
    assert not same_event(piece("Equity Group Q3 2026 Profit After Tax Rises 32%", "https://e.example/a", "Profit rose 32.0%."),
                          piece("KCB Group Q3 2026 Profit After Tax Rises 24%", "https://k.example/b", "Profit rose 23.9%."))
    # near-identical headlines whose figures differ are two events (one bank's two periods)
    assert not same_event(piece("KCB Group Profit After Tax Rises", "https://k.example/a", "It rose 24% to 58.6 bn."),
                          piece("KCB Group Profit After Tax Rises", "https://k.example/b", "It rose 20% to 40.8 bn."))


class Fixed(NarrativeProvider):
    """Gives each brief the piece named for it."""

    drafted_by = "fake:test"

    def __init__(self, pieces):
        self.pieces = pieces

    def draft_piece(self, brief, *, start, end, today):
        p = self.pieces[brief.id]
        return HighlightResult(company=brief.label, search_scope="web", ir_domain="", drafted_by=self.drafted_by,
                               headline=p["headline"], paragraph="p", paragraph_md="p", claims=p["claims"])


def briefs(*ids):
    return [NarrativeBrief(id=i, section="Equities", label=i.upper(), focus="f") for i in ids]


def test_a_duplicate_event_yields_one_item_and_the_primary_source_is_kept():
    provider = Fixed({"news": piece(CMA, "https://www.example-news.co.ke/markets/cma-africa-eats", news=True),
                      "reg": piece(CMA, "https://www.cma.or.ke/press/2026/africa-eats"),
                      "other": piece("NSE Extends Trading Hours to 4pm", "https://www.nse.co.ke/press/hours")})
    out = draft_pieces(briefs("news", "reg", "other"), 3, provider=provider, today=FRIDAY)
    assert [p["brief_id"] for p in out["pieces"]] == ["reg", "other"]   # in the earlier place, from the regulator
    assert out["skipped"] == {"news": "already drafted in this run under REG"}
    assert any("same event" in w and "better sourced" in w for w in out["warnings"])


def test_of_two_primary_sources_the_more_specific_page_is_kept_and_a_worse_later_one_is_dropped():
    provider = Fixed({"page": piece(CMA, "https://www.cma.or.ke/press/2026/africa-eats"),
                      "home": piece(CMA, "https://www.nse.co.ke/"),
                      "news": piece(CMA, "https://www.example-news.co.ke/markets/2026/11/cma/africa-eats", news=True)})
    out = draft_pieces(briefs("page", "home", "news"), 3, provider=provider, today=FRIDAY)
    assert [p["brief_id"] for p in out["pieces"]] == ["page"]
    assert set(out["skipped"]) == {"home", "news"}


def test_two_different_stories_about_one_company_both_survive():
    provider = Fixed({"a": piece("KCB Group Q3 Profit After Tax Rises 24%", "https://kcbgroup.com/a", "Profit rose 24%."),
                      "b": piece("KCB Signs Afreximbank Financing Deal", "https://kcbgroup.com/b", "A USD 100 mn deal.")})
    out = draft_pieces(briefs("a", "b"), 2, provider=provider, today=FRIDAY)
    assert [p["brief_id"] for p in out["pieces"]] == ["a", "b"] and "skipped" not in out
