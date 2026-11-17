import json
import time
from types import SimpleNamespace

import pytest

from cytonn_weekly.common import gather
from cytonn_weekly.common import run_events as ev
from cytonn_weekly.common import source_policy as sp
from cytonn_weekly.common import sources as src
from cytonn_weekly.equities import companies
from cytonn_weekly.narrative import bedrock_provider as bp
from cytonn_weekly.source_pieces import Piece
from tests.test_sources import FRIDAY, PARAGRAPH, Getter, article, fetch, refused, reply

NEVER = ("bloomberg.com", "businessdailyafrica.com", "nation.africa", "nation.co.ke")
SLUGS = ("fixed_income", "equities", "real_estate", "digital_payments", "global_markets", "ssa", "kenya_macro", "focus")


# --- kind_for and search_hosts ------------------------------------------------------------------------------------------

def test_kind_for_says_named_news_or_none():
    assert sp.kind_for("fixed_income", "T-bills", "centralbank.go.ke") == "named"
    assert sp.kind_for("fixed_income", "T-bills", "www.centralbank.go.ke") == "named"   # a subdomain counts
    assert sp.kind_for("real_estate", "Land", "standardmedia.co.ke") == "news"
    assert sp.kind_for("real_estate", "Land", "www.standardmedia.co.ke") == "news"
    assert sp.kind_for("fixed_income", "T-bills", "standardmedia.co.ke") is None   # news for one section only
    assert sp.kind_for("fixed_income", "T-bills", "example.org") is None
    assert sp.kind_for("fixed_income", "T-bills", "notcentralbank.go.ke") is None   # a look-alike is not a subdomain
    assert sp.kind_for("no_such_section", "x", "centralbank.go.ke") is None
    assert sp.kind_for("fixed_income", "T-bills", "") is None


def test_kind_for_reads_a_piece_of_digital_payments_by_its_own_site_and_a_section_by_its_title():
    assert sp.kind_for("digital_payments", "Visa", "investor.visa.com") == "named"
    assert sp.kind_for("digital_payments", "Visa", "investor.mastercard.com") is None
    assert sp.kind_for("digital_payments", "Block", "investor.visa.com") is None   # no list for it
    assert sp.kind_for("Global Markets Review", "Growth", "worldbank.org") == "named"
    assert sp.kind_for("equities", "Listed banks and insurers", "nse.co.ke") == "named"


def test_a_company_piece_of_equities_reads_its_own_site_and_nothing_else():
    company = next(c for c in companies.load() if c.domain)
    assert sp.kind_for("equities", company.name, company.domain) == "named"
    assert sp.kind_for("equities", company.name, "nse.co.ke") is None


def test_the_earnings_piece_reads_every_listed_companys_own_site_as_well_as_the_named_hosts():
    earnings = "Listed company earnings and dividends"
    company = next(c for c in companies.load() if c.domain)
    assert sp.kind_for("equities", earnings, company.domain) == "named"
    assert sp.kind_for("equities", earnings, "nse.co.ke") == "named"
    assert company.domain in sp.search_hosts("equities", earnings)
    assert sp.kind_for("equities", earnings, "example.org") is None
    assert sp.kind_for("equities", earnings, "bloomberg.com") is None   # never read stays never read
    assert sp.kind_for("equities", "Corporate actions and deals", company.domain) is None   # the other pieces keep their lists


def test_the_regulation_brief_asks_for_rules_that_touch_listed_companies_or_trading():
    from cytonn_weekly.equities.review_run import BRIEFS

    brief = next(b for b in BRIEFS if b.id == "market_regulation")
    assert "applies to listed companies or to trading" in brief.focus and "does not qualify" in brief.focus


