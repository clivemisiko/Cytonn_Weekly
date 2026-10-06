"""Email delivery of the Digital Payments Word-doc summary to Edwin and Liz.

summary.py produces the .docx and stops there; this module is the missing last step
of that part of the process flow: getting the coordinator-checked summary into the
insight recipients' inboxes before publish.  Stdlib only (smtplib + email).

Two safety rules, neither with an override:

* Only an APPROVED WEEKLY review is ever sent.  The guards are summary.py's own
  (require_approved, which also refuses every other report type), so a draft can never be
  mistaken for the checked version and a Markets Review can never be sent as the weekly.
* A DEV MODE draft is never sent.  A review whose highlights or outlook were drafted
  by the local model (``drafted_by`` starting "local:", the same signal summary.py
  uses for its "NOT FOR CIRCULATION" banner) raises DevModeDeliveryBlocked, even when
  the caller passes ``recipients`` explicitly.

An SMTP failure is never swallowed: every smtplib/OSError propagates, so the
coordinator learns a send failed instead of assuming it went out.

Configuration (library code reads os.environ only; entrypoints call env.load_env()
first)::

    CYTONN_SMTP_HOST          required
    CYTONN_SMTP_PORT          default 587 (STARTTLS, as Office365 and Gmail expect)
    CYTONN_SMTP_USER          login name; if unset, no login is attempted
    CYTONN_SMTP_PASSWORD      required when CYTONN_SMTP_USER is set
    CYTONN_SMTP_FROM          sender address; falls back to CYTONN_SMTP_USER
    CYTONN_SUMMARY_RECIPIENTS comma-separated addresses; used when ``recipients`` is not passed

Typical usage
-------------
    env.load_env()
    path = deliver_latest_summary()      # writes the latest approved summary, emails it, returns the path
"""

from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Optional, Union

from cytonn_weekly.digital_payments import review_store, summary
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview
from cytonn_weekly.report_types import WEEKLY

DEFAULT_SMTP_PORT = 587
SMTP_TIMEOUT_SECONDS = 30
DOCX_MAINTYPE = "application"
DOCX_SUBTYPE = "vnd.openxmlformats-officedocument.wordprocessingml.document"

ENV_RECIPIENTS = "CYTONN_SUMMARY_RECIPIENTS"


class DevModeDeliveryBlocked(RuntimeError):
    """The review was drafted by the local dev-mode model, so it must not be emailed."""


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    user: Optional[str]
    password: Optional[str]
    sender: str


# ---------------------------------------------------------------------------
# Guards and configuration
# ---------------------------------------------------------------------------

def is_dev_mode_review(review: CoordinatorReview) -> bool:
    """True if any highlight or the outlook was drafted by the local model (summary.py's banner signal)."""
    sec = review.section
    drafted_by = {i.get("drafted_by") for i in sec.get("items", []) if i.get("kind") == "highlight"}
    drafted_by.add((sec.get("outlook") or {}).get("drafted_by"))
    # Block-shaped reviews (Markets Reviews and their Executive Summary): narrative pieces, and the
    # summary's record of local pieces in the sections it was composed from.
    drafted_by |= {b.get("drafted_by") for b in sec.get("blocks", []) if b.get("kind") == "narrative"}
    drafted_by |= {p.get("drafted_by") for c in sec.get("not_covered", []) for p in c.get("dev_pieces", [])}
    return any(str(d).startswith("local:") for d in drafted_by)


def _clean_addresses(addresses) -> list[str]:
    return [a.strip() for a in addresses if a and a.strip()]


def resolve_recipients(recipients: Optional[list[str]] = None) -> list[str]:
    """The explicit list if given, else CYTONN_SUMMARY_RECIPIENTS; ValueError if that leaves nobody.

    An explicitly passed empty list is an error, not a cue to fall back to the environment.
    """
    if recipients is None:
        resolved = _clean_addresses(os.environ.get(ENV_RECIPIENTS, "").split(","))
        source = f"{ENV_RECIPIENTS} is not set or has no addresses"
    else:
        resolved = _clean_addresses(recipients)
        source = "the recipients list passed in is empty"
    if not resolved:
        raise ValueError(f"no recipients to email the summary to: {source}")
    return resolved


