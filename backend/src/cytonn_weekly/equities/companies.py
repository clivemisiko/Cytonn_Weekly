from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional

FILE = Path(__file__).with_name("companies.json")   # the team edits this file; a restart picks it up
TO_CONFIRM = "to confirm"
PART = "banks_insurers"
TITLE = "Listed banks and insurers"
KINDS = ("bank", "insurer")
SEARCHES_PER_COMPANY = 1   # one search, restricted to the company's own domain
PAGES_PER_COMPANY = 2      # saved pages per company, so a draft saves at most 2 x the companies with a domain
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
        out.append(Company(r["name"].strip(), r["type"], domain if _HOST.fullmatch(domain) else None, str(r.get("ir") or "").strip()))
    return sorted(out, key=lambda c: (KINDS.index(c.kind), c.name.casefold()))


def domains() -> tuple[str, ...]:
    """The known-sites labels: the domains that are set."""
    return tuple(c.domain for c in load() if c.domain)


def status() -> list[dict[str, Any]]:
    return [{"name": c.name, "type": c.kind, "domain": c.domain or TO_CONFIRM, "ir": c.ir, "set": bool(c.domain)} for c in load()]


def pieces(friday: date) -> list[Any]:
    """One source piece per company with a domain: searched on that domain alone, never on the open web."""
    from cytonn_weekly.source_pieces import Piece

    return [Piece(c.name, friday, domains=(c.domain,), market=False, only_domains=True, max_pages=PAGES_PER_COMPANY)
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
    lines = ["Each company is read from its own website only."]
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