def test_a_never_read_host_is_none_everywhere():
    for slug in SLUGS:
        for host in NEVER:
            for name in (host, f"www.{host}"):
                assert sp.kind_for(slug, "anything", name) is None, (slug, name)
                assert name not in sp.search_hosts(slug, "anything")
    assert all(sp.is_never_read(h) and sp.is_never_read(f"www.{h}") for h in NEVER)
    assert not sp.is_never_read("centralbank.go.ke")


def test_a_news_site_is_marked_news_and_so_is_one_never_read():
    assert sp.is_news("standardmedia.co.ke") and sp.is_news("www.nation.africa") and sp.is_news("bloomberg.com")
    assert not sp.is_news("centralbank.go.ke") and not sp.is_news("example.org")


def test_search_hosts_is_empty_when_a_piece_has_no_allowed_hosts():
    assert sp.search_hosts("digital_payments", "Block") == []
    assert sp.search_hosts("no_such_section", "x") == []
    assert sp.search_hosts("digital_payments", "Visa") == ["investor.visa.com"]
    assert "standardmedia.co.ke" in sp.search_hosts("real_estate", "Land")


# --- the gather step ------------------------------------------------------------------------------------------------------

def gather_with(piece, tmp_path, *pools):
    calls, fetched, events = [], [], []

    def search(query, start, domains):
        calls.append(domains)
        return pools[len(calls) - 1] if len(calls) <= len(pools) else []

    def fetch_stub(url, subject, week_end, **_):
        fetched.append(url)
        return SimpleNamespace(url=url)

    saved = gather.gather_piece(piece, search=search, fetch=fetch_stub, root=tmp_path, limits=gather.Limits(),
                                deadline=time.monotonic() + 100,
                                on_event=lambda kind, label, detail=None, counts=None: events.append((kind, detail)))
    return calls, fetched, events, saved


def result(url, day="2026-11-04"):
    return {"url": url, "title": "Page", "text": PARAGRAPH, "publishedDate": day}


def test_a_piece_with_no_allowed_hosts_has_no_search_at_all(tmp_path):
    calls, fetched, events, saved = gather_with(Piece("Block", FRIDAY, section="digital_payments"), tmp_path)
    assert calls == [] and fetched == [] and saved == []
    assert events[-1] == (ev.SOURCES_FOUND, "0 pages")


def test_pass_two_searches_only_the_hosts_the_policy_allows_for_the_piece(tmp_path):
    piece = Piece("Land", FRIDAY, domains=("hassconsult.co.ke",), section="real_estate")
    calls, _, _, _ = gather_with(piece, tmp_path)
    expected = [h for h in sp.search_hosts("real_estate", "Land") if h != "hassconsult.co.ke"]
    assert calls == [["hassconsult.co.ke"], expected]
    assert expected and not set(NEVER) & set(expected)


def test_a_found_page_is_read_only_when_its_host_is_allowed_for_the_piece(tmp_path):
    piece = Piece("Land", FRIDAY, domains=("hassconsult.co.ke",), section="real_estate")
    pool = [result("https://www.hassconsult.co.ke/land-index"), result("https://www.nation.africa/land"),
            result("https://example.org/land"), result("https://www.standardmedia.co.ke/land")]
    _, fetched, _, saved = gather_with(piece, tmp_path, pool)
    assert fetched == ["https://www.hassconsult.co.ke/land-index", "https://www.standardmedia.co.ke/land"] and len(saved) == 2


# --- by_policy -------------------------------------------------------------------------------------------------------------

def source(host, origin="found", flags=(), title="A page"):
    return {"host": host, "origin": origin, "flags": list(flags), "title": title, "url": f"https://{host}/x"}


def run_by_policy(results, section="fixed_income", label="T-bills"):
    events = []
    token = ev.current_observer.set(lambda kind, label, detail=None, counts=None: events.append((kind, label, detail)))
    try:
        return (*bp.by_policy(results, section, label), events)
    finally:
        ev.current_observer.reset(token)


