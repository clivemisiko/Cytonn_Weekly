from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Optional

# Flag kinds.
MISMATCH = "mismatch"                # drafted figure != normalized source figure
MISSING = "missing"                  # a sourced figure/row is absent from the draft
UNSOURCED = "unsourced"              # drafted figure exists with no source behind it
SOURCES_DISAGREE = "sources_disagree"  # independent sources differ; human call needed
NOT_IMPLEMENTED = "not_implemented"  # check not built yet (highlight citations, 6b)

_BLANKS = {"", "-", "–", "—", "n/a", "n/m", "na", "none"}


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SourceValue:
    """One independent source's value for a figure (for sources-disagree checks)."""

    source: str
    value: Any


@dataclass
class Flag:
    """One finding for the analyst.  Never an approval, only a flag."""

    kind: str                       # MISMATCH | MISSING | UNSOURCED | SOURCES_DISAGREE | NOT_IMPLEMENTED
    scope: str                      # "table" | "outlook" | "highlight"
    subject: str                    # ticker, "outlook", or highlight headline
    field: Optional[str]            # figure name, or None for a whole row/highlight
    message: str
    drafted: Any = None             # value as drafted (raw, as given)
    expected: Optional[str] = None  # normalized source value, as a string
    source_value: Any = None        # raw source value
    decimals: Optional[int] = None
    # Populated only for SOURCES_DISAGREE: [{"source", "value", "normalized"}, ...]
    sources: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CheckReport:
    flags: list[Flag] = field(default_factory=list)
    checked: int = 0  # figures compared (passes + flagged)

    @property
    def clean(self) -> bool:
        """True only if nothing was flagged.  Not an approval."""
        return not self.flags

    def by_kind(self, kind: str) -> list[Flag]:
        return [f for f in self.flags if f.kind == kind]


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    return isinstance(value, str) and value.strip().lower() in _BLANKS


def parse_number(value: Any) -> Decimal:
    """Parse a number or a display string as the real table prints it.

    Handles "372.7", "6.3%", "(4.0%)" (accounting-style negative), "15.5x", and
    also tolerates "$", "+", thousands commas and a unicode minus.

    Raises ValueError if it cannot be read as a finite number.
    """
    if isinstance(value, bool):
        raise ValueError(f"not a number: {value!r}")
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, (int, float)):
        d = Decimal(repr(value))  # shortest repr avoids binary-float artefacts
    elif isinstance(value, str):
        s = value.strip().replace("−", "-")
        negative = s.startswith("(") and s.endswith(")")
        if negative:
            s = s[1:-1]
        for ch in "$£€,% ":
            s = s.replace(ch, "")
        if s[-1:] in ("x", "X"):
            s = s[:-1]
        if s.startswith("+"):
            s = s[1:]
        try:
            d = Decimal(s)
        except InvalidOperation:
            raise ValueError(f"not a number: {value!r}") from None
        if negative:
            if d < 0 or s.startswith("-"):
                raise ValueError(f"not a number: {value!r}")  # e.g. "(-4.0%)" is ambiguous
            d = -d
    else:
        raise ValueError(f"not a number: {value!r}")
    if not d.is_finite():
        raise ValueError(f"not a finite number: {value!r}")
    return d


def normalize(value: Any, decimals: int) -> Decimal:
    """Source value -> display precision (round half up)."""
    return parse_number(value).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Core comparison
# ---------------------------------------------------------------------------

def check_figure(
    scope: str,
    subject: str,
    field_name: str,
    drafted: Any,
    source_value: Any,
    decimals: int,
    extra_sources: Optional[list[SourceValue]] = None,
    primary_source: str = "primary",
) -> Optional[Flag]:
    """Compare one drafted figure against its normalized source(s).

    Returns None if it passes, else a Flag.  If ``extra_sources`` carry a value
    that normalizes differently from the primary source, the result is a
    SOURCES_DISAGREE flag (a human picks the source) instead of a mismatch.
    """
    common = dict(scope=scope, subject=subject, field=field_name, drafted=drafted, decimals=decimals)

    sources = [SourceValue(primary_source, source_value), *(extra_sources or [])]
    present = [s for s in sources if not _is_blank(s.value)]

    if not present:  # nothing to check against
        if _is_blank(drafted):
            return None
        return Flag(
            kind=UNSOURCED,
            message=f"{field_name} is drafted as {drafted!r} but has no source value",
            **common,
        )

    try:
        normalized = [(s, normalize(s.value, decimals)) for s in present]
    except ValueError as exc:
        return Flag(kind=MISMATCH, message=f"source value unreadable: {exc}", source_value=source_value, **common)

    if len({n for _, n in normalized}) > 1:
        return Flag(
            kind=SOURCES_DISAGREE,
            message=(
                f"{field_name}: sources give different figures at {decimals}dp; "
                "a human call is needed on which to use (this does not imply the draft is wrong)"
            ),
            source_value=source_value,
            sources=[{"source": s.source, "value": s.value, "normalized": str(n)} for s, n in normalized],
            **common,
        )

    expected = normalized[0][1]
    if _is_blank(drafted):
        return Flag(
            kind=MISSING,
            message=f"{field_name} is absent from the draft; source gives {expected}",
            expected=str(expected),
            source_value=source_value,
            **common,
        )
    try:
        drafted_d = parse_number(drafted)
    except ValueError as exc:
        return Flag(
            kind=MISMATCH,
            message=f"drafted value unreadable: {exc}",
            expected=str(expected),
            source_value=source_value,
            **common,
        )
    if drafted_d == expected:
        return None

    extra = ""
    if drafted_d != drafted_d.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP):
        extra = f" (drafted value has more than the {decimals} display decimals)"
    return Flag(
        kind=MISMATCH,
        message=f"{field_name}: drafted {drafted!r} != normalized source {expected}{extra}",
        expected=str(expected),
        source_value=source_value,
        **common,
    )
