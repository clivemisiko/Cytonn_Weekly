"""Report jobs: one per (report type, period, section), with the limits it was opened under and its messages in order.

Storage only (tables report_jobs and job_messages).  Nothing here calls a model or a tool: agent/loop.py does, and enforces the three
limits this stores, using the counters and the status kept here.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from cytonn_weekly import db
from cytonn_weekly.common import run_events

log = logging.getLogger(__name__)

MAX_TOOL_CALLS_ENV = "CYTONN_JOB_MAX_TOOL_CALLS"
CALL_BUDGET_ENV = "CYTONN_JOB_CALL_BUDGET"
TOKEN_BUDGET_ENV = "CYTONN_JOB_TOKEN_BUDGET"
# Guesses, meant to be tuned.  Tool calls are per message.  The call budget is model calls over the whole job (a whole Bedrock draft
# is capped at 60 by CYTONN_BEDROCK_MAX_CALLS_PER_DRAFT, so half of that); the token budget is input plus output over the whole job.
DEFAULT_MAX_TOOL_CALLS = 8
DEFAULT_CALL_BUDGET = 30
DEFAULT_TOKEN_BUDGET = 300_000

ROLES = ("user", "assistant", "tool")

IDLE, WORKING, PAUSED = "idle", "working", "paused"
STATUSES = (IDLE, WORKING, PAUSED)
TOOL_CALLS, CALL_BUDGET, TOKEN_BUDGET = "tool_calls", "call_budget", "token_budget"   # why a job is paused
BUDGET_REASONS = (CALL_BUDGET, TOKEN_BUDGET)
# What the analyst's raise button adds to one job's budgets, once per press.  Fixed, not an environment setting: it is a nudge, not a policy.
RAISE_CALLS = 10
RAISE_TOKENS = 100_000


@dataclass(frozen=True)
class JobSettings:
    max_tool_calls: int
    call_budget: int
    token_budget: int


def _setting(name: str, default: int) -> int:
    """A whole number of 1 or more from the environment; unset or blank is the default, a bad value logs one warning and is the default."""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        n = int(raw)
    except ValueError:
        n = 0
    if n < 1:
        log.warning("%s must be a whole number of 1 or more; the default %d is used", name, default)
        return default
    return n


def job_settings() -> JobSettings:
    """The limits as the environment sets them now."""
    return JobSettings(_setting(MAX_TOOL_CALLS_ENV, DEFAULT_MAX_TOOL_CALLS), _setting(CALL_BUDGET_ENV, DEFAULT_CALL_BUDGET),
                       _setting(TOKEN_BUDGET_ENV, DEFAULT_TOKEN_BUDGET))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def open_job(db_path: Optional[Union[Path, str]], report_type: str, period: str, section: str) -> dict[str, Any]:
    """The job for this report, period and section.  The first call makes it and stores the limits in force then; a later call
    returns it as it is, whatever the environment says by now.  ``period`` is the normalized label (report_types.normalize_period)."""
    s = job_settings()
    conn = db.open_db(db_path)
    try:
        with conn.transaction():
            conn.execute(
                "INSERT INTO report_jobs (report_type, period, section, max_tool_calls, call_budget, token_budget, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (report_type, period, section) DO NOTHING",
                (report_type, period, section, s.max_tool_calls, s.call_budget, s.token_budget, _now()))
            return dict(conn.execute("SELECT * FROM report_jobs WHERE report_type = ? AND period = ? AND section = ?",
                                     (report_type, period, section)).fetchone())
    finally:
        conn.close()


def get_job(db_path: Optional[Union[Path, str]], job_id: int) -> dict[str, Any]:
    conn = db.open_db(db_path)
    try:
        row = conn.execute("SELECT * FROM report_jobs WHERE job_id = ?", (job_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise LookupError(f"there is no job {job_id}")
    return dict(row)


def begin(db_path: Optional[Union[Path, str]], job_id: int) -> bool:
    """Mark the job working, unless it already is.  False means another worker has it: the caller must not run the loop."""
    conn = db.open_db(db_path)
    try:
        with conn.transaction():
            return conn.execute("UPDATE report_jobs SET status = ?, paused_reason = NULL WHERE job_id = ? AND status != ?",
                                (WORKING, job_id, WORKING)).rowcount == 1
    finally:
        conn.close()


def finish(db_path: Optional[Union[Path, str]], job_id: int, paused_reason: Optional[str] = None) -> None:
    """The loop is done: the job is idle, or paused with the reason (tool_calls, call_budget or token_budget)."""
    if paused_reason is not None and paused_reason not in (TOOL_CALLS, *BUDGET_REASONS):
        raise ValueError(f"unknown pause reason {paused_reason!r}")
    conn = db.open_db(db_path)
    try:
        with conn.transaction():
            conn.execute("UPDATE report_jobs SET status = ?, paused_reason = ? WHERE job_id = ?",
                         (IDLE if paused_reason is None else PAUSED, paused_reason, job_id))
    finally:
        conn.close()


def add_usage(db_path: Optional[Union[Path, str]], job_id: int, input_tokens: int, output_tokens: int) -> None:
    """One model call made, with the tokens it reported (0 when the reply stated none)."""
    conn = db.open_db(db_path)
    try:
        with conn.transaction():
            conn.execute("UPDATE report_jobs SET calls_used = calls_used + 1, input_tokens = input_tokens + ?, "
                         "output_tokens = output_tokens + ? WHERE job_id = ?", (input_tokens, output_tokens, job_id))
    finally:
        conn.close()


def raise_budget(db_path: Optional[Union[Path, str]], job_id: int, on_event: Optional[run_events.Observer] = None) -> dict[str, Any]:
    """Add RAISE_CALLS and RAISE_TOKENS to this job's budgets and clear the pause.  Only a job paused on a budget may be raised,
    so a stray press cannot lift the limits of a job that has not hit them.  Logged as a ``budget_raised`` run event."""
    conn = db.open_db(db_path)
    try:
        with conn.transaction():
            if conn.execute("UPDATE report_jobs SET call_budget = call_budget + ?, token_budget = token_budget + ?, "
                            "budget_raises = budget_raises + 1, status = ?, paused_reason = NULL "
                            "WHERE job_id = ? AND status = ? AND paused_reason IN (?, ?)",
                            (RAISE_CALLS, RAISE_TOKENS, IDLE, job_id, PAUSED, *BUDGET_REASONS)).rowcount != 1:
                raise ValueError("Only a job that stopped at its call or token budget can be given more.")
    finally:
        conn.close()
    job = get_job(db_path, job_id)
    run_events.emit(on_event, run_events.BUDGET_RAISED, f"job {job_id}",
                    detail=f"Added {RAISE_CALLS} model calls and {RAISE_TOKENS} tokens. Budgets are now {job['call_budget']} calls "
                           f"and {job['token_budget']} tokens.")
    return job


def add_message(db_path: Optional[Union[Path, str]], job_id: int, role: str, content: str,
                tool_name: Optional[str] = None, tool_result: Optional[str] = None, *, tool_use_id: Optional[str] = None,
                tool_input: Optional[Any] = None, usage: Optional[dict[str, Any]] = None,
                cards: Optional[list[dict[str, Any]]] = None) -> int:
    """Append one message to the job and return its number (1, 2, ...).  ``tool_name``, ``tool_result``, ``tool_use_id`` and
    ``tool_input`` are for a tool turn; ``usage`` is the model's token use for an assistant turn it wrote; ``cards`` are the cards
    shown with an assistant turn.  The last three are stored as JSON.

    ponytail: the number is the highest so far plus one, read in the same transaction; two writers to one job at the same moment
    would collide on the primary key and the second would fail.  One writer per job is the design; a retry is the upgrade.
    """
    if role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}, not {role!r}")
    conn = db.open_db(db_path)
    try:
        with conn.transaction():
            if conn.execute("SELECT 1 FROM report_jobs WHERE job_id = ?", (job_id,)).fetchone() is None:
                raise LookupError(f"there is no job {job_id}")
            seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM job_messages WHERE job_id = ?", (job_id,)).fetchone()["n"]
            conn.execute("INSERT INTO job_messages (job_id, seq, role, content, tool_name, tool_result, created_at, tool_use_id, "
                         "tool_input, usage, cards) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (job_id, seq, role, content, tool_name, tool_result, _now(), tool_use_id,
                          None if tool_input is None else json.dumps(tool_input), None if usage is None else json.dumps(usage),
                          None if cards is None else json.dumps(cards)))
            return seq
    finally:
        conn.close()


def messages(db_path: Optional[Union[Path, str]], job_id: int) -> list[dict[str, Any]]:
    """The job's messages, oldest first."""
    conn = db.open_db(db_path)
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM job_messages WHERE job_id = ? ORDER BY seq", (job_id,))]
    finally:
        conn.close()
