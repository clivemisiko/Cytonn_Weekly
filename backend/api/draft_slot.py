"""The seats for drafts that call a provider, and who holds them.

A draft takes minutes and (on Anthropic or Bedrock) spends real budget, so the API lets only a few run at once:
``CYTONN_DRAFT_CONCURRENCY`` seats (default 3, 1 to 6).  A run that finds every seat taken waits in a bounded queue
(api/main.py); this module is only the seats.  It used to be a single holder, and still records what the overview shows:
which sections hold a seat and since when.

Seats live in process memory, so the API must be one process (see CLAUDE.md): a second uvicorn worker would have its own
seats and its own queue.  A crash or a restart frees every seat.  A *hang* does not free one: every network call in a
draft has a per-read timeout and none has an overall deadline, so a claim older than ``stale_after`` is treated as stuck
and a draft that finds the seats full takes over the oldest stale one.  Python cannot kill the stuck thread.  If it ever
finishes, ``release`` reports that it no longer holds a seat and the run discards its result rather than saving it, so an
abandoned run can never become a section's latest review over the one that replaced it.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

log = logging.getLogger(__name__)

# A real draft (several LLM calls; a local model on CPU allows 600s per call) can take tens of minutes, so this is
# deliberately generous: well past any healthy run, and past the web client's own 20-minute wait.
DRAFT_STALE_AFTER_SECONDS = 60 * 60

CONCURRENCY_ENV = "CYTONN_DRAFT_CONCURRENCY"
QUEUE_MAX_ENV = "CYTONN_DRAFT_QUEUE_MAX"
DEFAULT_CONCURRENCY = 3
DEFAULT_QUEUE_MAX = 20


def _whole(name: str, default: int, low: int, high: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        n = int(raw)
    except ValueError:
        n = low - 1
    if not low <= n <= high:
        log.warning("%s must be a whole number from %d to %d; the default %d is used", name, low, high, default)
        return default
    return n


def draft_concurrency() -> int:
    return _whole(CONCURRENCY_ENV, DEFAULT_CONCURRENCY, 1, 6)


def draft_queue_max() -> int:
    return _whole(QUEUE_MAX_ENV, DEFAULT_QUEUE_MAX, 0, 200)


@dataclass(frozen=True)
class Claim:
    token: int
    slug: str
    title: str
    started_at: float  # clock() seconds since the epoch
    # Which report the draft is for: the same slug drafts in several report types.
    report_type: str = "weekly"
    period: str = ""


class DraftBusy(Exception):
    """Every seat is taken and none is stale.  ``holder`` is the draft that has held a seat longest."""

    def __init__(self, holder: Claim, elapsed_seconds: int, capacity: int = 1):
        self.holder = holder
        self.elapsed_seconds = elapsed_seconds
        self.capacity = capacity
        super().__init__(holder.slug)


class DraftSlot:
    def __init__(self, capacity: int = 1, stale_after: float = DRAFT_STALE_AFTER_SECONDS,
                 clock: Callable[[], float] = time.time):
        self.capacity = capacity
        self._stale_after = stale_after
        self._clock = clock
        self._mutex = threading.Lock()
        self._held: list[Claim] = []
        self._next_token = 0

    def _is_stale(self, claim: Claim) -> bool:
        return self._clock() - claim.started_at >= self._stale_after

    def claim(self, slug: str, title: str, report_type: str = "weekly",
              period: str = "") -> tuple[Claim, Optional[Claim]]:
        """Take a seat, or raise DraftBusy.  Returns (this claim, the stale claim it replaced, if any)."""
        with self._mutex:
            replaced = None
            if len(self._held) >= self.capacity:
                oldest = min(self._held, key=lambda c: c.started_at)
                if not self._is_stale(oldest):
                    raise DraftBusy(oldest, int(self._clock() - oldest.started_at), self.capacity)
                replaced = oldest
                self._held.remove(oldest)
            self._next_token += 1
            claim = Claim(self._next_token, slug, title, self._clock(), report_type, period)
            self._held.append(claim)
            return claim, replaced

    def release(self, claim: Claim) -> bool:
        """Free the seat if ``claim`` still holds one.  False means it was taken over as stale."""
        with self._mutex:
            if claim in self._held:
                self._held.remove(claim)
                return True
            return False

    def _view(self, claim: Claim) -> dict:
        elapsed = int(self._clock() - claim.started_at)
        return {
            "slug": claim.slug,
            "title": claim.title,
            "report_type": claim.report_type,
            "period": claim.period,
            "started_at": datetime.fromtimestamp(claim.started_at, tz=timezone.utc).isoformat(timespec="seconds"),
            "elapsed_seconds": elapsed,
            "stale": self._is_stale(claim),
            "stale_after_seconds": int(self._stale_after),
        }

    def statuses(self) -> list[dict]:
        """Every held seat, longest first: which sections are drafting, since when, and whether one looks stuck."""
        with self._mutex:
            return [self._view(c) for c in sorted(self._held, key=lambda c: c.started_at)]

    def status(self) -> Optional[dict]:
        """The longest-held seat alone: the overview's older single ``drafting`` key, kept for one release."""
        held = self.statuses()
        return held[0] if held else None


def busy_message(exc: DraftBusy) -> str:
    """The 409 text for the synchronous draft routes (a run waits in the queue instead)."""
    minutes = exc.elapsed_seconds // 60
    since = "under a minute" if minutes < 1 else f"{minutes} min"
    return (
        f"All {exc.capacity} drafting {'seat is' if exc.capacity == 1 else 'seats are'} taken; the longest is "
        f"{exc.holder.title} ({since} so far). Wait for one to finish, then start this one."
    )
