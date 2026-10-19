"""The previous issue on cytonnreport.com: where the carried-forward paragraphs come from.

Some of a weekly section is Cytonn's own standing text that changes little from week to
week (the Fixed Income closing outlook, the shilling's pressure points, the Equities
outlook).  The tool never writes an opinion, so those paragraphs are carried forward from
the previous issue and flagged "carried forward, edit before approving".

How the previous issue is found (checked 2026-10-09):

* ``/api/series/1/research-reports/<id>`` returns an issue's sections (name, slug, body,
  summary, created_at).  Ids are sequential; an id not yet published answers 404.
* There is no listing endpoint.  ``/series/1`` links the newest issue, and
  ``/api/global/search/<text>`` answers with ``{id, title, url}`` rows, so a page address
  (``/research/<slug>``) resolves to an id by searching for its slug.
* The previous issue of the week ending Friday F is the newest one published on or before
  F (this week's own issue goes out the Sunday after), found by walking ids down from the
  newest and reading each one's ``created_at``.
* The site also holds copies of an issue with the charts stripped out, and the stripped copy can
  have the higher id (850 for 849, 889 for 888, 841 for 840).  The walk skips a candidate that is
  such a twin; see ``STRIPPED_BELOW_IMAGES`` and ``TWIN_WINDOW_DAYS``.  A Markets Review is a
  valid previous issue and is never skipped.

A coordinator can also paste the previous issue's address; it is resolved the same way.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Optional
from urllib.parse import quote, urlparse

from cytonn_weekly.common.http import NotFound, http_get

SOURCE_NAME = "cytonnreport.com"
SITE = "https://cytonnreport.com"
API = f"{SITE}/api/series/1/research-reports"
MAX_WALK = 12   # issues looked at when walking back from the newest

# A twin of an issue is skipped only if BOTH hold: (a) its Fixed Income and Equities sections together hold fewer than
# STRIPPED_BELOW_IMAGES images, and (b) an issue with more images in those two sections was published within TWIN_WINDOW_DAYS
# before it.  An image-light issue with no such twin is kept, and the walk never falls back to an older full issue for it.
# Where the numbers come from (the 53 issues saved 2026-10-15, ids 840 to 892):
#   4: every full weekly of 2026 (35) has at least 6 images in Fixed Income and 2 in Equities, 8 or more together; the stripped
#      copies (841, 850, 860, 875, 876, 889, 890) have 0 or 1.
#   6: the stripped copies were published 0 to 5 days after the full one (849/850: 5, 840/841: 1, 888/889: 1, 860/861: 0,
#      890/891: 0), and a weekly comes every 7 days, so a fuller issue 7 days earlier is last week's, not a twin.
STRIPPED_BELOW_IMAGES = 4
TWIN_WINDOW_DAYS = 6
REVIEW_SECTIONS = ("global-markets", "sub-saharan")   # what a Markets Review has and a weekly has not

Getter = Callable[[str], bytes]


class PreviousIssueError(LookupError):
    """The previous issue could not be found or read."""


@dataclass
class Issue:
    issue_id: int
    published: Optional[date]
    sections: dict[str, dict[str, str]] = field(default_factory=dict)   # slug -> {name, body (html), summary (html)}
    skipped_twins: list[int] = field(default_factory=list)   # ids of stripped copies the lookup passed over to reach this one

    @property
    def url(self) -> str:
        return f"{API}/{self.issue_id}"

    @property
    def kind(self) -> str:
        """"review" for a Markets Review (or the markets outlook, which has the same Global Markets and Africa sections), else "weekly"."""
        return "review" if any(slug.startswith(REVIEW_SECTIONS) for slug in self.sections) else "weekly"

    @property
    def chart_images(self) -> int:
        """The images in the Fixed Income and Equities sections together: what tells a full issue from a stripped copy."""
        return sum(len(re.findall(r"(?i)<img\b", (self.sections.get(slug) or {}).get("body") or "")) for slug in ("fixed-income", "equities"))

    def section(self, *slugs: str) -> Optional[dict[str, str]]:
        return next((self.sections[s] for s in slugs if s in self.sections), None)


def html_paragraphs(body: str) -> list[str]:
    """An issue section's HTML as plain paragraphs, in order (table cells become their own lines)."""
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", body or "")
    text = re.sub(r"\s+", " ", text)   # a line break in the HTML source is a space; only a closing tag ends a paragraph
    text = re.sub(r"(?i)<img[^>]*>", "", text)
    text = re.sub(r"(?i)</(p|tr|li|h\d|div|table|ul|ol|td|th)>|<br\s*/?>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", "", text)).replace("\xa0", " ")
    return [" ".join(line.split()) for line in text.split("\n") if line.strip()]


