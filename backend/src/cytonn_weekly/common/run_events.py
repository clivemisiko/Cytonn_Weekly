"""What a draft run reports about itself while it runs: one small event per real step.

Every draft builder takes an optional ``on_event`` observer (default None).  With None a
builder does exactly what it did before observers existed: every helper here returns at
once, or just calls the function it was given.  With an observer, the builder reports
each thing it really does, when it does it, and nothing else: there is no progress
estimate, no timer and no invented step.

An observer is called as ``on_event(kind, label, detail=None, counts=None)``.  It must
never be able to break a draft, so builders call it only through ``emit``, which swallows
and logs whatever it raises.  ``EventLog`` is the observer that turns those calls into
numbered, timestamped ``RunEvent``s (the review API's run registry uses one per run).

Kinds, and what each one means:

* ``run_started`` / ``run_finished`` / ``run_failed``: the whole draft.  They are emitted
  by whoever runs the builder (the review API), not by the builder, because a run is only
  finished once its review is saved.  ``run_finished`` carries the review's item counts;
  ``run_failed`` carries the error message in ``detail``.
* ``source_started`` / ``source_finished`` / ``source_failed``: one named data source
  (Yahoo Finance, afx.kwayisi.org, a CBK results PDF, KNBS's CPI release).  ``label`` is
  the source's name; ``source_failed`` puts the real reason in ``detail``.
* ``piece_started`` / ``piece_finished``: one drafted narrative piece, or one table.  A
  piece's headline is not known until it is drafted, and the two events must share a label
  to be matched, so a narrative piece is labelled with the theme or company it is drafted
  for (the piece's stored ``topic``) and ``piece_finished`` carries the headline in
  ``detail``.  A table is labelled with its title and only ever finishes: it is built in
  one step from rows already fetched.
* ``part_skipped``: a part of the section that was not produced.  For a blocked stub,
  ``label`` is the part's name and ``detail`` its blocked reason.  It is also what closes a
  ``piece_started`` whose search found nothing to draft that period (``detail`` says so),
  since no other kind says "started, and nothing was drafted".
* ``check_started`` / ``check_finished``: one table's exact-match check, or one drafted
  piece's claims checked against their cited text.  ``check_finished`` carries how many
  review items that check produces per status, using the statuses the review model
  already has (``clean``, ``flagged``, ``not_auto_verified``).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional, TypeVar

log = logging.getLogger(__name__)

RUN_STARTED = "run_started"
SOURCE_STARTED = "source_started"
SOURCE_FINISHED = "source_finished"
SOURCE_FAILED = "source_failed"
PIECE_STARTED = "piece_started"
PIECE_FINISHED = "piece_finished"
PART_SKIPPED = "part_skipped"
CHECK_STARTED = "check_started"
CHECK_FINISHED = "check_finished"
RUN_FINISHED = "run_finished"
RUN_FAILED = "run_failed"

KINDS = (RUN_STARTED, SOURCE_STARTED, SOURCE_FINISHED, SOURCE_FAILED, PIECE_STARTED, PIECE_FINISHED, PART_SKIPPED,
         CHECK_STARTED, CHECK_FINISHED, RUN_FINISHED, RUN_FAILED)
TERMINAL = (RUN_FINISHED, RUN_FAILED)

# The review model's statuses (digital_payments/coordinator_review.py), which the counts are keyed by.
COUNT_KEYS = ("clean", "flagged", "not_auto_verified")

Observer = Callable[..., Any]
T = TypeVar("T")


@dataclass(frozen=True)
class RunEvent:
    seq: int                                  # 1, 2, 3, ... within one run
    kind: str                                 # one of KINDS
    label: str
    detail: Optional[str] = None
    counts: Optional[dict[str, int]] = None   # keys: COUNT_KEYS
    at: str = ""                              # UTC, ISO 8601

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventLog:
    """An observer that records what it is told as numbered ``RunEvent``s.  Safe to call from any thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: list[RunEvent] = []

    def __call__(self, kind: str, label: str = "", detail: Optional[str] = None,
                 counts: Optional[dict[str, int]] = None) -> RunEvent:
        if kind not in KINDS:
            raise ValueError(f"unknown run event kind {kind!r}")
        clean = None if counts is None else {k: int(counts.get(k, 0)) for k in COUNT_KEYS}
        with self._lock:
            event = RunEvent(seq=len(self._events) + 1, kind=kind, label=label, detail=detail or None, counts=clean,
                             at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"))
            self._events.append(event)
        return event

    @property
    def events(self) -> list[RunEvent]:
        with self._lock:
            return list(self._events)


def emit(on_event: Optional[Observer], kind: str, label: str = "", detail: Optional[str] = None,
         counts: Optional[dict[str, int]] = None) -> None:
    """Tell the observer, if there is one.  Whatever it raises is logged and dropped: it must not reach the draft."""
    if on_event is None:
        return
    try:
        on_event(kind, label, detail=detail, counts=counts)
    except Exception:  # noqa: BLE001 - an observer's failure is never the draft's
        log.exception("run event observer failed on %s %r; the draft continues", kind, label)


def describe(exc: BaseException) -> str:
    """An error as one line for ``detail``: its type and message, never a traceback."""
    return " ".join(f"{type(exc).__name__}: {exc}".split())


def fetch_source(on_event: Optional[Observer], label: str, fetch: Callable[..., T], *args: Any) -> T:
    """Call ``fetch(*args)``, reporting it as one named source.  Its result and its errors are untouched."""
    if on_event is None:
        return fetch(*args)
    emit(on_event, SOURCE_STARTED, label)
    try:
        result = fetch(*args)
    except Exception as exc:
        emit(on_event, SOURCE_FAILED, label, detail=describe(exc))
        raise
    emit(on_event, SOURCE_FINISHED, label)
    return result


def report_failed_rows(on_event: Optional[Observer], rows: Iterable[dict[str, Any]],
                       label: Callable[[dict[str, Any]], str]) -> None:
    """A ``source_failed`` for each fetched row that carries an ``error`` (a fetcher isolates one row's failure to that row)."""
    if on_event is None:
        return
    for row in rows:
        if row.get("error"):
            emit(on_event, SOURCE_FAILED, label(row), detail=" ".join(str(row["error"]).split()))


def report_blocks(on_event: Optional[Observer], content: dict[str, Any]) -> None:
    """Report a block-shaped section's tables and computed paragraphs (built) and unavailable parts (skipped), in report order."""
    if on_event is None:
        return
    for b in content.get("blocks", []):
        if b["kind"] in ("table", "computed"):
            emit(on_event, PIECE_FINISHED, b["title"])
        elif b["kind"] == "unavailable":
            emit(on_event, PART_SKIPPED, b["title"], detail=b["reason"])


def status_counts(statuses: Iterable[str]) -> dict[str, int]:
    """How many of each review status, with every key present."""
    counts = dict.fromkeys(COUNT_KEYS, 0)
    for s in statuses:
        counts[s] = counts.get(s, 0) + 1
    return counts


def review_counts(review: Any) -> dict[str, int]:
    """A finished review's items per status: what ``run_finished`` carries."""
    return status_counts(i.status for i in review.review_items)
