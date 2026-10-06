"""Draft runs started through POST /api/runs, and the events each one has reported so far.

A run is one draft of one section of one report, running in a worker thread.  The
registry keeps, per run, what the screen shows while it runs (common/run_events.py's
events, in order) and, once it ends, the saved review's id.

The registry is a plain dict in process memory, guarded by a lock.  It is NOT persisted:
a server restart loses every run, running or finished, and a run id from before the
restart is simply unknown (404).  Nothing is lost that matters: a finished run's review
is in the database, and the overview shows it.  Only the most recent ``KEEP_ENDED`` ended
runs are kept, so the dict cannot grow without bound; a running run is never dropped.

One run per (report type, period, section) at a time: a second start while the first is
still running is refused (``RunAlreadyRunning``).  The one-draft-at-a-time slot
(api/draft_slot.py) still applies on top of this to every section that calls a provider.
"""

from __future__ import annotations

import json
import threading
import uuid
from typing import Any, Iterator, Optional

from cytonn_weekly.common.run_events import RUN_FAILED, RUN_FINISHED, EventLog, RunEvent

RUNNING = "running"
FINISHED = "finished"
FAILED = "failed"

KEEP_ENDED = 50
SSE_KEEPALIVE_SECONDS = 15.0


class RunAlreadyRunning(Exception):
    """A run of the same report type, period and section has not ended yet."""

    def __init__(self, run: "Run"):
        self.run = run
        super().__init__(run.run_id)


class Run:
    """One draft run.  ``record`` is the observer handed to the builder (``on_event``)."""

    def __init__(self, run_id: str, report_type: str, period: str, section: str, section_title: str, report_title: str):
        self.run_id = run_id
        self.report_type = report_type
        self.period = period
        self.section = section
        self.section_title = section_title
        self.report_title = report_title
        self.status = RUNNING
        self.review_id: Optional[int] = None
        self.is_dev_draft: Optional[bool] = None    # known only once the review exists
        self.dev_mode_label: Optional[str] = None
        self._log = EventLog()
        self._changed = threading.Condition()

    @property
    def key(self) -> tuple[str, str, str]:
        return self.report_type, self.period, self.section

    @property
    def events(self) -> list[RunEvent]:
        return self._log.events

    def record(self, kind: str, label: str = "", detail: Optional[str] = None,
               counts: Optional[dict[str, int]] = None) -> None:
        """Append one event and wake every open stream."""
        with self._changed:
            self._log(kind, label, detail=detail, counts=counts)
            self._changed.notify_all()

    def finish(self, review_id: int, counts: dict[str, int], is_dev_draft: bool, dev_mode_label: Optional[str]) -> None:
        """The review is saved: record it and the closing event together, so no reader sees one without the other."""
        with self._changed:
            self.review_id, self.is_dev_draft, self.dev_mode_label = review_id, is_dev_draft, dev_mode_label
            self.status = FINISHED
            self._log(RUN_FINISHED, self.section_title, counts=counts)
            self._changed.notify_all()

    def fail(self, message: str) -> None:
        with self._changed:
            self.status = FAILED
            self._log(RUN_FAILED, self.section_title, detail=message)
            self._changed.notify_all()

    def to_dict(self) -> dict[str, Any]:
        with self._changed:
            return {
                "run_id": self.run_id, "report_type": self.report_type, "report_title": self.report_title,
                "period": self.period, "section": self.section, "section_title": self.section_title,
                "status": self.status, "review_id": self.review_id, "is_dev_draft": self.is_dev_draft,
                "dev_mode_label": self.dev_mode_label, "events": [e.to_dict() for e in self._log.events],
            }

    def stream(self, keepalive: float = SSE_KEEPALIVE_SECONDS) -> Iterator[str]:
        """Server-Sent Events: every event so far, then each new one as it is recorded, until the run ends.

        Each event is ``event: step`` with the event as JSON in ``data:``.  While nothing
        happens, a ``: keepalive`` comment goes out every ``keepalive`` seconds so proxies
        and the browser keep the connection open.
        """
        sent = 0
        while True:
            with self._changed:
                if len(self._log.events) == sent and self.status == RUNNING:
                    self._changed.wait(timeout=keepalive)
                batch = self._log.events[sent:]
                ended = self.status != RUNNING
            for event in batch:
                yield f"event: step\ndata: {json.dumps(event.to_dict())}\n\n"
            sent += len(batch)
            if ended and not batch:
                return
            if ended:
                continue  # one more pass, in case an event landed between the read and the status
            if not batch:
                yield ": keepalive\n\n"


class RunRegistry:
    """Every run this process knows about.  In memory only: see the module docstring."""

    def __init__(self, keep_ended: int = KEEP_ENDED):
        self._lock = threading.Lock()
        self._runs: dict[str, Run] = {}
        self._keep_ended = keep_ended

    def start(self, report_type: str, period: str, section: str, section_title: str, report_title: str) -> Run:
        """Register a new running run, or raise RunAlreadyRunning if this section of this report has one."""
        with self._lock:
            for run in self._runs.values():
                if run.status == RUNNING and run.key == (report_type, period, section):
                    raise RunAlreadyRunning(run)
            run = Run(uuid.uuid4().hex, report_type, period, section, section_title, report_title)
            self._runs[run.run_id] = run
            ended = [r for r in self._runs.values() if r.status != RUNNING]
            for old in ended[: max(0, len(ended) - self._keep_ended)]:
                del self._runs[old.run_id]
            return run

    def discard(self, run: Run) -> None:
        """Forget a run that was registered but never started (its draft slot was refused)."""
        with self._lock:
            self._runs.pop(run.run_id, None)

    def get(self, run_id: str) -> Optional[Run]:
        with self._lock:
            return self._runs.get(run_id)
