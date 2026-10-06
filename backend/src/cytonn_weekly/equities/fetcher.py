"""Equities market-performance fetcher (afx.kwayisi.org, free, no access request).

Source choice, checked 2026-10-02 the way the Digital Payments fetcher settled on
Yahoo Finance:

* nse.co.ke/market-statistics/ renders its equity statistics client-side, and
  the daily price list it links (e.g. 01-OCT-26.pdf) is a scanned image with no
  text layer, so neither is scrapeable without OCR.
* afx.kwayisi.org/nse/ serves plain HTML: the NASI close with its one-week and
  year-to-date change, the NSE 10/20/25 and Banking Sector indices' one-week and
  YTD change, and the full daily price list.  Each per-ticker page
  (afx.kwayisi.org/nse/<ticker>.html) adds that stock's 1WK and YTD change.

The index figures are only published inside a prose paragraph, so they are read
with anchored regular expressions; any index the paragraph does not yield gets a
row with an ``error`` (and the checker flags it as missing), never a guess.

afx refreshes during the trading session.  ``as_of`` is the page's own update
time; run after the NSE close (15:00 EAT) or the figures are intraday.
"""

from __future__ import annotations

import html as html_lib
import re
import time
from datetime import datetime
from typing import Any, Callable, Optional

import httpx

from cytonn_weekly.common.formatting import NUMBER, PCT, PRICE, TEXT
from cytonn_weekly.common.http import http_session

BASE = "https://afx.kwayisi.org/nse/"

# A per-ticker failure is isolated (that row carries an error), but afx going dark part-way
# through must not be: each unanswered page waits out the full HTTP timeout, and there are
# ~60 ordinary shares, so a dead site turned one draft into an hour of silent waiting that
# held the API's one draft slot (seen live 2026-10-02: every afx address refused
# connections after the listing page had loaded).  This many network failures in a row
# means the site is down, and the run fails with that reason instead.
MAX_CONSECUTIVE_NETWORK_FAILURES = 3

# Twice now (2026-10-02 and 2026-10-05) afx served the listing page and some ticker pages
# (26 on the 5th), then refused every connection from this machine, kwayisi.org included,
# while other sites loaded.  The fetcher was then opening a new connection per page, five
# a second.  Whether that burst played a part is unknown: afx publishes no limit, and on
# the 5th it then timed out for three outside services as well (all four of its addresses),
# so the site itself was down.  Either way the ~60 pages now go over one connection, a
# second apart (about a minute in all), which costs little and asks less of a small site.
PAUSE_SECONDS = 1.0
_NETWORK_ERRORS = (httpx.TransportError, TimeoutError, ConnectionError)


class SourceUnreachable(RuntimeError):
    """afx stopped answering part-way through the per-ticker pages."""
SOURCE_NAME = "afx.kwayisi.org"

# afx being down (no answer, or an HTTP error status) must not cost the coordinator the
# whole section: the cited highlights do not depend on it.  The review runs catch these,
# and only these, and put each afx table in the draft as an ``unavailable`` part the
# coordinator has to acknowledge.  Anything else (a page that no longer parses, a bug)
# still fails the run, because that is not an outage and a retry will not cure it.
SOURCE_DOWN_ERRORS = (SourceUnreachable, httpx.HTTPError, TimeoutError, ConnectionError)
DOWN_UNBLOCK = (
    f"Draft this section again once {BASE} opens in a browser. A new draft fetches these figures and drafts "
    "the highlights again; this draft cannot be topped up."
)


def down_reason(exc: BaseException) -> str:
    """Why an afx table is missing from a draft, with the real error as one line."""
    error = " ".join(f"{type(exc).__name__}: {exc}".split())
    return (f"{SOURCE_NAME}, the only source of this table, could not be reached when this draft ran ({error}). "
            "Nothing was fetched, so the table is left out rather than filled from anywhere else.")

# (row key, name in the report, name in afx's paragraph)
INDICES: list[tuple[str, str, str]] = [
    ("NASI", "NASI", "NSE All Share Index"),
    ("NSE25", "NSE 25", "NSE 25 Share Index"),
    ("NSE20", "NSE 20", "NSE 20 Share Index"),
    ("NSE10", "NSE 10", "NSE 10 Share Index"),
    ("BANKING", "NSE Banking Sector Index", "NSE Banking Sector Index"),
]

