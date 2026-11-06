"""One small GET helper for the public-source fetchers (NSE, afx, CBK).

Every fetcher takes an injectable ``get`` so tests never touch the network; this
is the default.  Plain browser-like User-Agent, because some of these sites drop
requests from unknown clients.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
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


def http_head(url: str) -> dict[str, str]:
    """HEAD ``url``: its response headers, names in lower case (size and modification time, without the body)."""
    with _client() as client:
        resp = client.head(safe_url(url))
        if resp.status_code == 404:
            raise NotFound(url)
        resp.raise_for_status()
        return {k.lower(): v for k, v in resp.headers.items()}


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


class TooLarge(Exception):
    """The body is longer than the limit the caller set; nothing past it was read."""


@dataclass(frozen=True)
class Reply:
    """One HTTP answer, not followed anywhere: the status, the headers (names in lower case) and the body."""

    status: int
    headers: dict[str, str]
    body: bytes


def http_get_once(url: str, *, max_bytes: int, timeout: float = 20.0) -> Reply:
    """GET ``url`` once: no redirect is followed (the caller checks where it leads), the body stops at ``max_bytes``
    (TooLarge), and any status is an answer, not an error.  Network errors propagate."""
    with httpx.Client(timeout=timeout, follow_redirects=False, headers={"User-Agent": USER_AGENT}) as client:
        with client.stream("GET", safe_url(url)) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
            if (headers.get("content-length") or "0").isdigit() and int(headers["content-length"]) > max_bytes:
                raise TooLarge(url)
            body = bytearray()
            for chunk in resp.iter_bytes():
                body += chunk
                if len(body) > max_bytes:
                    raise TooLarge(url)
            return Reply(resp.status_code, headers, bytes(body))
