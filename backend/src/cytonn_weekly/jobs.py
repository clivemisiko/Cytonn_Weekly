"""Report jobs: one per (report type, period, section), with the limits it was opened under and its messages in order.

Storage only (tables report_jobs and job_messages).  Nothing here calls a model or a tool, and nothing enforces the three
limits yet: they are recorded so a later phase can enforce what the job was opened with.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from cytonn_weekly import db

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


def add_message(db_path: Optional[Union[Path, str]], job_id: int, role: str, content: str,
                tool_name: Optional[str] = None, tool_result: Optional[str] = None) -> int:
    """Append one message to the job and return its number (1, 2, ...).  ``tool_name`` and ``tool_result`` are for a tool turn.

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
            conn.execute("INSERT INTO job_messages (job_id, seq, role, content, tool_name, tool_result, created_at) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?)", (job_id, seq, role, content, tool_name, tool_result, _now()))
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