# Precision follows Cytonn Weekly #38.2026 (published 2026-09-27): index levels print to
# 1 dp ("the banking sector index increased by 6.1% to 293.5 from the 276.7"), share
# prices to 1 dp (Universe of Coverage: "Co-op Bank | 34.8 | 37.3 | 7.0%"), and
# changes to 1 dp with parentheses for a fall ("Standard Chartered Bank | ... | (1.9%)").
INDEX_COLUMNS = [
    {"key": "name", "label": "Index", "fmt": TEXT},
    {"key": "close", "label": "Close", "fmt": NUMBER, "decimals": 1},
    {"key": "wow_pct", "label": "w/w %", "fmt": PCT, "decimals": 1},
    {"key": "ytd_pct", "label": "YTD %", "fmt": PCT, "decimals": 1},
]

MOVER_COLUMNS = [
    {"key": "ticker", "label": "Ticker", "fmt": TEXT},
    {"key": "company", "label": "Company", "fmt": TEXT},
    {"key": "price", "label": "Price (KES)", "fmt": PRICE, "decimals": 1},
    {"key": "wow_pct", "label": "w/w %", "fmt": PCT, "decimals": 1},
]

N_MOVERS = 5

# Not ordinary shares: left out of the gainers/losers ranking.
_EXCLUDE_NAME = re.compile(r"\b(ETF|REIT|Preference|Investment Trust|Feeder)\b", re.I)

Getter = Callable[[str], bytes]


def _text(html: str) -> str:
    return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", html)).split())


def _signed(word: str, value: str) -> float:
    v = float(value.replace(",", ""))
    return -v if word in ("loss", "down", "decline") else v


def parse_as_of(html: str) -> Optional[str]:
    m = re.search(r"<time[^>]*datetime=\"?([0-9T:+\-]+)", html)
    return m.group(1) if m else None


def parse_indices(html: str) -> list[dict[str, Any]]:
    """The five index rows from afx's index-performance paragraph."""
    text = _text(html)
    rows: list[dict[str, Any]] = []
    nasi = re.search(
        r"NSE All Share Index \(NASI\) moved (?:up|down) [\d.,]+ \([\d.]+%\) points to close at ([\d,]+\.?\d*), "
        r"representing a one-week (gain|loss) of ([\d.]+)%.*?year-to-date (gain|loss) of ([\d.]+)%",
        text,
    )
    for key, name, afx_name in INDICES:
        row: dict[str, Any] = {"index": key, "name": name, "close": None, "wow_pct": None, "ytd_pct": None,
                               "error": None}
        if key == "NASI":
            if nasi:
                row.update(close=float(nasi.group(1).replace(",", "")), wow_pct=_signed(nasi.group(2), nasi.group(3)),
                           ytd_pct=_signed(nasi.group(4), nasi.group(5)))
            else:
                row["error"] = "NASI sentence not found on the afx index page"
        else:
            m = re.search(re.escape(afx_name) + r" \(([+-]?[\d.]+)%; ([+-]?[\d.]+)% 1WK; ([+-]?[\d.]+)% YTD\)", text)
            if m:
                row.update(wow_pct=float(m.group(2)), ytd_pct=float(m.group(3)))
            else:
                row["error"] = f"{afx_name} not found on the afx index page"
        rows.append(row)
    return rows


def parse_price_list(html: str) -> list[dict[str, Any]]:
    """Every listed security on the index page: ticker, company, last price."""
    out, seen = [], set()
    pattern = re.compile(
        r"<td><a href=https://afx\.kwayisi\.org/nse/([a-z0-9\-]+)\.html title=\"([^\"]+)\">([A-Z0-9\-]+)</a>"
        r"<td><a [^>]+>[^<]*</a><td>[^<]*<td>([\d,]+\.\d+)"
    )
    for m in pattern.finditer(html):
        ticker = m.group(3)
        if ticker in seen:
            continue
        seen.add(ticker)
        out.append({"ticker": ticker, "slug": m.group(1), "company": html_lib.unescape(m.group(2)),
                    "price": float(m.group(4).replace(",", ""))})
    return out


def parse_ticker_perf(html: str) -> dict[str, Optional[float]]:
    """1WK and YTD change from a per-ticker page's performance tables (None where absent)."""
    start = html.find("<div class=t data-perf")  # the bare word also appears in the page's CSS
    if start < 0:
        return {"wow_pct": None, "ytd_pct": None}
    seg = html[start:]
    seg = seg[: seg.find("</div>")] if "</div>" in seg else seg
    heads = re.findall(r"<th[^>]*>([^<]+)", seg)
    vals = re.findall(r"<td[^>]*>([^<]*)", seg)
    perf = dict(zip(heads, vals))

    def pct(k: str) -> Optional[float]:
        v = (perf.get(k) or "").strip().rstrip("%")
        try:
            return float(v) if v else None
        except ValueError:
            return None

    return {"wow_pct": pct("1WK"), "ytd_pct": pct("YTD")}


