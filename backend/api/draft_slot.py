"""The one draft that may run at a time, and who holds it.

A draft takes minutes and (in anthropic mode) spends real API budget, so the API lets only
one run at a time across every section.  This used to be a bare ``threading.Lock``, which
had two problems:

* nobody could see it.  A coordinator only learned a draft was running by trying to start
  another and being refused, with no word on which section or for how long (a draft keeps
  running on the server after the browser stops waiting for it, and it is not saved until
  it finishes, so the overview showed nothing either);
* nothing bounded it.  A crash or a server restart does release it (the routes release in
  ``finally``, and the slot lives only in process memory), but a *hang* does not: every
  network call in a draft has a per-read timeout (Anthropic 600s x 3 attempts, Ollama
  600s, httpx 60s) and none has an overall deadline, so a stalled source could hold the
  lock forever, indistinguishable from a slow draft.

So the slot records which section holds it and since when (the overview shows that), and
a claim older than ``stale_after`` is treated as stuck: the next draft takes the slot
over.  Python cannot kill the stuck thread.  If it ever finishes, ``release`` reports that
it no longer holds the slot and the route discards its result rather than saving it, so a
late, abandoned run can never become a section's latest review over the one that replaced
it (which the coordinator may already be reviewing).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

# A real draft (several web-searched LLM calls; a local model on CPU allows 600s per call)
# can take tens of minutes, so this is deliberately generous: well past any healthy run,
# and past the web client's own 20-minute wait.
DRAFT_STALE_AFTER_SECONDS = 60 * 60


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
    """Another draft holds the slot and is not stale."""

    def __init__(self, holder: Claim, elapsed_seconds: int):
        self.holder = holder
        self.elapsed_seconds = elapsed_seconds
        super().__init__(holder.slug)


class DraftSlot:
    def __init__(self, stale_after: float = DRAFT_STALE_AFTER_SECONDS, clock: Callable[[], float] = time.time):
        self._stale_after = stale_after
        self._clock = clock
        self._mutex = threading.Lock()
        self._holder: Optional[Claim] = None
        self._next_token = 0

    def _is_stale(self, claim: Claim) -> bool:
        return self._clock() - claim.started_at >= self._stale_after

    def claim(self, slug: str, title: str, report_type: str = "weekly",
              period: str = "") -> tuple[Claim, Optional[Claim]]:
        """Take the slot, or raise DraftBusy.  Returns (this claim, the stale claim it replaced, if any)."""
        with self._mutex:
            replaced = self._holder
            if replaced is not None and not self._is_stale(replaced):
                raise DraftBusy(replaced, int(self._clock() - replaced.started_at))
            self._next_token += 1
            self._holder = Claim(self._next_token, slug, title, self._clock(), report_type, period)
            return self._holder, replaced

    def release(self, claim: Claim) -> bool:
        """Free the slot if ``claim`` still holds it.  False means it was taken over as stale."""
        with self._mutex:
            if self._holder is not None and self._holder.token == claim.token:
                self._holder = None
                return True
            return False

    def status(self) -> Optional[dict]:
        """What the overview shows: which section is drafting, since when, and whether it looks stuck."""
        with self._mutex:
            holder = self._holder
            if holder is None:
                return None
            elapsed = int(self._clock() - holder.started_at)
            return {
                "slug": holder.slug,
                "title": holder.title,
                "report_type": holder.report_type,
                "period": holder.period,
                "started_at": datetime.fromtimestamp(holder.started_at, tz=timezone.utc).isoformat(timespec="seconds"),
                "elapsed_seconds": elapsed,
                "stale": self._is_stale(holder),
                "stale_after_seconds": int(self._stale_after),
            }


def busy_message(exc: DraftBusy) -> str:
    """The 409 text: which section is drafting and for how long, not just "something is running"."""
    minutes = exc.elapsed_seconds // 60
    since = "under a minute" if minutes < 1 else f"{minutes} min"
    return (
        f"A draft is already running: {exc.holder.title}, for {since}. Only one draft runs at a time, across "
        "every section; it is saved when it finishes, and the overview shows it until then."
    )
