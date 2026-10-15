"""Metadata of the cytonnreport.com issues that matter to previous_issue, and a fake site that serves tiny bodies built from it.

Nothing here is page text. Each real issue is one row: (published, kind, section slugs, Fixed Income images, Equities images),
read from the issues as they were saved on 2026-10-15 (ids 840 to 892). The same Fixed Income and Equities image counts are what
previous_issue compares: every full weekly of 2026 has at least 6 images in Fixed Income and 2 in Equities, a stripped copy of an
issue has 0 or 1 and none in Equities. ``None`` is an id the API answers with an empty list (846, 854, 857, 858, 871).
"""

from __future__ import annotations

import json
from datetime import date
from typing import Optional

from cytonn_weekly.common.http import NotFound

WEEKLY_SLUGS = ("company-updates", "fixed-income", "equities", "real-estate", "focus-of-the-week")

# id -> (published, kind, slugs, Fixed Income images, Equities images) | None for an empty id
ISSUES: dict[int, Optional[tuple]] = {
    840: ("2026-01-04", "review", ('company-updates', 'global-markets-review', 'sub-saharan-africa-regional-review', 'kenya-macro-economic-review', 'fixed-income', 'equities', 'real-estate'), 10, 5),
    841: ("2026-01-05", "review", ('company-updates', 'global-markets-review', 'sub-saharan-africa-regional-review', 'kenya-macro-economic-review', 'fixed-income', 'equities', 'real-estate'), 0, 0),
    842: ("2026-01-11", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'focus-of-the-week'), 9, 2),
    843: ("2026-01-18", "review", ('company-updates', 'global-markets', 'sub-saharan-africa-regional-market', 'kenya-macro-economic', 'fixed-income', 'equities', 'real-estate'), 8, 2),
    844: ("2026-01-25", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'focus-of-the-week'), 7, 2),
    845: ("2026-02-01", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate'), 9, 2),
    846: None,
    847: ("2026-02-08", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'focus-of-the-week'), 7, 2),
    848: ("2026-02-15", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'focus-of-the-week'), 8, 2),
    849: ("2026-02-22", "weekly", ('company-updates', 'fixed-income', 'for-more-information-please-check-our-bps-2026-note', 'equities', 'real-estate', 'focus-of-the-week'), 8, 2),
    850: ("2026-02-27", "weekly", ('company-updates', 'fixed-income', 'for-more-information-please-check-our-bps-2026-note', 'equities', 'real-estate', 'focus-of-the-week'), 0, 0),
    851: ("2026-03-01", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate'), 9, 2),
    852: ("2026-03-08", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'focus-of-the-week'), 7, 2),
    853: ("2026-03-15", "weekly", ('fixed-income', 'equities', 'real-estate', 'stablecoins-and-their-potential-applications-in-kenyas-digital-economy'), 7, 2),
    854: None,
    855: ("2026-03-22", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'focus-of-the-week'), 6, 2),
    856: ("2026-03-29", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'focus-of-the-week'), 6, 2),
    857: None,
    858: None,
    859: ("2026-04-05", "review", ('company-updates', 'global-markets-review', 'sub-saharan-africa-region-review', 'kenya-macro-economic-review', 'fixed-income', 'equities', 'real-estate'), 8, 2),
    860: ("2026-04-12", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'focus-of-the-week'), 0, 0),
    861: ("2026-04-12", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'focus-of-the-week'), 8, 2),
    862: ("2026-04-19", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'focus-of-the-week'), 7, 2),
    863: ("2026-04-26", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'focus-of-the-week'), 6, 2),
    864: ("2026-05-03", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate'), 11, 2),
    865: ("2026-05-10", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'stablecoin', 'focus-of-the-week'), 7, 2),
    866: ("2026-05-17", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'stablecoins', 'focus-of-the-week'), 7, 2),
    867: ("2026-05-24", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'digital-payments', 'focus-of-the-week'), 6, 2),
    868: ("2026-05-31", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'digital-payments'), 9, 2),
    869: ("2026-06-07", "other", ('section-i-banking-sector', 'section-ii-insurance-sector', 'section-iii-mobile-money-and-fintech-innovation', 'section-iv-capital-markets-and-investment-services', 'section-v-challenges-facing-the-financial-services-sector-in-sub-sahara-africa', 'section-vii-recommendations-and-conclusion'), 0, 0),
    870: ("2026-06-07", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'digital-payments', 'focus-of-the-week'), 7, 2),
    871: None,
    872: ("2026-06-14", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'digital-payments', 'focus-of-the-week'), 7, 2),
    873: ("2026-06-21", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'digital-payments', 'focus-of-the-week'), 7, 2),
    874: ("2026-06-28", "weekly", ('fixed-income', 'equities', 'real-estate', 'digital-payments', 'kenyas-fy-2026-2027-budget-review'), 6, 2),
    875: ("2026-07-05", "review", ('company-updates', 'global-markets-review', 'sub-saharan-africa-region-review', 'kenya-macro-economic-review', 'fixed-income', 'equities', 'real-estate'), 0, 0),
    876: ("2026-07-05", "review", ('company-updates', 'global-markets-review', 'sub-saharan-africa-region-review', 'kenya-macro-economic-review', 'fixed-income', 'equities', 'real-estate', 'digital-payments'), 0, 0),
    877: ("2026-07-05", "review", ('company-updates', 'global-markets-review', 'sub-saharan-africa-region-review', 'kenya-macro-economic-review', 'fixed-income', 'equities', 'real-estate', 'digital-payments'), 8, 2),
    878: ("2026-07-12", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'digital-payments', 'focus-of-the-week', ''), 9, 2),
    879: ("2026-07-19", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'digital-payments', 'fotw-rise-of-satellite-towns-in-nairobi-metropolitan-area', ''), 7, 2),
    880: ("2026-07-26", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'digital-payments', 'fotw-navigating-markets-in-an-era-of-geopolitical-fragmentation', ''), 6, 2),
    881: ("2026-08-02", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'digital-payments'), 9, 2),
    882: ("2026-08-09", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'digital-payments', 'focus-of-the-week'), 7, 2),
    883: ("2026-08-16", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'digital-payments-weekly-highlights', 'focus-of-the-week'), 7, 2),
    884: ("2026-08-23", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'digital-payments-weekly-highlights', 'focus-of-the-week'), 7, 2),
    885: ("2026-08-30", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'digital-payments-weekly-highlights', 'focus-of-the-week'), 6, 2),
    886: ("2026-09-06", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'digital-payments'), 10, 2),
    887: ("2026-09-13", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'digital-payments', 'focus-of-the-week'), 6, 2),
    888: ("2026-09-20", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'digital-payments', 'focus-of-the-week'), 7, 2),
    889: ("2026-09-21", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'digital-payments', 'focus-of-the-week'), 1, 0),
    890: ("2026-09-27", "weekly", ('fixed-income', 'equities', '', 'digital-payments-weekly-highlights', 'focus-of-the-week'), 0, 0),
    891: ("2026-09-27", "weekly", ('company-updates', 'fixed-income', 'equities', 'real-estate', 'digital-payments-weekly-highlights', 'focus-of-the-week'), 6, 2),
    892: ("2026-10-04", "review", ('company-updates', 'global-markets-review', 'sub-saharan-africa-region-review', 'kenya-macro-economic-review', 'fixed-income', 'equities', 'real-estate', 'digital-payments'), 8, 2),
}

