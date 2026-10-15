"""The shape of one "Notable this week" suggestion (version 1), and the checks every suggestion passes.

A suggestion is a sentence built by code from a template, with the working that produced it and where its history came
from.  It is a note to the analyst, nothing more: no draft, figure, review item, analyst form entry or export ever reads one.

The id is a hash of the kind, section, week, series and window, so the same finding in the same week has the same id
whatever its wording or rank, and a decision the analyst saved still points at it after a restart.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

VERSION = 1
KINDS = ("streak", "record", "since", "trailing_compare", "threshold_cross", "expected_range", "pace", "drift")
PROVENANCE_KINDS = ("published", "approved_review", "analyst_workbook", "typed", "demo")
# Two provenances have one wording only, so a screen can never show them under a kinder name.
FIXED_LABELS = {
    "analyst_workbook": "from the analyst workbook, not verified",
    "demo": "invented demo item",
}
MAX_HEADLINE = 300
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class InvalidSuggestion(ValueError):
    """A suggestion that is incomplete or malformed; the message says which part."""


def _text(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidSuggestion(f"{what} must be a non-empty string")
    return value


def _number(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidSuggestion(f"{what} must be a number")
    return value


def _iso(value: Any, what: str) -> str:
    try:
        if isinstance(value, str) and _DATE.match(value):
            date.fromisoformat(value)
            return value
    except ValueError:
        pass
    raise InvalidSuggestion(f"{what} must be a date written YYYY-MM-DD")


def _dict(value: Any, keys: set[str], what: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise InvalidSuggestion(f"{what} must have exactly {sorted(keys)}")
    return value


@dataclass(frozen=True)
class Suggestion:
    kind: str
    section: str
    week_ending: str
    headline: str
    figures: list
    working: dict
    provenance: dict
    rank: float
    version: int = VERSION

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise InvalidSuggestion(f"kind must be one of {list(KINDS)}")
        _text(self.section, "section")
        _iso(self.week_ending, "week_ending")
        if len(_text(self.headline, "headline").strip()) > MAX_HEADLINE:
            raise InvalidSuggestion(f"headline must be at most {MAX_HEADLINE} characters")
        if not isinstance(self.figures, list):
            raise InvalidSuggestion("figures must be a list")
        for f in self.figures:
            _dict(f, {"label", "value", "display", "unit"}, "a figure")
            _text(f["label"], "a figure's label"), _number(f["value"], "a figure's value"), _text(f["display"], "a figure's display")
            if not isinstance(f["unit"], str):
                raise InvalidSuggestion("a figure's unit must be a string")
        w = _dict(self.working, {"series", "rule", "window", "points"}, "working")
        _text(w["series"], "the working's series"), _text(w["rule"], "the working's rule"), _text(w["window"], "the working's window")
        if not isinstance(w["points"], list) or not w["points"]:
            raise InvalidSuggestion("the working needs at least one point")
        for p in w["points"]:
            _dict(p, {"date", "value", "display"}, "a point")
            _iso(p["date"], "a point's date"), _number(p["value"], "a point's value"), _text(p["display"], "a point's display")
        p = _dict(self.provenance, {"kind", "label"}, "provenance")
        if p["kind"] not in PROVENANCE_KINDS:
            raise InvalidSuggestion(f"provenance kind must be one of {list(PROVENANCE_KINDS)}")
        _text(p["label"], "the provenance label")
        if p["kind"] in FIXED_LABELS and p["label"] != FIXED_LABELS[p["kind"]]:
            raise InvalidSuggestion(f"a {p['kind']} suggestion's provenance label must read {FIXED_LABELS[p['kind']]!r}")
        if not 0 <= _number(self.rank, "rank") <= 100:
            raise InvalidSuggestion("rank must be between 0 and 100")
        if self.version != VERSION:
            raise InvalidSuggestion(f"version must be {VERSION}")

    @property
    def id(self) -> str:
        key = json.dumps([self.kind, self.section, self.week_ending, self.working["series"], self.working["window"]])
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "section": self.section, "week_ending": self.week_ending,
            "headline": self.headline, "figures": copy.deepcopy(self.figures), "working": copy.deepcopy(self.working),
            "provenance": dict(self.provenance), "rank": self.rank, "version": self.version,
        }
