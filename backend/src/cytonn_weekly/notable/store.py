"""The analyst's decisions on suggestions: one row per week, section and suggestion, in the table suggestion_decisions.

Nothing else is read or written here.  A decision never reaches coordinator_reviews, an approval, the analyst form or the export.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from cytonn_weekly import sections

_COLUMNS = "decision, edited_headline, dismiss_reason, decided_at"


def _open(db_path: Optional[Union[Path, str]]) -> sqlite3.Connection:
    sections.init_db(db_path)  # idempotent: creates the table on first use
    return sections._connect(db_path)


def load(db_path: Optional[Union[Path, str]], week_ending: str, section: str) -> dict[str, dict]:
    """The saved decisions for one section and week, by suggestion id."""
    conn = _open(db_path)
    try:
        cur = conn.execute(f"SELECT suggestion_id, {_COLUMNS} FROM suggestion_decisions WHERE week_ending = ? AND section = ?",
                           (week_ending, section))
        return {r["suggestion_id"]: {k: r[k] for k in r.keys() if k != "suggestion_id"} for r in cur}
    finally:
        conn.close()


def save(db_path: Optional[Union[Path, str]], week_ending: str, section: str, suggestion_id: str, decision: str,
         edited_headline: Optional[str], dismiss_reason: Optional[str]) -> None:
    """Keep the decision, replacing an earlier one on the same suggestion."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = _open(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO suggestion_decisions (week_ending, section, suggestion_id, decision, edited_headline, dismiss_reason, decided_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (week_ending, section, suggestion_id) DO UPDATE SET decision = excluded.decision, "
                "edited_headline = excluded.edited_headline, dismiss_reason = excluded.dismiss_reason, decided_at = excluded.decided_at",
                (week_ending, section, suggestion_id, decision, edited_headline, dismiss_reason, now),
            )
    finally:
        conn.close()


def delete(db_path: Optional[Union[Path, str]], week_ending: str, section: str, suggestion_id: str) -> bool:
    """Remove the decision (restore the suggestion).  False when there was none."""
    conn = _open(db_path)
    try:
        with conn:
            cur = conn.execute("DELETE FROM suggestion_decisions WHERE week_ending = ? AND section = ? AND suggestion_id = ?",
                               (week_ending, section, suggestion_id))
        return cur.rowcount > 0
    finally:
        conn.close()
