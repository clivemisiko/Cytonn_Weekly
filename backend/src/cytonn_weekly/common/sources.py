from __future__ import annotations

import hashlib
import io
import ipaddress
import json
import logging
import os
import re
import socket
import ssl
import threading
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urljoin, urlsplit

from cytonn_weekly import paths
from cytonn_weekly.common import http
from cytonn_weekly.weekly.week import latest_friday

log = logging.getLogger(__name__)

# The known sites: only a label. A fetch or a paste from any other host is kept too and flagged off_list, so the
# reviewer sees it. A host matches when it is a listed name or a subdomain of one (knightfrank.com covers
# content.knightfrank.com). It is built from the briefs' preferred domains in the section modules and
# real_estate.review_run.PREFERRED_SITES, and a test fails when a brief names a domain this list lacks.
APPROVED_SITES = (
    # Digital Payments: each company's own investor relations site
    "investor.visa.com", "investor.mastercard.com", "ir.americanexpress.com", "investor.pypl.com", "investor.circle.com",
    # Kenyan regulators, the Treasury, Parliament and the statistics office
    "centralbank.go.ke", "knbs.or.ke", "treasury.go.ke", "parliament.go.ke", "kra.go.ke", "epra.go.ke",
    "nse.co.ke", "cma.or.ke",
    # Real Estate: banking and housing bodies, tourism, and the research houses the team named
    "kba.co.ke", "kmrc.co.ke", "housing.go.ke", "bomayangu.go.ke", "tourism.go.ke", "ktb.go.ke",
    "knightfrank.com", "content.knightfrank.com", "knightfrank.co.ke", "hassconsult.co.ke",
    # Multilateral lenders
    "imf.org", "worldbank.org",
    # The team's preferred news sites (real_estate.review_run.PREFERRED_SITES)
    "nation.africa", "businessdailyafrica.com", "standardmedia.co.ke", "bloomberg.com",
)
# Never a source, fetched or pasted (the same list as real_estate.review_run.SOCIAL_DOMAINS, which a test compares).
SOCIAL_DOMAINS = ("x.com", "twitter.com", "facebook.com", "instagram.com", "tiktok.com")

NOT_ON_LIST = "host not on the approved list"       # the off_list flag, on a fetched source and a pasted one
INSECURE = "Not secure: the page could have been altered in transit"   # the insecure flag: fetched over http://
TEXT_FROM_SEARCH = "Text supplied by the search service"   # the text_from_search flag: the page itself could not be read
MAX_BYTES = 5 * 1024 * 1024
MAX_PASTE_CHARS = 200_000
MIN_CHARS = 400        # shorter than this is a stub or an error page, not an article
MAX_HOPS = 3
TIMEOUT = 20.0

NOT_HTTP = "Only http:// and https:// addresses are fetched. Use one of those, or paste the text with its address and date."
CERTIFICATE = ("The certificate of {host} could not be verified, so nothing was fetched. Paste the text with its address and "
               "date instead, or try the http:// version of the address if the site serves one.")
NOT_A_PAGE = "The address at {host} did not answer with a web page or a PDF ({kind}), so nothing was kept. Paste the text with its address and date instead."
SOCIAL = "{host} is a social media site, and social media is never used as a source."
PRIVATE = "{host} points to a private or internal address, so it is not fetched."
LOOKUP = "The address {host} could not be looked up, so nothing was fetched."
REDIRECT = ("{host} redirects to {other}, a different host, and the redirect was not followed. Use the final address, or "
            "paste the text.")
TOO_MANY = "{host} redirected more than {hops} times, so nothing was fetched."
TOO_LARGE = "The page is larger than {mb} MB, so it was not kept. Paste the part you need with its address and date."
NOT_FOUND = "No page was found at that address (HTTP {status}). Check the address."
GATED = ("{host} asked for a login or a subscription (HTTP {status}), so the page could not be read. Paste the text with "
         "its address and date instead.")
ERROR_STATUS = "{host} answered with an error (HTTP {status}), so nothing was kept."
NETWORK = "The page at {host} could not be fetched (a network error or a timeout). Try again, or paste the text."
EMPTY = "The page at {host} has no readable text, so nothing was kept. Paste the text with its address and date instead."
PAYWALL = ("The page at {host} shows a login or subscription prompt instead of the article, so nothing was kept. Paste the "
           "text with its address and date instead.")
