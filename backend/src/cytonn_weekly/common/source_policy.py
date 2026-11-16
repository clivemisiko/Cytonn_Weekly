from __future__ import annotations

import functools
import json
import re
from typing import Any, Optional

from cytonn_weekly.equities import companies

FILE = companies.FILE.with_name("source_policy.json")   # the team edits this file; a restart picks it up
NAMED, NEWS = "named", "news"


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")


def _under(host: str, domains: Any) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def _hosts(block: dict[str, Any], kind: str) -> tuple[str, ...]:
    raw = block.get(kind) or {}
    return tuple(str(h).strip().lower() for h in (raw.get("hosts") if kind == NEWS else raw) or [])


@functools.lru_cache(maxsize=1)
def _policy() -> dict[str, Any]:
    """The file, read once: the never-read hosts and each section's lists, by slug and by every title it goes by."""
    raw = json.loads(FILE.read_text(encoding="utf-8"))
    sections: dict[str, dict[str, Any]] = {}
    for slug, block in raw["sections"].items():
        entry = {NAMED: _hosts(block, NAMED), NEWS: _hosts(block, NEWS),
                 "pieces": {_norm(label): {NAMED: _hosts(p, NAMED), NEWS: _hosts(p, NEWS)} for label, p in (block.get("pieces") or {}).items()}}
        for name in (slug, *block.get("titles", [])):
            sections[_norm(name)] = entry
    return {"never": tuple(str(h).strip().lower() for h in raw["never_read"]), "sections": sections}


def _clean(host: str) -> str:
    return (host or "").strip().lower().rstrip(".")


def is_never_read(host: str) -> bool:
    return _under(_clean(host), _policy()["never"])


def _lists(section: str, piece: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    entry = _policy()["sections"].get(_norm(section))
    if entry is None:
        return (), ()
    if _norm(section) == "equities":
        try:
            own = next((c for c in companies.load() if c.domain and c.name.casefold() == piece.strip().casefold()), None)
        except (OSError, ValueError):
            own = None
        if own:
            return (own.domain, *own.hosts), ()
    chosen = entry["pieces"].get(_norm(piece), entry)
    return chosen[NAMED], chosen[NEWS]


def kind_for(section: str, piece: str, host: str) -> Optional[str]:
    """May ``host`` be read for this piece of this section, and as which kind: "named", "news" or None (not allowed)."""
    host = _clean(host)
    if not host or is_never_read(host):
        return None
    named, news = _lists(section, piece)
    return NAMED if _under(host, named) else NEWS if _under(host, news) else None


def search_hosts(section: str, piece: str) -> list[str]:
    """The hosts a search for this piece may be limited to (named, then news); empty means no open pass."""
    named, news = _lists(section, piece)
    return [*named, *news]


def is_news(host: str) -> bool:
    """A news site of any section, or one never read: a page or pasted text from it is marked as news."""
    host = _clean(host)
    return is_never_read(host) or any(_under(host, e[NEWS]) for e in _policy()["sections"].values())
