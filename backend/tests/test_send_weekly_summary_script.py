"""Tests for scripts/send_weekly_summary.py, the one entrypoint that emails the Word summary.

Real reviews (review_helpers) in a real temp SQLite file, the real .docx written to a
temp summaries dir; only smtplib.SMTP is mocked, so nothing ever leaves the machine.
The script is loaded from its file, as `python scripts/send_weekly_summary.py` would run it.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from review_helpers import LocalFakeProvider, make_review

from cytonn_weekly.digital_payments import coordinator_review as cr
from cytonn_weekly.digital_payments import delivery as dl
from cytonn_weekly.digital_payments import review_store as rs
from cytonn_weekly.digital_payments import summary as sm

SCRIPT = Path(__file__).parents[1] / "scripts" / "send_weekly_summary.py"
_spec = importlib.util.spec_from_file_location("send_weekly_summary", SCRIPT)
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

EDWIN, LIZ = "edwin@example.com", "liz@example.com"
SMTP_VARS = ("CYTONN_SMTP_HOST", "CYTONN_SMTP_PORT", "CYTONN_SMTP_USER", "CYTONN_SMTP_PASSWORD",
             "CYTONN_SMTP_FROM", "CYTONN_SUMMARY_RECIPIENTS")


@pytest.fixture(autouse=True)
def configured(monkeypatch, tmp_path):
    """A complete SMTP configuration, summaries written under tmp_path, nothing from the real shell."""
    for name in SMTP_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CYTONN_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("CYTONN_SMTP_USER", "tool@example.com")
    monkeypatch.setenv("CYTONN_SMTP_PASSWORD", "s3cret")
    monkeypatch.setenv("CYTONN_SUMMARY_RECIPIENTS", f"{EDWIN}, {LIZ}")
    monkeypatch.setattr(sm, "SUMMARY_DIR", tmp_path / "summaries")


@pytest.fixture
def smtp(monkeypatch):
    cls = MagicMock(name="SMTP")
    cls.return_value.__exit__.return_value = False
    monkeypatch.setattr(dl.smtplib, "SMTP", cls)
    return SimpleNamespace(cls=cls, server=cls.return_value.__enter__.return_value)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "reviews.db"


def saved(db, review, decision="approved"):
    if decision:
        review.accept_all_clean()
        for i in review.review_items:
            if i.resolution is None:
                i.resolve(cr.ACCEPT)
        review.decide(decision)
    rs.save_review(review, db_path=db)
    return review


def test_without_yes_it_previews_and_sends_nothing(db, smtp, capsys):
    review = saved(db, make_review())
    assert script.main([], db_path=db) == 0
    out = capsys.readouterr().out
    assert "digital_payments" in out and f"Review run:   {review.run_id}" in out
    assert "Approval:     approved" in out and f"{EDWIN}, {LIZ}" in out
    assert "Re-run with --yes" in out
    smtp.cls.assert_not_called()
    assert not sm.SUMMARY_DIR.exists()  # preview writes no file either


def test_yes_sends_the_previewed_approved_summary(db, smtp, capsys):
    review = saved(db, make_review())
    assert script.main(["--yes"], db_path=db) == 0
    smtp.server.send_message.assert_called_once()
    assert smtp.server.send_message.call_args.kwargs["to_addrs"] == [EDWIN, LIZ]
    assert sm.default_summary_path(review).is_file()
    assert "Sent" in capsys.readouterr().out


def test_dev_mode_review_is_refused_even_with_yes(db, smtp, capsys):
    saved(db, make_review(provider=LocalFakeProvider()))
    assert script.main(["--yes"], db_path=db) == 1
    out = capsys.readouterr().out
    assert "REFUSED" in out and "DEV MODE" in out and "local:phi4-mini" in out
    assert "Recipients" not in out  # refuses before showing anything that looks sendable
    smtp.cls.assert_not_called()


def test_dev_mode_anywhere_in_the_content_is_refused_by_the_script_itself(db, smtp, capsys):
    """A local: marker outside the highlights/outlook (where delivery.py looks) is still caught here."""
    review = make_review()
    review.section["table_note"] = {"drafted_by": "local:phi4-mini"}
    saved(db, review)
    assert not dl.is_dev_mode_review(review)  # delivery's own guard would not see this one
    assert script.main(["--yes"], db_path=db) == 1
    assert "DEV MODE" in capsys.readouterr().out
    smtp.cls.assert_not_called()


@pytest.mark.parametrize("decision", [None, "rejected"])
def test_undecided_or_rejected_review_is_refused(db, smtp, capsys, decision):
    saved(db, make_review(), decision=decision)
    assert script.main(["--yes"], db_path=db) == 1
    assert "only an approved review" in capsys.readouterr().out
    smtp.cls.assert_not_called()


def test_no_saved_review_is_refused(db, smtp, capsys):
    assert script.main(["--yes"], db_path=db) == 1
    assert "no saved review" in capsys.readouterr().out
    smtp.cls.assert_not_called()


def test_missing_smtp_configuration_is_refused_before_sending(db, smtp, capsys, monkeypatch):
    saved(db, make_review())
    monkeypatch.delenv("CYTONN_SMTP_HOST")
    assert script.main(["--yes"], db_path=db) == 1
    assert "CYTONN_SMTP_HOST" in capsys.readouterr().out
    smtp.cls.assert_not_called()


def test_section_without_a_summary_renderer_is_rejected(db, smtp):
    with pytest.raises(SystemExit):
        script.main(["equities", "--yes"], db_path=db)
    smtp.cls.assert_not_called()


def test_drafted_by_values_walks_nested_content():
    content = {"items": [{"drafted_by": "a"}, {"x": {"drafted_by": "b"}}], "outlook": {"drafted_by": None}}
    assert sorted(script.drafted_by_values(content)) == ["a", "b"]