# The one saved stripped copy whose Fixed Income section has no closing "Rates in the fixed income market ..." paragraph (checked
# against the saved issues): the weekly of 27 February 2026 read from id 850 finds no outlook, from 849 it does.
NO_FI_OUTLOOK = {850}
# The two FY'2025 review copies, which have no "The shilling is however expected to remain under pressure" paragraph in Fixed Income or
# in Kenya Macro (checked against the saved issues): the week ending 9 January 2026 has no shilling text from either.
NO_SHILLING = {840, 841}
# The markets outlook issue of 18 January 2026 (843) has no closing Equities outlook paragraph (checked against the saved issue): the
# week ending 23 January 2026 finds no Equities outlook from it.
NO_EQ_OUTLOOK = {843}


def newest_as_of(issues: dict, friday: date) -> int:
    """The newest non-empty id published on or before the day: what /series/1 links when the week's report is drafted."""
    return max(i for i, row in issues.items() if row is not None and date.fromisoformat(row[0]) <= friday)


def body(issue_id: int, slug: str, images: int, outlook: bool = True, shilling: bool = True, eq_outlook: bool = True) -> str:
    """One paragraph (up to two for Fixed Income) and ``images`` img tags: the smallest body the closing-text lookups can read."""
    if slug == "fixed-income":
        paragraphs = ([f"Rates in the fixed income market have declined MTD (issue {issue_id})."] if outlook else []) + (
            ["The shilling is however expected to remain under pressure in 2026 as a result of:"] if shilling else [])
        paragraphs = paragraphs or [f"Fixed Income of issue {issue_id}."]
    elif slug == "equities":
        paragraphs = [f"We maintain a cautiously optimistic short-term outlook (issue {issue_id})."] if eq_outlook else [
            f"Equities of issue {issue_id}."]
    else:
        paragraphs = [f"Section {slug} of issue {issue_id}."]
    return "".join(f"<p>{p}</p>" for p in paragraphs) + '<img src="chart.png" />' * images


