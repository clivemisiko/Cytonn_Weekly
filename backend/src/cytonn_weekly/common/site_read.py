from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import unquote, urldefrag, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from cytonn_weekly.common import sources as store
from cytonn_weekly.weekly.workbook import read_title_date

log = logging.getLogger(__name__)

MAX_START_PAGES = 3    # listing pages read per company
MAX_SAVED = 3          # pages saved per company
MAX_ATTEMPTS = 6       # article pages fetched per company, saved or refused (a page dated outside the week is refused)
PAUSE = 0.5            # seconds between two requests of one company's site
_NEWS = re.compile(r"news|press|announcement|results?\b|earnings|dividend|financial[\s_-]*statements?|investor[\s_-]*presentations?", re.I)
_HUB = re.compile(r"investor|results|news|media|press", re.I)   # where a company with no start page is looked at next
_PERIOD = re.compile(r"ended|ending|period|quarter|half|year|as at|fy|q[1-4]", re.I)   # a date in such a link is the results' period, not the day it was published
_NO_ROBOTS = store.NOT_FOUND.split("{")[0]   # robots.txt answered "not found": nothing is disallowed

ROBOTS_UNREADABLE = "robots.txt could not be read"
Raw = Callable[[str], tuple[str, bytes, str]]


@dataclass
class SiteRead:
    saved: list[store.SourceText]
    note: str = ""   # why the site was not used; empty when it gave pages


class _Links(HTMLParser):
    """The page's text and links in reading order, so a date next to a link can be found."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[tuple[str, str, str]] = []   # ("t", text, "") or ("a", href, anchor text)
        self._href: Optional[str] = None
        self._buf: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "a":
            self._href, self._buf = dict(attrs).get("href") or "", []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag == "a" and self._href is not None:
            self.items.append(("a", self._href, " ".join("".join(self._buf).split())))
            self._href = None

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._href is not None:
            self._buf.append(data)
        else:
            self.items.append(("t", data, ""))


def _gap(items: list[tuple[str, str, str]], i: int, step: int) -> str:
    """The text between link ``i`` and the next link (step 1) or the one before (step -1)."""
    out, j = [], i + step
    while 0 <= j < len(items) and items[j][0] == "t":
        out.append(items[j][1])
        j += step
    text = " ".join("".join(out if step > 0 else out[::-1]).split())
    return text[:40] if step > 0 else text[-40:]


def read_links(body: bytes, base: str) -> list[dict[str, Any]]:
    """Each link of a page as {url, text, day}. The day is the date in the link's own text, else the one date written
    right before or right after it; two different dates around it, or none, leave it None (the page itself is read then)."""
    parser = _Links()
    parser.feed(body.decode("utf-8", errors="replace"))
    out = []
    for i, (kind, href, text) in enumerate(parser.items):
        href = href.strip()
        if kind != "a" or not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        before, after = read_title_date(_gap(parser.items, i, -1)), read_title_date(_gap(parser.items, i, 1))
        own = None if _PERIOD.search(text) else read_title_date(text)
        day = own or (before if after in (None, before) else after if before is None else None)
        out.append({"url": urldefrag(urljoin(base, href))[0], "text": text, "day": day})
    return out


def _allowed(url: str, robots: dict[str, RobotFileParser], raw: Raw) -> bool:
    """Whether robots.txt lets a generic crawler fetch ``url``. A robots.txt that cannot be read raises SourceError."""
    parts = urlsplit(url)
    key = f"{parts.scheme}://{parts.netloc}"
    if key not in robots:
        rules = RobotFileParser()
        try:
            rules.parse(raw(f"{key}/robots.txt")[1].decode("utf-8", errors="replace").splitlines())
        except store.SourceError as exc:
            if not str(exc).startswith(_NO_ROBOTS):
                raise store.SourceError(ROBOTS_UNREADABLE) from None
            rules.parse([])
        robots[key] = rules
    return robots[key].can_fetch("*", url)


def read_site(company: Any, piece: Any, *, fetch: Callable[..., store.SourceText], root: Optional[Path], skip: set[str],
              deadline: float, raw: Raw = store.fetch_raw, sleep: Callable[[float], None] = time.sleep) -> SiteRead:
    """Read a company's own website for pages dated in the piece's window and save up to MAX_SAVED of them.

    robots.txt of each host is read first and a path it disallows is never fetched; a disallowed start page makes the site
    unreadable. Listing pages come from the company's start addresses (its home page when it has none, and from there at
    most two investor, results or news pages). Only links the company owns (host, scope, Kenyan pages) that look like news
    or results are kept, then dated: a link dated outside the week is dropped, one with no date is fetched and dated by its
    page. Never raises: SiteRead.note says why nothing was saved."""
    window = piece.window
    robots: dict[str, RobotFileParser] = {}
    requests = [0]

    def pause() -> None:
        if requests[0]:
            sleep(PAUSE)
        requests[0] += 1

    def get(url: str) -> tuple[str, bytes, str]:
        pause()
        return raw(url)

    try:
        explicit = bool(company.start)
        queue = list(company.start)[:MAX_START_PAGES] or [f"https://{company.domain}{company.scope}/"]
        starts, found, read = len(queue), {}, 0
        i = 0
        while i < len(queue) and time.monotonic() < deadline:
            url, i = queue[i], i + 1
            try:
                if not _allowed(url, robots, raw):
                    if i <= starts:
                        return SiteRead([], f"robots.txt disallows {urlsplit(url).path or '/'}")
                    continue
                final, body, _ = get(url)
            except Exception as exc:  # noqa: BLE001 - a page that cannot be read is skipped; all of them failing is the note
                log.warning("site read: %s: %s", store.host_of(url), type(exc).__name__)
                if i <= starts and str(exc) == ROBOTS_UNREADABLE:
                    return SiteRead([], ROBOTS_UNREADABLE)
                continue
            read += 1
            for link in read_links(body, final):
                u, label = link["url"], f"{link['text']} {unquote(urlsplit(link['url']).path)}"
                if not company.owns(u) or store.is_social(store.host_of(u)) or u in skip or u in queue:
                    continue
                if not explicit and i == 1 and len(queue) < MAX_START_PAGES and _HUB.search(label):
                    queue.append(u)
                elif _NEWS.search(label) and (u not in found or found[u]["day"] is None):
                    found[u] = link
        if not read:
            return SiteRead([], "its pages could not be read")
        first, last = window
        keep = sorted((c for c in found.values() if c["day"] and first <= c["day"] <= last), key=lambda c: c["day"], reverse=True)
        keep += [c for c in found.values() if c["day"] is None and not c["url"].lower().endswith(".pdf")]   # undated: the page itself tells, and is refused if outside the week; a PDF states no date
        saved, attempts = [], 0
        for c in keep:
            if len(saved) >= MAX_SAVED or attempts >= MAX_ATTEMPTS or time.monotonic() > deadline:
                break
            try:
                if not _allowed(c["url"], robots, raw):
                    continue
                attempts += 1
                pause()
                saved.append(fetch(c["url"], piece.subject, piece.end, root=root, origin="found",
                                   fallback_date=c["day"].isoformat() if c["day"] else "", window=window))
            except Exception as exc:  # noqa: BLE001
                log.warning("site read: page of %s not kept: %s", store.host_of(c["url"]), type(exc).__name__)
        if saved:
            return SiteRead(saved)
        return SiteRead([], "no news or results page dated in the week" if keep else "no news or results links found on its pages")
    except Exception as exc:  # noqa: BLE001 - reading a site never fails the gather
        log.warning("site read of %s failed: %s", company.domain, type(exc).__name__)
        return SiteRead([], "its site could not be read")