SHORT = "The page at {host} has only {n} characters of text, too short to be an article, so nothing was kept."
NO_SUBJECT = "Say which piece this source is for."
NO_URL = "Give the address (URL) of the page the text came from."
BAD_URL = "{url!r} is not a web address; it must start with http:// or https:// and name a site."
NO_DATE = "Give the date of the page as YYYY-MM-DD (for example 2026-11-06)."
BAD_DATE = "{date!r} is not a date; write it as YYYY-MM-DD (for example 2026-11-06)."
NO_TEXT = "Paste the text of the page."
PASTE_TOO_LONG = "The pasted text is longer than {n:,} characters. Paste the part you need."
CHANGED = ("The saved copy of {host} ({source_id}) no longer matches the fingerprint taken when it was saved, so it was not "
           "used. Remove it and add it again.")

_GATED_MARKERS = ("subscribe to continue", "subscribe to read", "sign in to continue", "sign in to read",
                  "log in to continue", "log in to read", "login to continue", "register to continue",
                  "create a free account to", "this article is for subscribers", "subscribers only",
                  "to continue reading")
_DATE_KEYS = {"article:published_time", "og:article:published_time", "datepublished", "pubdate", "publishdate",
              "publish-date", "date", "dc.date", "dc.date.issued", "citation_publication_date", "citation_date",
              "parsely-pub-date"}


class SourceError(ValueError):
    """Written for the coordinator and shown as it stands; never holds a stack trace or a secret."""


@dataclass
class SourceText:
    id: str
    subject: str
    week_end: str                 # the Friday the source is filed under (ISO)
    url: str
    host: str
    title: str
    published_date: str           # ISO date, or "" when the page does not say and nobody typed it
    fetched_at: str               # UTC, ISO with an offset; the screen shows it in East Africa Time
    origin: str                   # "fetched" or "pasted"
    text: str
    sha256: str                   # of the raw bytes fetched, or of the pasted text
    chars: int
    flags: list[str] = field(default_factory=list)

    def meta(self) -> dict[str, Any]:
        """Everything but the text, which is read on its own (GET /api/sources/{id}/text)."""
        out = asdict(self)
        del out["text"]
        return out

    def as_result(self) -> dict[str, Any]:
        """The shape of a search result, plus what the check and the reviewer need."""
        return {"id": self.id, "url": self.url, "title": self.title, "text": self.text, "publishedDate": self.published_date,
                "sha256": self.sha256, "fetched_at": self.fetched_at, "host": self.host, "origin": self.origin,
                "flags": list(self.flags)}


# --- addresses ----------------------------------------------------------------------------------------------------

def subject_key(subject: str) -> str:
    return " ".join(subject.split()).casefold()


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _under(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def is_social(host: str) -> bool:
    return _under(host, SOCIAL_DOMAINS)


def is_approved(host: str) -> bool:
    return _under(host, APPROVED_SITES)


def _certificate_failed(exc: BaseException) -> bool:
    while exc is not None:
        if isinstance(exc, ssl.SSLCertVerificationError):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def _resolve(host: str) -> list[str]:
    return sorted({info[4][0] for info in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)})


def list_flags(host: str) -> list[str]:
    """The off_list flag: one rule for a fetched source and a pasted one."""
    return [] if is_approved(host) else [NOT_ON_LIST]


def _refuse_address(url: str, resolve: Callable[[str], list[str]]) -> str:
    """The host of ``url`` once it passes every rule of a fetch, else SourceError saying which rule it broke.

    Any site may be fetched; the rules are about where the request goes, not which site it is."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise SourceError(BAD_URL.format(url=url)) from None
    host = host_of(url)
    if is_social(host):
        raise SourceError(SOCIAL.format(host=host))
    if parts.scheme not in ("http", "https"):
        raise SourceError(NOT_HTTP)
    if not host or parts.username or parts.password or port not in (None, 80, 443):
        raise SourceError(BAD_URL.format(url=url))
    try:
        addresses = [str(ipaddress.ip_address(host))]      # an address typed as the host is checked as it stands
    except ValueError:
        try:
            addresses = resolve(host)
        except OSError:
            raise SourceError(LOOKUP.format(host=host)) from None
    if not addresses:
        raise SourceError(LOOKUP.format(host=host))
    for a in addresses:
        ip = ipaddress.ip_address(a)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise SourceError(PRIVATE.format(host=host))
    return host


# --- reading a page -----------------------------------------------------------------------------------------------

class _Reader(HTMLParser):
    """The headings, paragraphs, list items and quotations of a page, without its scripts, styles and furniture."""

    SKIP = {"script", "style", "nav", "header", "footer", "noscript", "template", "svg"}
    KEEP = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.block: Optional[list[str]] = None
        self.blocks: list[str] = []
        self.title = ""
        self.og_title = ""
        self.in_title = False
        self.date = ""
        self.time_date = ""

    def _flush(self) -> None:
        if self.block is not None:
            text = " ".join("".join(self.block).split())
            if text:
                self.blocks.append(text)
        self.block = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if key == "og:title":
                self.og_title = a.get("content", "").strip()
            elif key in _DATE_KEYS and not self.date:
                self.date = _iso_date(a.get("content", ""))
        elif tag == "time" and not self.time_date:
            self.time_date = _iso_date(a.get("datetime", ""))
        elif tag == "title":
            self.in_title = True
        elif tag in self.SKIP:
            self.skip += 1
        elif tag in self.KEEP and not self.skip:
            self._flush()
            self.block = []
        elif tag == "br" and self.block is not None:
            self.block.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        elif tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.KEEP and not self.skip:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title += data
        elif self.block is not None and not self.skip:
            self.block.append(data)


def _iso_date(value: str) -> str:
    """A page's own date as YYYY-MM-DD, or "" when it is not plainly one (nothing is guessed)."""
    m = re.match(r"\s*(\d{4})[-/](\d{2})[-/](\d{2})", value or "")
    try:
        return date(int(m[1]), int(m[2]), int(m[3])).isoformat() if m else ""
    except ValueError:
        return ""