def ordinary_shares(listing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in listing if "-P" not in r["ticker"] and not _EXCLUDE_NAME.search(r["company"])]


def fetch_market_performance(get: Optional[Getter] = None, pause: float = PAUSE_SECONDS) -> dict[str, Any]:
    """fetch_market_pages() on one kept-open connection unless a ``get`` is given."""
    if get is not None:
        return fetch_market_pages(get, pause)
    with http_session() as session_get:
        return fetch_market_pages(session_get, pause)


def fetch_market_pages(get: Getter, pause: float = PAUSE_SECONDS) -> dict[str, Any]:
    """Index rows, and every ordinary share's weekly change for the gainers/losers tables.

    Returns {"as_of", "source_url", "indices": [...], "shares": [...]}.  A failed
    per-ticker page is recorded in that row's ``error`` and does not stop the rest,
    unless MAX_CONSECUTIVE_NETWORK_FAILURES pages in a row get no answer at all: then
    the site is down, and SourceUnreachable is raised rather than waiting out every
    remaining page's timeout.  (An HTTP error status, or a page that does not parse,
    is an answer: it stays isolated to its row.)
    """
    page = get(BASE).decode("utf-8", errors="replace")
    shares = []
    unanswered = 0
    for r in ordinary_shares(parse_price_list(page)):
        row = {"ticker": r["ticker"], "company": r["company"], "price": r["price"], "wow_pct": None,
               "ytd_pct": None, "error": None}
        try:
            row.update(parse_ticker_perf(get(f"{BASE}{r['slug']}.html").decode("utf-8", errors="replace")))
            unanswered = 0
            if row["wow_pct"] is None:
                row["error"] = "no 1WK figure on the ticker page"
        except _NETWORK_ERRORS as exc:
            unanswered += 1
            if unanswered >= MAX_CONSECUTIVE_NETWORK_FAILURES:
                raise SourceUnreachable(
                    f"{BASE} stopped answering after {len(shares) + 1 - unanswered} of the ticker pages: "
                    f"{unanswered} in a row failed, the last with {type(exc).__name__}: {exc}"
                ) from exc
            row["error"] = f"{type(exc).__name__}: {exc}"
        except Exception as exc:  # noqa: BLE001 - isolate any per-ticker failure
            unanswered = 0
            row["error"] = f"{type(exc).__name__}: {exc}"
        shares.append(row)
        if pause:
            time.sleep(pause)
    return {"as_of": parse_as_of(page), "source_url": BASE, "indices": parse_indices(page), "shares": shares}


def top_movers(shares: list[dict[str, Any]], n: int = N_MOVERS) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(gainers, losers): the n largest weekly rises and falls; ties broken by ticker for a stable order."""
    ok = [s for s in shares if not s.get("error") and s.get("wow_pct") is not None]
    gainers = sorted((s for s in ok if s["wow_pct"] > 0), key=lambda s: (-s["wow_pct"], s["ticker"]))[:n]
    losers = sorted((s for s in ok if s["wow_pct"] < 0), key=lambda s: (s["wow_pct"], s["ticker"]))[:n]
    return gainers, losers


def intraday_warning(as_of: Optional[str]) -> Optional[str]:
    """A warning when afx's update time falls inside NSE trading hours (09:00-15:00 EAT, UTC+3)."""
    if not as_of:
        return "afx page has no update time; cannot confirm the figures are end-of-day"
    try:
        stamp = datetime.fromisoformat(as_of)
    except ValueError:
        return f"afx update time {as_of!r} is unreadable; cannot confirm the figures are end-of-day"
    offset = stamp.utcoffset()
    utc_hour = stamp.hour + stamp.minute / 60 - (offset.total_seconds() / 3600 if offset else 0)  # no offset: read as UTC
    eat_hour = (utc_hour + 3) % 24
    if stamp.weekday() < 5 and 9 <= eat_hour < 15:
        return (f"afx was last updated {as_of}, during NSE trading hours: index and price figures may be "
                "intraday, not the week's close. Re-run after 15:00 EAT.")
    return None
