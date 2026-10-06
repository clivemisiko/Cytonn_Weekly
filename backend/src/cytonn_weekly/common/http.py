"""One small GET helper for the public-source fetchers (NSE, afx, CBK).

Every fetcher takes an injectable ``get`` so tests never touch the network; this
is the default.  Plain browser-like User-Agent, because some of these sites drop
requests from unknown clients.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Iterator
from urllib.parse import quote

import httpx

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"
TIMEOUT = 60


class NotFound(Exception):
    """The source answered, but has nothing at this address (HTTP 404, or HTML where a PDF was expected)."""


def safe_url(url: str) -> str:
    """CBK upload paths contain spaces; percent-encode them without touching the rest."""
    return quote(url, safe=":/?&=%#,+")


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT})


def _get(client: httpx.Client, url: str) -> bytes:
    resp = client.get(safe_url(url))
    if resp.status_code == 404:
        raise NotFound(url)
    resp.raise_for_status()
    return resp.content


def http_get(url: str) -> bytes:
    """GET ``url`` and return the body; NotFound on 404, httpx errors for anything else."""
    with _client() as client:
        return _get(client, url)


@contextmanager
def http_session() -> Iterator[Callable[[str], bytes]]:
    """A ``get`` like http_get that keeps one connection open, for a fetcher reading many pages of one site."""
    with _client() as client:
        yield lambda url: _get(client, url)


def http_get_pdf(url: str) -> bytes:
    """Like http_get, but a non-PDF answer (NSE serves an HTML 404 page) is NotFound."""
    body = http_get(url)
    if not body.startswith(b"%PDF"):
        raise NotFound(url)
    return body
