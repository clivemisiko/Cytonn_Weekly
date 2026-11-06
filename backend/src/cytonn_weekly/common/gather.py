from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import httpx

from cytonn_weekly import paths
from cytonn_weekly.common import run_events as ev
from cytonn_weekly.common import sources as store
from cytonn_weekly.source_pieces import Piece

log = logging.getLogger(__name__)

KEY_ENV = "EXA_API_KEY"
REFRESH_ENV = "CYTONN_EXA_REFRESH"   # the local path's switch: 1, true or yes ignores cached results
SEARCH_TIMEOUT = 20.0
NOT_CONFIGURED = "The search service is not configured, so no sources were looked for. Add them under Sources."

# (query, first day of the window, domains to restrict to or None) -> Exa's result dicts (url, title, text, publishedDate)
Search = Callable[[str, date, Optional[list[str]]], list[dict[str, Any]]]
Fetch = Callable[..., store.SourceText]


@dataclass(frozen=True)
class Limits:
    enough: int = 3        # a piece with this many saved sources is not searched
    max_queries: int = 2   # per piece
    max_pages: int = 4     # saved per piece, per gather
    seconds: int = 60      # for the whole gather


def limits_from_env() -> Limits:
    def number(name: str, default: int) -> int:
        raw = (os.environ.get(name) or "").strip()
        if not raw:
            return default
        try:
            n = int(raw)
        except ValueError:
            n = 0
        if n < 1:
            log.warning("%s must be a whole number of 1 or more; the default %d is used", name, default)
            return default
        return n

    d = Limits()
    return Limits(number("CYTONN_SOURCES_ENOUGH", d.enough), number("CYTONN_SOURCES_MAX_QUERIES", d.max_queries),
                  number("CYTONN_SOURCES_MAX_PAGES", d.max_pages), number("CYTONN_SOURCES_GATHER_SECONDS", d.seconds))


def search_key_set() -> bool:
    return bool((os.environ.get(KEY_ENV) or "").strip())


def exa_search(query: str, start: date, domains: Optional[list[str]] = None) -> list[dict[str, Any]]:
    """The tool's Exa search (the local provider's request, unchanged), through a results cache in exa_cache/ keyed by the
    query, the domains, the window start and today, so a second look the same day costs nothing."""
    key = "|".join([query, ",".join(domains or []), start.isoformat(), date.today().isoformat()])
    cache = paths.DATA_DIR / "exa_cache" / f"gather_{hashlib.sha256(key.encode()).hexdigest()[:16]}.json"
    if (os.environ.get(REFRESH_ENV) or "").strip().lower() not in ("1", "true", "yes"):
        try:
            return json.loads(cache.read_text(encoding="utf-8"))["results"]
        except (OSError, ValueError, KeyError):
            pass   # absent or unreadable: asked again and rewritten
    from cytonn_weekly.digital_payments.providers.local_provider import LocalProvider   # the request code only; no model call

    with httpx.Client(timeout=SEARCH_TIMEOUT) as client:   # the provider's own client waits 10 minutes, for a local model
        results = LocalProvider(http_client=client)._exa_search(query, start, domains)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"query": query, "results": results}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        log.warning("gather: the search cache could not be written")
    return results


def _usable(pool: Iterable[dict[str, Any]], start: date, end: date, skip: set[str]) -> list[dict[str, Any]]:
    """Results with an address and a date inside the window, no duplicate address, none skipped, newest first."""
    seen: set[str] = set()
    out = []
    for r in pool:
        url = str(r.get("url") or "").strip()
        day = store._iso_date(str(r.get("publishedDate") or ""))
        host = store.host_of(url)
        if not (url and host and day) or url in seen or url in skip or store.is_social(host):
            continue
        if start.isoformat() <= day <= end.isoformat():
            seen.add(url)
            out.append({**r, "url": url, "day": day})
    return sorted(out, key=lambda r: r["day"], reverse=True)