def read_html(body: bytes, content_type: str = "") -> tuple[str, str, str, bool]:
    """(text, title, published date, whether the page looks like a login or subscription prompt) of an HTML page."""
    charset = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    try:
        html = body.decode(charset[1] if charset else "utf-8", errors="replace")
    except LookupError:
        html = body.decode("utf-8", errors="replace")
    reader = _Reader()
    reader.feed(html)
    reader._flush()
    text = "\n\n".join(reader.blocks)
    lower = html.lower()
    gated = len(text) < 2500 and (any(m in lower for m in _GATED_MARKERS) or 'type="password"' in lower)
    return text, (reader.og_title or " ".join(reader.title.split())), reader.date or reader.time_date, gated


def read_pdf(body: bytes) -> tuple[str, str]:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(body)) as pdf:
        text = "\n\n".join((page.extract_text() or "").strip() for page in pdf.pages).strip()
        title = str((pdf.metadata or {}).get("Title") or "").strip()
    return text, title


# --- storage ------------------------------------------------------------------------------------------------------

_DEFAULT_ROOT: Optional[Path] = None
_LOCK = threading.Lock()


def sources_root(root: Optional[Path] = None) -> Path:
    return Path(root) if root is not None else (_DEFAULT_ROOT or paths.DATA_DIR / "inputs" / "sources")


def _folder(week_end: date, root: Optional[Path]) -> Path:
    return sources_root(root) / latest_friday(week_end).isoformat()


def _read_manifest(folder: Path) -> list[dict[str, Any]]:
    try:
        return json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["sources"]
    except FileNotFoundError:
        return []
    except (OSError, ValueError, KeyError) as exc:
        raise SourceError(f"The list of saved sources for the week of {folder.name} cannot be read ({type(exc).__name__}). "
                          "Its folder is under inputs/sources in the data folder.") from None


