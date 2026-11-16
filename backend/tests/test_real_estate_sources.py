"""The weekly Real Estate search: the team's preferred sites first, and never social media on the open web."""

import json
from datetime import date

import httpx
import pytest

from cytonn_weekly.narrative.local_provider import LocalNarrativeProvider
from cytonn_weekly.periodic import real_estate as periodic_real_estate
from cytonn_weekly.common import source_policy
from cytonn_weekly.common import sources as source_store
from cytonn_weekly.real_estate import fetcher, review_run, snips
from tests import periodic_helpers as ph
from tests import section_helpers as sh

SITES = ("standardmedia.co.ke",)   # Nation, Business Daily and Bloomberg are never read (equities/source_policy.json)
SOCIAL = ("x.com", "twitter.com", "facebook.com", "instagram.com", "tiktok.com")
TODAY, START = date(2026, 10, 2), date(2026, 9, 26)


def test_the_list_is_the_one_site_the_tool_may_read():
    assert review_run.PREFERRED_SITES == SITES and review_run.SOCIAL_DOMAINS == SOCIAL
    assert review_run.SOCIAL_DOMAINS == source_store.SOCIAL_DOMAINS
    assert not any(source_policy.is_never_read(h) for b in review_run.BRIEFS for h in b.preferred_domains)


def test_every_domain_a_real_estate_brief_names_is_on_the_known_sites_list():
    named = {h for b in review_run.BRIEFS + review_run.SECTOR_BRIEFS for h in b.preferred_domains}
    assert named and all(source_store.is_approved(h) for h in named), sorted(h for h in named if not source_store.is_approved(h))


def test_every_weekly_brief_searches_the_sites_and_blocks_social_media():
    assert len(review_run.BRIEFS) == 6 and review_run.N_SUBSECTIONS == 4
    for brief in review_run.BRIEFS:
        assert brief.preferred_domains[-len(SITES):] == SITES, brief.id
        assert len(set(brief.preferred_domains)) == len(brief.preferred_domains)
        assert brief.blocked_domains == SOCIAL
    residential = next(b for b in review_run.BRIEFS if b.id == "residential")
    assert residential.preferred_domains[:3] == ("centralbank.go.ke", "kba.co.ke", "kmrc.co.ke")   # its own first


def test_the_sources_the_team_named_are_in_their_themes_and_the_exclusion_list_is_unchanged():
    own = {b.id: b.preferred_domains[:-len(SITES)] for b in review_run.BRIEFS}
    knight_frank = ("knightfrank.com", "content.knightfrank.com")
    assert own["residential"] == ("centralbank.go.ke", "kba.co.ke", "kmrc.co.ke", "knbs.or.ke", *knight_frank, "hassconsult.co.ke")
    assert own["land"] == ("hassconsult.co.ke",) and own["commercial"] == knight_frank
    assert own["affordable_housing"] == ("housing.go.ke", "bomayangu.go.ke") and own["hospitality"] == ("tourism.go.ke", "ktb.go.ke")
    assert own["infrastructure"] == ()
    assert review_run.SOCIAL_DOMAINS == ("x.com", "twitter.com", "facebook.com", "instagram.com", "tiktok.com")


def test_the_periodic_themes_reuse_the_weekly_briefs():
    themes = periodic_real_estate.briefs(ph.ctx("quarterly", "Q3'2026"))[1:]
    assert [t.preferred_domains for t in themes] == [b.preferred_domains for b in review_run.BRIEFS]


@pytest.mark.parametrize("bad", ["https://nation.africa", "nation.africa/news", "Nation.Africa", "localhost",
                                 "nation .africa", "nation.africa:443"])
def test_an_invalid_line_is_refused(bad):
    with pytest.raises(ValueError, match="not a lowercase hostname"):
        review_run.preferred_sites(f"nation.africa\n{bad}\n")


def test_duplicates_and_blank_lines_are_dropped():
    assert review_run.preferred_sites("\n a.example \n\nb.example\na.example\n") == ("a.example", "b.example")


def _brief():
    return next(b for b in review_run.BRIEFS if b.id == "land")


def test_exa_excludes_social_media_only_in_the_open_web_pass():
    bodies = []

    def backend(request):
        if str(request.url).endswith("/api/tags"):
            return httpx.Response(200, json={"models": [{"name": "phi4-mini:latest"}]})
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"results": []})

    provider = LocalNarrativeProvider(exa_api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(backend)))
    assert provider.draft_piece(_brief(), start=START, end=TODAY, today=TODAY).no_story
    preferred, web = bodies
    assert preferred["includeDomains"] == list(_brief().preferred_domains) and "excludeDomains" not in preferred
    assert web["excludeDomains"] == list(SOCIAL) and "includeDomains" not in web


def test_the_ibuka_text_is_saved_as_a_found_source_not_one_the_analyst_added():
    sh.real_estate_review()
    saved = [s for s in source_store.list_for(snips.LABELS["reits"], sh.TODAY) if s.title == fetcher.SOURCE_NAME]
    assert len(saved) == 1 and saved[0].origin == "found"
    assert source_store.ADDED_BY_ANALYST not in saved[0].flags
