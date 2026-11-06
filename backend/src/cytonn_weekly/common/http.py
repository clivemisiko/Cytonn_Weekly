"""One small GET helper for the public-source fetchers (NSE, afx, CBK).

Every fetcher takes an injectable ``get`` so tests never touch the network; this
is the default.  Plain browser-like User-Agent, because some of these sites drop
requests from unknown clients.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator
from urllib.parse import quote

import httpx

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"
TIMEOUT = 30   # one request, including its retry, never holds a draft longer than this


class NotFound(Exception):
    """The source answered, but has nothing at this address (HTTP 404, or HTML where a PDF was expected)."""


def safe_url(url: str) -> str:
    """CBK upload paths contain spaces; percent-encode them without touching the rest."""
    return quote(url, safe=":/?&=%#,+")


def _client() -> httpx.Client:
    # httpx times each phase, and each address a host resolves to, on its own (afx's four addresses took 4 x 60 s)
    return httpx.Client(timeout=httpx.Timeout(TIMEOUT, connect=8), follow_redirects=True, headers={"User-Agent": USER_AGENT})


def _capped(url: str, call: Callable[[], Any]) -> Any:
    """``call()`` within TIMEOUT seconds in all, tried a second time only if the first failed quickly."""
    deadline = time.monotonic() + TIMEOUT
    for attempt in (1, 2):
        pool = ThreadPoolExecutor(1)
        try:
            return pool.submit(call).result(max(deadline - time.monotonic(), 0.1))
        except FutureTimeout:   # ponytail: the abandoned thread ends at httpx's own timeouts
            raise httpx.ConnectTimeout(f"no answer in {TIMEOUT} s", request=httpx.Request("GET", safe_url(url))) from None
        except httpx.TransportError:
            if attempt == 2 or time.monotonic() >= deadline:
                raise
        finally:
            pool.shutdown(wait=False)
    raise AssertionError("unreachable")


def _get(client: httpx.Client, url: str) -> bytes:
    resp = client.get(safe_url(url))
    if resp.status_code == 404:
        raise NotFound(url)
    resp.raise_for_status()
    return resp.content


def http_get(url: str) -> bytes:
    """GET ``url`` and return the body; NotFound on 404, httpx errors for anything else."""
    def once() -> bytes:
        with _client() as client:
            return _get(client, url)

    return _capped(url, once)


def http_head(url: str) -> dict[str, str]:
    """HEAD ``url``: its response headers, names in lower case (size and modification time, without the body)."""
    def once() -> dict[str, str]:
        with _client() as client:
            resp = client.head(safe_url(url))
            if resp.status_code == 404:
                raise NotFound(url)
            resp.raise_for_status()
            return {k.lower(): v for k, v in resp.headers.items()}

    return _capped(url, once)


@contextmanager
def http_session() -> Iterator[Callable[[str], bytes]]:
    """A ``get`` like http_get that keeps one connection open, for a fetcher reading many pages of one site."""
    with _client() as client:
        yield lambda url: _capped(url, lambda: _get(client, url))


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