def parse_issue(issue_id: int, payload: bytes) -> Issue:
    try:
        rows = json.loads(payload.decode("utf-8"))
    except ValueError:
        raise PreviousIssueError(f"cytonnreport.com issue {issue_id} did not answer with JSON")
    if not isinstance(rows, list) or not rows:
        raise PreviousIssueError(f"cytonnreport.com issue {issue_id} has no sections")
    issue = Issue(issue_id, None)
    for row in rows:
        slug = row.get("slug") or ""
        issue.sections[slug] = {"name": row.get("name") or "", "body": row.get("body") or "",
                                "summary": row.get("summary") or ""}
        created = row.get("created_at")
        if created and issue.published is None:
            try:
                issue.published = datetime.strptime(created[:10], "%Y-%m-%d").date()
            except ValueError:
                pass
    return issue


def fetch_issue(issue_id: int, get: Getter = http_get) -> Issue:
    try:
        return parse_issue(issue_id, get(f"{API}/{issue_id}"))
    except NotFound:
        raise PreviousIssueError(f"cytonnreport.com has no issue {issue_id}")


def _search(text: str, get: Getter) -> list[dict[str, Any]]:
    try:
        data = json.loads(get(f"{SITE}/api/global/search/{quote(text, safe='')}").decode("utf-8"))
    except (NotFound, ValueError):
        return []
    return [r for r in (data.get("data") or []) if isinstance(r, dict)]


def resolve_issue_id(reference: str, get: Getter = http_get) -> int:
    """An issue id from what a coordinator pasted: the id itself, an API address, or a page address."""
    ref = (reference or "").strip()
    if ref.isdigit():
        return int(ref)
    m = re.search(r"/research-reports/(\d+)", ref)
    if m:
        return int(m.group(1))
    if re.fullmatch(r"[a-z0-9][a-z0-9-]*", ref):
        slug = ref   # the page's own name, without its address
    else:
        parsed = urlparse(ref if "//" in ref else f"//{ref}")
        if "cytonnreport.com" not in parsed.netloc:
            raise PreviousIssueError(f"{ref!r} is not a cytonnreport.com address")
        slug = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if not slug:
        raise PreviousIssueError(f"{ref!r} names no issue")
    for row in _search(slug, get):
        if str(row.get("url", "")).rstrip("/").endswith(f"/{slug}") and isinstance(row.get("id"), int):
            return row["id"]
    raise PreviousIssueError(f"cytonnreport.com's search does not find the issue page {slug!r}")


def newest_issue_id(get: Getter = http_get) -> int:
    page = get(f"{SITE}/series/1").decode("utf-8", errors="replace")
    slugs = [s for s in re.findall(r'href="/research/([a-z0-9][a-z0-9-]*)"', page)]
    for slug in slugs:
        for row in _search(slug, get):
            if str(row.get("url", "")).rstrip("/").endswith(f"/{slug}") and isinstance(row.get("id"), int):
                return row["id"]
    raise PreviousIssueError("cytonnreport.com's series page links no issue that its search can find")


def _has_fuller_twin(candidate: Issue, candidate_id: int, floor: int, issue_at: Callable[[int], Optional[Issue]]) -> bool:
    """Whether the candidate is a stripped twin: image-light (a) and with a fuller issue shortly before it (b), within the walk."""
    images = candidate.chart_images
    if images >= STRIPPED_BELOW_IMAGES:
        return False
    for other_id in range(candidate_id - 1, floor - 1, -1):
        other = issue_at(other_id)
        if other is None or other.published is None:
            continue
        days_before = (candidate.published - other.published).days
        if days_before > TWIN_WINDOW_DAYS:
            break   # ids rise with time: nothing further down is a twin
        if days_before >= 0 and other.chart_images > images:
            return True
    return False


def find_previous_issue(week_ending: date, get: Getter = http_get, reference: Optional[str] = None) -> Issue:
    """The issue to carry text forward from, for the week ending ``week_ending``.

    With ``reference`` (an id or address the coordinator pasted) it is that issue.  Otherwise
    the newest issue published on or before ``week_ending``, passing over any stripped twin of
    an issue (``skipped_twins`` names them).  PreviousIssueError if none within the newest
    ``MAX_WALK`` ids; the look-ahead for a twin stays inside them too.
    """
    if reference and reference.strip():
        return fetch_issue(resolve_issue_id(reference, get), get)
    newest = newest_issue_id(get)
    floor = max(newest - MAX_WALK + 1, 1)
    seen: dict[int, Optional[Issue]] = {}

    def issue_at(issue_id: int) -> Optional[Issue]:
        if issue_id not in seen:
            try:
                seen[issue_id] = fetch_issue(issue_id, get)
            except PreviousIssueError:
                seen[issue_id] = None   # an empty or unpublished id
        return seen[issue_id]

    skipped: list[int] = []
    for issue_id in range(newest, floor - 1, -1):
        issue = issue_at(issue_id)
        if issue is None or issue.published is None or issue.published > week_ending:
            continue
        if _has_fuller_twin(issue, issue_id, floor, issue_at):
            skipped.append(issue_id)
            continue
        issue.skipped_twins = skipped
        return issue
    raise PreviousIssueError(f"no issue published on or before {week_ending.isoformat()} among the newest {MAX_WALK} "
                             "on cytonnreport.com")
