from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlsplit

FILE = Path(__file__).with_name("companies.json")   # the team edits this file; a restart picks it up
TO_CONFIRM = "to confirm"
PART = "banks_insurers"
TITLE = "Listed banks and insurers"
KINDS = ("bank", "insurer")
SEARCHES_PER_COMPANY = 1   # the fallback: one search, restricted to the company's own domain and scope
PAGES_PER_COMPANY = 2      # pages saved from that search
# first path segments that name another country of the same group: such a page is never a Kenyan one
OTHER_COUNTRIES = frozenset({"ug", "tz", "rw", "zm", "ss", "bi", "drc", "cd", "mw", "mz", "et", "ng", "gh", "za", "bw", "ls", "na"})
_HOST = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)+")
FOCUS = ("what this company's own website says this week: the results period, profit or net income, dividend, book "
         "closure and payment dates, and notices to shareholders")
FACTS = ("Write only from what the supplied pages of this company say. State a figure only with the sentence it is in. "
         "Make no comparison with another company, and add nothing from memory.")


@dataclass(frozen=True)
class Company:
    name: str
    kind: str
    domain: Optional[str]   # None while the file says "to confirm"
    ir: str                 # an investor relations address, shown to the analyst and not fetched
    scope: str = ""         # a path prefix that limits the company to its Kenyan pages ("" is the whole site)
    hosts: tuple[str, ...] = ()   # other hostnames that belong to the company
    start: tuple[str, ...] = ()   # full addresses where reading its site begins; none means its home page
    kenya_only: bool = True       # False for a group whose home market is not Kenya (BK Group)

    def owns(self, url: str) -> bool:
        """Whether a link belongs to this company: its host is the domain, a subdomain of it (on the dot, so
        "evilkcbgroup.com" is not kcbgroup.com's) or one of its hosts, the path is inside the scope, and, for a
        Kenyan company, it does not start with another country's code."""
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        if not self.domain or parts.scheme not in ("http", "https"):
            return False
        if not (host == self.domain or host.endswith("." + self.domain) or host in self.hosts):
            return False
        path = parts.path or "/"
        if self.scope and path != self.scope and not path.startswith(self.scope + "/"):
            return False
        first = path.strip("/").split("/")[0].lower()
        return not (self.kenya_only and first in OTHER_COUNTRIES)

    @property
    def id(self) -> str:
        return "company_" + re.sub(r"[^a-z0-9]+", "_", self.name.lower()).strip("_")


def load(path: Path = FILE) -> list[Company]:
    """The companies, banks first then insurers, each group by name (the price list gives no market size for them all)."""
    rows = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for r in rows:
        if r.get("type") not in KINDS or not str(r.get("name") or "").strip():
            raise ValueError(f"companies.json: {r!r} needs a name and a type of bank or insurer")
        domain = str(r.get("domain") or "").strip().lower()
        scope = "/" + str(r.get("scope") or "").strip().strip("/").lower() if str(r.get("scope") or "").strip("/ ") else ""
        hosts = tuple(h for h in (str(x).strip().lower() for x in r.get("hosts") or []) if _HOST.fullmatch(h))
        c = Company(r["name"].strip(), r["type"], domain if _HOST.fullmatch(domain) else None, str(r.get("ir") or "").strip(),
                    scope, hosts, (), r.get("kenya_only", True) is not False)
        base = f"https://{c.domain}/"
        start = tuple(u for u in (urljoin(base, str(x).strip()) for x in r.get("start") or []) if c.owns(u))
        out.append(Company(c.name, c.kind, c.domain, c.ir, c.scope, c.hosts, start, c.kenya_only))
    return sorted(out, key=lambda c: (KINDS.index(c.kind), c.name.casefold()))


def domains() -> tuple[str, ...]:
    """The known-sites labels: the domains that are set."""
    return tuple(h for c in load() if c.domain for h in (c.domain, *c.hosts))


def status() -> list[dict[str, Any]]:
    return [{"name": c.name, "type": c.kind, "domain": c.domain or TO_CONFIRM, "ir": c.ir, "set": bool(c.domain),
             "scope": c.scope} for c in load()]


def pieces(friday: date) -> list[Any]:
    """One source piece per company with a domain: its own website is read first, and a search on that domain (and its
    hosts) is the fallback, never the open web."""
    from cytonn_weekly.source_pieces import Piece

    return [Piece(c.name, friday, domains=(c.domain, *c.hosts), market=False, only_domains=True, max_pages=PAGES_PER_COMPANY, site=c)
            for c in load() if c.domain]


