"""Tests for cytonn_weekly.digital_payments.delivery (emailing the Edwin/Liz Word summary).

Reviews are real CoordinatorReviews built by the real pipeline code on fake edges
(review_helpers), saved to a real temp SQLite file, with the real .docx written to
disk, as in test_digital_payments_summary.py.  Only smtplib.SMTP is mocked, so no
network call is ever made.
"""

import io
import smtplib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from docx import Document
from review_helpers import LocalFakeProvider, make_review

from cytonn_weekly.digital_payments import coordinator_review as cr
from cytonn_weekly.digital_payments import delivery as dl
from cytonn_weekly.digital_payments import review_store as rs
from cytonn_weekly.digital_payments import summary as sm

EDWIN, LIZ = "edwin@example.com", "liz@example.com"
SMTP_VARS = ("CYTONN_SMTP_HOST", "CYTONN_SMTP_PORT", "CYTONN_SMTP_USER", "CYTONN_SMTP_PASSWORD",
             "CYTONN_SMTP_FROM", "CYTONN_SUMMARY_RECIPIENTS")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """No delivery variable from the developer's own shell can leak into a test."""
    for name in SMTP_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def smtp_env(monkeypatch):
    """A complete, ordinary configuration: STARTTLS on 587, authenticated, two recipients."""
    monkeypatch.setenv("CYTONN_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("CYTONN_SMTP_USER", "tool@example.com")
    monkeypatch.setenv("CYTONN_SMTP_PASSWORD", "s3cret")
    monkeypatch.setenv("CYTONN_SUMMARY_RECIPIENTS", f"{EDWIN}, {LIZ}")


@pytest.fixture
def smtp(monkeypatch):
    """smtplib.SMTP replaced by a mock; ``.server`` is the object the ``with`` block yields."""
    cls = MagicMock(name="SMTP")
    cls.return_value.__exit__.return_value = False  # a failure inside the with block must propagate
    monkeypatch.setattr(dl.smtplib, "SMTP", cls)
    return SimpleNamespace(cls=cls, server=cls.return_value.__enter__.return_value)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "reviews.db"


def approve(review):
    review.accept_all_clean()
    for i in review.review_items:
        if i.resolution is None:
            i.resolve(cr.ACCEPT)
    review.decide("approved")
    return review


def approved_review(db, **kwargs):
    review = approve(make_review(**kwargs))
    rs.save_review(review, db_path=db)
    return review


def written_summary(review, tmp_path, name="summary.docx"):
    return sm.write_summary(review, tmp_path / name)


def sent_message(smtp):
    (msg,), kwargs = smtp.server.send_message.call_args
    return msg, kwargs


def the_attachment(msg):
    (att,) = list(msg.iter_attachments())
    return att


# ---------------------------------------------------------------------------
# A normal send
# ---------------------------------------------------------------------------

def test_approved_review_is_emailed_with_the_docx_attached(db, tmp_path, smtp, smtp_env):
    review = approved_review(db)
    path = written_summary(review, tmp_path)

    dl.email_summary(path, review)

    assert smtp.cls.call_args.args[:2] == ("smtp.example.com", 587)
    smtp.server.starttls.assert_called_once_with()
    smtp.server.login.assert_called_once_with("tool@example.com", "s3cret")
    smtp.server.send_message.assert_called_once()
    msg, kwargs = sent_message(smtp)
    assert kwargs == {"from_addr": "tool@example.com", "to_addrs": [EDWIN, LIZ]}
    assert msg["To"] == f"{EDWIN}, {LIZ}" and msg["From"] == "tool@example.com"

    att = the_attachment(msg)
    assert att.get_content_type() == dl.DOCX_MAINTYPE + "/" + dl.DOCX_SUBTYPE
    assert att.get_filename() == sm.default_summary_path(review).name
    payload = att.get_content()
    assert len(payload) > 0 and payload == path.read_bytes()
    assert Document(io.BytesIO(payload)).paragraphs[0].text == sm.TITLE  # a real, openable .docx


def test_starttls_precedes_login_and_send(db, tmp_path, smtp, smtp_env):
    review = approved_review(db)
    dl.email_summary(written_summary(review, tmp_path), review)
    steps = [c[0] for c in smtp.server.mock_calls if c[0] in ("starttls", "login", "send_message")]
    assert steps == ["starttls", "login", "send_message"]


def test_subject_names_the_report_week_and_the_body_is_a_short_note(db, tmp_path, smtp, smtp_env):
    review = approved_review(db)
    dl.email_summary(written_summary(review, tmp_path), review)
    msg, _ = sent_message(smtp)
    assert msg["Subject"] == "Cytonn Weekly: Digital Payments summary, week 24 Sep 2026 to 30 Sep 2026"
    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert "attached" in body and "for your awareness" in body and "coordinator-checked" in body
    assert sm._fmt_date(review.decided_at) in body


def test_attachment_is_named_for_the_week_even_when_written_to_a_custom_path(db, tmp_path, smtp, smtp_env):
    review = approved_review(db)
    dl.email_summary(written_summary(review, tmp_path, "tmp123.docx"), review)
    msg, _ = sent_message(smtp)
    assert the_attachment(msg).get_filename() == f"digital_payments_summary_2026-09-30_run{review.run_id}.docx"


def test_explicit_recipients_win_over_the_environment(db, tmp_path, smtp, smtp_env):
    review = approved_review(db)
    dl.email_summary(written_summary(review, tmp_path), review, recipients=["someone@example.com"])
    _, kwargs = sent_message(smtp)
    assert kwargs["to_addrs"] == ["someone@example.com"]


def test_nothing_in_the_message_but_the_summary_itself(db, tmp_path, smtp, smtp_env):
    review = approved_review(db)
    dl.email_summary(written_summary(review, tmp_path), review)
    msg, _ = sent_message(smtp)
    assert len(list(msg.iter_attachments())) == 1


# ---------------------------------------------------------------------------
# Recipients
# ---------------------------------------------------------------------------

def test_recipients_from_the_environment_are_stripped_and_empties_dropped(monkeypatch):
    monkeypatch.setenv("CYTONN_SUMMARY_RECIPIENTS", f"  {EDWIN} , ,{LIZ},, ")
    assert dl.resolve_recipients() == [EDWIN, LIZ]
    assert dl.resolve_recipients([f" {LIZ} ", "", "  "]) == [LIZ]


def test_no_recipients_configured_raises_and_sends_nothing(db, tmp_path, smtp, monkeypatch):
    monkeypatch.setenv("CYTONN_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("CYTONN_SMTP_FROM", "tool@example.com")
    review = approved_review(db)
    path = written_summary(review, tmp_path)
    with pytest.raises(ValueError, match="CYTONN_SUMMARY_RECIPIENTS"):
        dl.email_summary(path, review)
    monkeypatch.setenv("CYTONN_SUMMARY_RECIPIENTS", " , ,")  # set, but no actual address
    with pytest.raises(ValueError, match="CYTONN_SUMMARY_RECIPIENTS"):
        dl.email_summary(path, review)
    smtp.cls.assert_not_called()


def test_an_explicit_empty_list_does_not_fall_back_to_the_environment(db, tmp_path, smtp, smtp_env):
    review = approved_review(db)
    with pytest.raises(ValueError, match="recipients list passed in is empty"):
        dl.email_summary(written_summary(review, tmp_path), review, recipients=[])
    smtp.cls.assert_not_called()


# ---------------------------------------------------------------------------
# SMTP configuration
# ---------------------------------------------------------------------------

def test_port_defaults_to_587_and_can_be_set(monkeypatch):
    monkeypatch.setenv("CYTONN_SMTP_HOST", "h")
    monkeypatch.setenv("CYTONN_SMTP_FROM", "a@example.com")
    assert dl.smtp_settings().port == 587
    monkeypatch.setenv("CYTONN_SMTP_PORT", "2525")
    assert dl.smtp_settings().port == 2525


def test_sender_falls_back_to_the_smtp_user_unless_from_is_set(monkeypatch, smtp_env):
    assert dl.smtp_settings().sender == "tool@example.com"
    monkeypatch.setenv("CYTONN_SMTP_FROM", "reports@example.com")
    assert dl.smtp_settings().sender == "reports@example.com"


def test_unusable_smtp_configuration_raises_naming_the_variable(monkeypatch):
    with pytest.raises(ValueError, match="CYTONN_SMTP_HOST"):
        dl.smtp_settings()
    monkeypatch.setenv("CYTONN_SMTP_HOST", "h")
    with pytest.raises(ValueError, match="CYTONN_SMTP_FROM"):
        dl.smtp_settings()  # no sender at all
    monkeypatch.setenv("CYTONN_SMTP_FROM", "a@example.com")
    monkeypatch.setenv("CYTONN_SMTP_PORT", "five-eight-seven")
    with pytest.raises(ValueError, match="CYTONN_SMTP_PORT"):
        dl.smtp_settings()
    monkeypatch.delenv("CYTONN_SMTP_PORT")
    monkeypatch.setenv("CYTONN_SMTP_USER", "tool@example.com")
    with pytest.raises(ValueError, match="CYTONN_SMTP_PASSWORD"):
        dl.smtp_settings()


def test_bad_smtp_configuration_sends_nothing(db, tmp_path, smtp, monkeypatch):
    monkeypatch.setenv("CYTONN_SUMMARY_RECIPIENTS", EDWIN)  # recipients fine, host missing
    review = approved_review(db)
    with pytest.raises(ValueError, match="CYTONN_SMTP_HOST"):
        dl.email_summary(written_summary(review, tmp_path), review)
    smtp.cls.assert_not_called()


def test_no_login_is_attempted_when_no_smtp_user_is_configured(db, tmp_path, smtp, monkeypatch):
    monkeypatch.setenv("CYTONN_SMTP_HOST", "relay.internal")
    monkeypatch.setenv("CYTONN_SMTP_FROM", "reports@example.com")
    monkeypatch.setenv("CYTONN_SUMMARY_RECIPIENTS", EDWIN)
    review = approved_review(db)
    dl.email_summary(written_summary(review, tmp_path), review)
    smtp.server.starttls.assert_called_once()
    smtp.server.login.assert_not_called()
    smtp.server.send_message.assert_called_once()


# ---------------------------------------------------------------------------
# Dev-mode drafts never leave the building
# ---------------------------------------------------------------------------

def test_dev_mode_review_is_blocked_even_with_explicit_recipients(db, tmp_path, smtp, smtp_env):
    review = approved_review(db, provider=LocalFakeProvider())
    path = written_summary(review, tmp_path)  # the doc itself is stamped NOT FOR CIRCULATION
    with pytest.raises(dl.DevModeDeliveryBlocked):
        dl.email_summary(path, review)
    with pytest.raises(dl.DevModeDeliveryBlocked):
        dl.email_summary(path, review, recipients=[EDWIN, LIZ])
    smtp.cls.assert_not_called()


def test_dev_mode_is_blocked_with_nothing_configured_at_all(db, tmp_path, smtp):
    review = approved_review(db, provider=LocalFakeProvider())
    with pytest.raises(dl.DevModeDeliveryBlocked):  # not a ValueError about recipients or host
        dl.email_summary(written_summary(review, tmp_path), review)
    smtp.cls.assert_not_called()


@pytest.mark.parametrize("where", ["outlook only", "one highlight only"])
def test_one_local_draft_in_an_otherwise_production_review_still_blocks(db, tmp_path, smtp, smtp_env, where):
    review = make_review()  # FakeProvider: drafted_by "fake:test" everywhere
    if where == "outlook only":
        review.section["outlook"]["drafted_by"] = "local:phi4-mini"
    else:
        next(i for i in review.section["items"] if i["kind"] == "highlight")["drafted_by"] = "local:phi4-mini"
    approve(review)
    assert dl.is_dev_mode_review(review)
    with pytest.raises(dl.DevModeDeliveryBlocked):
        dl.email_summary(written_summary(review, tmp_path), review, recipients=[EDWIN])
    smtp.cls.assert_not_called()


def test_a_production_review_is_not_dev_mode(db):
    assert not dl.is_dev_mode_review(approved_review(db))


def test_deliver_latest_summary_blocks_a_dev_mode_review(db, tmp_path, smtp, smtp_env):
    approved_review(db, provider=LocalFakeProvider())
    with pytest.raises(dl.DevModeDeliveryBlocked):
        dl.deliver_latest_summary(db_path=db, out_path=tmp_path / "out.docx", recipients=[EDWIN])
    smtp.cls.assert_not_called()


# ---------------------------------------------------------------------------
# Only an approved review is ever sent
# ---------------------------------------------------------------------------

def test_email_summary_refuses_a_review_that_is_not_approved(tmp_path, smtp, smtp_env):
    review = make_review()  # in progress
    path = tmp_path / "draft.docx"
    path.write_bytes(b"not a real summary")
    with pytest.raises(sm.SummaryNotAllowed, match="still in progress"):
        dl.email_summary(path, review)
    rejected = make_review()
    rejected.decide("rejected")
    with pytest.raises(sm.SummaryNotAllowed, match="rejected"):
        dl.email_summary(path, rejected)
    smtp.cls.assert_not_called()


# ---------------------------------------------------------------------------
# deliver_latest_summary
# ---------------------------------------------------------------------------

def test_deliver_latest_summary_writes_then_sends_and_returns_the_path(db, tmp_path, smtp, smtp_env):
    review = approved_review(db)
    out = tmp_path / "out.docx"
    path = dl.deliver_latest_summary(db_path=db, out_path=out)
    assert path == out and out.is_file()
    msg, kwargs = sent_message(smtp)
    assert kwargs["to_addrs"] == [EDWIN, LIZ]
    assert the_attachment(msg).get_content() == out.read_bytes()
    assert the_attachment(msg).get_filename() == sm.default_summary_path(review).name


def test_deliver_latest_summary_defaults_to_the_summary_directory(db, tmp_path, smtp, smtp_env, monkeypatch):
    monkeypatch.setattr(sm, "SUMMARY_DIR", tmp_path / "summaries")
    review = approved_review(db)
    path = dl.deliver_latest_summary(db_path=db)
    assert path == tmp_path / "summaries" / f"digital_payments_summary_2026-09-30_run{review.run_id}.docx"
    assert path.is_file()
    smtp.server.send_message.assert_called_once()


def test_deliver_latest_summary_passes_explicit_recipients_through(db, tmp_path, smtp, smtp_env):
    approved_review(db)
    dl.deliver_latest_summary(db_path=db, out_path=tmp_path / "out.docx", recipients=["only@example.com"])
    assert sent_message(smtp)[1]["to_addrs"] == ["only@example.com"]


def _save_in_progress(db):
    rs.save_review(make_review(), db_path=db)


def _save_rejected(db):
    review = make_review()
    review.decide("rejected")
    rs.save_review(review, db_path=db)


def _save_in_progress_over_older_approved(db):
    approved_review(db)
    rs.save_review(make_review(), db_path=db)


@pytest.mark.parametrize("seed", [lambda db: None, _save_in_progress, _save_rejected, _save_in_progress_over_older_approved],
                         ids=["no review", "in progress", "rejected", "newer draft over older approved"])
def test_summary_not_allowed_propagates_unchanged_and_nothing_is_written_or_sent(db, tmp_path, smtp, smtp_env, seed):
    seed(db)
    with pytest.raises(sm.SummaryNotAllowed) as direct:
        sm.write_latest_summary(tmp_path / "direct.docx", db_path=db)
    with pytest.raises(sm.SummaryNotAllowed) as via_delivery:
        dl.deliver_latest_summary(db_path=db, out_path=tmp_path / "out.docx")
    assert type(via_delivery.value) is sm.SummaryNotAllowed
    assert str(via_delivery.value) == str(direct.value)  # the same words, not a reworded copy
    assert not (tmp_path / "out.docx").exists()
    smtp.cls.assert_not_called()


# ---------------------------------------------------------------------------
# SMTP failures are never swallowed
# ---------------------------------------------------------------------------

def _fail_connect(smtp, exc):
    smtp.cls.side_effect = exc


def _fail_starttls(smtp, exc):
    smtp.server.starttls.side_effect = exc


def _fail_login(smtp, exc):
    smtp.server.login.side_effect = exc


def _fail_send(smtp, exc):
    smtp.server.send_message.side_effect = exc


@pytest.mark.parametrize("arm, exc", [
    (_fail_connect, ConnectionRefusedError("connection refused")),
    (_fail_connect, smtplib.SMTPConnectError(421, "service not available")),
    (_fail_starttls, smtplib.SMTPNotSupportedError("STARTTLS extension not supported by server")),
    (_fail_login, smtplib.SMTPAuthenticationError(535, b"bad credentials")),
    (_fail_send, smtplib.SMTPDataError(554, b"message rejected")),
    (_fail_send, smtplib.SMTPServerDisconnected("connection unexpectedly closed")),
], ids=["connect refused", "connect error", "no starttls", "auth", "send rejected", "send disconnected"])
def test_an_smtp_exception_propagates_out_of_email_summary(db, tmp_path, smtp, smtp_env, arm, exc):
    review = approved_review(db)
    path = written_summary(review, tmp_path)
    arm(smtp, exc)
    with pytest.raises(type(exc)) as raised:
        dl.email_summary(path, review)
    assert raised.value is exc  # the original exception, not a wrapped or reworded one


def test_an_smtp_exception_propagates_out_of_deliver_latest_summary(db, tmp_path, smtp, smtp_env):
    approved_review(db)
    exc = smtplib.SMTPDataError(554, b"message rejected")
    smtp.server.send_message.side_effect = exc
    with pytest.raises(smtplib.SMTPDataError) as raised:
        dl.deliver_latest_summary(db_path=db, out_path=tmp_path / "out.docx")
    assert raised.value is exc