def smtp_settings() -> SmtpSettings:
    """SMTP configuration from the environment; ValueError naming the variable if it is unusable."""
    env = os.environ
    host = (env.get("CYTONN_SMTP_HOST") or "").strip()
    if not host:
        raise ValueError("CYTONN_SMTP_HOST is not set; cannot email the summary")
    raw_port = (env.get("CYTONN_SMTP_PORT") or "").strip()
    try:
        port = int(raw_port) if raw_port else DEFAULT_SMTP_PORT
    except ValueError:
        raise ValueError(f"CYTONN_SMTP_PORT must be a number, got {raw_port!r}") from None
    user = (env.get("CYTONN_SMTP_USER") or "").strip() or None
    password = env.get("CYTONN_SMTP_PASSWORD") or None
    if user and not password:
        raise ValueError("CYTONN_SMTP_USER is set but CYTONN_SMTP_PASSWORD is not")
    sender = (env.get("CYTONN_SMTP_FROM") or "").strip() or user
    if not sender:
        raise ValueError("neither CYTONN_SMTP_FROM nor CYTONN_SMTP_USER is set; no sender address")
    return SmtpSettings(host=host, port=port, user=user, password=password, sender=sender)


# ---------------------------------------------------------------------------
# Message and send
# ---------------------------------------------------------------------------

def build_message(
    path: Path, review: CoordinatorReview, *, sender: str, recipients: list[str],
) -> EmailMessage:
    """The email: week-identifying subject, short plain-text note, the .docx attached."""
    sec = review.section
    week = f"{summary._fmt_date(sec['week_start'])} to {summary._fmt_date(sec['week_end'])}"
    msg = EmailMessage()
    msg["Subject"] = f"Cytonn Weekly: Digital Payments summary, week {week}"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(
        f"Digital Payments weekly summary attached, for your awareness: coordinator-checked "
        f"values as of {summary._fmt_date(review.decided_at)}.\n\n"
        f"Report week {week}. For information only; no action or sign-off is needed.\n"
    )
    msg.add_attachment(
        path.read_bytes(), maintype=DOCX_MAINTYPE, subtype=DOCX_SUBTYPE,
        filename=summary.default_summary_path(review).name,  # identifiable even if written to a custom path
    )
    return msg


def email_summary(
    path: Path, review: CoordinatorReview, *, recipients: Optional[list[str]] = None,
) -> None:
    """Email the .docx at ``path`` (the summary of ``review``) to the recipients.

    Raises, sending nothing: SummaryNotAllowed if the review is not approved or is not a
    weekly review,
    DevModeDeliveryBlocked if it is a dev-mode draft (no override, whatever
    ``recipients`` says), ValueError if there are no recipients or the SMTP
    configuration is unusable.  Any SMTP/network error during the send propagates.
    """
    summary.require_approved(review)
    if is_dev_mode_review(review):
        raise DevModeDeliveryBlocked(
            f"review run {review.run_id} was drafted by the local dev-mode model; "
            "a DEV MODE draft is never emailed"
        )
    to_addrs = resolve_recipients(recipients)
    settings = smtp_settings()
    msg = build_message(Path(path), review, sender=settings.sender, recipients=to_addrs)

    with smtplib.SMTP(settings.host, settings.port, timeout=SMTP_TIMEOUT_SECONDS) as server:
        server.starttls()
        if settings.user:
            server.login(settings.user, settings.password)
        server.send_message(msg, from_addr=settings.sender, to_addrs=to_addrs)


def deliver_latest_summary(
    *,
    section: str = review_store.SECTION,
    report_type: str = WEEKLY,
    db_path: Optional[Union[Path, str]] = None,
    out_path: Optional[Union[Path, str]] = None,
    recipients: Optional[list[str]] = None,
) -> Path:
    """Write the latest saved review's summary (which must be approved) and email it.

    Returns the path that was both written and sent.  The review is loaded once and
    handed to summary.write_summary(), which is what write_latest_summary() does
    internally (it returns only a path, and a second load could pick up a newer run
    than the one written).  So the approval guard and its SummaryNotAllowed messages
    are summary.py's, unchanged: a missing, in-progress or rejected latest review
    raises before anything is written or sent.
    """
    review = review_store.load_latest_review(section, report_type=report_type, db_path=db_path)
    path = summary.write_summary(review, out_path)
    email_summary(path, review, recipients=recipients)
    return path