def test_by_policy_keeps_what_an_analyst_added_and_drops_a_gathered_page_off_the_list():
    gathered_ok, gathered_off = source("centralbank.go.ke"), source("example.org", title="Stray")
    by_hand = [source("example.org", "fetched"), source("example.org", "pasted"), source("example.org", "snip"),
               source("example.org", "found", [src.ADDED_BY_ANALYST])]
    kept, notes, events = run_by_policy([gathered_ok, gathered_off, *by_hand])
    assert kept == [gathered_ok, *by_hand]
    assert len(notes) == 1 and "Stray" in notes[0] and "not on the source list for this piece" in notes[0]
    assert events == [(ev.SOURCE_LEFT_OUT, "Stray", "From example.org: not on the source list for this piece, so it was not used for T-bills.")]


def test_by_policy_drops_a_gathered_never_read_page_but_keeps_text_pasted_from_one():
    gathered, pasted = source("www.nation.africa", title="Daily Nation"), source("www.nation.africa", "pasted")
    kept, notes, events = run_by_policy([gathered, pasted])
    assert kept == [pasted] and "never read by the tool" in notes[0]
    assert [e[0] for e in events] == [ev.SOURCE_LEFT_OUT]


# --- saved sources and their flags -----------------------------------------------------------------------------------------

def test_an_old_manifest_with_no_new_flags_still_loads_and_is_kept_by_policy(tmp_path):
    fetch(Getter(reply(article())), root=tmp_path)
    manifest = tmp_path / FRIDAY.isoformat() / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["sources"][0]["flags"] = []   # as saved before the news and analyst flags existed
    manifest.write_text(json.dumps(data), encoding="utf-8")
    (saved,) = src.list_for("Mortgage lending", FRIDAY, tmp_path)
    assert saved.flags == [] and saved.origin == "fetched"
    kept, notes, _ = run_by_policy([saved.as_result()], "real_estate", "Mortgage lending")
    assert len(kept) == 1 and notes == []   # fetched by hand: judged by its origin, not by a flag


def test_the_flags_follow_the_host_and_the_origin():
    assert src.policy_flags("centralbank.go.ke", "fetched") == [src.ADDED_BY_ANALYST]
    assert src.policy_flags("centralbank.go.ke", "found") == []
    assert src.policy_flags("www.standardmedia.co.ke", "found") == [src.NEWS_SITE]
    assert src.policy_flags("www.standardmedia.co.ke", "pasted") == [src.NEWS_SITE, src.ADDED_BY_ANALYST]
    assert src.policy_flags("example.org", "snip") == []


def test_a_fetched_page_carries_the_analyst_flag_and_a_found_one_does_not(tmp_path):
    assert src.ADDED_BY_ANALYST in fetch(Getter(reply(article())), root=tmp_path).flags
    assert src.ADDED_BY_ANALYST not in fetch(Getter(reply(article())), root=tmp_path, subject="Land", origin="found").flags


@pytest.mark.parametrize("url", ["https://www.nation.africa/news/credit", "https://businessdailyafrica.com/a", "https://bloomberg.com/news/x"])
def test_fetch_page_refuses_a_never_read_host_with_the_plain_sentence(url):
    getter = Getter()   # no reply: a request would raise
    assert refused(getter, url) == src.NEVER_READ.format(host=src.host_of(url))
    assert getter.asked == [] and "Paste the text with its date, or send a snip." in src.NEVER_READ


def test_pasted_text_from_a_never_read_host_is_kept_and_marked_as_a_news_site(tmp_path):
    saved = src.from_paste("https://www.nation.africa/news/credit", "2026-11-05", PARAGRAPH * 3, "Mortgage lending", FRIDAY, root=tmp_path)
    assert saved.origin == "pasted" and saved.text == PARAGRAPH * 3
    assert src.NEWS_SITE in saved.flags and src.ADDED_BY_ANALYST in saved.flags
    assert [s.id for s in src.list_for("Mortgage lending", FRIDAY, tmp_path)] == [saved.id]