def _brief(c: Company) -> Any:
    from cytonn_weekly.narrative.base import NarrativeBrief

    return NarrativeBrief(id=c.id, section="Equities", label=c.name, focus=FOCUS, words=(60, 140),
                          preferred_domains=(c.domain,) if c.domain else (), context=FACTS)


def _urls(piece: dict[str, Any]) -> set[str]:
    return {u for u in (str(c.get("url") or "").split("#")[0].rstrip("/").lower() for c in piece.get("claims", [])) if u}


def _held_by(piece: dict[str, Any], existing: list[dict[str, Any]]) -> Optional[str]:
    """The topic of an already drafted highlight whose claims cite every page this piece cites, so the event is shown once.
    ponytail: same page address, not same event; a closer match needs the sentences compared."""
    mine = _urls(piece)
    return next((e["topic"] for e in existing if mine and mine <= _urls(e)), None)


ROUTE_TEXT = {"site": "own website read", "search": "search fallback", "nothing": "nothing found"}


def _routes(companies: list[Company], friday: date) -> str:
    """Which route each company's pages came from at the last look: the site read, the search fallback or nothing found,
    with the reason a site was not used. Empty when no company has been looked for."""
    from cytonn_weekly.common import sources as store

    groups: dict[str, list[str]] = {}
    for c in companies:
        look = store.last_look(c.name, friday) if c.domain else None
        if look and look.get("route") in ROUTE_TEXT:
            groups.setdefault(look["route"], []).append(f"{c.name} ({look['note']})" if look.get("note") else c.name)
    return "Route used: " + "; ".join(f"{ROUTE_TEXT[k]}: {', '.join(groups[k])}" for k in ROUTE_TEXT if k in groups) + "." if groups else ""


def part(friday: date, window: tuple[date, date], today: date, provider: Any, existing: list[dict[str, Any]],
         on_event: Any = None) -> tuple[list[dict[str, Any]], list[str]]:
    """(the blocks of the part, warnings).  A company is drafted only from pages already saved for it (the gather step, or the
    analyst); no source means no model call.  Notes in the first block name each company not searched, quiet or shown elsewhere."""
    from cytonn_weekly.common import sources as store
    from cytonn_weekly.common.review import narrative_block
    from cytonn_weekly.narrative.drafter import draft_pieces

    companies = load()
    if not companies:
        return [], []
    drafting = [c for c in companies if c.domain and store.list_for(c.name, friday)]
    drafted = (draft_pieces([_brief(c) for c in drafting], len(drafting), provider=provider, today=today, window=window,
                            on_event=on_event) if drafting else {"pieces": [], "warnings": []})
    by_id = {p["brief_id"]: p for p in drafted["pieces"]}
    blocks, elsewhere, drafted_ids = [], {}, set()
    for c in drafting:
        piece = by_id.get(c.id)
        holder = _held_by(piece, existing) if piece else None
        if holder:
            elsewhere[c.id] = f"{c.name} (in {holder})"
        elif piece:
            drafted_ids.add(c.id)
            blocks.append({**narrative_block(c.id, piece), "part": PART, "company_kind": c.kind})
    unset = [c.name for c in companies if not c.domain]
    quiet = [c.name for c in companies if c.domain and c.id not in drafted_ids and c.id not in elsewhere]
    lines = ["Each company's own website is read for news and results dated in the report week, Kenyan pages only; where a site "
             "cannot be read, a search limited to that site is used."]
    routes = _routes(companies, friday)
    if routes:
        lines.append(routes)
    if unset:
        lines.append("Not searched: website not set: " + ", ".join(unset) + ".")
    if quiet:
        lines.append("Nothing this week: " + ", ".join(quiet) + ".")
    if elsewhere:
        lines.append("Already shown in another part: " + ", ".join(elsewhere.values()) + ".")
    head = {"kind": "computed", "id": "company_notes", "role": "company_notes", "part": PART, "title": TITLE,
            "body_md": "\n\n".join(lines), "figures": [], "sources": [], "notes": []}
    # the drafter's "only n of m" and "nothing qualifying" lines are the quiet companies again, which the notes already name
    return [head, *blocks], [w for w in drafted["warnings"] if not w.startswith("only ") and "nothing qualifying" not in w]