def _save(r: dict[str, Any], piece: Piece, fetch: Fetch, root: Optional[Path]) -> Optional[store.SourceText]:
    """The page itself through fetch_page; if it cannot be read, the text the search returned; else nothing."""
    url = r["url"]
    try:
        return fetch(url, piece.subject, piece.end, root=root, origin="found", fallback_date=r["day"])
    except Exception as exc:  # noqa: BLE001 - one page never stops the gather
        log.warning("gather: fetch of %s failed: %s", store.host_of(url), type(exc).__name__)
    text = str(r.get("text") or "").strip()
    if len(text) < store.MIN_CHARS:
        return None
    flags = (store.TEXT_FROM_SEARCH,) + ((store.INSECURE,) if url.lower().startswith("http://") else ())
    try:
        return store.from_paste(url, r["day"], text, piece.subject, piece.end, title=str(r.get("title") or ""), root=root,
                                origin="found", extra_flags=flags)
    except Exception as exc:  # noqa: BLE001
        log.warning("gather: the search text from %s could not be kept: %s", store.host_of(url), type(exc).__name__)
        return None


def gather_piece(piece: Piece, *, search: Search, fetch: Fetch, root: Optional[Path], limits: Limits, deadline: float,
                 on_event: Optional[ev.Observer] = None) -> list[store.SourceText]:
    """Look for the pages of one piece. The query is the piece's label alone; the window is the piece's own.
    Pass 1 is restricted to the brief's domains; pass 2 is open and runs when pass 1 gave fewer than ``enough`` usable pages
    or the piece has no domains."""
    have = store.list_for(piece.subject, piece.end, root)
    if len(have) >= limits.enough:
        return []
    start, end = piece.window
    skip = {s.url for s in have} | store.dismissed(piece.subject, piece.end, root)
    ev.emit(on_event, ev.SOURCES_LOOKING, piece.subject)
    saved: list[store.SourceText] = []
    queries, pool, failed = 0, [], False
    try:
        for domains in ([list(piece.domains)] if piece.domains else []) + [None]:
            if queries >= limits.max_queries or time.monotonic() > deadline:
                break
            if domains is None and piece.domains and len(_usable(pool, start, end, skip)) >= limits.enough:
                break
            queries += 1
            try:
                pool += search(piece.subject, start, domains)
            except Exception as exc:  # noqa: BLE001 - a failed search leaves the piece without sources, never fails the draft
                failed = True
                log.warning("gather: search failed for %s: %s", piece.subject, type(exc).__name__)
        for r in _usable(pool, start, end, skip)[:limits.max_pages]:
            if time.monotonic() > deadline:
                break
            if got := _save(r, piece, fetch, root):
                saved.append(got)
    finally:
        n = len(saved)
        ev.emit(on_event, ev.SOURCES_FOUND, piece.subject,
                detail=f"{n} page{'' if n == 1 else 's'}" + (" (the search did not answer)" if failed and not n else ""))
        log.info("gather: %s: %d queries, %d results, %d pages saved", piece.subject, queries, len(pool), len(saved))
    return saved


def gather(pieces: Iterable[Piece], *, search: Search = exa_search, fetch: Fetch = store.fetch_page,
           root: Optional[Path] = None, on_event: Optional[ev.Observer] = None,
           limits: Optional[Limits] = None) -> tuple[list[store.SourceText], bool]:
    """(the sources saved, whether a search could be made). Never raises: a piece or a page that fails is logged by host and
    error class and skipped. With the real search and no EXA_API_KEY nothing is searched and one event says so."""
    if search is exa_search and not search_key_set():
        ev.emit(on_event, ev.SOURCES_SEARCH_UNAVAILABLE, "Sources", detail=NOT_CONFIGURED)
        return [], False
    limits = limits or limits_from_env()
    deadline = time.monotonic() + limits.seconds
    saved: list[store.SourceText] = []
    for piece in pieces:
        try:
            saved += gather_piece(piece, search=search, fetch=fetch, root=root, limits=limits, deadline=deadline, on_event=on_event)
        except Exception as exc:  # noqa: BLE001
            log.warning("gather: %s skipped: %s", piece.subject, type(exc).__name__)
    return saved, True
