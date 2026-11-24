"""Draft runs kept in the database as they happen: the tables draft_runs, run_events and draft_usage.

api/runs.py writes through here on every status change and event, so a restart, or the registry dropping an old run from
memory, loses nothing.  A storage failure is logged by its class name alone (a database error can name the host) and never
reaches the draft that caused it: every public method returns None instead of raising.
"""

from __future__ import annotations

import functools
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Union

from cytonn_weekly import db
from cytonn_weekly.common.run_events import RUN_FAILED, RunEvent

log = logging.getLogger(__name__)

INTERRUPTED = "interrupted"
ACTIVE = ("queued", "running")
INTERRUPTED_MESSAGE = ("The tool was restarted while this draft was queued or running, so it was stopped. If it had not finished, "
                       "nothing was saved from it: check the overview, then start the draft again if it is not there.")

_RUN_COLUMNS = ("run_id", "report_type", "period", "section", "section_title", "report_title", "status", "started_at",
                "finished_at", "error", "review_id", "is_dev_draft", "dev_mode_label")
_UPSERT_RUN = (f"INSERT INTO draft_runs ({', '.join(_RUN_COLUMNS)}) VALUES ({', '.join('?' * len(_RUN_COLUMNS))}) "
               f"ON CONFLICT (run_id) DO UPDATE SET {', '.join(f'{c} = excluded.{c}' for c in _RUN_COLUMNS[1:])}")
_INSERT_EVENT = ("INSERT INTO run_events (run_id, seq, kind, label, detail, counts_json, event_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                 "ON CONFLICT (run_id, seq) DO NOTHING")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _event_row(run_id: str, e: RunEvent) -> tuple:
    return (run_id, e.seq, e.kind, e.label, e.detail, None if e.counts is None else json.dumps(e.counts), e.at)


def _safe(fn: Callable) -> Callable:
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - a draft must never fail because its record could not be kept
            log.warning("run store: %s failed (%s)", fn.__name__, type(exc).__name__)
            return None
    return wrapper


class RunStore:
    """The run tables of one database (``db_path`` as everywhere: a SQLite file, or None for CYTONN_DATABASE_URL's PostgreSQL)."""

    def __init__(self, db_path: Optional[Union[Path, str]] = None) -> None:
        self.db_path = db_path

    @_safe
    def put_run(self, row: dict[str, Any], event: Optional[RunEvent] = None) -> None:
        """Insert or update the run's row (``_RUN_COLUMNS``), with an event in the same transaction when one comes with it."""
        conn = db.open_db(self.db_path)
        try:
            with conn.transaction():
                conn.execute(_UPSERT_RUN, tuple(row[c] for c in _RUN_COLUMNS))
                if event is not None:
                    conn.execute(_INSERT_EVENT, _event_row(row["run_id"], event))
        finally:
            conn.close()

    @_safe
    def put_event(self, run_id: str, event: RunEvent) -> None:
        conn = db.open_db(self.db_path)
        try:
            with conn.transaction():
                conn.execute(_INSERT_EVENT, _event_row(run_id, event))
        finally:
            conn.close()

    @_safe
    def put_usage(self, run_id: str, usage: dict[str, Any]) -> None:
        """The draft's ``section["usage"]`` (drafting/bedrock.usage_record), saved against the run."""
        conn = db.open_db(self.db_path)
        try:
            with conn.transaction():
                conn.execute(
                    "INSERT INTO draft_usage (run_id, model, calls, input_tokens, output_tokens, calls_without_token_counts, saved_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (run_id) DO NOTHING",
                    (run_id, usage["model"], usage["calls"], usage["input_tokens"], usage["output_tokens"],
                     usage.get("calls_without_token_counts", 0), _now()))
        finally:
            conn.close()

    @_safe
    def delete_run(self, run_id: str) -> None:
        """Forget a run that was registered but never started."""
        conn = db.open_db(self.db_path)
        try:
            with conn.transaction():
                for table in ("run_events", "draft_usage", "draft_runs"):
                    conn.execute(f"DELETE FROM {table} WHERE run_id = ?", (run_id,))
        finally:
            conn.close()

    @_safe
    def load(self, run_id: str) -> Optional[tuple[dict[str, Any], list[RunEvent]]]:
        """(the run's row, its events in order), or None when there is no such run."""
        conn = db.open_db(self.db_path)
        try:
            row = conn.execute("SELECT * FROM draft_runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            events = [RunEvent(seq=r["seq"], kind=r["kind"], label=r["label"], detail=r["detail"], at=r["event_at"],
                               counts=None if r["counts_json"] is None else json.loads(r["counts_json"]))
                      for r in conn.execute("SELECT * FROM run_events WHERE run_id = ? ORDER BY seq", (run_id,))]
            return dict(row), events
        finally:
            conn.close()

    @_safe
    def latest_for(self, report_type: str, period: str, section: str) -> Optional[tuple[dict[str, Any], list[RunEvent]]]:
        """The newest saved run of this section of this report, as ``load`` gives it, or None."""
        conn = db.open_db(self.db_path)
        try:
            row = conn.execute("SELECT run_id FROM draft_runs WHERE report_type = ? AND period = ? AND section = ? "
                               "ORDER BY started_at DESC LIMIT 1", (report_type, period, section)).fetchone()
        finally:
            conn.close()
        return None if row is None else self.load(row["run_id"])

    @_safe
    def interrupt_active(self) -> int:
        """At startup: every run still queued or running belongs to a process that is gone.  Each becomes ``interrupted``, with a
        closing ``run_failed`` event that says so (the kind the run screen already shows as a stop).  Returns how many.

        Known limit: assumes one API process (CLAUDE.md: never a second worker); with two, the second to start would mark the
        first one's live runs.  A process id or heartbeat column is the upgrade if that ever changes.
        """
        now = _now()
        conn = db.open_db(self.db_path)
        try:
            with conn.transaction():
                active = conn.execute("SELECT run_id, section_title FROM draft_runs WHERE status IN ('queued', 'running')").fetchall()
                for r in active:
                    seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM run_events WHERE run_id = ?", (r["run_id"],)).fetchone()["n"]
                    conn.execute(_INSERT_EVENT, (r["run_id"], seq, RUN_FAILED, r["section_title"], INTERRUPTED_MESSAGE, None, now))
                    conn.execute("UPDATE draft_runs SET status = ?, finished_at = ?, error = ? WHERE run_id = ?",
                                 (INTERRUPTED, now, INTERRUPTED_MESSAGE, r["run_id"]))
            return len(active)
        finally:
            conn.close()