def _write_manifest(folder: Path, sources: list[dict[str, Any]]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / "manifest.json.tmp"
    tmp.write_text(json.dumps({"sources": sources}, indent=2), encoding="utf-8")
    os.replace(tmp, folder / "manifest.json")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _id(subject: str, url: str, sha256: str) -> str:
    return _sha(f"{subject_key(subject)}|{url}|{sha256}".encode())[:8]


def _save(src: SourceText, raw: Optional[bytes], raw_name: str, root: Optional[Path]) -> SourceText:
    """Keep the text (and the raw bytes beside it for a fetched page) and list it; the same source twice is one."""
    folder = _folder(date.fromisoformat(src.week_end), root)
    with _LOCK:
        listed = _read_manifest(folder)
        same = next((m for m in listed if m["id"] == src.id), None)
        if same:
            return _load(folder, same)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{src.id}.txt").write_bytes(src.text.encode())
        if raw is not None:
            (folder / f"{src.id}{raw_name}").write_bytes(raw)
        meta = src.meta()
        meta["text_sha256"] = _sha(src.text.encode())
        meta["raw"] = f"{src.id}{raw_name}" if raw is not None else ""
        _write_manifest(folder, listed + [meta])
    return src


def _load(folder: Path, meta: dict[str, Any]) -> SourceText:
    """One saved source with its text, after checking both files still match what was saved."""
    try:
        text = (folder / f"{meta['id']}.txt").read_bytes().decode("utf-8")   # not read_text, which rewrites line endings
        raw =(folder / meta["raw"]).read_bytes() if meta.get("raw") else None
    except OSError:
        raise SourceError(f"A saved source ({meta.get('host')}, {meta.get('id')}) is missing its file. Remove it and add it "
                          "again.") from None
    expected = _sha(raw) if raw is not None else _sha(text.encode())
    if _sha(text.encode()) != meta.get("text_sha256") or expected != meta["sha256"]:
        raise SourceError(CHANGED.format(host=meta["host"], source_id=meta["id"]))
    fields = {k: meta[k] for k in SourceText.__dataclass_fields__ if k != "text"}
    return SourceText(text=text, **fields)


def list_all(week_end: date, root: Optional[Path] = None) -> list[SourceText]:
    folder = _folder(week_end, root)
    return [_load(folder, m) for m in _read_manifest(folder)]


def list_for(subject: str, week_end: date, root: Optional[Path] = None) -> list[SourceText]:
    """The sources saved for one piece, oldest first.  SourceError if any file changed since it was saved."""
    key = subject_key(subject)
    return [s for s in list_all(week_end, root) if subject_key(s.subject) == key]


def _find(source_id: str, root: Optional[Path]) -> Optional[tuple[Path, dict[str, Any]]]:
    base = sources_root(root)
    for folder in sorted(base.iterdir()) if base.is_dir() else []:
        for m in _read_manifest(folder):
            if m["id"] == source_id:
                return folder, m
    return None


def get(source_id: str, root: Optional[Path] = None) -> Optional[SourceText]:
    found = _find(source_id, root)
    return _load(*found) if found else None


def _read_dismissed(folder: Path) -> list[dict[str, str]]:
    try:
        return json.loads((folder / "dismissed.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):   # absent or unreadable: nothing is dismissed, and the next removal rewrites it
        return []


def dismissed(subject: str, week_end: date, root: Optional[Path] = None) -> set[str]:
    """The addresses removed from a piece's automatically found sources: a later gather does not bring them back."""
    key = subject_key(subject)
    return {d["url"] for d in _read_dismissed(_folder(week_end, root)) if d.get("subject") == key}


def remove(source_id: str, root: Optional[Path] = None) -> bool:
    """Delete one source and its files; False when there is none.  A source found automatically is also recorded in
    dismissed.json (by piece and address) so a later gather skips it; a pasted or fetched-by-hand one is not."""
    with _LOCK:
        found = _find(source_id, root)
        if not found:
            return False
        folder, meta = found
        _write_manifest(folder, [m for m in _read_manifest(folder) if m["id"] != source_id])
        for name in (f"{source_id}.txt", meta.get("raw") or ""):
            if name:
                (folder / name).unlink(missing_ok=True)
        if meta.get("origin") == "found":
            tmp = folder / "dismissed.json.tmp"
            tmp.write_text(json.dumps(_read_dismissed(folder) + [{"subject": subject_key(meta["subject"]), "url": meta["url"]}],
                                      indent=2), encoding="utf-8")
            os.replace(tmp, folder / "dismissed.json")
    return True


# --- adding a source ----------------------------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch_page(url: str, subject: str, week_end: date, *, http_get: Callable[..., http.Reply] = http.http_get_once,
               resolve: Callable[[str], list[str]] = _resolve, root: Optional[Path] = None,
               now: Callable[[], str] = _now, origin: str = "fetched", fallback_date: str = "") -> SourceText:
    """Fetch one page from any site, keep its readable text, and list it for ``subject``.

    ``origin`` is "found" for a page the gather step chose; ``fallback_date`` (YYYY-MM-DD) is the date used only when the
    page states none of its own (a PDF never does).

    ``http_get(url, max_bytes=...)`` answers once and follows nothing (common/http.http_get_once); this function
    follows at most MAX_HOPS redirects itself, each only to the same host, and applies every rule to each address.
    SourceError says, in the coordinator's terms, why a page was not kept.
    ponytail: the address is resolved before the request, so a DNS answer that changes between the two (rebinding) is not
    caught; pin the checked IP in the connection if that matters. TLS is verified by httpx and cannot be turned off.
    """
    if not subject.strip():
        raise SourceError(NO_SUBJECT)
    url = url.strip()
    host = _refuse_address(url, resolve)
    current, hops = url, 0
    while True:
        try:
            reply = http_get(current, max_bytes=MAX_BYTES)
        except http.TooLarge:
            raise SourceError(TOO_LARGE.format(mb=MAX_BYTES // (1024 * 1024))) from None
        except Exception as exc:  # noqa: BLE001 - the coordinator gets a sentence, the log gets the class
            if _certificate_failed(exc):
                raise SourceError(CERTIFICATE.format(host=host)) from None
            log.warning("fetch of %s failed: %s", host, type(exc).__name__)
            raise SourceError(NETWORK.format(host=host)) from None
        if reply.status not in (301, 302, 303, 307, 308):
            break
        target = urljoin(current, reply.headers.get("location", ""))
        other = host_of(target)
        if other != host:
            raise SourceError(REDIRECT.format(host=host, other=other or "an unreadable address"))
        hops += 1
        if hops > MAX_HOPS:
            raise SourceError(TOO_MANY.format(host=host, hops=MAX_HOPS))
        _refuse_address(target, resolve)
        current = target
    if reply.status in (404, 410):
        raise SourceError(NOT_FOUND.format(status=reply.status))
    if reply.status in (401, 402, 403, 451):
        raise SourceError(GATED.format(host=host, status=reply.status))
    if reply.status >= 400 or reply.status < 200:
        raise SourceError(ERROR_STATUS.format(host=host, status=reply.status))
    body = reply.body
    kind = reply.headers.get("content-type", "").split(";")[0].strip().lower()
    if kind and not body.startswith(b"%PDF") and "html" not in kind and "pdf" not in kind:
        raise SourceError(NOT_A_PAGE.format(host=host, kind=kind))
    if body.startswith(b"%PDF"):
        try:
            text, title = read_pdf(body)
        except Exception:  # noqa: BLE001 - pdfplumber raises many kinds for a damaged file
            raise SourceError(EMPTY.format(host=host)) from None
        published, gated, raw_name = "", False, ".pdf"
    else:
        text, title, published, gated = read_html(body, reply.headers.get("content-type", ""))
        raw_name = ".html"
    if not text.strip():
        raise SourceError(PAYWALL.format(host=host) if gated else EMPTY.format(host=host))
    if gated:
        raise SourceError(PAYWALL.format(host=host))
    if len(text) < MIN_CHARS:
        raise SourceError(SHORT.format(host=host, n=len(text)))
    sha = _sha(body)
    src = SourceText(id=_id(subject, current, sha), subject=" ".join(subject.split()),
                     week_end=latest_friday(week_end).isoformat(), url=current, host=host,
                     title=title or current.rsplit("/", 1)[-1] or host, published_date=published or fallback_date,
                     fetched_at=now(), origin=origin, text=text, sha256=sha, chars=len(text),
                     flags=list_flags(host) + ([INSECURE] if current.lower().startswith("http://") else []))
    return _save(src, body, raw_name, root)


def from_paste(url: str, date_text: str, text: str, subject: str, week_end: date, *, title: str = "",
               root: Optional[Path] = None, now: Callable[[], str] = _now, origin: str = "pasted",
               extra_flags: tuple[str, ...] = ()) -> SourceText:
    """Keep text the coordinator pasted, exactly as given, with the address and date they say it came from.
    The gather step uses it with origin "found" and the text_from_search flag for a page it could not fetch."""
    if not subject.strip():
        raise SourceError(NO_SUBJECT)
    url = (url or "").strip()
    if not url:
        raise SourceError(NO_URL)
    parts = urlsplit(url)
    host = host_of(url)
    if parts.scheme not in ("http", "https") or not host:
        raise SourceError(BAD_URL.format(url=url))
    if is_social(host):
        raise SourceError(SOCIAL.format(host=host))
    if not (date_text or "").strip():
        raise SourceError(NO_DATE)
    try:
        published = date.fromisoformat(date_text.strip()).isoformat()
    except ValueError:
        raise SourceError(BAD_DATE.format(date=date_text.strip())) from None
    if not (text or "").strip():
        raise SourceError(NO_TEXT)
    if len(text) > MAX_PASTE_CHARS:
        raise SourceError(PASTE_TOO_LONG.format(n=MAX_PASTE_CHARS))
    sha = _sha(text.encode())
    src = SourceText(id=_id(subject, url, sha), subject=" ".join(subject.split()),
                     week_end=latest_friday(week_end).isoformat(), url=url, host=host,
                     title=" ".join((title or "").split()) or host, published_date=published, fetched_at=now(),
                     origin=origin, text=text, sha256=sha, chars=len(text),
                     flags=list_flags(host) + list(extra_flags))
    return _save(src, None, "", root)
