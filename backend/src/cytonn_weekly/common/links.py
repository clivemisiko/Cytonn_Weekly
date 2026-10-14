"""Find text that is, or may be, a web link: text analysis only.

Nothing here fetches, opens or resolves an address, or contacts a domain it finds.  Used on the
coordinator's pasted Company Updates text, so the reviewer sees each link before it is published.

``find_links(text)`` returns each hit with the text matched (hidden characters left out), its
1-based character position in ``text``, a confidence (``LINK`` or ``POSSIBLE``), a kind
(``url``, ``email`` or ``missing``) and the reason.  Rules:

* LINK: an http:// or https:// address; text starting www.; a markdown link [text](url); an HTML
  ``<a href=...>``; a link shortener with a path (bit.ly/..., t.co/..., lnkd.in/...); a bare domain
  followed by a query string (example.co.ke/news?id=3).
* POSSIBLE: a bare domain ending in a known top-level domain, with or without a path (nse.co.ke,
  nse.co.ke/news); an email address; a phrase that points at a link ("click here", "link below",
  "visit our website", ...) when the text holds no other link.
* Never: numbers and decimals, abbreviations (e.g., i.e., Ltd., Mr.), file names (report.pdf), a
  missing space after a full stop ("end.Next"), or a dotted name with no known top-level domain.
  A full stop, comma or unmatched bracket after a link is not part of it; zero-width characters
  inside a link are left out of the match and named; non-Latin letters inside one are named.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LINK = "link"
POSSIBLE = "possible"
URL, EMAIL, MISSING = "url", "email", "missing"

# Characters that do not show but can sit inside an address.
HIDDEN = {chr(c) for c in (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD)}

# Known top-level domains, the longest first so co.ke wins over ke.
TLDS = sorted({
    "co.ke", "go.ke", "or.ke", "ac.ke", "ne.ke", "sc.ke", "me.ke", "info.ke", "mobi.ke", "ke",
    "co.ug", "ug", "co.tz", "tz", "co.rw", "rw", "co.za", "za", "com.ng", "ng", "com.gh", "gh",
    "co.uk", "uk", "com", "org", "net", "io", "info", "biz", "africa", "gov", "edu", "int", "co",
    "news", "online", "site", "tech", "app", "dev", "ai", "us", "eu",
}, key=lambda t: (-t.count("."), -len(t)))
SHORTENERS = ("bit.ly", "t.co", "tinyurl.com", "lnkd.in", "ow.ly", "buff.ly", "goo.gl", "is.gd", "rb.gy", "cutt.ly",
              "shorturl.at", "tiny.cc", "rebrand.ly", "t.ly", "bit.do", "s.id")
POINTERS = ("click here", "click the link", "see the link", "see link", "follow the link", "follow this link",
            "link below", "link above", "link in bio", "via the link", "tap here", "visit our website", "visit our site",
            "visit the website", "on our website")

_LABEL = r"[^\W_](?:[\w-]{0,62}[^\W_])?"
_TLD = "(?:" + "|".join(re.escape(t) for t in TLDS) + ")"
_SHORT = "(?:" + "|".join(re.escape(s) for s in SHORTENERS) + ")"
_REST = r"[^\s<>\"'`]*"

_PATTERNS = (  # (regex, confidence, kind, reason), tried in this order; a later hit inside an earlier one is dropped
    (re.compile(r"<a\b[^>]*?\bhref\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)[^>]*>", re.I), LINK, URL, "an HTML link"),
    (re.compile(r"\[[^\]\n]*\]\(\s*[^)\s]+\s*\)"), LINK, URL, "a markdown link"),
    (re.compile(r"(?<![\w/])https?://" + _REST, re.I), LINK, URL, "a web address starting http:// or https://"),
    (re.compile(r"(?<![\w./@-])www\." + _LABEL + _REST, re.I), LINK, URL, "a web address starting www."),
    (re.compile(r"(?<![\w./@-])" + _SHORT + r"/[\w-]" + _REST, re.I), LINK, URL, "a link shortener"),
    (re.compile(r"(?<![\w.+-])[\w.+-]+@" + _LABEL + r"(?:\." + _LABEL + r")+", re.I), POSSIBLE, EMAIL, "an email address"),
    (re.compile(r"(?<![\w./@-])(?:" + _LABEL + r"\.)+" + _TLD + r"(?![\w-])(?:[/?#]" + _REST + ")?", re.I),
     POSSIBLE, URL, "a domain without http"),
)
_POINTER = re.compile(r"\b(?:" + "|".join(re.escape(p) for p in POINTERS) + r")\b", re.I)
_TRAIL = ".,;:!?'\"*"
_PAIRS = {")": "(", "]": "[", "}": "{"}


@dataclass(frozen=True)
class FoundLink:
    text: str            # what was matched, hidden characters left out
    position: int        # 1-based character position in the text given
    confidence: str      # LINK | POSSIBLE
    kind: str            # URL | EMAIL | MISSING
    reason: str

    @property
    def message(self) -> str:
        label = {(LINK, URL): "Link", (POSSIBLE, URL): "Possible link", (POSSIBLE, EMAIL): "Possible email address",
                 (POSSIBLE, MISSING): "Possible missing link"}[(self.confidence, self.kind)]
        shown = f'"{self.text}"' if self.kind == MISSING else self.text
        return f"{label}: {shown} ({self.reason}), position {self.position}"


def _trim(s: str) -> str:
    """Drop a full stop, comma or closing bracket that ends the sentence rather than the address."""
    while s:
        last = s[-1]
        if last in _TRAIL or (last in _PAIRS and s.count(_PAIRS[last]) < s.count(last)):
            s = s[:-1]
        else:
            break
    return s


def _odd_letters(s: str) -> list[str]:
    return sorted({f"U+{ord(c):04X}" for c in s if c.isalpha() and not c.isascii()})


def find_links(text: str) -> list[FoundLink]:
    text = text or ""
    keep = [i for i, c in enumerate(text) if c not in HIDDEN]     # position in ``clean`` -> position in ``text``
    clean = "".join(text[i] for i in keep)
    spans: list[tuple[int, int]] = []
    found: list[FoundLink] = []
    for pattern, confidence, kind, reason in _PATTERNS:
        for m in pattern.finditer(clean):
            start = m.start()
            matched = m.group(0) if reason in ("an HTML link", "a markdown link") else _trim(m.group(0))
            end = start + len(matched)
            if not matched or any(s < end and start < e for s, e in spans):
                continue
            # a domain followed by a query string is an address, not a bare domain
            level, why = confidence, reason
            if reason == "a domain without http" and "?" in matched:
                level, why = LINK, "an address with a query after a domain"
            first, last = keep[start], keep[end - 1]
            hidden = sorted({f"U+{ord(c):04X}" for c in text[first:last + 1] if c in HIDDEN})
            if hidden:
                why += f"; it holds hidden characters ({', '.join(hidden)}), left out here"
            odd = _odd_letters(matched)
            if odd and kind == URL:
                why += f"; it holds non-Latin letters that can look like Latin ones ({', '.join(odd)})"
            spans.append((start, end))
            found.append(FoundLink(matched, first + 1, level, kind, why))
    if not any(f.kind == URL for f in found):
        for m in _POINTER.finditer(clean):
            found.append(FoundLink(m.group(0), keep[m.start()] + 1, POSSIBLE, MISSING,
                                   "points at a link the text does not hold"))
    return sorted(found, key=lambda f: f.position)


if __name__ == "__main__":   # a quick look: python -m cytonn_weekly.common.links "text"
    import sys
    for hit in find_links(" ".join(sys.argv[1:])):
        print(hit.message)