def site(issues: dict, newest: int, asked: Optional[list] = None):
    """A fake cytonnreport.com serving ``issues`` (see ISSUES); ``newest`` is the id its series page links; ``asked`` collects
    the issue ids fetched."""

    def get(url: str) -> bytes:
        if url.endswith("/series/1"):
            return b'<a href="/research/newest-issue" class="whites"></a>'
        if "/api/global/search/" in url:
            return json.dumps({"data": [{"id": newest, "title": "t", "url": "/research/newest-issue"}]}).encode()
        issue_id = int(url.rsplit("/", 1)[-1])
        if issue_id not in issues:
            raise NotFound(url)
        if asked is not None:
            asked.append(issue_id)
        row = issues[issue_id]
        if row is None:
            return b"[]"
        published, _kind, slugs, fi, eq = row
        images = {"fixed-income": fi, "equities": eq}
        return json.dumps([
            {"name": slug, "slug": slug, "summary": "", "created_at": f"{published} 12:00:00",
             "body": body(issue_id, slug, images.get(slug, 0), outlook=issue_id not in NO_FI_OUTLOOK,
                          shilling=issue_id not in NO_SHILLING, eq_outlook=issue_id not in NO_EQ_OUTLOOK)}
            for slug in slugs]).encode()

    return get


def weekly_issue(published: str, fi: int, eq: int) -> tuple:
    """A row for a synthetic weekly (the tests that need a case the real issues do not hold)."""
    return (published, "weekly", WEEKLY_SLUGS, fi, eq)

# The 37 weeks previous_issue was replayed over (every 2026 Friday that has a published weekly, 35, and the weeks ending 2 and 9
# October): the id it must return. Three weeks changed when twins were skipped; the other 34 are what it returned before.
WEEKS = [
    ("2026-01-09", 840),  # was 841: the stripped copy
    ("2026-01-23", 843),
    ("2026-01-30", 844),
    ("2026-02-06", 845),
    ("2026-02-13", 847),
    ("2026-02-20", 848),
    ("2026-02-27", 849),  # was 850: the stripped copy
    ("2026-03-06", 851),
    ("2026-03-13", 852),
    ("2026-03-20", 853),
    ("2026-03-27", 855),
    ("2026-04-10", 859),
    ("2026-04-17", 861),
    ("2026-04-24", 862),
    ("2026-05-01", 863),
    ("2026-05-08", 864),
    ("2026-05-15", 865),
    ("2026-05-22", 866),
    ("2026-05-29", 867),
    ("2026-06-05", 868),
    ("2026-06-12", 870),
    ("2026-06-19", 872),
    ("2026-06-26", 873),
    ("2026-07-10", 877),
    ("2026-07-17", 878),
    ("2026-07-24", 879),
    ("2026-07-31", 880),
    ("2026-08-07", 881),
    ("2026-08-14", 882),
    ("2026-08-21", 883),
    ("2026-08-28", 884),
    ("2026-09-04", 885),
    ("2026-09-11", 886),
    ("2026-09-18", 887),
    ("2026-09-25", 888),  # was 889: the stripped copy
    ("2026-10-02", 891),
    ("2026-10-09", 892),
]
