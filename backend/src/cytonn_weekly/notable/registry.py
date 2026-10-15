"""Where detectors plug in: a registry of detector functions per section slug, and the one way they are run.

A detector is a function of a small context (the week only, for now) that returns a list of Suggestions.  It is given no
database, no file and no way to write anything: it can only return values.  The real registry is empty; the detectors
come in later tasks.

Each detector is run on its own.  One that raises, returns something that is not a list of Suggestions for this section
and week, or builds an invalid Suggestion, counts as one check that could not run: none of its output is used, the rest
are unaffected, and the panel is told only the count (the reason goes to the server log, never to the screen).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Callable, Mapping, Sequence

from cytonn_weekly.notable.suggestion import Suggestion

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DetectorContext:
    week_ending: date


Detector = Callable[[DetectorContext], Sequence[Suggestion]]

# Section slug -> detectors.  Empty on purpose: the real app has none yet.
REGISTRY: dict[str, list[Detector]] = {}


def run_detectors(registry: Mapping[str, Sequence[Detector]], section: str, ctx: DetectorContext) -> tuple[list[Suggestion], int]:
    """The section's suggestions, highest rank first, and how many detectors could not run."""
    found: dict[str, Suggestion] = {}
    failed = 0
    for detector in registry.get(section, ()):
        try:
            result = detector(ctx)
            if not isinstance(result, (list, tuple)):
                raise TypeError("a detector returns a list of suggestions")
            for s in result:
                if not isinstance(s, Suggestion) or s.section != section or s.week_ending != ctx.week_ending.isoformat():
                    raise ValueError("a detector returns suggestions for its own section and week")
        except Exception as exc:  # noqa: BLE001 - one detector must never break the panel
            failed += 1
            log.warning("notable detector %s for %s could not run: %s: %s", getattr(detector, "__name__", "?"), section, type(exc).__name__, exc)
            continue
        for s in result:
            found.setdefault(s.id, s)
    return sorted(found.values(), key=lambda s: (-s.rank, s.id)), failed
