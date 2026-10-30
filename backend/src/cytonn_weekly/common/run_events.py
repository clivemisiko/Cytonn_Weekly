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
import os
import re
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional, TypeVar
from urllib.parse import urlsplit

import httpx

from cytonn_weekly import db as database

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


_SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|DATABASE_URL", re.I)
_URL_WITH_CREDENTIALS = re.compile(r"[a-z][a-z0-9+.\-]*://[^\s/?#]*@\S*", re.I)  # scheme://user:password@host... in a message
# A configured value is judged more broadly than a message: a raw / in its password would end the pattern above early.
_CONFIGURED_URL_WITH_CREDENTIALS = re.compile(r"[a-z][a-z0-9+.\-]*://\S*@", re.I)
MIN_SECRET_CHARS = 8    # a shorter value is not removed from a message: it would mangle ordinary words
MIN_PASSWORD_CHARS = 4  # the password inside a URL is removed on its own, at this length or more


def redact(text: str) -> str:
    """``text`` with every configured secret removed: the value of any variable named like a key, token, secret,
    password or database URL; any variable whose value is a URL carrying credentials, and that URL's password on its
    own; and any URL in the text that carries credentials, whether or not it is configured."""
    for name, value in os.environ.items():
        if len(value) < MIN_SECRET_CHARS:
            continue
        has_credentials = _CONFIGURED_URL_WITH_CREDENTIALS.match(value) is not None
        if has_credentials or _SECRET_NAME.search(name):
            text = text.replace(value, "[redacted]")
        if has_credentials:
            try:
                password = urlsplit(value).password or ""
            except ValueError:
                password = ""
            if len(password) >= MIN_PASSWORD_CHARS:
                text = text.replace(password, "[redacted]")
    return _URL_WITH_CREDENTIALS.sub("[redacted]", text)


def safe_describe(exc: BaseException) -> str:
    """``describe`` for a log line: a database driver error is named by its class alone (its message can name the host
    and the user); anything else keeps its message with the secrets removed."""
    if anthropic_problem(exc):
        return f"{type(exc).__name__} (status {exc.status_code})"  # type: ignore[attr-defined]  # the SDK's message quotes the response body
    return type(exc).__name__ if database.is_postgres_error(exc) else redact(describe(exc))


CREDIT_TOO_LOW = "credit balance is too low"
CREDIT_EMPTY = ("The Anthropic credit balance is empty, so drafting cannot continue. Ask whoever manages Billing to add "
                "credit. Trying again will not help until they do.")
ANTHROPIC_PROBLEMS: dict[int, tuple[str, bool]] = {
    401: ("The Anthropic key was not accepted. It may be wrong, revoked or expired. Ask the person who looks after the "
          "server settings to replace it.", False),
    403: ("The Anthropic key is not allowed to do this. Ask the person who looks after the account to check the key's "
          "workspace and permissions.", False),
    429: ("Anthropic is limiting requests right now. Wait a minute and try again. If it keeps happening, the workspace's "
          "monthly limit may be reached.", True),
}


def anthropic_problem(exc: BaseException) -> Optional[tuple[str, bool]]:
    """(the plain sentence, whether trying again can help) for an Anthropic billing, key or limit error, or None.

    The sentence is fixed text, so the key, the request and the response body cannot reach the screen.
    """
    import anthropic  # imported here: only a failed run needs it

    if not isinstance(exc, anthropic.APIStatusError):
        return None
    if exc.status_code == 400:
        return (CREDIT_EMPTY, False) if CREDIT_TOO_LOW in str(exc).lower() else None
    return ANTHROPIC_PROBLEMS.get(exc.status_code)


def user_message(exc: BaseException) -> str:
    """``describe`` for the screen: a connection failure is worded for a coordinator, anything else as ``describe``.

    "ConnectTimeout: _ssl.c:983: The handshake operation timed out" names neither the service nor
    what to do.  httpx's errors, and the Anthropic SDK's, which wrap them, carry the request, so
    the host is named (its address only: the key travels in a header).  A database driver error is
    one of two fixed sentences, by class: its own words can name the host and the user.  An Anthropic
    billing, key or limit error is its fixed sentence (``anthropic_problem``).
    """
    if isinstance(exc, database.DatabaseNotAvailable):
        return str(exc)  # fixed text or the name of a setting, never the driver's words (it is UNREACHABLE for a connection failure)
    if database.is_postgres_error(exc):
        return database.UNREACHABLE if database.is_connection_error(exc) else database.REJECTED
    problem = anthropic_problem(exc)
    if problem:
        return problem[0]
    import anthropic  # imported here: only a failed run needs it

    if not isinstance(exc, (httpx.TransportError, anthropic.APIConnectionError)):
        return redact(describe(exc))  # a built-in ConnectionError says for itself what it was reaching
    try:
        host = exc.request.url.host  # type: ignore[attr-defined]  # httpx raises RuntimeError when none is set
    except Exception:  # noqa: BLE001
        host = None
    slow = isinstance(exc, (httpx.TimeoutException, anthropic.APITimeoutError))
    return (f"Could not reach {host or 'an outside service'}: it {'did not answer in time' if slow else 'could not be reached'}. "
            "Check your internet connection (a VPN, proxy or firewall can block it) and try again.")


def fetch_source(on_event: Optional[Observer], label: str, fetch: Callable[..., T], *args: Any) -> T:
    """Call ``fetch(*args)``, reporting it as one named source.  Its result and its errors are untouched."""
    if on_event is None:
        return fetch(*args)
    emit(on_event, SOURCE_STARTED, label)
    try:
        result = fetch(*args)
    except Exception as exc:
        emit(on_event, SOURCE_FAILED, label, detail=user_message(exc))
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
